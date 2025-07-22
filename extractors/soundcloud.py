#extractors/soundcloud.py

import asyncio
import concurrent.futures
import functools
from yt_dlp import YoutubeDL

def is_valid(url: str) -> bool:
    """
    Vérifie si l'URL vient de SoundCloud.
    Permet de router automatiquement cette source vers cet extracteur.
    """
    return "soundcloud.com" in url


def search(query: str):
    """
    Recherche des pistes SoundCloud correspondant au texte `query`.
    Retourne une liste d’objets dict avec les métadonnées des résultats.
    """
    ydl_opts = {
        'quiet': True,                         # Pas de log bruyant
        'default_search': 'scsearch3',         # Recherche SoundCloud (3 premiers)
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'extract_flat': True,                  # Pas de téléchargement, juste les métadonnées
    }

    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []


import asyncio
import functools
import os
from yt_dlp import YoutubeDL

async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge une piste SoundCloud en audio .mp3 (asynchrone).
    Retourne (chemin du fichier, titre, durée).
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/greg_audio.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'ffmpeg_location': ffmpeg_path,
        'quiet': False,
        'nocheckcertificate': True,
        'ratelimit': 5.0,
        'sleep_interval_requests': 1,
    }

    print(f"🎧 Extraction SoundCloud : {url}")

    loop = asyncio.get_event_loop()

    with YoutubeDL(ydl_opts) as ydl:
        # Récupère les métadonnées sans bloquer l’event loop
        info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, url, False))
        title = info.get("title", "Son inconnu")
        duration = info.get("duration", 0)

        # Lance le téléchargement audio
        await loop.run_in_executor(None, functools.partial(ydl.download, [url]))
        filename = (
            ydl.prepare_filename(info)
            .replace(".webm", ".mp3")
            .replace(".m4a", ".mp3")
            .replace(".opus", ".mp3")
        )

        if not os.path.exists(filename):
            raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    return filename, title, duration
