# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin)
# - Clients sûrs (évite TV/SABR) : ios → web → web_creator → web_mobile → android
# - Formats fallback : bestaudio m4a/opus → best → itag 18
# - Stream : URL directe → FFmpeg (reconnect) ; refresh automatique si 403
# - Download : MP3 (192 kbps, 48 kHz), nom "<title> - <id>.mp3"
# - Cookies : navigateur (cookiesfrombrowser) prioritaire, sinon fichier Netscape
# - Recherche : ytsearch5
from __future__ import annotations

import os
import asyncio
import discord
from typing import Optional, Tuple, Dict, Any, List

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


_YT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

# ------------------------ helpers ------------------------

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u)


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
        "http_headers": {"User-Agent": _YT_UA},
        "extractor_args": {"youtube": {"player_client": ["ios", "web", "web_creator", "web_mobile", "android"]}},
        "format": "bestaudio[ext=m4a]/bestaudio/best/140/251/18",
    }
    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

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
    Prépare un stream pour Discord.
    Si URL invalide ou 403 → refresh auto avec client iOS.
    """
    def _probe(q: str, force_ios: bool = False):
        opts = _mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser)
        if force_ios:
            opts["extractor_args"]["youtube"]["player_client"] = ["ios"]
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(q, download=False)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            return info

    info = await asyncio.get_running_loop().run_in_executor(None, _probe, url_or_query)
    if not info:
        raise RuntimeError("Aucun résultat YouTube")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")

    if not stream_url:
        # Retente avec client iOS
        info = await asyncio.get_running_loop().run_in_executor(None, _probe, url_or_query, True)
        stream_url = (info or {}).get("url")
        title = (info or {}).get("title", title)

    if not stream_url:
        raise RuntimeError("Flux audio indisponible (clients bloqués).")

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        options="-vn",
        executable=ffmpeg_path,
    )
    setattr(source, "_ytdlp_proc", None)
    return source, title


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
            # Fallback ultime : itag 18
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
