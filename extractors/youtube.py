# extractors/youtube.py
#
# YouTube robuste:
# - clients sûrs (évite TV/SABR): ios → web → web_creator → web_mobile → android
# - cookies: navigateur prioritaire (cookiesfrombrowser) sinon fichier Netscape
# - stream: URL directe -> FFmpeg (léger, stable)
# - download: MP3 (192 kbps), fallback formats si indisponibles
# - search: ytsearch5 (flat)
from __future__ import annotations

import os
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


_YT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)


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
    for_stream: bool = False,
    for_download: bool = False,
) -> Dict[str, Any]:
    """
    Fabrique des options yt-dlp robustes.
    """
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "http_headers": {"User-Agent": _YT_UA},
        # ✅ éviter le client TV/SABR en forçant des clients stables
        "extractor_args": {"youtube": {"player_client": ["ios", "web", "web_creator", "web_mobile", "android"]}},
        # Ne bloque pas sur le manifest DASH (nécessaire pour ba/140 souvent)
        "youtube_include_dash_manifest": True,
    }

    # Formats avec fallback : m4a (140) → bestaudio → 18 (mp4 360p, contient audio)
    # (18 permet d'extraire l'audio quand aucun flux audio-only n'est dispo)
    ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best/18"

    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    # Cookies : navigateur prioritaire
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
        # MP3 192 kbps (48 kHz forcé)
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
    Prépare un stream pour Discord en récupérant l'URL directe du flux,
    puis en laissant FFmpeg décoder (léger et stable).
    Retourne (source_ffmpeg, title).
    """
    import asyncio

    def _probe(q: str):
        with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser)) as ydl:
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
        # Si le client choisi n'expose pas d'URL, retenter en forçant iOS uniquement
        def _probe_ios(q: str):
            opts = _mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser)
            opts["extractor_args"]["youtube"]["player_client"] = ["ios"]
            with YoutubeDL(opts) as ydl:
                data = ydl.extract_info(q, download=False)
                if data and "entries" in data and data["entries"]:
                    data = data["entries"][0]
                return data
        info = await asyncio.get_running_loop().run_in_executor(None, _probe_ios, url_or_query)
        stream_url = (info or {}).get("url")
        title = (info or {}).get("title", title)

    if not stream_url:
        raise RuntimeError("Flux audio indisponible (client bloqué). Ré-essayez plus tard.")

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        options="-vn",
        executable=ffmpeg_path,
    )
    # on peut attacher un champ si besoin de cleanup spécifique
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
    # Nom stable: "<title> - <id>.mp3" dans out_dir
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]

            # yt-dlp retourne toujours le/les fichiers réellement écrits ici:
            req = (info or {}).get("requested_downloads") or []
            if req:
                filepath = req[0].get("filepath")
            else:
                # fallback (rare)
                base = ydl.prepare_filename(info)
                filepath = os.path.splitext(base)[0] + ".mp3"

            title = (info or {}).get("title", "Musique inconnue")
            duration = (info or {}).get("duration")
            return filepath, title, duration
    except DownloadError as e:
        # Fallback ultime : forcer format 18 et réessayer une fois
        if "Requested format is not available" in str(e):
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
