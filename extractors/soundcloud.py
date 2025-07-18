#extractors/soundcloud.py

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


def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge une piste SoundCloud sous forme audio .mp3.
    Retourne (chemin du fichier, titre, durée).
    """
    ydl_opts = {
        'format': 'bestaudio/best',            # Qualité audio optimale
        'outtmpl': 'downloads/greg_audio.%(ext)s',  # Fichier temporaire de sortie
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',       # Conversion via FFmpeg en mp3
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'ffmpeg_location': ffmpeg_path,        # Chemin vers ffmpeg (fourni par l’appelant)
        'quiet': False,
        'nocheckcertificate': True,
        'ratelimit': 5.0,
        'sleep_interval_requests': 1,
    }

    print(f"🎧 Extraction SoundCloud : {url}")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)  # Récupération des métadonnées
        title = info.get("title", "Son inconnu")
        duration = info.get("duration", 0)

        ydl.download([url])  # Téléchargement effectif
        filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

    return filename, title, duration
