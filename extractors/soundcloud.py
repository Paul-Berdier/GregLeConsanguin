import asyncio
import functools
import os
import subprocess
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
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'extract_flat': True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []


async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge une piste SoundCloud en audio .mp3 (asynchrone).
    Si le fichier est au format .opus, le convertit automatiquement.
    Retourne (chemin du fichier, titre, durée).
    """
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',  # Privilégie le m4a avant .opus
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
        # Extraction des métadonnées
        info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, url, False))
        title = info.get("title", "Son inconnu")
        duration = info.get("duration", 0)

        # Téléchargement effectif
        await loop.run_in_executor(None, functools.partial(ydl.download, [url]))
        original_filename = ydl.prepare_filename(info)

        # Gestion des formats : conversion si .opus
        if original_filename.endswith(".opus"):
            converted = original_filename.replace(".opus", ".mp3")
            subprocess.run([
                ffmpeg_path, "-y", "-i", original_filename,
                "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", converted
            ])
            os.remove(original_filename)
            filename = converted
        else:
            filename = (
                original_filename
                .replace(".webm", ".mp3")
                .replace(".m4a", ".mp3")
            )

        if not os.path.exists(filename):
            raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    return filename, title, duration
