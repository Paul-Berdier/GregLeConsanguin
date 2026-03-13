from __future__ import annotations

import argparse
import asyncio
import functools
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.request as _ureq
from typing import Any, Dict, List, Optional, Tuple

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from extractors.youtube_policy import (
    YouTubeStrategy,
    resolve_cookie_inputs,
    strategy_order,
)

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
_YTDBG_HTTP_PROBE = os.getenv("YTDBG_HTTP_PROBE", "0").lower() not in ("0", "false", "")

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
_DEFAULT_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio/best[protocol^=m3u8]/best",
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"

_YTID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_\-]{11})")
_PO_TOKEN_CACHE: Dict[Tuple[str, str], Tuple[str, float]] = {}
_PO_TOKEN_TTL_SECONDS = int(os.getenv("YTDLP_PO_TOKEN_TTL", "900"))


def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}")


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


def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


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


def _cookie_inputs(
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    return resolve_cookie_inputs(
        cookies_file,
        cookies_from_browser,
        default_cookie_file=_COOKIE_FILE_DEFAULT,
    )


def _po_token_from_env_for(client: str) -> Optional[str]:
    client_upper = client.upper()
    candidates = [
        os.getenv(f"YT_PO_TOKEN_{client_upper}"),
        os.getenv(f"YTDLP_PO_TOKEN_{client_upper}"),
        os.getenv("YT_PO_TOKEN"),
        os.getenv("YTDLP_PO_TOKEN"),
    ]

    for raw in candidates:
        raw = (raw or "").strip()
        if not raw:
            continue

        # Cas "mweb.gvs+TOKEN"
        if "+" in raw:
            prefix, token = raw.split("+", 1)
            if prefix == f"{client}.gvs":
                return token.strip() or None
            continue

        # Cas token brut
        return raw

    return None


def _fetch_po_token_for(video_id: str, client: str) -> Optional[str]:
    if client not in {"mweb", "web"}:
        return None

    cache_key = (video_id, client)
    cached = _PO_TOKEN_CACHE.get(cache_key)
    now = time.monotonic()

    if cached and (now - cached[1]) <= _PO_TOKEN_TTL_SECONDS:
        return cached[0]

    env_token = _po_token_from_env_for(client)
    if env_token:
        _PO_TOKEN_CACHE[cache_key] = (env_token, now)
        return env_token

    try:
        from extractors.token_fetcher import fetch_po_token
    except Exception:
        fetch_po_token = None

    if not fetch_po_token:
        return None

    try:
        token = fetch_po_token(video_id, timeout_ms=15000)
        if token and isinstance(token, str) and len(token) > 10:
            _PO_TOKEN_CACHE[cache_key] = (token, now)
            return token
    except Exception as e:
        _dbg(f"PO token fetch failed for {client}: {e}")

    return None


def _strategy_po_token(strategy: YouTubeStrategy, url_or_query: str) -> Optional[str]:
    if not strategy.needs_po_token:
        return None

    vid = _extract_video_id(url_or_query)
    if not vid:
        return None

    token = _fetch_po_token_for(vid, strategy.client)
    if token:
        _dbg(f"PO token ready for client={strategy.client} len={len(token)}")
    else:
        _dbg(f"PO token missing for client={strategy.client}")
    return token


def _base_ydl_opts(
    *,
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
    allow_playlist: bool,
    extract_flat: bool,
    search: bool,
) -> Dict[str, Any]:
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
        "extract_flat": extract_flat,
        "extractor_args": {"youtube": {}},
        "format": _DEFAULT_FORMAT_CHAIN,
        "hls_prefer_native": True,
    }

    if ffmpeg_path:
        opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ffmpeg_path

    if _HTTP_PROXY:
        opts["proxy"] = _HTTP_PROXY

    if ratelimit_bps:
        opts["ratelimit"] = int(ratelimit_bps)

    if search:
        opts["default_search"] = "ytsearch5"

    for k in list(opts.keys()):
        if opts[k] is None:
            del opts[k]

    return opts


def _opts_for_strategy(
    strategy: YouTubeStrategy,
    query: str,
    *,
    ffmpeg_path: Optional[str],
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ratelimit_bps: Optional[int],
    allow_playlist: bool = False,
    extract_flat: bool = False,
    search: bool = False,
) -> Dict[str, Any]:
    opts = _base_ydl_opts(
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
        allow_playlist=allow_playlist,
        extract_flat=extract_flat,
        search=search,
    )

    opts["extractor_args"]["youtube"]["player_client"] = [strategy.client]

    po_token = _strategy_po_token(strategy, query)
    if po_token:
        opts["extractor_args"]["youtube"]["po_token"] = [f"{strategy.client}.gvs+{po_token}"]

    resolved_cookiefile, resolved_browser = _cookie_inputs(cookies_file, cookies_from_browser)
    if strategy.use_cookies:
        if resolved_browser:
            parts = resolved_browser.split(":", 1)
            opts["cookiesfrombrowser"] = (parts[0], parts[1]) if len(parts) == 2 else (parts[0],)
        elif resolved_cookiefile and os.path.exists(resolved_cookiefile):
            opts["cookiefile"] = resolved_cookiefile

    return opts


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

    strategy = strategy_order(cookies_file, cookies_from_browser)[0]
    with YoutubeDL(
        _opts_for_strategy(
            strategy,
            query,
            ffmpeg_path=None,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=None,
            search=True,
        )
    ) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        return _normalize_search_entries((data or {}).get("entries") or [])


from urllib.parse import parse_qs, urlparse


def is_playlist_or_mix_url(url: str) -> bool:
    try:
        u = urlparse(url)
        if not u.netloc:
            return False
        host = u.netloc.lower()
        if ("youtube.com" not in host) and ("youtu.be" not in host) and ("music.youtube.com" not in host):
            return False
        q = parse_qs(u.query)
        if (q.get("list") or [None])[0]:
            return True
        if (q.get("start_radio") or ["0"])[0] in ("1", "true"):
            return True
        return u.path.strip("/").lower() == "playlist"
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
) -> List[Dict[str, Any]]:
    import yt_dlp

    n = int(limit_total or limit or 10)
    parsed = urlparse(page_url)
    q = parse_qs(parsed.query)
    list_id = (q.get("list") or [None])[0]

    strategies = strategy_order(cookies_file, cookies_from_browser)
    info = None

    for strategy in strategies:
        try:
            opts = _opts_for_strategy(
                strategy,
                page_url,
                ffmpeg_path=None,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                ratelimit_bps=None,
                allow_playlist=True,
                extract_flat=True,
            )
            opts["playlistend"] = n
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(page_url, download=False)
            if info and info.get("entries"):
                break
        except Exception as e:
            _dbg(f"expand_bundle strategy {strategy.display_name()} failed: {e}")

    if (not info or not info.get("entries")) and list_id:
        for strategy in strategies:
            try:
                playlist_url = f"https://www.youtube.com/playlist?list={list_id}"
                opts = _opts_for_strategy(
                    strategy,
                    playlist_url,
                    ffmpeg_path=None,
                    cookies_file=cookies_file,
                    cookies_from_browser=cookies_from_browser,
                    ratelimit_bps=None,
                    allow_playlist=True,
                    extract_flat=True,
                )
                opts["playlistend"] = n
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(playlist_url, download=False)
                if info and info.get("entries"):
                    break
            except Exception:
                pass

    entries = (info or {}).get("entries") or []
    out: List[Dict[str, Any]] = []

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

        if len(out) >= n:
            break

    return out


def _http_probe(url: str, headers: Dict[str, str]) -> Optional[int]:
    if not _YTDBG_HTTP_PROBE:
        return None

    try:
        handlers = []
        if _HTTP_PROXY:
            handlers.append(_ureq.ProxyHandler({"http": _HTTP_PROXY, "https": _HTTP_PROXY}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        req = _ureq.Request(url, method="HEAD", headers=headers)
        with opener.open(req, timeout=8) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            _dbg(f"HTTP_PROBE HEAD={code}")
            return int(code)
    except Exception as e:
        _dbg(f"HTTP_PROBE failed: {e}")
        return None


def _probe_info_once(
    query: str,
    *,
    strategy: YouTubeStrategy,
    ffmpeg_path: Optional[str],
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ratelimit_bps: Optional[int],
) -> Optional[dict]:
    try:
        opts = _opts_for_strategy(
            strategy,
            query,
            ffmpeg_path=ffmpeg_path,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps,
        )
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            if info:
                info["_strategy"] = strategy.display_name()
            return info or None
    except Exception as e:
        _dbg(f"info probe failed [{strategy.display_name()}]: {e}")
        return None


def _best_info_with_fallbacks(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
) -> Tuple[Optional[dict], Optional[YouTubeStrategy]]:
    strategies = strategy_order(cookies_file, cookies_from_browser)
    _dbg("strategy order=" + ", ".join(s.display_name() for s in strategies))

    for strategy in strategies:
        info = _probe_info_once(
            query,
            strategy=strategy,
            ffmpeg_path=ffmpeg_path,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps,
        )
        if info and info.get("url"):
            _dbg(f"strategy {strategy.display_name()} yielded direct url")
            return info, strategy
        _dbg(f"strategy {strategy.display_name()} yielded no direct url")

    return None, None


def _build_cli_command(
    strategy: YouTubeStrategy,
    query: str,
    *,
    fmt: str,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ratelimit_bps: Optional[int],
) -> List[str]:
    cmd = _resolve_ytdlp_cli() + [
        "-f", fmt,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--concurrent-fragments", "1",
        "--newline",
        "--user-agent", _YT_UA,
        "--add-header", "Referer:https://www.youtube.com/",
        "--add-header", "Origin:https://www.youtube.com",
        "-o", "-",
    ]

    if _FORCE_IPV4:
        cmd += ["--force-ipv4"]
    if _HTTP_PROXY:
        cmd += ["--proxy", _HTTP_PROXY]
    if ratelimit_bps:
        cmd += ["--limit-rate", str(int(ratelimit_bps))]

    extractor_arg_parts = [f"player_client={strategy.client}"]
    po_token = _strategy_po_token(strategy, query)
    if po_token:
        extractor_arg_parts.append(f"po_token={strategy.client}.gvs+{po_token}")
    cmd += ["--extractor-args", "youtube:" + ";".join(extractor_arg_parts)]

    resolved_cookiefile, resolved_browser = _cookie_inputs(cookies_file, cookies_from_browser)
    if strategy.use_cookies:
        if resolved_browser:
            cmd += ["--cookies-from-browser", resolved_browser]
        elif resolved_cookiefile and os.path.exists(resolved_cookiefile):
            cmd += ["--cookies", resolved_cookiefile]

    cmd += [query]
    return cmd


async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)

    info, strategy = await asyncio.get_running_loop().run_in_executor(
        None,
        functools.partial(
            _best_info_with_fallbacks,
            url_or_query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ff_loc or ff_exec,
            ratelimit_bps=ratelimit_bps,
        ),
    )

    if not info or not strategy:
        raise RuntimeError("Aucun flux YouTube direct exploitable.")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible.")

    headers = dict(info.get("http_headers") or {})
    ua = headers.pop("User-Agent", _YT_UA)
    hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

    code = _http_probe(stream_url, {
        "User-Agent": ua,
        "Referer": "https://www.youtube.com/",
        "Origin": "https://www.youtube.com",
    })
    if code in (403, 410, 429):
        _dbg(f"direct probe got {code}, switching to pipe")
        return await stream_pipe(
            url_or_query,
            ffmpeg_path,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps,
            afilter=afilter,
        )

    def _preflight_direct_ok_sync() -> bool:
        try:
            cmd = [
                ff_exec,
                "-nostdin",
                "-hide_banner",
                "-loglevel", "warning",
                *_ff_reconnect_flags(),
                "-protocol_whitelist", "file,https,tcp,tls,crypto",
                "-user_agent", ua,
                "-headers", hdr_blob,
                "-probesize", "32k",
                "-analyzeduration", "0",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-i", stream_url,
                "-t", "2",
                "-f", "null", "-",
            ]
            cp = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=25,
            )
            return cp.returncode == 0
        except Exception:
            return False

    ok_direct = await asyncio.to_thread(_preflight_direct_ok_sync)
    if not ok_direct:
        _dbg(f"direct preflight failed for strategy={strategy.display_name()}, switching to pipe")
        return await stream_pipe(
            url_or_query,
            ffmpeg_path,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps,
            afilter=afilter,
        )

    before_opts = (
        "-nostdin -hide_banner -loglevel warning "
        f"-user_agent {shlex.quote(ua)} "
        f"-headers {shlex.quote(hdr_blob)} "
        "-probesize 32k -analyzeduration 0 "
        "-fflags nobuffer -flags low_delay "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 "
        "-reconnect_on_network_error 1 -reconnect_delay_max 5 "
        "-rw_timeout 60000000 -timeout 60000000 "
        "-protocol_whitelist file,https,tcp,tls,crypto"
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


async def stream_pipe(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)

    info, _strategy = await asyncio.get_running_loop().run_in_executor(
        None,
        functools.partial(
            _best_info_with_fallbacks,
            url_or_query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ff_loc or ff_exec,
            ratelimit_bps=ratelimit_bps,
        ),
    )
    title = (info or {}).get("title", "Musique inconnue")
    strategies = strategy_order(cookies_file, cookies_from_browser)

    def _preflight_strategy_sync(strategy: YouTubeStrategy, fmt: str) -> bool:
        cmd = _build_cli_command(
            strategy,
            url_or_query,
            fmt=fmt,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ratelimit_bps=ratelimit_bps,
        )

        yt = None
        ff = None
        try:
            yt = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                close_fds=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            if not yt.stdout:
                return False

            ff = subprocess.Popen(
                [
                    ff_exec,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel", "warning",
                    "-probesize", "32k",
                    "-analyzeduration", "0",
                    "-fflags", "nobuffer",
                    "-flags", "low_delay",
                    "-i", "pipe:0",
                    "-t", "2",
                    "-f", "null", "-",
                ],
                stdin=yt.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            try:
                ff.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                return True

            return ff.returncode == 0
        finally:
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
            try:
                if ff and ff.poll() is None:
                    ff.kill()
            except Exception:
                pass
            try:
                if yt and yt.poll() is None:
                    yt.kill()
            except Exception:
                pass

    chosen_strategy = None
    chosen_format = None

    for strategy in strategies:
        for fmt in (_DEFAULT_FORMAT_CHAIN, "18"):
            ok = await asyncio.to_thread(_preflight_strategy_sync, strategy, fmt)
            _dbg(f"pipe preflight [{strategy.display_name()}] fmt={fmt} ok={ok}")
            if ok:
                chosen_strategy = strategy
                chosen_format = fmt
                break
        if chosen_strategy:
            break

    if not chosen_strategy or not chosen_format:
        raise RuntimeError("Aucune stratégie yt-dlp/ffmpeg n'a permis d'ouvrir le flux YouTube.")

    cmd = _build_cli_command(
        chosen_strategy,
        url_or_query,
        fmt=chosen_format,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
    )
    _dbg("PIPE command=" + " ".join(shlex.quote(c) for c in cmd))

    yt = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        close_fds=True,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    if not yt.stdout:
        try:
            yt.kill()
        except Exception:
            pass
        raise RuntimeError("yt-dlp did not provide stdout pipe")

    def _drain_stderr() -> None:
        try:
            if not yt.stderr:
                return
            while True:
                chunk = yt.stderr.readline()
                if not chunk:
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                if line:
                    print(f"[YTDBG][yt-dlp] {line}")
        except Exception as e:
            print(f"[YTDBG][yt-dlp] <stderr reader died: {e}>")

    threading.Thread(target=_drain_stderr, daemon=True).start()

    before_opts = "-nostdin -re -hide_banner -loglevel warning -probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay"
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
    last_error: Optional[Exception] = None

    for strategy in strategy_order(cookies_file, cookies_from_browser):
        try:
            opts = _opts_for_strategy(
                strategy,
                url,
                ffmpeg_path=ff_loc or ff_exec,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                ratelimit_bps=ratelimit_bps,
            )
            opts.update({
                "paths": {"home": out_dir},
                "outtmpl": "%(title).200B - %(id)s.%(ext)s",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "postprocessor_args": ["-ar", "48000"],
            })

            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]

                req = (info or {}).get("requested_downloads") or []
                filepath = req[0].get("filepath") if req else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
                title = (info or {}).get("title", "Musique inconnue")
                duration = (info or {}).get("duration")
                return filepath, title, duration

        except DownloadError as e:
            last_error = e
            _dbg(f"download strategy failed [{strategy.display_name()}]: {e}")
            continue

    raise RuntimeError(f"Échec download YouTube: {last_error}")


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke test yt-dlp streaming for Greg")
    parser.add_argument("--test", choices=["direct", "pipe"], required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--cookies", dest="cookies_file", default=None)
    parser.add_argument("--cookies-from-browser", dest="cookies_from_browser", default=None)
    parser.add_argument("--ratelimit-bps", type=int, default=None)
    args = parser.parse_args()

    async def _amain():
        if args.test == "direct":
            src, title = await stream(
                args.url,
                args.ffmpeg,
                cookies_file=args.cookies_file,
                cookies_from_browser=args.cookies_from_browser,
                ratelimit_bps=args.ratelimit_bps,
            )
        else:
            src, title = await stream_pipe(
                args.url,
                args.ffmpeg,
                cookies_file=args.cookies_file,
                cookies_from_browser=args.cookies_from_browser,
                ratelimit_bps=args.ratelimit_bps,
            )

        print(f"[TEST] OK title={title!r}")
        safe_cleanup(src)

    asyncio.run(_amain())