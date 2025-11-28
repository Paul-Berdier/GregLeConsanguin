# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — auto PO_TOKEN + cookies + anti-403/429/153
# - Clients (override via YTDLP_CLIENTS): ios, android, web_creator, web, web_mobile
# - PO Token: auto via extractors.token_fetcher (Playwright) ou fallback .env (YT_PO_TOKEN / YTDLP_PO_TOKEN)
# - STREAM direct: URL+headers → FFmpeg (low-latency, preflight)
# - STREAM PIPE: yt-dlp → stdout → FFmpeg (préflight 2s + fallback itag 18)
# - DOWNLOAD: MP3 (192kbps, 48kHz) avec fallback itag 18
# - Cookies: YTDLP_COOKIES_BROWSER / YOUTUBE_COOKIES_PATH / YTDLP_COOKIES_B64 / youtube.com_cookies.txt
# - Proxy: YTDLP_HTTP_PROXY/HTTPS_PROXY/ALL_PROXY propagés à yt-dlp & FFmpeg
# - IPv4: source_address=0.0.0.0 + --force-ipv4 pour le PIPE
# - Recherche: ytsearch5 (flat)
from __future__ import annotations

import argparse
import base64
import functools
import os
import re
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

__all__ = [
    "is_valid", "search",
    "is_playlist_like", "expand_bundle",
    "stream", "stream_pipe", "download",
    "safe_cleanup",
]

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

_clients_env = os.getenv("YTDLP_CLIENTS")
if _clients_env:
    _CLIENTS_ORDER = [c.strip() for c in _clients_env.split(",") if c.strip()]
else:
    _CLIENTS_ORDER = ["ios", "android", "web_creator", "web", "web_mobile"]

_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/18/best[protocol^=m3u8]/best"
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"

_AUTO_PIPE_ON_403 = os.getenv("YTDLP_AUTO_PIPE_ON_403", "1").lower() not in ("0", "false", "")

# ==== PO tokens ====
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
    # dedup
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

def _pick_cookiefile(cookies_file: Optional[str]) -> Optional[str]:
    """Ordre de priorité: paramètre → env:YOUTUBE_COOKIES_PATH → local → YTDLP_COOKIES_B64."""
    if cookies_file and os.path.exists(cookies_file):
        return cookies_file
    env_path = os.getenv("YOUTUBE_COOKIES_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    if os.path.exists(_COOKIE_FILE_DEFAULT):
        return _COOKIE_FILE_DEFAULT
    if os.getenv("YTDLP_COOKIES_B64"):
        _ensure_cookiefile_from_b64(_COOKIE_FILE_DEFAULT)
        if os.path.exists(_COOKIE_FILE_DEFAULT):
            return _COOKIE_FILE_DEFAULT
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

    cookies_file = _pick_cookiefile(cookies_file)

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
        "hls_prefer_native": True,
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
_YTID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_\-]{11})")

def _extract_video_id(s: str) -> Optional[str]:
    m = _YTID_RE.search(s or "")
    return m.group(1) if m else None

def _ensure_po_tokens_for(query_or_url: str, ffmpeg_hint: Optional[str]) -> None:
    """ Tente d'obtenir un PO token auto; sinon fallback ENV; sinon rien. """
    global _PO_TOKENS
    if _PO_TOKENS:
        return

    vid = _extract_video_id(query_or_url)

    if not vid:
        try:
            with YoutubeDL(_mk_opts()) as ydl:
                info = ydl.extract_info(query_or_url, download=False)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                vid = (info or {}).get("id")
        except Exception:
            vid = None

    token_from_env = _collect_po_tokens_from_env()

    auto_token = None
    if vid:
        try:
            from extractors.token_fetcher import fetch_po_token
        except Exception:
            fetch_po_token = None  # type: ignore

        if fetch_po_token:
            try:
                _dbg(f"PO: attempting auto-fetch for video {vid}")
                auto = fetch_po_token(vid, timeout_ms=15000)
                if auto and isinstance(auto, str) and len(auto) > 10:
                    auto_token = auto
                    _dbg(f"PO: auto-fetch OK (len={len(auto_token)})")
                else:
                    _dbg("PO: auto-fetch returned none")
            except Exception as e:
                _dbg(f"PO: auto-fetch failed: {e}")
        else:
            _dbg("PO: token_fetcher unavailable (not importable)")

    final: List[str] = []
    if auto_token:
        final += [f"ios.gvs+{auto_token}", f"android.gvs+{auto_token}", f"web.gvs+{auto_token}"]
    elif token_from_env:
        _dbg("PO: using env token(s)")
        final += token_from_env

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
        host = u.netloc.lower()
        if ("youtube.com" not in host) and ("youtu.be" not in host) and ("music.youtube.com" not in host):
            return False
        q = parse_qs(u.query)

        # cas 1: vraies playlists
        if (q.get("list") or [None])[0]:
            return True

        # cas 2: "radio/mix" partagé sans list= (start_radio=1 & rv=…)
        if (q.get("start_radio") or ["0"])[0] in ("1", "true"):
            return True

        # cas 3: page playlist directe
        if u.path.strip("/").lower() == "playlist":
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
    if not _YTDBG_HTTP_PROBE:
        return None
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

    headers = dict(info.get("http_headers") or {})
    ua = headers.pop("User-Agent", _YT_UA)
    headers["Referer"] = "https://www.youtube.com/"
    headers["Origin"] = "https://www.youtube.com"
    hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

    code = _http_probe(stream_url, {"User-Agent": ua, "Referer": "https://www.youtube.com/",
                                    "Origin": "https://www.youtube.com"}) or 200
    if _AUTO_PIPE_ON_403 and code in (403, 410, 429):
        _dbg(f"STREAM: probe got HTTP {code} → auto fallback to PIPE")
        return await stream_pipe(
            url_or_query, ffmpeg_path,
            cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps, afilter=afilter,
        )

    def _preflight_direct_ok() -> bool:
        try:
            cmd = [
                ff_exec,
                "-nostdin",
                "-user_agent", ua,
                "-headers", hdr_blob,
                "-probesize", "32k",
                "-analyzeduration", "0",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-rw_timeout", "15000000",
                "-protocol_whitelist", "file,https,tcp,tls,crypto",
                "-i", stream_url,
                "-t", "2",
                "-f", "null", "-"
            ]
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

    out_opts = "-vn"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    _dbg(f"FFMPEG before_options={before_opts}")
    _dbg(f"FFMPEG headers (redacted)={_redact_headers({'Referer': 'https://www.youtube.com/', 'Origin': 'https://www.youtube.com'})}")

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

# ==== STREAM PIPE ====
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
            "--concurrent-fragments", "1",
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
        else:
            picked = _pick_cookiefile(cookies_file)
            if picked:
                cmd += ["--cookies", picked]
        if ratelimit_bps:
            cmd += ["--limit-rate", str(int(ratelimit_bps))]
        cmd += [url_or_query]
        return cmd

    def _preflight_and_choose_format() -> str:
        primary_fmt = _FORMAT_CHAIN
        for attempt, fmt in enumerate([primary_fmt, "18"]):
            cmd = _build_cmd(fmt)
            _dbg(f"yt-dlp PRE-FLIGHT (attempt={attempt}, fmt={fmt}): {' '.join(shlex.quote(c) for c in cmd)}")
            yt = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=False, bufsize=0, close_fds=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            ff = subprocess.Popen(
                [ff_exec, "-nostdin", "-probesize", "32k", "-analyzeduration", "0",
                 "-fflags", "nobuffer", "-flags", "low_delay",
                 "-i", "pipe:0", "-t", "2", "-f", "null", "-"],
                stdin=yt.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            try:
                _ = ff.communicate(timeout=6)[0] or ""
            except subprocess.TimeoutExpired:
                try: ff.kill()
                except Exception: pass
                try: yt.kill()
                except Exception: pass
                return fmt if attempt == 0 else "18"

            rc = ff.returncode
            stderr_join = ""
            try:
                stderr_join = (yt.stderr.read() or b"").decode("utf-8", errors="replace")
            except Exception:
                pass
            try: yt.kill()
            except Exception: pass

            if rc == 0 and "Requested format is not available" not in stderr_join:
                return fmt
            _dbg(f"preflight rc={rc}, yt-stderr-match={'Requested format is not available' in stderr_join}")
        return "18"

    chosen_fmt = _preflight_and_choose_format()
    _dbg(f"PIPE chosen format: {chosen_fmt}")

    yt = subprocess.Popen(
        _build_cmd(chosen_fmt),
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
    out_opts = "-vn"
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

# ==== Nettoyage sûr des process ====
def safe_cleanup(src: Any) -> None:
    try:
        proc = getattr(src, "_ytdlp_proc", None)
        if proc and getattr(proc, "poll", lambda: None)() is None:
            proc.kill()
    except Exception:
        pass
    try:
        src.cleanup()
    except Exception:
        pass

# ===========================
# === Mode test en local  ===
# ===========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke test yt-dlp streaming for Greg")
    parser.add_argument("--test", choices=["direct", "pipe"], required=True, help="mode de test")
    parser.add_argument("--url", required=True, help="URL YouTube ou requête de recherche")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg", help="chemin FFmpeg (exe ou dossier)")
    parser.add_argument("--cookies", dest="cookies_file", default=None, help="cookiefile Netscape")
    parser.add_argument("--cookies-from-browser", dest="cookies_from_browser", default=None, help="ex: chrome[:Profile]")
    parser.add_argument("--ratelimit-bps", type=int, default=None)
    args = parser.parse_args()

    import asyncio

    async def _amain():
        if args.test == "direct":
            src, title = await stream(
                args.url, args.ffmpeg,
                cookies_file=args.cookies_file,
                cookies_from_browser=args.cookies_from_browser,
                ratelimit_bps=args.ratelimit_bps,
            )
        else:
            src, title = await stream_pipe(
                args.url, args.ffmpeg,
                cookies_file=args.cookies_file,
                cookies_from_browser=args.cookies_from_browser,
                ratelimit_bps=args.ratelimit_bps,
            )
        print(f"[TEST] OK: source créée — title={title!r}")
        safe_cleanup(src)
        print("[TEST] Cleanup OK")

    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\n[TEST] Interrupted")
