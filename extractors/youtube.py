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

    Cette fonction utilise ``yt-dlp`` pour récupérer la meilleure piste
    audio disponible et la convertir en MP3 grâce à ffmpeg.  De
    nombreuses options sont définies pour tenter de contourner les
    restrictions YouTube en simulant un navigateur classique et en
    limitant la vitesse.  Si un fichier de cookies est fourni, il
    sera utilisé pour authentifier les requêtes et ainsi éviter
    l'apparition du message « Sign in to confirm you're not a bot ».

    Parameters
    ----------
    url: str
        L'URL complète de la vidéo YouTube.
    ffmpeg_path: str
        Le chemin vers l'exécutable ``ffmpeg``.
    cookies_file: str, optional
        Chemin vers un fichier de cookies (format Netscape).  Si
        ``None``, aucune authentification n'est utilisée.

    Returns
    -------
    tuple
        (chemin du fichier MP3, titre, durée en secondes)
    """
    # Crée le dossier de sortie si nécessaire
    os.makedirs('downloads', exist_ok=True)

    # Options partagées pour yt‑dlp.  Voir la documentation pour plus
    # d'informations : yt‑dlp est un fork de youtube‑dl riche en
    # fonctionnalités【503558306535876†L122-L124】.
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/greg_audio.%(ext)s',
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }
        ],
        'ffmpeg_location': ffmpeg_path,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'quiet': False,
        'sleep_interval_requests': 1,
        'ratelimit': 5.0,
        'extractor_args': {
            'youtube': ['--no-check-certificate', '--force-ipv4']
        },
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/115.0.0.0 Safari/537.36'
            )
        },
        'youtube_include_dash_manifest': False,
    }
    # Ajout des cookies si disponibles
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file

    print(f"🎩 Extraction YouTube : {url}")
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'Musique inconnue')
        duration = info.get('duration', 0)
        # Téléchargement effectif
        ydl.download([url])
        filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

    return filename, title, duration


async def stream(url_or_query: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Récupère un flux audio direct pour une vidéo YouTube sans
    téléchargement.  Le flux est renvoyé sous forme d'objet
    ``discord.FFmpegPCMAudio`` prêt à être joué.

    Si ``url_or_query`` ne contient pas ``"http"``, la chaîne est
    interprétée comme une recherche et la première vidéo du résultat
    sera utilisée.  Cette méthode s'efforce de limiter l'impact
    d'éventuelles protections anti‑bots en réutilisant les mêmes
    options que ``download()`` et en utilisant un fichier de cookies
    le cas échéant.

    Parameters
    ----------
    url_or_query: str
        L'URL complète de la vidéo ou un terme de recherche.
    ffmpeg_path: str
        Le chemin vers l'exécutable ``ffmpeg``.
    cookies_file: str, optional
        Chemin vers le fichier de cookies Netscape pour YouTube.

    Returns
    -------
    tuple
        (source, titre) où ``source`` est une instance de
        ``discord.FFmpegPCMAudio`` et ``titre`` est une chaîne.
    """
    import asyncio
    import discord
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'ytsearch3',
        'nocheckcertificate': True,
        'extract_flat': False,
        'ignoreerrors': True,
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/115.0.0.0 Safari/537.36'
            )
        },
    }
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file
    loop = asyncio.get_event_loop()
    def extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)
    try:
        data = await loop.run_in_executor(None, extract)
        if not data:
            raise RuntimeError("Aucun résultat YouTube")
        info = data['entries'][0] if 'entries' in data else data
        stream_url = info['url']
        title = info.get('title', 'Musique inconnue')
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn",
            executable=ffmpeg_path,
        )
        return source, title
    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction YouTube : {e}")