#extractors/youtube.py

from yt_dlp import YoutubeDL
import os

def is_valid(url: str) -> bool:
    """
    Vérifie si l'URL est une vidéo YouTube.
    Utilisé pour choisir automatiquement cet extracteur.
    """
    return "youtube.com/watch" in url or "youtu.be/" in url


def search(query: str):
    """
    Recherche des vidéos YouTube correspondant à la requête (texte).
    Retourne une liste d'entrées (chaque entrée = dict avec 'title', 'url', etc.).
    """
    ydl_opts = {
        'quiet': True,                        # Pas de spam console
        'default_search': 'ytsearch3',        # Recherche top 3 vidéos
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'extract_flat': True,                 # Ne pas télécharger, juste récupérer les métadonnées
    }

    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"ytsearch3:{query}", download=False)
        return results.get("entries", []) if results else []


def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge une vidéo YouTube sous forme audio MP3.
    Retourne : (chemin du fichier, titre, durée en secondes)
    """
    ydl_opts = {
        'format': 'bestaudio/best',            # Meilleure qualité audio dispo
        'outtmpl': 'downloads/greg_audio.%(ext)s',  # Nom du fichier de sortie
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',       # Conversion audio avec ffmpeg
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'ffmpeg_location': ffmpeg_path,        # Chemin vers ffmpeg
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'quiet': False,
        'sleep_interval_requests': 1,          # Pause entre les requêtes
        'ratelimit': 5.0,                      # Limite de débit en octets/s
        'extractor_args': {
            'youtube': ['--no-check-certificate', '--force-ipv4']  # Arguments spécifiques YouTube
        },
        'http_headers': {
            'User-Agent': (                     # En-tête navigateur réaliste pour éviter blocage
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/115.0.0.0 Safari/537.36'
            )
        },
        'youtube_include_dash_manifest': False  # Ne pas récupérer les flux DASH
    }

    # Si des cookies sont fournis (connexion à YouTube), on les ajoute
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file

    print(f"🎩 Extraction YouTube : {url}")
    print(f"Options : {ydl_opts}")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)  # Récupération des métadonnées
        title = info.get('title', 'Musique inconnue')
        duration = info.get('duration', 0)

        ydl.download([url])  # Téléchargement effectif
        filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

    return filename, title, duration