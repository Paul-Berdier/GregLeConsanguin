# extractors/soundcloud.py

import asyncio
import functools
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from yt_dlp import YoutubeDL


# --- Détection d'URL SoundCloud / streams SoundCloud ------------------------

_SCDN_RX = re.compile(
    r"(?:^|://)(?:www\.)?(?:soundcloud\.com|sndcdn\.com|cf-(?:hls-)?media\.sndcdn\.com)",
    re.I,
)
_STREAM_EXT_RX = re.compile(r"\.(?:m3u8|mp3)(?:\?|$)", re.I)


def is_valid(url: str) -> bool:
    """
    Vrai si l'URL est une page SoundCloud OU un stream CDN SoundCloud (.m3u8/.mp3).
    """
    if not isinstance(url, str) or not url:
        return False
    if _SCDN_RX.search(url):
        return True
    if _STREAM_EXT_RX.search(url):
        return True
    return False


# --- Recherche (page/permalink) ---------------------------------------------

def search(query: str):
    """
    Recherche des pistes SoundCloud correspondant à `query`.
    Retourne des entrées "flat" (rapides) via yt-dlp (scsearch3).
    """
    ydl_opts = {
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,  # plus rapide, pas de résolution détaillée
    }
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []


# --- Téléchargement (mp3) ---------------------------------------------------

async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge une piste SoundCloud en audio .mp3.
    Convertit .opus en .mp3 si nécessaire.
    Retourne (chemin du fichier, titre, durée).
    """
    os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best",
        "outtmpl": "downloads/greg_audio.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "ffmpeg_location": ffmpeg_path,
        "quiet": False,
        "nocheckcertificate": True,
        "ratelimit": 5.0,
        "sleep_interval_requests": 1,
        "prefer_ffmpeg": True,
        "force_generic_extractor": False,
    }

    print(f"🎧 Extraction SoundCloud : {url}")
    loop = asyncio.get_event_loop()

    with YoutubeDL(ydl_opts) as ydl:
        # Métadonnées
        info = await loop.run_in_executor(
            None, functools.partial(ydl.extract_info, url, False)
        )
        title = info.get("title", "Son inconnu")
        duration = info.get("duration", 0)
        print(f"[DEBUG] Format choisi : {info.get('ext')} ({info.get('format_id')})")

        # Téléchargement
        await loop.run_in_executor(None, functools.partial(ydl.download, [url]))
        original_filename = ydl.prepare_filename(info)

        # Conversion si .opus
        if original_filename.endswith(".opus"):
            converted = original_filename.replace(".opus", ".mp3")
            subprocess.run([
                ffmpeg_path, "-y", "-i", original_filename,
                "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", converted
            ], check=False)
            try:
                os.remove(original_filename)
            except Exception:
                pass
            filename = converted
        else:
            filename = Path(original_filename).with_suffix(".mp3")

        if not os.path.exists(filename):
            raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    return filename, title, duration


# --- Lecture en flux (prioritaire) ------------------------------------------

def _pick_best_audio_url(info: dict) -> Optional[str]:
    """
    Essaie de sélectionner la meilleure URL audio :
    - si info['url'] est déjà un flux direct -> OK
    - sinon, regarder dans info['formats'] et prendre un HLS/AAC/MP3 correct.
    """
    # URL directe ?
    url = (info or {}).get("url")
    if isinstance(url, str) and ( _STREAM_EXT_RX.search(url) or "sndcdn.com" in url ):
        return url

    # Chercher dans formats
    for prefer_hls in (True, False):
        fmts = (info or {}).get("formats") or []
        # tri simple: bitrate/abr/height
        fmts = sorted(
            fmts,
            key=lambda f: (f.get("abr") or 0, f.get("tbr") or 0, f.get("asr") or 0),
            reverse=True,
        )
        for f in fmts:
            furl = f.get("url")
            if not isinstance(furl, str):
                continue
            is_hls = ".m3u8" in furl
            if prefer_hls and not is_hls:
                continue
            if not prefer_hls and is_hls:
                continue
            if "sndcdn.com" in furl or _STREAM_EXT_RX.search(furl):
                return furl

    # fallback final
    return url if isinstance(url, str) else None


# extractors/soundcloud.py

async def stream(url_or_query: str, ffmpeg_path: str):
    """
    Retourne (source, title). url_or_query peut être une URL de page SC
    ou un texte de recherche; yt-dlp trouve le bon flux.
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'extract_flat': False,  # important pour obtenir l'URL de flux résolue
        'geo_bypass': True,
    }

    loop = asyncio.get_event_loop()

    def extract():
        from yt_dlp import YoutubeDL
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
        info = data['entries'][0] if isinstance(data, dict) and 'entries' in data else data
        stream_url = info.get('url') or info.get('webpage_url')
        title = info.get('title', 'Son inconnu')

        if not stream_url:
            raise RuntimeError("Flux introuvable (yt-dlp n'a pas résolu l'URL).")

        import discord
        before = (
            "-nostdin "
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-protocol_whitelist file,http,https,tcp,tls,crypto "
            "-allowed_extensions ALL"
        )
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=before,
            options="-vn",
            executable=ffmpeg_path
        )
        return source, title

    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
