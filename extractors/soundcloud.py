# extractors/soundcloud.py
import asyncio
import functools
import os
import subprocess
from yt_dlp import YoutubeDL
from pathlib import Path

def is_valid(url: str) -> bool:
    return "soundcloud.com" in url

def search(query: str):
    """
    Recherche SoundCloud et renvoie des entrées 'flat' (avec 'webpage_url').
    C'est parfait pour: UI (title/thumbnail/duration) + lecture ultérieure.
    """
    ydl_opts = {
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'extract_flat': True,   # <-- IMPORTANT: on veut des URL de page
    }
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []

async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge en .mp3 (fallback si stream KO).
    """
    os.makedirs('downloads', exist_ok=True)
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best',
        'outtmpl': 'downloads/greg_audio.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192',
        }],
        'ffmpeg_location': ffmpeg_path,
        'quiet': False,
        'nocheckcertificate': True,
        'ratelimit': 5.0,
        'sleep_interval_requests': 1,
        'prefer_ffmpeg': True,
        'force_generic_extractor': False
    }
    loop = asyncio.get_event_loop()
    with YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, url, False))
        title = info.get("title", "Son inconnu")
        duration = info.get("duration", 0)
        await loop.run_in_executor(None, functools.partial(ydl.download, [url]))
        original = ydl.prepare_filename(info)
        if original.endswith(".opus"):
            converted = original.replace(".opus", ".mp3")
            subprocess.run([ffmpeg_path, "-y", "-i", original, "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", converted])
            os.remove(original)
            filename = converted
        else:
            filename = Path(original).with_suffix(".mp3")
        if not os.path.exists(filename):
            raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")
    return filename, title, duration

async def stream(url_or_query: str, ffmpeg_path: str):
    """
    Récupère les infos nécessaires pour lire un flux audio SoundCloud avec FFmpegPCMAudio.
    Retourne (source, titre).
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        # IMPORTANT: pas d'extract_flat ici (on veut l'URL stream résolue)
    }

    loop = asyncio.get_event_loop()

    def extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
        info = data['entries'][0] if 'entries' in data else data
        stream_url = info['url']  # URL de flux résolue par yt_dlp
        title = info.get('title', 'Son inconnu')

        import discord
        before = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-nostdin "
            "-protocol_whitelist https,tls,tcp,crypto,file "
            "-allowed_extensions ALL"
        )
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=(
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                "-protocol_whitelist file,http,https,tcp,tls,crypto "
                "-allowed_extensions ALL"),
            options="-vn",
            executable=ffmpeg_path
        )
        return source, title

    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
