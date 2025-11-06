# extractors/youtube.py
# ------------------------------------------------------------
# YouTube robuste (Greg le Consanguin)
# - AUTO poToken via Playwright d'abord, sinon fallback ENV (.env)
# - STREAM direct: URL + headers → FFmpeg (reconnect + low-latency)
# - STREAM PIPE: yt-dlp → stdout → FFmpeg (fallback)
# - DOWNLOAD: MP3 (192 kbps / 48 kHz)
# - Cookies: navigateur via YTDLP_COOKIES_BROWSER, sinon YTDLP_COOKIES_B64/Netscape
# - Proxies: YTDLP_HTTP_PROXY / HTTPS_PROXY / HTTP_PROXY / ALL_PROXY
# - IPv4: forçage source_address=0.0.0.0 + --force-ipv4 pour le PIPE
# ------------------------------------------------------------
from __future__ import annotations

import base64
import functools
import os
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.parse as _url
import urllib.request as _ureq
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

try:
    # auto-fetch (optionnel)
    from .token_fetcher import fetch_po_token  # type: ignore
except Exception:
    fetch_po_token = None

# ====== DEBUG ======
_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")
_YTDBG_HTTP_PROBE = os.getenv("YTDBG_HTTP_PROBE", "0").lower() not in ("0", "false", "")

def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}")

def _redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = dict(h or {})
    for k in list(out.keys()):
        if k.lower() in ("cookie", "authorization", "x-youtube-identity-token"):
            v = out.get(k)
            out[k] = f"<redacted:{len(v) if isinstance(v, str) else '?'}>"
    return out

def _parse_qs(url: str) -> Dict[str, str]:
    try:
        q = _url.urlsplit(url).query
        return {k: v[0] for k, v in _url.parse_qs(q).items()}
    except Exception:
        return {}

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("music.youtube.com/watch" in u) or ("youtube.com/shorts/" in u)

# ====== ENV / CONFIG ======
_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)
_FORCE_IPV4 = os.getenv("YTDLP_FORCE_IPV4", "1").lower() not in ("0", "false", "")
_HTTP_PROXY = os.getenv("YTDLP_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

_CLIENTS_ORDER = ["ios", "android", "web_creator", "web", "web_mobile"]
_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/bestaudio/18"
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"

# ====== PO TOKEN: auto-first → fallback ENV ======
def _collect_env_po_tokens() -> List[str]:
    raw_candidates: List[object] = []
    prefixed_candidates: List[str] = []

    for k in ("YT_PO_TOKEN", "YTDLP_PO_TOKEN"):
        v = (os.getenv(k) or "").strip()
        if not v:
            continue
        if "+" in v:
            prefixed_candidates.append(v)
        else:
            raw_candidates.append(v)

    ios = (os.getenv("YT_PO_TOKEN_IOS") or "").strip()
    if ios:
        raw_candidates.append(("ios.gvs", ios))
    android = (os.getenv("YT_PO_TOKEN_ANDROID") or "").strip()
    if android:
        raw_candidates.append(("android.gvs", android))
    web = (os.getenv("YT_PO_TOKEN_WEB") or "").strip()
    if web:
        raw_candidates.append(("web.gvs", web))

    v_pref = (os.getenv("YT_PO_TOKEN_PREFIXED") or "").strip()
    if v_pref:
        prefixed_candidates.append(v_pref)

    tokens: List[str] = []
    for raw in raw_candidates:
        if isinstance(raw, tuple):
            prefix, tok = raw
            if tok:
                tokens.append(f"{prefix}+{tok}")
        else:
            tok = raw
            if tok:
                tokens += [f"ios.gvs+{tok}", f"android.gvs+{tok}", f"web.gvs+{tok}"]

    for p in prefixed_candidates:
        if p:
            tokens.append(p)

    out, seen = [], set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)

    if out:
        _dbg(f"PO tokens (ENV detected) → {', '.join(p.split('+',1)[0] for p in out)}")
    else:
        _dbg("PO tokens (ENV): none")
    return out

_ENV_PO_TOKENS = _collect_env_po_tokens()
_PO_TOKENS: List[str] = []

_AUTO_PO = os.getenv("YTDLP_AUTO_PO", "1").lower() not in ("0", "false", "")

def _video_id_from_any(x: str) -> Optional[str]:
    try:
        if len(x) == 11 and "/" not in x and "?" not in x:
            return x
        u = _url.urlsplit(x)
        if "youtu.be" in (u.netloc or ""):
            vid = (u.path or "").strip("/").split("/")[0]
            return vid or None
        if "youtube.com" in (u.netloc or "") or "music.youtube.com" in (u.netloc or ""):
            q = _url.parse_qs(u.query)
            return (q.get("v") or [None])[0]
        return None
    except Exception:
        return None

def _ensure_po_tokens_for(url_or_query: str) -> None:
    """
    Priorité : AUTO d'abord (Playwright) → si échec, fallback ENV.
    """
    global _PO_TOKENS
    if _PO_TOKENS:
        return

    tok = None
    if _AUTO_PO and fetch_po_token is not None:
        vid = _video_id_from_any(url_or_query)
        if vid:
            _dbg("Trying to auto-fetch poToken via Playwright (auto-first)…")
            try:
                tok = fetch_po_token(vid, timeout_ms=15000)
            except Exception as e:
                _dbg(f"poToken auto-fetch error: {e}")

    if tok:
        _PO_TOKENS = [f"ios.gvs+{tok}", f"android.gvs+{tok}", f"web.gvs+{tok}"]
        _dbg("poToken fetched → enabled for ios/android/web")
        return

    if _ENV_PO_TOKENS:
        _PO_TOKENS = list(_ENV_PO_TOKENS)
        _dbg("Using ENV poToken(s) as fallback.")
    else:
        _dbg("No poToken found (auto failed, no ENV); continuing without.")

# ====== helpers: ffmpeg path, cookies, ytdlp cli ======
def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if not ffmpeg_hint:
        which = shutil.which(exe) or shutil.which("ffmpeg")
        return (which or "ffmpeg"), (os.path.dirname(which) if which else None)
    p = os.path.abspath(os.path.expanduser(ffmpeg_hint))
    if os.path.isdir(p):
        cand = os.path.join(p, exe)
        cand2 = os.path.join(p, "bin", exe)
        if os.path.isfile(cand):
            return cand, p
        if os.path.isfile(cand2):
            return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg not found in folder: {p}")
    if os.path.isfile(p):
        return p, os.path.dirname(p)
    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)
    return p, None

def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64).decode("utf-8", errors="replace")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(raw)
        _dbg(f"cookies: written from env to {target_path} ({len(raw)} chars)")
        return target_path
    except Exception as e:
        _dbg(f"cookies: failed to write from env: {e}")
        return None

def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec:
        return None
    parts = spec.split(":", 1)
    browser = parts[0].strip().lower()
    profile = parts[1].strip() if len(parts) > 1 else None
    return (browser,) if profile is None else (browser, profile)

def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]

# ====== yt-dlp opts ======
def _mk_opts(
    *,
    ffmpeg_path: Optional[str] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    search: bool = False,
    for_download: bool = False,
    allow_playlist: bool = False,
    extract_flat: bool = False,
) -> Dict[str, Any]:

    if (not cookies_file) and os.path.exists(_COOKIE_FILE_DEFAULT):
        cookies_file = _COOKIE_FILE_DEFAULT
    if (not cookies_file) and os.getenv("YTDLP_COOKIES_B64"):
        _ensure_cookiefile_from_b64(_COOKIE_FILE_DEFAULT)
        if os.path.exists(_COOKIE_FILE_DEFAULT):
            cookies_file = _COOKIE_FILE_DEFAULT

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": (not allow_playlist),
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "source_address": "0.0.0.0" if _FORCE_IPV4 else None,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": {"youtube": {"player_client": list(_CLIENTS_ORDER)}},
        "youtube_include_dash_manifest": True,
        "format": _FORMAT_CHAIN,
    }

    if _PO_TOKENS:
        ydl_opts["extractor_args"]["youtube"]["po_token"] = ",".join(_PO_TOKENS)

    if extract_flat:
        ydl_opts["extract_flat"] = True

    if ffmpeg_path:
        if os.path.isfile(ffmpeg_path):
            ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path)
        else:
            ydl_opts["ffmpeg_location"] = ffmpeg_path

    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY

    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
        _dbg(f"cookiesfrombrowser={cfb}")
    elif cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file
        _dbg(f"cookiefile={cookies_file} (exists=True)")
    else:
        _dbg("cookies: none")

    if search:
        ydl_opts.update({"default_search": "ytsearch5", "extract_flat": True})

    if for_download:
        ydl_opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "postprocessor_args": ["-ar", "48000"],
        })

    for k in list(ydl_opts.keys()):
        if ydl_opts[k] is None:
            del ydl_opts[k]
    return ydl_opts

# --- Helpers format pour le PIPE (yt-dlp) ---

def _format_with_itag18(fmt: str) -> str:
    """
    S'assure que la chaîne de formats termine par '/18' (MP4 H.264/AAC ~ fréquemment dispo).
    Si l'ENV YTDLP_FORMAT force déjà un format, on lui ajoute '/18' s'il manque.
    """
    fmt = (fmt or "").strip()
    if not fmt:
        return "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/bestaudio/18"
    parts = [p.strip() for p in fmt.split("/") if p.strip()]
    if "18" not in parts:
        parts.append("18")
    return "/".join(parts)

def _build_extract_args_for_cli() -> str:
    """
    Construit la valeur de --extractor-args youtube:... pour le CLI yt-dlp,
    en réutilisant l'ordre de clients et les po_tokens éventuels.
    """
    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if _PO_TOKENS:
        ea_parts.append(f"po_token={','.join(_PO_TOKENS)}")
    return "youtube:" + ";".join(ea_parts)

def _pick_pipe_format(url: str,
                      cookies_file: Optional[str],
                      cookies_from_browser: Optional[str]) -> str:
    """
    Pré-sonde yt-dlp en CLI pour savoir si la chaîne de formats passe.
    - Si yt-dlp répond "Requested format is not available" → on bascule en '18'
    - Sinon, on garde la chaîne (avec '/18' garanti en fin).
    Cette sonde est rapide (--get-url) et évite un échec juste après le démarrage de ffmpeg.
    """
    import subprocess, shlex

    base_fmt = os.getenv("YTDLP_FORMAT", _FORMAT_CHAIN)
    fmt = _format_with_itag18(base_fmt)

    ea = _build_extract_args_for_cli()
    cmd = _resolve_ytdlp_cli() + [
        "-f", fmt,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "2",
        "--fragment-retries", "2",
        "--user-agent", _YT_UA,
        "--extractor-args", ea,
        "--add-header", "Referer:https://www.youtube.com/",
        "--add-header", "Origin:https://www.youtube.com",
        "--get-url", url
    ]
    if _FORCE_IPV4:
        cmd += ["--force-ipv4"]
    if _HTTP_PROXY:
        cmd += ["--proxy", _HTTP_PROXY]

    spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
    if spec:
        cmd += ["--cookies-from-browser", spec]
    elif cookies_file and os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]
    elif os.path.exists(_COOKIE_FILE_DEFAULT):
        cmd += ["--cookies", _COOKIE_FILE_DEFAULT]

    try:
        # petite sonde 5s max
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if cp.returncode == 0 and (cp.stdout or "").strip():
            return fmt
        # message d'erreur typique de yt-dlp
        err = (cp.stderr or "") + (cp.stdout or "")
        if "Requested format is not available" in err:
            _dbg("[PIPE/FMT] fallback → itag 18 (Requested format is not available)")
            return "18"
    except Exception as e:
        _dbg(f"[PIPE/FMT] probe error (ignore, keep chain): {e}")

    return fmt

# ====== HTTP probe (debug) ======
def _http_probe(url: str, headers: Dict[str, str]) -> None:
    if not _YTDBG_HTTP_PROBE:
        return
    _dbg("HTTP_PROBE: start")
    opener = None
    try:
        handlers = []
        if _HTTP_PROXY:
            handlers.append(_ureq.ProxyHandler({"http": _HTTP_PROXY, "https": _HTTP_PROXY}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        r = _ureq.Request(url, method="HEAD", headers=headers)
        with opener.open(r, timeout=10) as resp:
            _dbg(f"HTTP_PROBE: HEAD {getattr(resp, 'status', resp.getcode())}")
            return
    except Exception as e:
        _dbg(f"HTTP_PROBE: HEAD failed: {e}")
    try:
        req_h2 = dict(headers or {})
        req_h2["Range"] = "bytes=0-1"
        r2 = _ureq.Request(url, method="GET", headers=req_h2)
        resp2 = (opener or _ureq.build_opener()).open(r2, timeout=10)
        with resp2 as resp:
            _dbg(f"HTTP_PROBE: GET Range→ {getattr(resp, 'status', resp.getcode())}, len={resp.headers.get('Content-Length')}")
    except Exception as e:
        _dbg(f"HTTP_PROBE: GET Range failed: {e}")

# ====== Public APIs ======
def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        out = []
        for e in entries:
            title = e.get("title") or "Titre inconnu"
            url = e.get("webpage_url") or e.get("url") or ""
            if not (url.startswith("http://") or url.startswith("https://")):
                vid = e.get("id")
                if vid:
                    url = f"https://www.youtube.com/watch?v={vid}"
            out.append({
                "title": title,
                "url": url,
                "webpage_url": url,
                "duration": e.get("duration"),
                "thumb": e.get("thumbnail"),
                "provider": "youtube",
                "uploader": e.get("uploader"),
            })
        return out

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Résout un flux bestaudio (yt-dlp) puis lit directement l'URL via FFmpeg
    avec headers cohérents + options anti-153/403.
    """
    import asyncio
    _ensure_po_tokens_for(url_or_query)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM request: {url_or_query!r}")

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec,
        ratelimit_bps=ratelimit_bps,
    ))
    if not info:
        raise RuntimeError("Aucun résultat YouTube (aucun client n’a fourni d’URL).")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    client_used = info.get("_dbg_client_used", "unknown")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible (clients bloqués).")

    qs = _parse_qs(stream_url)
    _dbg(f"yt-dlp client_used={client_used}, title={title!r}")
    _dbg(f"URL host={_url.urlsplit(stream_url).hostname}, itag={qs.get('itag')} mime={qs.get('mime')} clen={qs.get('clen')}")
    _dbg(f"URL expire={qs.get('expire')}")

    headers = (info.get("http_headers") or {})
    headers.setdefault("User-Agent", _YT_UA)
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    headers.setdefault("Accept-Language", "en-us,en;q=0.5")
    headers.setdefault("Sec-Fetch-Mode", "navigate")
    headers.setdefault("Referer", "https://www.youtube.com/")
    headers.setdefault("Origin", "https://www.youtube.com")
    hdr_blob = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"

    try:
        _http_probe(stream_url, headers)
    except Exception as e:
        _dbg(f"http_probe error: {e}")

    before_opts = (
        "-nostdin "
        f"-user_agent {shlex.quote(headers['User-Agent'])} "
        f"-headers {shlex.quote(hdr_blob)} "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 -reconnect_delay_max 5 "
        "-rw_timeout 15000000 "
        "-probesize 32k -analyzeduration 0 "
        "-fflags nobuffer -flags low_delay "
        "-seekable 0"
    )
    # ... juste après la construction de before_opts et hdr_blob ...

    out_opts = "-vn -ar 48000 -ac 2 -loglevel warning"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    if _HTTP_PROXY:
        before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"

    _dbg(f"FFMPEG before_options={before_opts}")
    _dbg(f"FFMPEG headers (redacted)={_redact_headers(headers)}")

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options=out_opts,
        executable=ff_exec,
    )
    setattr(source, "_ytdlp_proc", None)
    return source, title

async def stream_pipe(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Fallback "pipe" : yt-dlp → stdout → FFmpeg.
    + Pré-sonde la chaîne de formats et force '18' si indisponible (évite l'erreur immédiate).
    """
    import asyncio, subprocess, shlex, threading

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")
    _dbg(f"FFmpeg exec resolved: {ff_exec}")
    _dbg(f"yt-dlp ffmpeg_location: {ff_loc or '-'}")

    loop = asyncio.get_running_loop()
    # récupère le titre via la meilleure info dispo (non bloquant si None)
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec,
        ratelimit_bps=ratelimit_bps,
    ))
    title = (info or {}).get("title", "Musique inconnue")

    # détermine le format à utiliser (chaîne + '/18' garanti) avec fallback '18' si indispo
    fmt = _pick_pipe_format(url_or_query, cookies_file, cookies_from_browser)

    # --extractor-args : player_client + po_token (si dispo)
    ea = _build_extract_args_for_cli()

    cmd = _resolve_ytdlp_cli() + [
        "-f", fmt,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", ea,
        "--add-header", "Referer:https://www.youtube.com/",
        "--add-header", "Origin:https://www.youtube.com",
        "-o", "-",
        url_or_query,
    ]
    if _FORCE_IPV4:
        cmd += ["--force-ipv4"]
    if _HTTP_PROXY:
        cmd += ["--proxy", _HTTP_PROXY]

    spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
    if spec:
        cmd += ["--cookies-from-browser", spec]
    elif cookies_file and os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]
    elif os.path.exists(_COOKIE_FILE_DEFAULT):
        cmd += ["--cookies", _COOKIE_FILE_DEFAULT]

    if ratelimit_bps:
        cmd += ["--limit-rate", str(int(ratelimit_bps))]

    _dbg(f"yt-dlp PIPE cmd: {' '.join(shlex.quote(c) for c in cmd)}")

    yt = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        close_fds=True,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    def _drain_stderr():
        try:
            while True:
                chunk = yt.stderr.readline()
                if not chunk:
                    break
                try:
                    line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                except Exception:
                    line = repr(chunk)
                if line:
                    print(f"[YTDBG][yt-dlp] {line}")
        except Exception as e:
            print(f"[YTDBG][yt-dlp] <stderr reader died: {e}>")

    threading.Thread(target=_drain_stderr, daemon=True).start()

    out_opts = "-vn -ar 48000 -ac 2 -f s16le"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    # ⚠️ IMPORTANT: pas de '-re' ici ; on garde un pipe bas-latence.
    before_opts = "-nostdin -probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay"

    src = discord.FFmpegPCMAudio(
        source=yt.stdout,
        executable=ff_exec,
        before_options=before_opts,
        options=out_opts,
        pipe=True,
    )

    _dbg(f"FFMPEG source created (PIPE, fmt={fmt}).")

    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title

def _probe_with_client(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
    client: Optional[str] = None,
) -> Optional[dict]:
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
    )
    if client:
        opts.setdefault("extractor_args", {}).setdefault("youtube", {})["player_client"] = [client]

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info and info["entries"]:
            info = info["entries"][0]
        if info is not None:
            info["_dbg_client_used"] = client or "auto"
        return info or None

def _best_info_with_fallbacks(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
) -> Optional[dict]:
    _ensure_po_tokens_for(query)

    info = _probe_with_client(
        query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
        client=None,
    )
    if info and info.get("url"):
        return info

    for c in _CLIENTS_ORDER:
        info = _probe_with_client(
            query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ffmpeg_path,
            ratelimit_bps=ratelimit_bps,
            client=c,
        )
        if info and info.get("url"):
            return info
    return None

def download(
    url: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    out_dir: str = "downloads",
    ratelimit_bps: Optional[int] = 2_500_000,
) -> Tuple[str, str, Optional[int]]:
    import os as _os
    _os.makedirs(out_dir, exist_ok=True)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    opts = _mk_opts(
        ffmpeg_path=ff_loc or ff_exec,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        for_download=True,
    )
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"

    try:
        with YoutubeDL(opts) as ydl:
            _dbg(f"DOWNLOAD start: {url}")
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]

            req = (info or {}).get("requested_downloads") or []
            if req:
                filepath = req[0].get("filepath")
            else:
                base = ydl.prepare_filename(info)
                filepath = os.path.splitext(base)[0] + ".mp3"

            title = (info or {}).get("title", "Musique inconnue")
            duration = (info or {}).get("duration")
            _dbg(f"DOWNLOAD ok: path={filepath}, title={title!r}, dur={duration}")
            return filepath, title, duration
    except DownloadError as e:
        _dbg(f"DOWNLOAD failed: {e}")
        if "Requested format is not available" in str(e):
            opts2 = _mk_opts(
                ffmpeg_path=ff_loc or ff_exec,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                ratelimit_bps=ratelimit_bps,
                for_download=True,
            )
            opts2["format"] = "18"
            opts2["paths"] = {"home": out_dir}
            opts2["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"
            with YoutubeDL(opts2) as ydl2:
                _dbg("DOWNLOAD fallback: itag=18")
                info = ydl2.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = req[0].get("filepath") if req else (os.path.splitext(ydl2.prepare_filename(info))[0] + ".mp3")
                title = (info or {}).get("title", "Musique inconnue")
                duration = (info or {}).get("duration")
                _dbg(f"DOWNLOAD fallback ok: path={filepath}, title={title!r}, dur={duration}")
                return filepath, title, duration
        raise RuntimeError(f"Échec download YouTube: {e}") from e
