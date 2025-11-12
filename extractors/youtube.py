# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — auto PO_TOKEN + cookies + anti-403/153
# - Clients sûrs: ios → android → web_creator → web → web_mobile
# - PO Token: auto via Playwright (m.youtube.com) sinon fallback .env YT_PO_TOKEN
# - STREAM direct: URL + headers → FFmpeg (reconnect, low-latency)
# - STREAM PIPE: yt-dlp → stdout → FFmpeg (préflight 2s + fallback -f 18)
# - DOWNLOAD: MP3 (192kbps, 48kHz) avec fallback itag 18
# - Cookies: YTDLP_COOKIES_BROWSER ou YTDLP_COOKIES_B64 (Netscape)
# - Proxy: YTDLP_HTTP_PROXY / HTTPS_PROXY / ALL_PROXY propagé à yt-dlp & FFmpeg
# - IPv4: source_address=0.0.0.0 + --force-ipv4 pour le PIPE
# - Recherche: ytsearch5 (flat)
from __future__ import annotations

import base64
import functools
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse as _url
import urllib.request as _ureq
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# ==== DEBUG flags ====
_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")
_YTDBG_HTTP_PROBE = os.getenv("YTDBG_HTTP_PROBE", "0").lower() not in ("0", "false", "")

def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}")

def _redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = dict(h or {})
    for k in list(out.keys()):
        if k.lower() in ("cookie", "authorization", "x-youtube-identity-token", "x-goog-authuser"):
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
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u) or ("music.youtube.com/watch" in u)

# ==== ENV / defaults ====
_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
_FORCE_IPV4 = os.getenv("YTDLP_FORCE_IPV4", "1").lower() not in ("0", "false", "")
_HTTP_PROXY = os.getenv("YTDLP_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

_CLIENTS_ORDER = ["web_mobile", "web", "ios", "android", "web_creator" ]

_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    # opus/webm prioritaire, puis m4a; secours ID; et enfin HLS/best génériques (utile quand SABR casse le reste)
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/18/best[protocol^=m3u8]/best"
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"

# Fallback auto → passer sur PIPE si 403/410 détecté en pré-sondage GVS
_AUTO_PIPE_ON_403 = os.getenv("YTDLP_AUTO_PIPE_ON_403", "1").lower() not in ("0", "false", "")

# ==== PO tokens (peuvent être remplis dynamiquement) ====
_PO_TOKENS: List[str] = []

def _collect_po_tokens_from_env() -> List[str]:
    raw = (os.getenv("YT_PO_TOKEN") or os.getenv("YTDLP_PO_TOKEN") or "").strip()
    prefixed = (os.getenv("YT_PO_TOKEN_PREFIXED") or "").strip()
    out: List[str] = []
    if raw and "+" not in raw:
        out += [f"ios.gvs+{raw}", f"android.gvs+{raw}", f"web.gvs+{raw}"]
    if raw and "+" in raw:
        out.append(raw)
    if prefixed:
        out.append(prefixed)
    # dédup
    seen = set()
    dedup = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            dedup.append(t)
    if dedup:
        _dbg(f"ENV PO tokens → {', '.join(t.split('+',1)[0] for t in dedup)}")
    return dedup

def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    def _abs(p: str) -> str:
        return os.path.abspath(os.path.expanduser(p))
    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        if which:
            return which, os.path.dirname(which)
        return "ffmpeg", None
    p = _abs(ffmpeg_hint)
    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand): return cand, p
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2): return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans: {p}")
    if os.path.isfile(p):
        return p, os.path.dirname(p)
    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)
    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")

def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
        text = raw.decode("utf-8", errors="replace")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(text)
        _dbg(f"cookies: written from env to {target_path} ({len(text)} chars)")
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

# ==== yt-dlp opts builder ====
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
        "extractor_args": {
            "youtube": {
                "player_client": list(_CLIENTS_ORDER),
            }
        },
        "youtube_include_dash_manifest": True,
        "hls_prefer_native": True,   # ★ évite certaines régressions quand YT force SABR
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

# ==== PO token auto/fallback ====
_YTID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_\-]{8,})")

def _extract_video_id(s: str) -> Optional[str]:
    m = _YTID_RE.search(s or "")
    return m.group(1) if m else None

def _ensure_po_tokens_for(query_or_url: str, ffmpeg_hint: Optional[str]) -> None:
    """ Tente d'obtenir un PO token auto; sinon fallback ENV. """
    global _PO_TOKENS
    if _PO_TOKENS:
        return

    # 1) tentative ENV d'abord ? → non, on tente AUTO d'abord (comme demandé)
    vid = _extract_video_id(query_or_url)

    if not vid:
        # récupère via yt-dlp l'id si on a une recherche/titre
        try:
            with YoutubeDL(_mk_opts()) as ydl:
                info = ydl.extract_info(query_or_url, download=False)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                vid = (info or {}).get("id")
        except Exception:
            vid = None

    token_from_env = _collect_po_tokens_from_env()

    try:
        from extractors.token_fetcher import fetch_po_token
    except Exception:
        fetch_po_token = None  # type: ignore

    auto_token = None
    if fetch_po_token and vid:
        try:
            auto = fetch_po_token(vid, timeout_ms=15000)
            if auto and isinstance(auto, str) and len(auto) > 10:
                auto_token = auto
        except Exception as e:
            _dbg(f"auto po_token failed: {e}")

    final: List[str] = []
    if auto_token:
        final += [f"ios.gvs+{auto_token}", f"android.gvs+{auto_token}", f"web.gvs+{auto_token}"]
    elif token_from_env:
        final += token_from_env

    # dédup
    seen = set()
    _PO_TOKENS = [t for t in final if (t and (t not in seen) and not seen.add(t))]
    if _PO_TOKENS:
        _dbg(f"PO tokens set: {', '.join(t.split('+',1)[0] for t in _PO_TOKENS)}")
    else:
        _dbg("PO tokens: none (will continue without)")

# ==== search ====
def _normalize_search_entries(entries: List[dict]) -> List[dict]:
    out = []
    for e in entries or []:
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

def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        return _normalize_search_entries(entries)

# ==== playlist / mix ====
from urllib.parse import urlparse, parse_qs
def is_playlist_or_mix_url(url: str) -> bool:
    try:
        u = urlparse(url)
        if not u.netloc:
            return False
        if "youtube.com" not in u.netloc and "youtu.be" not in u.netloc and "music.youtube.com" not in u.netloc:
            return False
        q = parse_qs(u.query)
        lst = (q.get("list") or [None])[0]
        if lst:
            return True
        if u.path.strip("/").lower() == "playlist" and lst:
            return True
        return False
    except Exception:
        return False

def is_playlist_like(url: str) -> bool:
    return is_playlist_or_mix_url(url)

def expand_bundle(
    page_url: str,
    limit_total: Optional[int] = None,
    limit: Optional[int] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> List[Dict]:
    import yt_dlp
    N = int(limit_total or limit or 10)

    parsed = urlparse(page_url)
    q = parse_qs(parsed.query)
    list_id = (q.get("list") or [None])[0]
    start_idx: Optional[int] = None
    try:
        raw_idx = (q.get("index") or [None])[0]
        if raw_idx is not None:
            start_idx = max(1, int(raw_idx))
    except Exception:
        start_idx = None

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": False,
        "playlistend": N,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": { "youtube": { "player_client": list(_CLIENTS_ORDER) } }
    }
    if start_idx:
        ydl_opts["playliststart"] = start_idx
        ydl_opts["playlistend"]   = start_idx + N - 1
    else:
        ydl_opts["playlistend"] = N

    if _PO_TOKENS:
        ydl_opts["extractor_args"]["youtube"]["po_token"] = ",".join(_PO_TOKENS)

    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = tuple(
            cookies_from_browser.split(":", 1)
        ) if ":" in cookies_from_browser else (cookies_from_browser,)

    def _extract(u):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(u, download=False)

    info = _extract(page_url)

    if (not info or not info.get("entries")) and list_id:
        playlist_url = f"https://www.youtube.com/playlist?list={list_id}"
        info2 = _extract(playlist_url)
        if info2 and info2.get("entries"):
            info = info2

    if (not info or not info.get("entries")) and info and info.get("_type") == "url":
        try:
            info3 = _extract(info["url"])
            if info3 and info3.get("entries"):
                info = info3
        except Exception:
            pass

    entries = (info or {}).get("entries") or []
    if not entries:
        return []

    v_id = None
    try:
        v_id = (parse_qs(urlparse(page_url).query).get("v") or [None])[0]
    except Exception:
        v_id = None

    if v_id and not start_idx:
        try:
            idx = next((i for i, e in enumerate(entries) if (e.get("id") or e.get("url")) == v_id), None)
            if idx is not None:
                entries = entries[idx:] + entries[:idx]
        except Exception:
            pass

    out: List[Dict] = []
    for e in entries:
        vid = e.get("id") or e.get("url")
        if not vid:
            continue
        title = e.get("title") or ""
        artist = e.get("uploader") or e.get("channel") or e.get("uploader_id")
        thumb = e.get("thumbnail") or (e.get("thumbnails") or [{}])[-1].get("url") or None
        dur = e.get("duration")
        url = f"https://www.youtube.com/watch?v={vid}"
        if list_id:
            url += f"&list={list_id}"
        out.append({
            "title": title or url,
            "url": url,
            "webpage_url": url,
            "artist": artist,
            "thumb": thumb,
            "duration": dur,
            "provider": "youtube",
        })
        if len(out) >= N:
            break
    return out

def _http_probe(url: str, headers: Dict[str, str]) -> Optional[int]:
    """
    HEAD puis GET Range pour tester rapidement l’accessibilité GVS.
    Retourne le code HTTP significatif (ex. 200, 206, 403, 410, …) ou None si indéterminé.
    """
    if not _YTDBG_HTTP_PROBE:
        # En mode normal, on fait quand même un HEAD court pour lire le code
        pass
    opener = None
    try:
        handlers = []
        if _HTTP_PROXY:
            handlers.append(_ureq.ProxyHandler({"http": _HTTP_PROXY, "https": _HTTP_PROXY}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        r = _ureq.Request(url, method="HEAD", headers=headers)
        with opener.open(r, timeout=8) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            _dbg(f"HTTP_PROBE: HEAD {code}")
            return int(code)
    except Exception as e:
        _dbg(f"HTTP_PROBE: HEAD failed: {e}")
    try:
        req_h2 = dict(headers or {})
        req_h2["Range"] = "bytes=0-1"
        r2 = _ureq.Request(url, method="GET", headers=req_h2)
        resp2 = (opener or _ureq.build_opener()).open(r2, timeout=8)
        with resp2 as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            _dbg(f"HTTP_PROBE: GET Range {code} (len={resp.headers.get('Content-Length')})")
            return int(code)
    except Exception as e:
        _dbg(f"HTTP_PROBE: GET Range failed: {e}")
        return None

# ==== STREAM direct (URL) ====
async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    import asyncio

    _ensure_po_tokens_for(url_or_query, ffmpeg_path)

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
    if not stream_url:
        raise RuntimeError("Flux audio indisponible (clients bloqués).")

    # --- headers minimaux & pas de double UA ---
    headers = dict(info.get("http_headers") or {})
    ua = headers.pop("User-Agent", _YT_UA)  # on retire le UA du blob, on le met SEULEMENT via -user_agent
    # impose au minimum Referer/Origin (le reste est inutile et parfois nuisible)
    headers["Referer"] = "https://www.youtube.com/"
    headers["Origin"] = "https://www.youtube.com"
    # NE PAS remettre Accept/Accept-Language/Sec-Fetch-*
    hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

    # Probe HTTP rapide
    code = _http_probe(stream_url, {"User-Agent": ua, "Referer": "https://www.youtube.com/",
                                    "Origin": "https://www.youtube.com"}) or 200
    if _AUTO_PIPE_ON_403 and code in (403, 410):
        _dbg(f"STREAM: probe got HTTP {code} → auto fallback to PIPE")
        return await stream_pipe(
            url_or_query, ffmpeg_path,
            cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps, afilter=afilter,
        )

    # --- preflight 2s FFmpeg→null : si ça bloque, on fallback PIPE ---
    def _preflight_direct_ok() -> bool:
        try:
            cmd = [
                ff_exec,
                "-nostdin",
                "-user_agent", ua,
                "-headers", hdr_blob,
                "-probesize", "32k",
                "-analyzeduration", "0",
                # flags allégés (PLUS de -avioflags direct, PLUS de -http_persistent 0)
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-rw_timeout", "15000000",  # 15 sec
                "-protocol_whitelist", "file,https,tcp,tls,crypto",
                "-i", stream_url,
                "-t", "2",
                "-f", "null", "-"
            ]
            # seconds(2) + marge réseau 12–15 s
            cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=18)
            return cp.returncode == 0
        except Exception as e:
            _dbg(f"preflight direct failed: {e}")
            return False

    if not _preflight_direct_ok():
        _dbg("STREAM: direct preflight failed → fallback to PIPE")
        return await stream_pipe(
            url_or_query, ffmpeg_path,
            cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps, afilter=afilter,
        )

    # --- options finales (direct) : UA via -user_agent, headers/min, flags soft ---
    before_opts = (
        "-nostdin "
        f"-user_agent {shlex.quote(ua)} "
        f"-headers {shlex.quote(hdr_blob)} "
        "-probesize 32k -analyzeduration 0 "
        "-fflags nobuffer -flags low_delay "
        "-rw_timeout 15000000 "
        "-protocol_whitelist file,https,tcp,tls,crypto"
    )
    if _HTTP_PROXY:
        before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"

    out_opts = "-vn -ar 48000 -ac 2 -loglevel warning"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    _dbg(f"FFMPEG before_options={before_opts}")
    _dbg(
        f"FFMPEG headers (redacted)={_redact_headers({'Referer': 'https://www.youtube.com/', 'Origin': 'https://www.youtube.com'})}")

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options=out_opts,
        executable=ff_exec,
    )
    setattr(source, "_ytdlp_proc", None)
    return source, title

# ==== helpers: info with fallbacks ====
def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]

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
    _dbg(f"_best_info_with_fallbacks(query={query})")
    info = _probe_with_client(
        query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
        client=None,
    )
    if info and info.get("url"):
        _dbg(f"yt-dlp chose client={info.get('_dbg_client_used')}, title={info.get('title')!r}")
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
            _dbg(f"fallback client={c} worked, title={info.get('title')!r}")
            return info
        else:
            _dbg(f"client={c} → no direct url")
    return None

# ==== STREAM PIPE (préflight + fallback itag18) ====
async def stream_pipe(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    import asyncio

    _ensure_po_tokens_for(url_or_query, ffmpeg_path)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec,
        ratelimit_bps=ratelimit_bps,
    ))
    title = (info or {}).get("title", "Musique inconnue")

    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if _PO_TOKENS:
        ea_parts.append(f"po_token={','.join(_PO_TOKENS)}")
    ea = "youtube:" + ";".join(ea_parts)

    def _build_cmd(format_str: str) -> List[str]:
        cmd = _resolve_ytdlp_cli() + [
            "-f", format_str,
            "--no-playlist",
            "--no-check-certificates",
            "--retries", "5",
            "--fragment-retries", "5",
            "--concurrent-fragments", "1",  # ★ limite la pression réseau
            "--newline",
            "--user-agent", _YT_UA,
            "--extractor-args", ea,
            "--add-header", "Referer:https://www.youtube.com/",
            "--add-header", "Origin:https://www.youtube.com",
            "-o", "-",
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
        cmd += [url_or_query]
        return cmd

    def _preflight_and_choose_format() -> str:
        """ Teste le chainage yt-dlp -> ffmpeg pendant ~2s.
            Si ffmpeg échoue vite ou si yt-dlp log 'Requested format is not available'
            → fallback itag 18. """
        # 1) essai format chaîne
        primary_fmt = _FORMAT_CHAIN
        for attempt, fmt in enumerate([primary_fmt, "18"]):
            cmd = _build_cmd(fmt)
            _dbg(f"yt-dlp PRE-FLIGHT (attempt={attempt}, fmt={fmt}): {' '.join(shlex.quote(c) for c in cmd)}")
            yt = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=False, bufsize=0, close_fds=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            # ffmpeg → nul (2 secondes)
            ff = subprocess.Popen(
                [ff_exec, "-nostdin", "-probesize", "32k", "-analyzeduration", "0",
                 "-fflags", "nobuffer", "-flags", "low_delay",
                 "-i", "pipe:0", "-t", "2", "-f", "null", "-"],
                stdin=yt.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            try:
                out = ff.communicate(timeout=6)[0] or ""
            except subprocess.TimeoutExpired:
                try:
                    ff.kill()
                except Exception:
                    pass
                try:
                    yt.kill()
                except Exception:
                    pass
                # si ça tourne encore >6s, c'est bon signe -> on garde primary_fmt
                return fmt if attempt == 0 else "18"

            # if ffmpeg exit != 0 or yt-dlp said format not available → retry fmt=18
            rc = ff.returncode
            stderr_join = ""
            try:
                stderr_join = (yt.stderr.read() or b"").decode("utf-8", errors="replace")
            except Exception:
                pass
            try:
                yt.kill()
            except Exception:
                pass

            if rc == 0 and "Requested format is not available" not in stderr_join:
                return fmt
            _dbg(f"preflight rc={rc}, yt-stderr-match={'Requested format is not available' in stderr_join}")
        return "18"

    chosen_fmt = _preflight_and_choose_format()
    _dbg(f"PIPE chosen format: {chosen_fmt}")

    # Lance la vraie lecture pour Discord
    cmd = _build_cmd(chosen_fmt)
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

    before_opts = "-nostdin -re -probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay"
    out_opts = "-vn -ar 48000 -ac 2 -f s16le"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(
        source=yt.stdout,
        executable=ff_exec,
        before_options=before_opts,
        options=out_opts,
        pipe=True,
    )
    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title

# ==== DOWNLOAD ====
def download(
    url: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    out_dir: str = "downloads",
    ratelimit_bps: Optional[int] = 2_500_000,
) -> Tuple[str, str, Optional[int]]:
    os.makedirs(out_dir, exist_ok=True)

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





# ==== DIAGNOSTICS / TESTS LOCAUX ===========================================
# Usage (depuis le repo):
#   python -m extractors.youtube diag --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
#   python -m extractors.youtube diag --query "lofi hip hop"
#   python -m extractors.youtube env
#   python -m extractors.youtube token --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
#   python -m extractors.youtube direct --url "..." --ffmpeg /usr/bin/ffmpeg --seconds 3
#   python -m extractors.youtube pipe --url "..." --ffmpeg /usr/bin/ffmpeg --seconds 3
#   python -m extractors.youtube download --url "..." --ffmpeg /usr/bin/ffmpeg --out /tmp
#
# Astuces utiles en local:
#   setx YTDLP_COOKIES_BROWSER "chrome:Default"         # Windows (PowerShell)
#   export YTDLP_COOKIES_BROWSER="chromium:Default"     # Linux
#   export YTDLP_COOKIES_B64="$(base64 -w0 cookies.txt)" # Netscape cookies
#   export YT_PO_TOKEN="..."                            # fallback si auto-fetch échoue
#   export YTDLP_HTTP_PROXY="http://127.0.0.1:8888"     # proxy (mitm/proxy rési)
# ===========================================================================

def _print_env_summary_local():
    import platform
    print("\n=== ENV / VERSIONS ===")
    print("Python        :", sys.version.replace("\n", " "))
    try:
        import yt_dlp as _yt
        print("yt-dlp        :", getattr(_yt, "__version__", "?"))
    except Exception as e:
        print("yt-dlp        : <import FAIL>", e)
    try:
        import discord as _dc
        print("discord.py    :", getattr(_dc, "__version__", "?"))
    except Exception as e:
        print("discord.py    : <import FAIL>", e)
    print("Platform      :", platform.platform())
    print("IPv4 forced   :", _FORCE_IPV4)
    print("User-Agent    :", _YT_UA[:120] + ("..." if len(_YT_UA) > 120 else ""))
    print("Proxy         :", _HTTP_PROXY or "none")
    print("CookiesFromBr :", os.getenv("YTDLP_COOKIES_BROWSER") or "none")
    print("CookiesB64    :", "set" if os.getenv("YTDLP_COOKIES_B64") else "unset")
    print("YT_PO_TOKEN   :", "set" if (os.getenv("YT_PO_TOKEN") or os.getenv("YTDLP_PO_TOKEN") or os.getenv("YT_PO_TOKEN_PREFIXED")) else "unset")
    print("=======================\n")

def _dns_check(hosts: List[str]):
    import socket
    print("=== DNS CHECK ===")
    for h in hosts:
        try:
            fam = socket.AF_INET if _FORCE_IPV4 else 0
            res = socket.getaddrinfo(h, 443, fam, socket.SOCK_STREAM)
            addrs = sorted({r[4][0] for r in res})
            print(f"{h:40s} -> {', '.join(addrs[:5])}" + (" ..." if len(addrs) > 5 else ""))
        except Exception as e:
            print(f"{h:40s} -> <DNS FAIL> {e}")
    print("=================\n")

def _ffmpeg_version(ffmpeg_hint: Optional[str] = None):
    try:
        ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_hint)
        cp = subprocess.run([ff_exec, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
        line0 = (cp.stdout or "").splitlines()[0] if cp.stdout else ""
        print("FFmpeg        :", line0.strip() or f"<rc {cp.returncode}>")
        return ff_exec
    except Exception as e:
        print("FFmpeg        : <NOT FOUND>", e)
        return None

def _classify_common_failure(text: str) -> str:
    t = text.lower()
    if "requested format is not available" in t:
        return "yt-dlp: Requested format not available (essaye -f 18 / cookies / autre client)."
    if "http error 403" in t or "403 forbidden" in t or "permission denied" in t:
        return "403: SABR/geo/cookies/UA/Referer/Origin — tente PO-token, cookies, proxy résident, clients iOS/Android."
    if "http error 410" in t or "410 gone" in t:
        return "410: URL GVS expirée — re-résoudre puis lancer rapidement FFmpeg."
    if "unknown error" in t and "innertube" in t:
        return "Innertube player: blocage côté Player — change de client/PO-token/cookies."
    if "ssl" in t and ("cert" in t or "handshake" in t):
        return "TLS/SSL: certif/proxy — vérifie proxy MITM ou certs système."
    if "name or service not known" in t or "temporary failure in name resolution" in t:
        return "DNS: résolution hôte cassée — résout googlevideo.com / youtube.com."
    if "connection reset" in t or "broken pipe" in t:
        return "Réseau instable / proxy — active reconnect FFmpeg, change d’IP/proxy."
    return "Inconnu: ouvrir logs YTDBG et observer étapes Player → GVS."

def _diag_player_resolution(query_or_url: str, ffmpeg_hint: Optional[str]):
    print("=== STEP 1: PLAYER RESOLUTION (yt-dlp) ===")
    try:
        info = _best_info_with_fallbacks(
            query_or_url,
            cookies_file=_COOKIE_FILE_DEFAULT if os.path.exists(_COOKIE_FILE_DEFAULT) else None,
            cookies_from_browser=os.getenv("YTDLP_COOKIES_BROWSER"),
            ffmpeg_path=_resolve_ffmpeg_paths(ffmpeg_hint)[0] if ffmpeg_hint else None,
            ratelimit_bps=None,
        )
        if not info:
            print("Player: <NO INFO> — aucun format résolu.")
            return None
        url = info.get("url")
        title = info.get("title")
        client = info.get("_dbg_client_used")
        headers = info.get("http_headers") or {}
        print("Player: OK")
        print("  title  :", title)
        print("  client :", client)
        print("  hasURL :", bool(url))
        print("  headers:", _redact_headers(headers))
        return info
    except Exception as e:
        print("Player: <FAIL>", e)
        return None
    finally:
        print("===============================\n")

def _diag_gvs_pull(stream_url: str, headers: Dict[str, str], ffmpeg_exec: str, seconds: int = 3):
    print("=== STEP 2: GVS PULL (FFmpeg direct) ===")
    try:
        ua = headers.get("User-Agent", _YT_UA)
        hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

        before_opts = [
            "-nostdin",
            "-user_agent", ua,
            "-headers", hdr_blob,
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_at_eof", "1", "-reconnect_delay_max", "5",
            "-rw_timeout", "15000000",
            "-probesize", "32k", "-analyzeduration", "0",
            "-fflags", "nobuffer", "-flags", "low_delay",
            # retiré: "-seekable","0", "-http_persistent","0", "-avioflags","direct",
            "-protocol_whitelist", "file,https,tcp,tls,crypto",
        ]
        if _HTTP_PROXY:
            before_opts += ["-http_proxy", _HTTP_PROXY]

        cmd = [ffmpeg_exec] + before_opts + ["-i", stream_url, "-t", str(seconds), "-f", "null", "-"]
        print("FFmpeg cmd   :", " ".join(shlex.quote(c) for c in cmd[:10]), "...")

        # seconds + marge réseau (au moins 18–20)
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=seconds + 20)
        rc = cp.returncode
        print("FFmpeg rc    :", rc)
        tail = (cp.stdout or "")
        print("FFmpeg tail  :\n", "\n".join(tail.splitlines()[-12:]))
        if rc != 0:
            print("Diagnosis    :", _classify_common_failure(tail))
        else:
            print("Diagnosis    : GVS direct OK (headers valides).")
    except Exception as e:
        print("GVS pull     : <FAIL>", e)
        print("Diagnosis    :", _classify_common_failure(str(e)))
    finally:
        print("===============================\n")

def _diag_pipe_preflight(url_or_query: str, ffmpeg_exec: str, seconds: int = 3):
    print("=== STEP 3: PIPE PRE-FLIGHT (yt-dlp → FFmpeg) ===")
    try:
        ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
        if _PO_TOKENS:
            ea_parts.append(f"po_token={','.join(_PO_TOKENS)}")
        ea = "youtube:" + ";".join(ea_parts)

        def build_cmd(fmt: str) -> List[str]:
            cmd = _resolve_ytdlp_cli() + [
                "-f", fmt,
                "--no-playlist",
                "--no-check-certificates",
                "--retries", "3",
                "--fragment-retries", "3",
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
            spec = os.getenv("YTDLP_COOKIES_BROWSER")
            if spec:
                cmd += ["--cookies-from-browser", spec]
            elif os.path.exists(_COOKIE_FILE_DEFAULT):
                cmd += ["--cookies", _COOKIE_FILE_DEFAULT]
            return cmd

        for attempt, fmt in enumerate([_FORMAT_CHAIN, "18"]):
            print(f"Attempt {attempt}: fmt={fmt}")
            yt = subprocess.Popen(build_cmd(fmt), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
            ff = subprocess.Popen(
                [ffmpeg_exec, "-nostdin", "-probesize", "32k", "-analyzeduration", "0", "-fflags", "nobuffer", "-flags", "low_delay",
                 "-i", "pipe:0", "-t", str(seconds), "-f", "null", "-"],
                stdin=yt.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            try:
                out = ff.communicate(timeout=seconds+6)[0] or ""
            except subprocess.TimeoutExpired:
                try: ff.kill()
                except: pass
                try: yt.kill()
                except: pass
                print("Preflight    : TIMEOUT>OK (flux se maintient) — fmt valide.")
                return
            finally:
                try: yt.kill()
                except: pass

            rc = ff.returncode
            err = ""
            try:
                err = (yt.stderr.read() or b"").decode("utf-8", errors="replace")
            except Exception:
                pass

            print("rc           :", rc)
            if rc == 0 and "Requested format is not available" not in err:
                print("Diagnosis    : PIPE OK (fmt accepté).")
                return
            if "Requested format is not available" in err:
                print("Diagnosis    : fmt indisponible → on essaie itag 18.")
                continue
            print("Tail (ff)    :\n", "\n".join(out.splitlines()[-8:]))
            print("Tail (yt)    :\n", "\n".join(err.splitlines()[-8:]))
            print("Diagnosis    :", _classify_common_failure(out + "\n" + err))
        print("Final        : PIPE KO même avec -f 18 — voir cookies/PO-token/proxy/IP.")
    except Exception as e:
        print("PIPE         : <FAIL>", e)
        print("Diagnosis    :", _classify_common_failure(str(e)))
    finally:
        print("===============================\n")

def _diag_all(url: Optional[str], query: Optional[str], ffmpeg_hint: Optional[str], seconds: int):
    _print_env_summary_local()
    _dns_check(["www.youtube.com", "m.youtube.com", "music.youtube.com", "r5---sn-25ge7nzk.googlevideo.com", "googlevideo.com"])
    ff_exec = _ffmpeg_version(ffmpeg_hint)
    if not ff_exec:
        print("⛔ FFmpeg introuvable — installe-le ou donne --ffmpeg.")
        return

    subject = url or query or "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    print("Sujet        :", subject)

    # PO-token (auto puis env)
    try:
        _ensure_po_tokens_for(subject, ffmpeg_hint)
    except Exception as e:
        print("PO-token     : auto-fetch FAIL", e)

    info = _diag_player_resolution(subject, ffmpeg_hint)
    if info and info.get("url"):
        hdrs = info.get("http_headers") or {}
        hdrs.setdefault("User-Agent", _YT_UA)
        hdrs.setdefault("Referer", "https://www.youtube.com/")
        hdrs.setdefault("Origin", "https://www.youtube.com")
        _diag_gvs_pull(info["url"], hdrs, ff_exec, seconds=seconds)
    else:
        print("⟶ Skip GVS direct: pas d’URL Player.")

    _diag_pipe_preflight(subject, ff_exec, seconds=seconds)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser("YouTube extractor diagnostics")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="Afficher info ENV/versions/DNS/FFmpeg")

    p_diag = sub.add_parser("diag", help="Diagnostic complet (Player→GVS + PIPE)")
    p_diag.add_argument("--url")
    p_diag.add_argument("--query")
    p_diag.add_argument("--ffmpeg")
    p_diag.add_argument("--seconds", type=int, default=3)

    p_tok = sub.add_parser("token", help="Essai d'auto-récupération PO-token + ENV")
    p_tok.add_argument("--url", required=True)

    p_direct = sub.add_parser("direct", help="Test GVS direct (FFmpeg null sink)")
    p_direct.add_argument("--url", required=True)
    p_direct.add_argument("--ffmpeg", required=True)
    p_direct.add_argument("--seconds", type=int, default=3)

    p_pipe = sub.add_parser("pipe", help="Test PIPE (yt-dlp→ffmpeg) sur 2–3 s")
    p_pipe.add_argument("--url", required=True)
    p_pipe.add_argument("--ffmpeg", required=True)
    p_pipe.add_argument("--seconds", type=int, default=3)

    p_dl = sub.add_parser("download", help="Télécharger & convertir (mp3)")
    p_dl.add_argument("--url", required=True)
    p_dl.add_argument("--ffmpeg")
    p_dl.add_argument("--out", default="downloads")

    args = parser.parse_args()

    if args.cmd == "env":
        _print_env_summary_local()
        _dns_check(["www.youtube.com", "m.youtube.com", "music.youtube.com", "googlevideo.com"])
        _ffmpeg_version()
        sys.exit(0)

    if args.cmd == "token":
        _print_env_summary_local()
        _ensure_po_tokens_for(args.url, None)
        print("PO tokens    :", _PO_TOKENS or "<none>")
        sys.exit(0)

    if args.cmd == "diag":
        _diag_all(args.url, args.query, args.ffmpeg, args.seconds)
        sys.exit(0)

    if args.cmd == "direct":
        ff = _ffmpeg_version(args.ffmpeg)

        if not ff:
                sys.exit(2)
        # Accepter indifféremment une URL YouTube (page) OU une URL GVS (manifest.googlevideo...)
        url = args.url.strip()
        hdrs = {
                "User-Agent": _YT_UA,
                "Referer": "https://www.youtube.com/",
                "Origin": "https://www.youtube.com",
            }
        try:
            if ("youtube.com" in url) or ("youtu.be" in url) or ("music.youtube.com" in url):
                info = _best_info_with_fallbacks(
                                    url,
                                    cookies_file = _COOKIE_FILE_DEFAULT if os.path.exists(
                        _COOKIE_FILE_DEFAULT) else None,
                                cookies_from_browser = os.getenv("YTDLP_COOKIES_BROWSER"),
                                ffmpeg_path = ff,
                                ratelimit_bps = None,
                            )
                if not info or not info.get("url"):
                    print("Direct: impossible de résoudre l’URL de flux depuis la page YouTube.")
                    sys.exit(3)
                if info.get("http_headers"):
                    hdrs.update(info["http_headers"])
                url = info["url"]
        except Exception as e:
            print("Direct: résolution Player → GVS échouée:", e)
            sys.exit(3)
        _diag_gvs_pull(url, hdrs, ff, seconds=args.seconds)

    if args.cmd == "pipe":
        ff = _ffmpeg_version(args.ffmpeg)
        if not ff:
            sys.exit(2)
        _diag_pipe_preflight(args.url, ff, seconds=args.seconds)
        sys.exit(0)

    if args.cmd == "download":
        _print_env_summary_local()
        ff = args.ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
        try:
            path, title, dur = download(
                args.url, ff,
                cookies_file=_COOKIE_FILE_DEFAULT if os.path.exists(_COOKIE_FILE_DEFAULT) else None,
                cookies_from_browser=os.getenv("YTDLP_COOKIES_BROWSER"),
                out_dir=args.out,
            )
            print("Download OK  :", path, "|", title, "|", dur)
            sys.exit(0)
        except Exception as e:
            print("Download FAIL:", e)
            print("Diagnosis    :", _classify_common_failure(str(e)))
            sys.exit(3)
