# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin)
# - Clients sûrs (évite TV/SABR): ios → web → web_creator → web_mobile → android
# - Formats fallback: bestaudio m4a/opus → best → 140/251/18
# - STREAM: récupère une URL directe fraîche; si pas d'URL → réessaie avec clients alternatifs
# - STREAM (PIPE): yt-dlp → stdout → FFmpeg (avant le fallback download)
# - DOWNLOAD: MP3 (192 kbps, 48 kHz) avec fallback propre; chemin fiable
# - Cookies: navigateur (cookiesfrombrowser, via YTDLP_COOKIES_BROWSER) prioritaire, sinon fichier Netscape
# - Recherche: ytsearch5 (flat)

from __future__ import annotations

import os
import sys
import shlex
import shutil
import functools
import subprocess
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# UA par défaut ; peut être surchargé par l'env (recommandé: UA de ton navigateur)
_DEFAULT_YT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
_YT_UA = os.getenv("YTDLP_FORCE_UA", _DEFAULT_YT_UA)

_CLIENTS_ORDER = ["ios", "web", "web_creator", "web_mobile", "android"]
_FORMAT_CHAIN = "bestaudio[ext=m4a]/bestaudio/best/140/251/18"


def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u)


# ------------------------ helpers ------------------------

def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec:
        return None
    parts = spec.split(":", 1)
    browser = parts[0].strip().lower()
    profile = parts[1].strip() if len(parts) > 1 else None
    return (browser,) if profile is None else (browser, profile)


def _mk_opts(
    *,
    ffmpeg_path: Optional[str] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    search: bool = False,
    for_download: bool = False,
) -> Dict[str, Any]:
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        # important: forcer IPv4 sur certains DC (Railway/IPv6 souvent 403)
        "source_address": "0.0.0.0",
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
        },
        "extractor_args": {
            "youtube": {
                # ordre de clients pour éviter TV/SABR
                "player_client": list(_CLIENTS_ORDER),
            }
        },
        "youtube_include_dash_manifest": True,
        "format": _FORMAT_CHAIN,
    }
    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    # Cookies: navigateur d'abord, sinon fichier
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    if search:
        ydl_opts.update({
            "default_search": "ytsearch5",
            "extract_flat": True,
        })

    if for_download:
        ydl_opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            # 48 kHz pour Discord
            "postprocessor_args": ["-ar", "48000"],
        })

    return ydl_opts


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


def _probe_with_client(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
    client: Optional[str] = None,
) -> Optional[dict]:
    """Essaye d'extraire info (avec URL directe) en forçant un client précis si fourni."""
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
    )
    if client:
        opts["extractor_args"]["youtube"]["player_client"] = [client]

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info and info["entries"]:
            info = info["entries"][0]
        return info or None


def _best_info_with_fallbacks(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
) -> Optional[dict]:
    """Tente successivement les clients jusqu'à obtenir un info['url'] exploitable."""
    # 1) tentative avec chaîne complète (laisser yt-dlp choisir)
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

    # 2) forcer iOS, puis autres clients en séquence
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


def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


# ------------------------ public: search ------------------------

def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        return _normalize_search_entries(entries)


# ------------------------ public: stream ------------------------

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Prépare un stream pour Discord via URL directe (yt-dlp choisit un flux audio).
    Passe les http_headers à FFmpeg (anti-403) et corrige l'appel executor pour les kwargs.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
    ))
    if not info:
        raise RuntimeError("Aucun résultat YouTube")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible (clients bloqués).")

    # >>>>>> HEADERS POUR FFMPEG (crucial pour éviter 403) <<<<<<
    headers = (info.get("http_headers") or {})
    headers.setdefault("User-Agent", _YT_UA)
    headers.setdefault("Referer", "https://www.youtube.com/")
    headers.setdefault("Origin", "https://www.youtube.com")
    # Blob multi-lignes pour -headers
    hdr_blob = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"

    before_opts = (
        f"-user_agent {shlex.quote(headers['User-Agent'])} "
        f"-headers {shlex.quote(hdr_blob)} "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    )

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options="-vn",
        executable=ffmpeg_path,
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
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Fallback streaming robuste: yt-dlp → stdout → FFmpeg (pipe) → Discord.
    Utilisé si FFmpeg en direct prend 403 malgré les headers.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
    ))
    title = (info or {}).get("title", "Musique inconnue")

    cmd = _resolve_ytdlp_cli() + [
        "-f", _FORMAT_CHAIN,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", f"youtube:player_client={','.join(_CLIENTS_ORDER)}",
        "-o", "-",  # → stdout
        url_or_query,
    ]
    spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
    if spec:
        cmd += ["--cookies-from-browser", spec]
    elif cookies_file and os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]
    if ratelimit_bps:
        cmd += ["--limit-rate", str(int(ratelimit_bps))]

    yt = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    src = discord.FFmpegPCMAudio(
        source=yt.stdout,
        executable=ffmpeg_path,
        before_options=None,
        options="-vn -ar 48000 -ac 2 -f s16le",
        pipe=True,
    )
    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title


# ------------------------ public: download ------------------------

def download(
    url: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    out_dir: str = "downloads",
    ratelimit_bps: Optional[int] = 2_500_000,
) -> Tuple[str, str, Optional[int]]:
    """
    Télécharge l'audio et convertit en MP3.
    Retourne (filepath_mp3, title, duration_seconds|None).
    """
    os.makedirs(out_dir, exist_ok=True)
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        for_download=True,
    )
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"

    try:
        with YoutubeDL(opts) as ydl:
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
            return filepath, title, duration
    except DownloadError as e:
        if "Requested format is not available" in str(e):
            # Fallback ultime: itag 18 (mp4) puis conversion audio
            opts2 = _mk_opts(
                ffmpeg_path=ffmpeg_path,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                ratelimit_bps=ratelimit_bps,
                for_download=True,
            )
            opts2["format"] = "18"
            opts2["paths"] = {"home": out_dir}
            opts2["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"
            with YoutubeDL(opts2) as ydl2:
                info = ydl2.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = req[0].get("filepath") if req else (os.path.splitext(ydl2.prepare_filename(info))[0] + ".mp3")
                title = (info or {}).get("title", "Musique inconnue")
                duration = (info or {}).get("duration")
                return filepath, title, duration
        raise RuntimeError(f"Échec download YouTube: {e}") from e
