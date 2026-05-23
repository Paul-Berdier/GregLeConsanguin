# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — PO_TOKEN + cookies + anti-403/429/SABR
#
# Différences clés vs version précédente :
# - Ordre par défaut des clients : `tv` (no PO, no cookies) en premier,
#   puis `mweb` + PO, puis ios/android/web en fallback.
# - PO tokens en cache *par video_id* (TTL court), invalidé sur 403.
# - `stream_pipe._preflight_pipe_sync` LÈVE une exception si tous les
#   formats échouent (avant on retournait silencieusement "18" → ffmpeg
#   se prenait un 403 et discord.py interprétait ça comme une coupure
#   réseau, bouclant à l'infini).
# - `_AUTO_PIPE_ON_403` enfin câblé : invalidation du PO + bascule explicite.
# - Logs lisibles, sans bruit.

from __future__ import annotations

import asyncio
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
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

__all__ = [
    "is_valid",
    "search",
    "is_playlist_like",
    "is_playlist_or_mix_url",
    "expand_bundle",
    "stream",
    "stream_pipe",
    "download",
    "safe_cleanup",
    "invalidate_po_cache",
]

_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")


def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}", flush=True)


# ─── Reconnaissance d'URLs YouTube ───
_YTID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_\-]{11})")


def _extract_video_id(s: str) -> Optional[str]:
    m = _YTID_RE.search(s or "")
    return m.group(1) if m else None


def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return (
        ("youtube.com/watch" in u)
        or ("youtu.be/" in u)
        or ("youtube.com/shorts/" in u)
        or ("music.youtube.com/watch" in u)
    )


# ─── Config réseau ───
_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
_FORCE_IPV4 = os.getenv("YTDLP_FORCE_IPV4", "1").lower() not in ("0", "false", "")
_HTTP_PROXY = (
    os.getenv("YTDLP_HTTP_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("HTTP_PROXY")
    or os.getenv("ALL_PROXY")
)

# Ordre des clients yt-dlp.
#
# `tv` et `tv_simply` ne nécessitent PAS de PO token (YouTube laisse passer
# les TVs/consoles). C'est notre voie royale en 2025/2026.
# `mweb` reste nécessaire pour certains contenus (Music, age-gate) mais
# nécessite un PO token → on l'utilise en second.
# Les anciens `ios`, `android`, `web` sont en dernier (ils ramassent
# fréquemment des 403 sans PO token).
_DEFAULT_CLIENTS = ["tv", "tv_simply", "mweb", "web_safari", "ios", "android", "web"]
_clients_env = os.getenv("YTDLP_CLIENTS")
if _clients_env:
    _CLIENTS_ORDER = [c.strip() for c in _clients_env.split(",") if c.strip()]
else:
    _CLIENTS_ORDER = list(_DEFAULT_CLIENTS)

_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]"
    "/251/140/18/best[protocol^=m3u8]/best",
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"
_AUTO_PIPE_ON_403 = os.getenv("YTDLP_AUTO_PIPE_ON_403", "1").lower() not in ("0", "false", "")


# ══════════════════════════════════════════
# PO Tokens — cache par video_id, TTL court
# ══════════════════════════════════════════
_PO_TTL = float(os.getenv("PO_CACHE_TTL_SEC", "1800"))  # 30 min
_PO_CACHE: Dict[str, Tuple[float, List[str]]] = {}  # video_id → (expires_at, tokens)
_PO_LOCK = threading.Lock()


def _po_cache_get(video_id: Optional[str]) -> Optional[List[str]]:
    if not video_id:
        return None
    with _PO_LOCK:
        entry = _PO_CACHE.get(video_id)
        if not entry:
            return None
        exp, toks = entry
        if time.monotonic() > exp:
            _PO_CACHE.pop(video_id, None)
            return None
        return list(toks)


def _po_cache_set(video_id: Optional[str], tokens: List[str]) -> None:
    if not video_id:
        return
    with _PO_LOCK:
        _PO_CACHE[video_id] = (time.monotonic() + _PO_TTL, list(tokens))


def invalidate_po_cache(video_id: Optional[str] = None) -> None:
    """Vide le cache PO. Si video_id fourni, uniquement cette entrée."""
    with _PO_LOCK:
        if video_id is None:
            _PO_CACHE.clear()
        else:
            _PO_CACHE.pop(video_id, None)


def _collect_po_tokens_from_env() -> List[str]:
    raw = (os.getenv("YT_PO_TOKEN") or os.getenv("YTDLP_PO_TOKEN") or "").strip()
    prefixed = (os.getenv("YT_PO_TOKEN_PREFIXED") or "").strip()
    out: List[str] = []
    if raw and "+" not in raw:
        out += [f"mweb.gvs+{raw}", f"web.gvs+{raw}", f"ios.gvs+{raw}", f"android.gvs+{raw}"]
    if raw and "+" in raw:
        out.append(raw)
    if prefixed:
        out.append(prefixed)
    seen = set()
    return [t for t in out if t and not (t in seen or seen.add(t))]


def _resolve_po_tokens_for(query_or_url: str) -> List[str]:
    """Renvoie la liste de PO tokens à passer à yt-dlp pour cette vidéo.

    Ordre de résolution :
    1. Cache (par video_id).
    2. Tokens fournis via env (YT_PO_TOKEN / YT_PO_TOKEN_PREFIXED).
    3. Auto-fetch via Playwright (token_fetcher), si possible.
    """
    vid = _extract_video_id(query_or_url)

    cached = _po_cache_get(vid)
    if cached is not None:
        return cached

    # 1) Env d'abord (déterministe, pas de network)
    env_tokens = _collect_po_tokens_from_env()
    if env_tokens:
        _po_cache_set(vid, env_tokens)
        _dbg(f"PO tokens from env: {len(env_tokens)}")
        return env_tokens

    # 2) Sinon, tentative auto-fetch Playwright
    if not vid:
        try:
            with YoutubeDL(_mk_opts()) as ydl:
                info = ydl.extract_info(query_or_url, download=False)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                vid = (info or {}).get("id")
        except Exception:
            vid = None

    if not vid:
        return []

    try:
        from .token_fetcher import fetch_po_token  # type: ignore
    except Exception:
        fetch_po_token = None

    if not fetch_po_token:
        _po_cache_set(vid, [])
        return []

    try:
        _dbg(f"PO: auto-fetch for video {vid}")
        auto = fetch_po_token(vid, timeout_ms=15000)
    except Exception as e:
        _dbg(f"PO: auto-fetch failed: {e}")
        auto = None

    tokens: List[str] = []
    if auto and isinstance(auto, str) and len(auto) > 10:
        # Préfixe pour tous les clients courants (yt-dlp dédup en interne)
        tokens = [
            f"mweb.gvs+{auto}",
            f"web.gvs+{auto}",
            f"ios.gvs+{auto}",
            f"android.gvs+{auto}",
        ]
        _dbg(f"PO: auto-fetch OK (len={len(auto)})")
    else:
        _dbg("PO: auto-fetch returned none")

    _po_cache_set(vid, tokens)
    return tokens


# ── Cookies ──
def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64).decode("utf-8", errors="replace")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(raw)
        return target_path
    except Exception:
        return None


def _pick_cookiefile(cookies_file: Optional[str]) -> Optional[str]:
    if cookies_file and os.path.exists(cookies_file):
        return cookies_file
    env_path = os.getenv("YTDLP_COOKIES_FILE") or os.getenv("YOUTUBE_COOKIES_PATH")
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
    return (
        (parts[0].strip().lower(),)
        if len(parts) == 1
        else (parts[0].strip().lower(), parts[1].strip())
    )


# ── FFmpeg ──
def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        return (which or "ffmpeg", os.path.dirname(which) if which else None)
    p = os.path.abspath(os.path.expanduser(ffmpeg_hint))
    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand):
            return cand, p
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2):
            return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans: {p}")
    if os.path.isfile(p):
        return p, os.path.dirname(p)
    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)
    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")


def _ff_reconnect_flags() -> List[str]:
    return [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_on_network_error", "1",
        "-reconnect_delay_max", "5",
        "-rw_timeout", "60000000",
        "-timeout", "60000000",
    ]


def _kill_proc(p) -> None:
    try:
        if p and getattr(p, "poll", lambda: None)() is None:
            p.kill()
    except Exception:
        pass


def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


# ── yt-dlp opts ──
def _mk_opts(
    *,
    ffmpeg_path=None,
    cookies_file=None,
    cookies_from_browser=None,
    ratelimit_bps=None,
    search=False,
    for_download=False,
    allow_playlist=False,
    extract_flat=False,
    po_tokens: Optional[List[str]] = None,
) -> Dict[str, Any]:
    cookies_file = _pick_cookiefile(cookies_file)
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": not allow_playlist,
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 20,
        "source_address": "0.0.0.0" if _FORCE_IPV4 else None,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": {"youtube": {"player_client": list(_CLIENTS_ORDER)}},
        "hls_prefer_native": True,
        "format": _FORMAT_CHAIN,
    }
    if po_tokens:
        opts["extractor_args"]["youtube"]["po_token"] = ",".join(po_tokens)
    if extract_flat:
        opts["extract_flat"] = True
    if ffmpeg_path:
        opts["ffmpeg_location"] = (
            os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ffmpeg_path
        )
    if _HTTP_PROXY:
        opts["proxy"] = _HTTP_PROXY
    if ratelimit_bps:
        opts["ratelimit"] = int(ratelimit_bps)

    cfb = _parse_cookies_from_browser_spec(
        cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")
    )
    if cfb:
        opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file

    if search:
        opts.update({"default_search": "ytsearch5", "extract_flat": True})
    if for_download:
        opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "postprocessor_args": ["-ar", "48000"],
        })
    for k in list(opts):
        if opts[k] is None:
            del opts[k]
    return opts


# ── Search ──
def _normalize_search_entries(entries):
    out = []
    for e in entries or []:
        title = e.get("title") or "Titre inconnu"
        url = e.get("webpage_url") or e.get("url") or ""
        if not url.startswith("http"):
            vid = e.get("id")
            if vid:
                url = f"https://www.youtube.com/watch?v={vid}"
        out.append({
            "title": title,
            "url": url,
            "webpage_url": url,
            "duration": e.get("duration"),
            "thumb": e.get("thumbnail"),
            "thumbnail": e.get("thumbnail"),
            "provider": "youtube",
            "uploader": e.get("uploader"),
        })
    return out


def search(query: str, *, cookies_file=None, cookies_from_browser=None,
           limit: int = 5) -> List[dict]:
    if not query or not query.strip():
        return []
    opts = _mk_opts(
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        search=True,
    )
    with YoutubeDL(opts) as ydl:
        data = ydl.extract_info(f"ytsearch{max(1, limit)}:{query}", download=False)
        return _normalize_search_entries((data or {}).get("entries") or [])


# ── Playlist ──
def is_playlist_or_mix_url(url: str) -> bool:
    try:
        u = urlparse(url)
        host = u.netloc.lower()
        if not any(h in host for h in ("youtube.com", "youtu.be", "music.youtube.com")):
            return False
        q = parse_qs(u.query)
        return (
            bool((q.get("list") or [None])[0])
            or (q.get("start_radio") or ["0"])[0] in ("1", "true")
            or u.path.strip("/").lower() == "playlist"
        )
    except Exception:
        return False


def is_playlist_like(url: str) -> bool:
    return is_playlist_or_mix_url(url)


def expand_bundle(page_url, limit_total=None, limit=None,
                  cookies_file=None, cookies_from_browser=None):
    import yt_dlp
    N = int(limit_total or limit or 10)
    parsed = urlparse(page_url)
    q = parse_qs(parsed.query)
    list_id = (q.get("list") or [None])[0]

    po_tokens = _resolve_po_tokens_for(page_url)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": False,
        "playlistend": N,
        "socket_timeout": 20,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": {"youtube": {"player_client": list(_CLIENTS_ORDER)}},
    }
    if po_tokens:
        opts["extractor_args"]["youtube"]["po_token"] = ",".join(po_tokens)
    picked = _pick_cookiefile(cookies_file)
    if picked:
        opts["cookiefile"] = picked

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(page_url, download=False)
    if (not info or not info.get("entries")) and list_id:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/playlist?list={list_id}", download=False
            )
    entries = (info or {}).get("entries") or []

    out = []
    for e in entries:
        vid = e.get("id") or e.get("url")
        if not vid:
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        if list_id:
            url += f"&list={list_id}"
        thumb = (
            e.get("thumbnail")
            or (e.get("thumbnails") or [{}])[-1].get("url")
            or None
        )
        out.append({
            "title": e.get("title") or url,
            "url": url,
            "webpage_url": url,
            "artist": e.get("uploader") or e.get("channel"),
            "thumb": thumb,
            "duration": e.get("duration"),
            "provider": "youtube",
        })
        if len(out) >= N:
            break
    return out


# ── Info fallbacks ──
def _probe_with_client(
    query, *, cookies_file, cookies_from_browser, ffmpeg_path,
    ratelimit_bps, client=None, po_tokens: Optional[List[str]] = None
):
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        po_tokens=po_tokens,
    )
    if client:
        opts.setdefault("extractor_args", {}).setdefault("youtube", {})["player_client"] = [client]
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info and info["entries"]:
            info = info["entries"][0]
        return info or None


def _best_info_with_fallbacks(
    query, *, cookies_file, cookies_from_browser, ffmpeg_path, ratelimit_bps
):
    po_tokens = _resolve_po_tokens_for(query)

    # 1) Tentative avec l'ordre complet de clients (laisse yt-dlp choisir)
    info = _probe_with_client(
        query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
        client=None,
        po_tokens=po_tokens,
    )
    if info and info.get("url"):
        return info

    # 2) Fallback : un client à la fois
    for c in _CLIENTS_ORDER:
        info = _probe_with_client(
            query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ffmpeg_path,
            ratelimit_bps=ratelimit_bps,
            client=c,
            po_tokens=po_tokens,
        )
        if info and info.get("url"):
            _dbg(f"fallback client={c} worked")
            return info
        _dbg(f"client={c} → no direct url")
    return None


# ══════════════════════════════════════════
# STREAM direct (avec PREFLIGHT obligatoire)
# ══════════════════════════════════════════
async def stream(
    url_or_query, ffmpeg_path,
    *, cookies_file=None, cookies_from_browser=None,
    ratelimit_bps=None, afilter=None,
):
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM request: {url_or_query!r}")

    info = await asyncio.get_running_loop().run_in_executor(
        None,
        functools.partial(
            _best_info_with_fallbacks, url_or_query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ff_loc or ff_exec,
            ratelimit_bps=ratelimit_bps,
        ),
    )

    if not info:
        raise RuntimeError("Aucun résultat YouTube.")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible.")

    headers = dict(info.get("http_headers") or {})
    ua = headers.pop("User-Agent", _YT_UA)
    hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

    # ─── Preflight FFmpeg 2s — bloque tôt sur les 403/429 ───
    def _preflight_direct_sync() -> Tuple[bool, str]:
        try:
            cmd = [
                ff_exec, "-nostdin", "-hide_banner", "-loglevel", "warning",
                *_ff_reconnect_flags(),
                "-protocol_whitelist", "file,https,tcp,tls,crypto",
                "-user_agent", ua, "-headers", hdr_blob,
                "-probesize", "32k", "-analyzeduration", "0",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-i", stream_url, "-t", "2", "-f", "null", "-",
            ]
            if _HTTP_PROXY:
                cmd = cmd[:1] + ["-http_proxy", _HTTP_PROXY] + cmd[1:]
            cp = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=25,
            )
            tail = (cp.stdout or "")[-400:]
            if cp.returncode != 0:
                _dbg(f"preflight direct FAILED rc={cp.returncode} tail={tail}")
            return cp.returncode == 0, tail
        except Exception as e:
            _dbg(f"preflight direct exception: {e}")
            return False, str(e)

    ok_direct, tail = await asyncio.to_thread(_preflight_direct_sync)

    # ─── 403 → invalide le cache PO et tente PIPE ───
    if not ok_direct:
        if _AUTO_PIPE_ON_403 and ("403" in tail or "Forbidden" in tail or "429" in tail):
            vid = _extract_video_id(url_or_query) or info.get("id")
            _dbg(f"403/429 détecté → invalidation cache PO pour {vid}, bascule PIPE")
            invalidate_po_cache(vid)
        _dbg("STREAM: direct preflight FAILED → fallback to PIPE")
        return await stream_pipe(
            url_or_query, ffmpeg_path,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps,
            afilter=afilter,
        )

    _dbg("STREAM: preflight OK → direct mode")

    before_opts = (
        f"-nostdin -hide_banner -loglevel warning "
        f"-user_agent {shlex.quote(ua)} -headers {shlex.quote(hdr_blob)} "
        f"-probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay "
        f"-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 "
        f"-reconnect_on_network_error 1 -reconnect_delay_max 5 "
        f"-rw_timeout 60000000 -timeout 60000000 "
        f"-protocol_whitelist file,https,tcp,tls,crypto"
    )
    if _HTTP_PROXY:
        before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
    out_opts = "-vn"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options=out_opts,
        executable=ff_exec,
    )
    setattr(src, "_ytdlp_proc", None)
    return src, title


# ══════════════════════════════════════════
# STREAM PIPE (yt-dlp stdout → FFmpeg)
# ══════════════════════════════════════════
async def stream_pipe(
    url_or_query, ffmpeg_path,
    *, cookies_file=None, cookies_from_browser=None,
    ratelimit_bps=None, afilter=None,
):
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")

    po_tokens = await asyncio.to_thread(_resolve_po_tokens_for, url_or_query)

    info = await asyncio.get_running_loop().run_in_executor(
        None,
        functools.partial(
            _best_info_with_fallbacks, url_or_query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ff_loc or ff_exec,
            ratelimit_bps=ratelimit_bps,
        ),
    )
    title = (info or {}).get("title", "Musique inconnue")

    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if po_tokens:
        ea_parts.append(f"po_token={','.join(po_tokens)}")
    ea = "youtube:" + ";".join(ea_parts)

    def _build_cmd(fmt: str) -> List[str]:
        cmd = _resolve_ytdlp_cli() + [
            "-f", fmt,
            "--no-playlist", "--no-check-certificates",
            "--retries", "5", "--fragment-retries", "5",
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

    def _preflight_pipe_sync() -> Optional[str]:
        """Renvoie le format gagnant, ou None si TOUS les essais échouent.

        ⚠️ FIX MAJEUR : l'ancienne version retournait "18" même en échec,
        ce qui faisait démarrer FFmpeg sur un flux mort et déclenchait la
        boucle de "reconnect réseau" dans le PlayerService.
        """
        last_rc = None
        for fmt in [_FORMAT_CHAIN, "18"]:
            yt = ff = None
            try:
                yt = subprocess.Popen(
                    _build_cmd(fmt),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=False, bufsize=0, close_fds=True,
                )
                if not yt.stdout:
                    _kill_proc(yt)
                    continue
                ff = subprocess.Popen(
                    [
                        ff_exec, "-nostdin", "-hide_banner", "-loglevel", "warning",
                        "-probesize", "32k", "-analyzeduration", "0",
                        "-fflags", "nobuffer", "-flags", "low_delay",
                        "-i", "pipe:0", "-t", "2", "-f", "null", "-",
                    ],
                    stdin=yt.stdout,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    ff.communicate(timeout=12)
                except subprocess.TimeoutExpired:
                    # Timeout = de l'audio coulait, on considère que c'est bon
                    return fmt
                last_rc = ff.returncode
                if ff.returncode == 0:
                    return fmt
                _dbg(f"pipe preflight fmt={fmt} rc={ff.returncode}")
            finally:
                _kill_proc(ff)
                _kill_proc(yt)
                try:
                    if yt and yt.stdout:
                        yt.stdout.close()
                except Exception:
                    pass
                try:
                    if yt and yt.stderr:
                        yt.stderr.close()
                except Exception:
                    pass
        _dbg(f"pipe preflight: TOUS les formats ont échoué (last rc={last_rc})")
        return None

    chosen_fmt = await asyncio.to_thread(_preflight_pipe_sync)

    if chosen_fmt is None:
        # On invalide le cache PO pour cette vidéo : il y a peut-être un PO périmé.
        vid = _extract_video_id(url_or_query) or (info or {}).get("id")
        invalidate_po_cache(vid)
        raise RuntimeError(
            "Stream YouTube indisponible (403/SABR). Vérifie les cookies YT "
            "et Playwright/Chromium (PO token)."
        )

    _dbg(f"PIPE chosen format: {chosen_fmt}")

    yt = subprocess.Popen(
        _build_cmd(chosen_fmt),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=False, bufsize=0, close_fds=True,
    )
    if not yt.stdout:
        _kill_proc(yt)
        raise RuntimeError("yt-dlp pipe unavailable")

    def _drain():
        try:
            while True:
                chunk = yt.stderr.readline()
                if not chunk:
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                if line:
                    print(f"[YTDBG][yt-dlp] {line}", flush=True)
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True).start()

    before_opts = (
        "-nostdin -re -hide_banner -loglevel warning "
        "-probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay"
    )
    out_opts = "-vn"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(
        source=yt.stdout, executable=ff_exec,
        before_options=before_opts, options=out_opts, pipe=True,
    )
    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title


# ── Download ──
def download(
    url, ffmpeg_path,
    *, cookies_file=None, cookies_from_browser=None,
    out_dir="downloads", ratelimit_bps=2_500_000,
):
    os.makedirs(out_dir, exist_ok=True)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    po_tokens = _resolve_po_tokens_for(url)
    opts = _mk_opts(
        ffmpeg_path=ff_loc or ff_exec,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        for_download=True,
        po_tokens=po_tokens,
    )
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            req = (info or {}).get("requested_downloads") or []
            filepath = (
                req[0].get("filepath")
                if req
                else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
            )
            return (
                filepath,
                (info or {}).get("title", "Musique inconnue"),
                (info or {}).get("duration"),
            )
    except DownloadError as e:
        if "Requested format is not available" in str(e):
            opts["format"] = "18"
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = (
                    req[0].get("filepath")
                    if req
                    else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
                )
                return (
                    filepath,
                    (info or {}).get("title", "Musique inconnue"),
                    (info or {}).get("duration"),
                )
        raise RuntimeError(f"Échec download YouTube: {e}") from e


def safe_cleanup(src) -> None:
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
