# extractors/soundcloud.py
#
# SoundCloud robuste (Greg le Consanguin)
# - search: scsearch5 (flat) → 5 résultats normalisés
# - stream: URL directe (yt-dlp) → FFmpeg (avec headers & reconnexions)
# - download: MP3 (192 kbps, 48 kHz), chemin fiable via requested_downloads
# - cookies: navigateur prioritaire (cookiesfrombrowser), sinon fichier Netscape
# - options: cookies_file / cookies_from_browser / ratelimit_bps pris en charge
from __future__ import annotations

import os
import shlex
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

_SC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

_PROVIDER = "soundcloud"


def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("soundcloud.com/" in u) or ("sndcdn.com/" in u)


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
        "http_headers": {"User-Agent": _SC_UA, "Referer": "https://soundcloud.com/"},
        "format": "bestaudio/best",
        # Important pour certains streams HLS SC
        "extractor_args": {"soundcloud": {"client_id": []}},  # laisser yt-dlp gérer le client_id
    }

    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    # Cookies : navigateur prioritaire (même variable d'env que YouTube si tu l'utilises)
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    if search:
        ydl_opts.update({
            "default_search": "scsearch5",
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


def _normalize_entries(entries: List[dict]) -> List[dict]:
    out = []
    for e in entries or []:
        title = e.get("title") or "Titre inconnu"
        url = e.get("webpage_url") or e.get("url") or ""
        # duration: yt-dlp renvoie parfois ms → préférer secondes si dispo
        duration = e.get("duration")
        if isinstance(duration, str) and duration.isdigit():
            duration = int(duration)
        thumb = e.get("thumbnail") or (e.get("thumbnails") or [{}])[-1].get("url") if e.get("thumbnails") else None
        out.append({
            "title": title,
            "url": url,
            "webpage_url": url,
            "duration": duration,
            "thumb": thumb,
            "provider": _PROVIDER,
            "uploader": e.get("uploader") or e.get("uploader_id") or e.get("uploader_url"),
        })
    return out


# ------------------------ public: search ------------------------

def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"scsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        return _normalize_entries(entries)


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
    Prépare un stream pour Discord à partir de SoundCloud :
    - résout l'URL/ID avec yt-dlp (récupère aussi les http_headers)
    - passe les headers à FFmpeg (-headers + -user_agent), reconnexions activées
    Retourne (source_ffmpeg, title).
    """
    import asyncio

    def _probe(q: str):
        # Si ce n'est pas une URL SC, on transforme en scsearch1:<query>
        qb = q if is_valid(q) else f"scsearch1:{q}"
        with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser)) as ydl:
            info = ydl.extract_info(qb, download=False)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            return info or {}

    info = await asyncio.get_running_loop().run_in_executor(None, _probe, url_or_query)
    if not info:
        raise RuntimeError("Aucun résultat SoundCloud")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    if not stream_url:
        raise RuntimeError("Flux SoundCloud indisponible.")

    # Préparer headers pour FFmpeg (utile sur HLS *.m3u8)
    headers = (info.get("http_headers") or {})
    headers.setdefault("User-Agent", _SC_UA)
    headers.setdefault("Referer", "https://soundcloud.com/")
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
    setattr(source, "_ytdlp_proc", None)  # par homogénéité avec YouTube
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
    Télécharge l'audio SoundCloud et convertit en MP3.
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
        # Sur SC, les erreurs de format sont rares; normaliser le message
        raise RuntimeError(f"Échec download SoundCloud: {e}") from e
