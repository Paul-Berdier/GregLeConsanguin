# extractors/soundcloud.py
import asyncio
import functools
import os
import subprocess
from yt_dlp import YoutubeDL
from pathlib import Path

# NEW
import json
import random
import time
import requests
from urllib.parse import urlencode

def is_valid(url: str) -> bool:
    return "soundcloud.com" in url

def _sc_client_ids():
    """
    Return a list of SoundCloud client IDs from env SC_CLIENT_IDS
    (comma- or whitespace-separated). Example:
      export SC_CLIENT_IDS="abcd123, efgh456"
    """
    raw = os.getenv("SOUNDCLOUD_CLIENT_ID", "").strip()
    if not raw:
        return []
    ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
    random.shuffle(ids)
    return ids

def _sc_resolve_track(url: str, client_id: str, timeout: float = 8.0):
    """
    Resolve a SoundCloud page URL to a track JSON using v2 resolve.
    Returns the parsed JSON or None.
    """
    ses = requests.Session()
    ses.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome Safari"
    })
    res_url = "https://api-v2.soundcloud.com/resolve"
    r = ses.get(res_url, params={"url": url, "client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    # Some resolve responses wrap the track in {"kind":"track", ...}
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None

def _sc_pick_progressive_stream(track_json: dict, client_id: str, timeout: float = 8.0):
    """
    Given a resolved track JSON, pick progressive > hls, and fetch the signed stream URL.
    Returns (stream_url, title, duration_seconds) or (None, None, None).
    """
    title = track_json.get("title") or "Son inconnu"
    duration_ms = track_json.get("duration") or 0
    duration = int(round(duration_ms / 1000)) if duration_ms else None

    media = track_json.get("media") or {}
    transcodings = media.get("transcodings") or []
    progressive = None
    hls = None
    for t in transcodings:
        fmt = (t.get("format") or {}).get("protocol")
        if fmt == "progressive" and not progressive:
            progressive = t
        elif fmt == "hls" and not hls:
            hls = t

    chosen = progressive or hls  # prefer mp3 progressive; if not, try hls (last resort)
    if not chosen or not chosen.get("url"):
        return None, title, duration

    # Resolve the signed URL
    ses = requests.Session()
    ses.headers.update({"User-Agent": "Mozilla/5.0"})
    r = ses.get(chosen["url"], params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None, title, duration

    j = r.json()
    stream_url = j.get("url")
    if not isinstance(stream_url, str) or not stream_url.startswith("http"):
        return None, title, duration

    # If we fell back to HLS, it'll be an m3u8; ffmpeg may still choke.
    # We return it anyway; the caller can decide to try yt_dlp.
    return stream_url, title, duration

def search(query: str):
    """
    Recherche SoundCloud et renvoie des entrées 'flat' (avec 'webpage_url').
    Parfait pour l’UI et pour remettre l’URL de page dans stream().
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
    Stream SoundCloud de façon fiable :
    1) si c’est une URL de page SC → tente progressive MP3 via API v2 (client_id)
    2) sinon → yt_dlp (download=False) et récupère le stream résolu (fallback)
    3) si flux HLS seulement et FFmpeg refuse → le caller basculera en download()
    """
    import discord
    # --- 1) Progressive via API v2 si on a une URL SoundCloud
    if isinstance(url_or_query, str) and "soundcloud.com" in url_or_query:
        client_ids = _sc_client_ids()
        for cid in client_ids or [None]:
            if not cid:
                break  # no client id configured -> skip API attempt
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if tr:
                    stream_url, title, duration = _sc_pick_progressive_stream(tr, cid)
                    if stream_url and ".mp3" in stream_url.split("?")[0].lower():
                        # Progressive MP3 : parfait pour FFmpeg
                        source = discord.FFmpegPCMAudio(
                            stream_url,
                            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                            options="-vn",
                            executable=ffmpeg_path
                        )
                        return source, (title or "Son inconnu")
                    # HLS only -> we’ll try yt_dlp fallback below
            except Exception:
                # try next client id
                continue

    # --- 2) Fallback: yt_dlp stream resolution (may return HLS)
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
    }
    loop = asyncio.get_event_loop()
    def extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)
    try:
        data = await loop.run_in_executor(None, extract)
        info = data['entries'][0] if 'entries' in data else data
        stream_url = info['url']
        title = info.get('title', 'Son inconnu')

        # This might be HLS; may still fail on some tracks (we’ll let caller fallback to download()).
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=(
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                "-protocol_whitelist file,http,https,tcp,tls,crypto "
                "-allowed_extensions ALL"
            ),
            options="-vn",
            executable=ffmpeg_path
        )
        return source, title
    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
