# extractors/soundcloud.py
# Stream SoundCloud fiable :
# 1) si URL SoundCloud -> API v2 + progressive MP3 quand dispo (via SOUNDCLOUD_CLIENT_ID)
# 2) sinon -> yt_dlp (download=False). En cas de HLS, on passe les headers à FFmpeg.
# 3) fallback download() si stream échoue
#
# DEBUG: imprime les choix de transcodings, headers, host, etc.

import asyncio
import functools
import os
import subprocess
from yt_dlp import YoutubeDL
from pathlib import Path

import json
import random
import time
import requests
from urllib.parse import urlencode, urlparse
import shlex


def is_valid(url: str) -> bool:
    return isinstance(url, str) and "soundcloud.com" in url


def _sc_client_ids():
    """
    Lit une liste d'IDs API SoundCloud depuis l'env SOUNDCLOUD_CLIENT_ID,
    séparés par virgule/point-virgule/espace. Exemple:
        export SOUNDCLOUD_CLIENT_ID="abcd123, efgh456"
    """
    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    if not raw:
        return []
    ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
    random.shuffle(ids)
    return ids


def _sc_resolve_track(url: str, client_id: str, timeout: float = 8.0):
    """
    Resolve v2 -> JSON de track (avec media.transcodings).
    Retourne le JSON ou None si échec.
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
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None


def _sc_pick_progressive_stream(track_json: dict, client_id: str, timeout: float = 8.0):
    """
    Choisit le transcoding: progressive > hls. Résout l'URL signée.
    Retourne (stream_url, title, duration_seconds, protocol|None)
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

    chosen = progressive or hls
    protocol = (chosen and (chosen.get("format") or {}).get("protocol")) or None
    if not chosen or not chosen.get("url"):
        return None, title, duration, protocol

    # Resolve l'URL signée
    ses = requests.Session()
    ses.headers.update({"User-Agent": "Mozilla/5.0"})
    r = ses.get(chosen["url"], params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None, title, duration, protocol
    j = r.json()
    stream_url = j.get("url")
    if not isinstance(stream_url, str) or not stream_url.startswith("http"):
        return None, title, duration, protocol

    return stream_url, title, duration, protocol


def _ffmpeg_headers_str(h: dict | None) -> str:
    """
    Construit les en-têtes CRLF que FFmpeg attend avec -headers.
    On passe au minimum: User-Agent, Referer, Origin (+ Authorization si fournie).
    """
    h = {str(k).lower(): str(v) for k, v in (h or {}).items()}
    ua = h.get("user-agent") or "Mozilla/5.0"
    ref = h.get("referer") or "https://soundcloud.com"
    org = h.get("origin") or "https://soundcloud.com"
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    return "\r\n".join(out)


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
            try:
                os.remove(original)
            except Exception:
                pass
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
    3) si flux HLS seulement → passe headers à FFmpeg ; sinon caller basculera en download()
    """
    import discord

    # --- 1) Progressive via API v2 si on a une URL SoundCloud
    if isinstance(url_or_query, str) and "soundcloud.com" in url_or_query:
        cids = _sc_client_ids()
        print("[SC] using client_ids:", (len(cids) if cids else 0))
        for cid in cids or [None]:
            if not cid:
                print("[SC] no client_id configured → skip resolve, go yt_dlp fallback")
                break
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if tr:
                    trans = (tr.get("media", {}) or {}).get("transcodings") or []
                    print("[SC] resolve → transcodings:", [(t.get("format") or {}).get("protocol") for t in trans])
                    stream_url, title, duration, proto = _sc_pick_progressive_stream(tr, cid)
                    if stream_url:
                        host = urlparse(stream_url).hostname
                        print(f"[SC] chosen protocol={proto}, host={host}")
                        # Progressive MP3 idéal pour FFmpeg
                        if proto == "progressive" and ".mp3" in stream_url.split("?")[0].lower():
                            before = (
                                f"-headers {shlex.quote(_ffmpeg_headers_str(None))} "
                                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                            )
                            source = discord.FFmpegPCMAudio(
                                stream_url,
                                before_options=before,
                                options="-vn",
                                executable=ffmpeg_path
                            )
                            return source, (title or "Son inconnu")
                        # HLS signé via resolve → on tente quand même avec headers de base
                        before = (
                            f"-headers {shlex.quote(_ffmpeg_headers_str(None))} "
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
                        return source, (title or "Son inconnu")
            except Exception as e:
                print(f"[SC] resolve attempt with client_id failed: {e}")
                # essaie client_id suivant
                continue

    # --- 2) Fallback: yt_dlp stream resolution (may return HLS)
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        # 'extract_flat': False  # par défaut
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

        # NEW: passer les headers yt_dlp à FFmpeg (vital pour SC HLS/opus)
        http_headers = info.get('http_headers') or data.get('http_headers') or {}
        hdr = _ffmpeg_headers_str(http_headers)
        host = urlparse(stream_url).hostname
        print("[SC] yt_dlp fallback; headers:", bool(http_headers), "host:", host)

        before = (
            f"-headers {shlex.quote(hdr)} "
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
