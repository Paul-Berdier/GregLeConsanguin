# extractors/soundcloud.py
import asyncio
import functools
import os
import subprocess
from yt_dlp import YoutubeDL
from pathlib import Path

def is_valid(url: str) -> bool:
    return "soundcloud.com" in url

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

def search(query: str):
    """
    Recherche SoundCloud et renvoie des entrées *normalisées* avec toujours
    un champ 'webpage_url' (URL de page officielle), jamais une URL CDN.
    Champs utiles pour l'UI : title, uploader, duration, thumbnail.
    """
    def _is_cdn(u: str) -> bool:
        if not isinstance(u, str):
            return False
        return u.startswith(("https://cf-hls-media.sndcdn.com",
                             "https://cf-media.sndcdn.com",
                             "https://cf-hls-opus-media.sndcdn.com"))

    ydl_opts = {
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,  # on veut la page officielle
    }

    with YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(f"scsearch3:{query}", download=False) or {}
        entries = data.get("entries") or []
        out = []
        for e in entries:
            # yt_dlp flat renvoie typiquement: {title, url, uploader, duration, thumbnail, ...}
            url = e.get("webpage_url") or e.get("url") or ""
            if not url or _is_cdn(url):
                # on jette les résultats bizarres (CDN/flux)
                continue

            out.append({
                # on laisse les noms attendus par /api/autocomplete (qui remappe ensuite)
                "title": e.get("title") or url,
                "webpage_url": url,
                "url": url,  # pour compat partout : url = page
                "uploader": e.get("uploader"),
                "artist": e.get("uploader"),  # alias pratique
                "duration": e.get("duration"),  # peut être None en flat
                "thumbnail": e.get("thumbnail"),
            })
        return out


async def stream(url_or_query: str, ffmpeg_path: str):
    """
    Résout la page SoundCloud -> URL de flux via yt_dlp (pas l'UI),
    puis prépare FFmpegPCMAudio avec la whitelist/protocols pour HLS .opus.
    """
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        # surtout PAS 'extract_flat' ici, on veut l'URL stream résolue
    }

    loop = asyncio.get_event_loop()

    def extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
        info = data["entries"][0] if "entries" in data else data
        stream_url = info["url"]
        title = info.get("title", "Son inconnu")

        import discord
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=(
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                "-protocol_whitelist file,http,https,tcp,tls,crypto "
                "-allowed_extensions ALL"
            ),
            options="-vn",
            executable=ffmpeg_path,
        )
        return source, title

    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
