# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — auto PO_TOKEN + cookies + anti-403/429/153
# - Clients: ios, android, web_creator, web, web_mobile (override via YTDLP_CLIENTS)
# - STREAM direct: URL+headers → FFmpeg (preflight 2s + auto fallback pipe)
# - STREAM PIPE: yt-dlp → stdout → FFmpeg
# - DOWNLOAD: MP3 (192kbps, 48kHz)
#
# FIX CRITIQUE vs ancienne version:
# - Preflight FFmpeg 2s OBLIGATOIRE avant stream direct
# - Si preflight échoue (403/429) → fallback automatique vers stream_pipe

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
import asyncio
import threading
import urllib.parse as _url
import urllib.request as _ureq
from typing import Optional, Tuple, Dict, Any, List

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
]

_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")

def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}")

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
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/18/best[protocol^=m3u8]/best",
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"
_AUTO_PIPE_ON_403 = os.getenv("YTDLP_AUTO_PIPE_ON_403", "1").lower() not in ("0", "false", "")

# ── PO Tokens ──
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
    seen = set()
    return [t for t in out if t and t not in seen and not seen.add(t)]

def _ensure_po_tokens_for(query_or_url: str, ffmpeg_hint: Optional[str]) -> None:
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
    auto_token: Optional[str] = None

    if vid:
        try:
            from .token_fetcher import fetch_po_token
        except Exception:
            fetch_po_token = None

        if fetch_po_token:
            try:
                _dbg(f"PO: auto-fetch for video {vid}")
                auto = fetch_po_token(vid, timeout_ms=15000)
                if auto and isinstance(auto, str) and len(auto) > 10:
                    auto_token = auto
                    _dbg(f"PO: auto-fetch OK (len={len(auto_token)})")
                else:
                    _dbg("PO: auto-fetch returned none")
            except Exception as e:
                _dbg(f"PO: auto-fetch failed: {e}")

    final: List[str] = []
    if auto_token:
        final += [f"ios.gvs+{auto_token}", f"android.gvs+{auto_token}", f"web.gvs+{auto_token}"]
    elif token_from_env:
        final += token_from_env

    seen = set()
    _PO_TOKENS = [t for t in final if t and t not in seen and not seen.add(t)]
    _dbg(f"PO tokens: {len(_PO_TOKENS)} set" if _PO_TOKENS else "PO tokens: none")

# ── Cookies ──
def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64: return None
    try:
        raw = base64.b64decode(b64).decode("utf-8", errors="replace")
        with open(target_path, "w", encoding="utf-8") as f: f.write(raw)
        return target_path
    except Exception: return None

def _pick_cookiefile(cookies_file: Optional[str]) -> Optional[str]:
    if cookies_file and os.path.exists(cookies_file): return cookies_file
    env_path = os.getenv("YOUTUBE_COOKIES_PATH")
    if env_path and os.path.exists(env_path): return env_path
    if os.path.exists(_COOKIE_FILE_DEFAULT): return _COOKIE_FILE_DEFAULT
    if os.getenv("YTDLP_COOKIES_B64"):
        _ensure_cookiefile_from_b64(_COOKIE_FILE_DEFAULT)
        if os.path.exists(_COOKIE_FILE_DEFAULT): return _COOKIE_FILE_DEFAULT
    return None

def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec: return None
    parts = spec.split(":", 1)
    return (parts[0].strip().lower(),) if len(parts) == 1 else (parts[0].strip().lower(), parts[1].strip())

# ── FFmpeg ──
def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        return (which or "ffmpeg", os.path.dirname(which) if which else None)
    p = os.path.abspath(os.path.expanduser(ffmpeg_hint))
    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand): return cand, p
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2): return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans: {p}")
    if os.path.isfile(p): return p, os.path.dirname(p)
    which = shutil.which(p)
    if which: return which, os.path.dirname(which)
    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")

def _ff_reconnect_flags() -> List[str]:
    return ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_at_eof", "1",
            "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
            "-rw_timeout", "60000000", "-timeout", "60000000"]

def _kill_proc(p) -> None:
    try:
        if p and getattr(p, "poll", lambda: None)() is None: p.kill()
    except Exception: pass

def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]

# ── yt-dlp opts ──
def _mk_opts(*, ffmpeg_path=None, cookies_file=None, cookies_from_browser=None,
             ratelimit_bps=None, search=False, for_download=False,
             allow_playlist=False, extract_flat=False) -> Dict[str, Any]:
    cookies_file = _pick_cookiefile(cookies_file)
    opts: Dict[str, Any] = {
        "quiet": True, "no_warnings": True,
        "noplaylist": not allow_playlist, "ignoreerrors": True,
        "retries": 5, "fragment_retries": 5, "socket_timeout": 20,
        "source_address": "0.0.0.0" if _FORCE_IPV4 else None,
        "http_headers": {"User-Agent": _YT_UA, "Referer": "https://www.youtube.com/", "Origin": "https://www.youtube.com"},
        "extractor_args": {"youtube": {"player_client": list(_CLIENTS_ORDER)}},
        "hls_prefer_native": True, "format": _FORMAT_CHAIN,
    }
    if _PO_TOKENS: opts["extractor_args"]["youtube"]["po_token"] = ",".join(_PO_TOKENS)
    if extract_flat: opts["extract_flat"] = True
    if ffmpeg_path: opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ffmpeg_path
    if _HTTP_PROXY: opts["proxy"] = _HTTP_PROXY
    if ratelimit_bps: opts["ratelimit"] = int(ratelimit_bps)
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb: opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file): opts["cookiefile"] = cookies_file
    if search: opts.update({"default_search": "ytsearch5", "extract_flat": True})
    if for_download:
        opts.update({"postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}], "postprocessor_args": ["-ar", "48000"]})
    for k in list(opts): 
        if opts[k] is None: del opts[k]
    return opts

# ── Search ──
def _normalize_search_entries(entries):
    out = []
    for e in entries or []:
        title = e.get("title") or "Titre inconnu"
        url = e.get("webpage_url") or e.get("url") or ""
        if not url.startswith("http"):
            vid = e.get("id")
            if vid: url = f"https://www.youtube.com/watch?v={vid}"
        out.append({"title": title, "url": url, "webpage_url": url, "duration": e.get("duration"),
                     "thumb": e.get("thumbnail"), "thumbnail": e.get("thumbnail"), "provider": "youtube", "uploader": e.get("uploader")})
    return out

def search(query: str, *, cookies_file=None, cookies_from_browser=None) -> List[dict]:
    if not query or not query.strip(): return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        return _normalize_search_entries((data or {}).get("entries") or [])

# ── Playlist ──
from urllib.parse import urlparse, parse_qs

def is_playlist_or_mix_url(url: str) -> bool:
    try:
        u = urlparse(url)
        host = u.netloc.lower()
        if not any(h in host for h in ("youtube.com", "youtu.be", "music.youtube.com")): return False
        q = parse_qs(u.query)
        return bool((q.get("list") or [None])[0]) or (q.get("start_radio") or ["0"])[0] in ("1", "true") or u.path.strip("/").lower() == "playlist"
    except Exception: return False

def is_playlist_like(url: str) -> bool:
    return is_playlist_or_mix_url(url)

def expand_bundle(page_url, limit_total=None, limit=None, cookies_file=None, cookies_from_browser=None):
    import yt_dlp
    N = int(limit_total or limit or 10)
    parsed = urlparse(page_url); q = parse_qs(parsed.query); list_id = (q.get("list") or [None])[0]
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "noplaylist": False,
            "playlistend": N, "socket_timeout": 20, "http_headers": {"User-Agent": _YT_UA, "Referer": "https://www.youtube.com/", "Origin": "https://www.youtube.com"},
            "extractor_args": {"youtube": {"player_client": list(_CLIENTS_ORDER)}}}
    if _PO_TOKENS: opts["extractor_args"]["youtube"]["po_token"] = ",".join(_PO_TOKENS)
    picked = _pick_cookiefile(cookies_file)
    if picked: opts["cookiefile"] = picked
    with yt_dlp.YoutubeDL(opts) as ydl: info = ydl.extract_info(page_url, download=False)
    if (not info or not info.get("entries")) and list_id:
        with yt_dlp.YoutubeDL(opts) as ydl: info = ydl.extract_info(f"https://www.youtube.com/playlist?list={list_id}", download=False)
    entries = (info or {}).get("entries") or []
    out = []
    for e in entries:
        vid = e.get("id") or e.get("url")
        if not vid: continue
        url = f"https://www.youtube.com/watch?v={vid}"
        if list_id: url += f"&list={list_id}"
        thumb = e.get("thumbnail") or (e.get("thumbnails") or [{}])[-1].get("url") or None
        out.append({"title": e.get("title") or url, "url": url, "webpage_url": url,
                     "artist": e.get("uploader") or e.get("channel"), "thumb": thumb, "duration": e.get("duration"), "provider": "youtube"})
        if len(out) >= N: break
    return out

# ── Info fallbacks ──
def _probe_with_client(query, *, cookies_file, cookies_from_browser, ffmpeg_path, ratelimit_bps, client=None):
    opts = _mk_opts(ffmpeg_path=ffmpeg_path, cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, ratelimit_bps=ratelimit_bps)
    if client: opts.setdefault("extractor_args", {}).setdefault("youtube", {})["player_client"] = [client]
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info and info["entries"]: info = info["entries"][0]
        return info or None

def _best_info_with_fallbacks(query, *, cookies_file, cookies_from_browser, ffmpeg_path, ratelimit_bps):
    info = _probe_with_client(query, cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, ffmpeg_path=ffmpeg_path, ratelimit_bps=ratelimit_bps, client=None)
    if info and info.get("url"): return info
    for c in _CLIENTS_ORDER:
        info = _probe_with_client(query, cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, ffmpeg_path=ffmpeg_path, ratelimit_bps=ratelimit_bps, client=c)
        if info and info.get("url"):
            _dbg(f"fallback client={c} worked")
            return info
        _dbg(f"client={c} → no direct url")
    return None

# ══════════════════════════════════════════
# STREAM direct (avec PREFLIGHT obligatoire)
# ══════════════════════════════════════════
async def stream(url_or_query, ffmpeg_path, *, cookies_file=None, cookies_from_browser=None, ratelimit_bps=None, afilter=None):
    await asyncio.to_thread(_ensure_po_tokens_for, url_or_query, ffmpeg_path)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM request: {url_or_query!r}")

    info = await asyncio.get_running_loop().run_in_executor(None, functools.partial(
        _best_info_with_fallbacks, url_or_query,
        cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec, ratelimit_bps=ratelimit_bps))

    if not info:
        raise RuntimeError("Aucun résultat YouTube.")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible.")

    headers = dict(info.get("http_headers") or {})
    ua = headers.pop("User-Agent", _YT_UA)
    hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

    # ═══ PREFLIGHT FFmpeg 2s — test OBLIGATOIRE avant de servir l'URL ═══
    def _preflight_direct_ok_sync() -> bool:
        try:
            cmd = [ff_exec, "-nostdin", "-hide_banner", "-loglevel", "warning",
                   *_ff_reconnect_flags(),
                   "-protocol_whitelist", "file,https,tcp,tls,crypto",
                   "-user_agent", ua, "-headers", hdr_blob,
                   "-probesize", "32k", "-analyzeduration", "0",
                   "-fflags", "nobuffer", "-flags", "low_delay",
                   "-i", stream_url, "-t", "2", "-f", "null", "-"]
            if _HTTP_PROXY: cmd = cmd[:1] + ["-http_proxy", _HTTP_PROXY] + cmd[1:]
            cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=25)
            if cp.returncode != 0:
                _dbg(f"preflight direct FAILED rc={cp.returncode} stderr={cp.stdout[-300:] if cp.stdout else ''}")
            return cp.returncode == 0
        except Exception as e:
            _dbg(f"preflight direct exception: {e}")
            return False

    ok_direct = await asyncio.to_thread(_preflight_direct_ok_sync)

    if not ok_direct:
        _dbg("STREAM: direct preflight FAILED → fallback to PIPE")
        return await stream_pipe(url_or_query, ffmpeg_path,
            cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps, afilter=afilter)

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
    if _HTTP_PROXY: before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
    out_opts = "-vn"
    if afilter: out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(stream_url, before_options=before_opts, options=out_opts, executable=ff_exec)
    setattr(src, "_ytdlp_proc", None)
    return src, title

# ══════════════════════════════════════════
# STREAM PIPE (yt-dlp stdout → FFmpeg)
# ══════════════════════════════════════════
async def stream_pipe(url_or_query, ffmpeg_path, *, cookies_file=None, cookies_from_browser=None, ratelimit_bps=None, afilter=None):
    await asyncio.to_thread(_ensure_po_tokens_for, url_or_query, ffmpeg_path)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")

    info = await asyncio.get_running_loop().run_in_executor(None, functools.partial(
        _best_info_with_fallbacks, url_or_query,
        cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec, ratelimit_bps=ratelimit_bps))
    title = (info or {}).get("title", "Musique inconnue")

    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if _PO_TOKENS: ea_parts.append(f"po_token={','.join(_PO_TOKENS)}")
    ea = "youtube:" + ";".join(ea_parts)

    def _build_cmd(fmt):
        cmd = _resolve_ytdlp_cli() + [
            "-f", fmt, "--no-playlist", "--no-check-certificates",
            "--retries", "5", "--fragment-retries", "5", "--concurrent-fragments", "1",
            "--newline", "--user-agent", _YT_UA, "--extractor-args", ea,
            "--add-header", "Referer:https://www.youtube.com/",
            "--add-header", "Origin:https://www.youtube.com", "-o", "-"]
        if _FORCE_IPV4: cmd += ["--force-ipv4"]
        if _HTTP_PROXY: cmd += ["--proxy", _HTTP_PROXY]
        spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
        if spec: cmd += ["--cookies-from-browser", spec]
        else:
            picked = _pick_cookiefile(cookies_file)
            if picked: cmd += ["--cookies", picked]
        if ratelimit_bps: cmd += ["--limit-rate", str(int(ratelimit_bps))]
        cmd += [url_or_query]
        return cmd

    def _preflight_pipe_sync():
        for fmt in [_FORMAT_CHAIN, "18"]:
            yt = ff = None
            try:
                yt = subprocess.Popen(_build_cmd(fmt), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False, bufsize=0, close_fds=True)
                if not yt.stdout: _kill_proc(yt); continue
                ff = subprocess.Popen([ff_exec, "-nostdin", "-hide_banner", "-loglevel", "warning",
                    "-probesize", "32k", "-analyzeduration", "0", "-fflags", "nobuffer", "-flags", "low_delay",
                    "-i", "pipe:0", "-t", "2", "-f", "null", "-"],
                    stdin=yt.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                try: ff.communicate(timeout=12)
                except subprocess.TimeoutExpired: return fmt
                if ff.returncode == 0: return fmt
                _dbg(f"pipe preflight fmt={fmt} rc={ff.returncode}")
            finally:
                _kill_proc(ff); _kill_proc(yt)
                try:
                    if yt and yt.stdout: yt.stdout.close()
                except: pass
                try:
                    if yt and yt.stderr: yt.stderr.close()
                except: pass
        return "18"

    chosen_fmt = await asyncio.to_thread(_preflight_pipe_sync)
    _dbg(f"PIPE chosen format: {chosen_fmt}")

    yt = subprocess.Popen(_build_cmd(chosen_fmt), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False, bufsize=0, close_fds=True)
    if not yt.stdout: _kill_proc(yt); raise RuntimeError("yt-dlp pipe unavailable")

    def _drain():
        try:
            while True:
                chunk = yt.stderr.readline()
                if not chunk: break
                line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                if line: print(f"[YTDBG][yt-dlp] {line}")
        except: pass
    threading.Thread(target=_drain, daemon=True).start()

    before_opts = "-nostdin -re -hide_banner -loglevel warning -probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay"
    out_opts = "-vn"
    if afilter: out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(source=yt.stdout, executable=ff_exec, before_options=before_opts, options=out_opts, pipe=True)
    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title

# ── Download ──
def download(url, ffmpeg_path, *, cookies_file=None, cookies_from_browser=None, out_dir="downloads", ratelimit_bps=2_500_000):
    os.makedirs(out_dir, exist_ok=True)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    opts = _mk_opts(ffmpeg_path=ff_loc or ff_exec, cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, ratelimit_bps=ratelimit_bps, for_download=True)
    opts["paths"] = {"home": out_dir}; opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info and info["entries"]: info = info["entries"][0]
            req = (info or {}).get("requested_downloads") or []
            filepath = req[0].get("filepath") if req else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
            return filepath, (info or {}).get("title", "Musique inconnue"), (info or {}).get("duration")
    except DownloadError as e:
        if "Requested format is not available" in str(e):
            opts["format"] = "18"
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]: info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = req[0].get("filepath") if req else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
                return filepath, (info or {}).get("title", "Musique inconnue"), (info or {}).get("duration")
        raise RuntimeError(f"Échec download YouTube: {e}") from e

def safe_cleanup(src) -> None:
    try:
        proc = getattr(src, "_ytdlp_proc", None)
        if proc and getattr(proc, "poll", lambda: None)() is None: proc.kill()
    except: pass
    try: src.cleanup()
    except: pass
