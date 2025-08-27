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
import re
import shlex
from urllib.parse import urlencode, urlparse, urljoin


def is_valid(url: str) -> bool:
    return "soundcloud.com" in url


# ----------------------------- Client ID helpers -----------------------------

def _sc_extract_client_ids_from_text(text: str):
    """
    Extrait les client_id potentiels depuis un contenu texte (JS/HTML).
    Retourne une liste unique (ordre d'apparition).
    """
    patterns = [
        r'client_id\s*:\s*"([a-zA-Z0-9]{32})"',         # client_id:"abcd..."
        r'client_id\\":\\"([a-zA-Z0-9]{32})\\"',         # JSON échappé
        r'client_id=([a-zA-Z0-9]{32})',                  # éventuels query fragments
    ]
    found = []
    seen = set()
    for pat in patterns:
        for m in re.findall(pat, text):
            if m not in seen:
                seen.add(m)
                found.append(m)
    return found


def _sc_scrape_client_ids(timeout: float = 6.0, max_js: int = 8):
    """
    Va chercher des client_id directement depuis la page SoundCloud
    en scannant les assets JS.
    - Ne nécessite pas de client_id préalable
    - Retourne une liste (potentiellement vide) d'IDs trouvés
    """
    base = "https://soundcloud.com/"
    ses = requests.Session()
    ses.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    })
    try:
        print("[SC] scraping client_id — GET /")
        r = ses.get(base, timeout=timeout)
        if not r.ok or not r.text:
            print(f"[SC] scraping failed: status={r.status_code}")
            return []
        html = r.text
        # Récupère les <script src="...js"> les plus probables (cdn a-v2.sndcdn.com)
        script_urls = re.findall(r'<script[^>]+src="([^"]+\.js)"', html)
        # Absolutiser & filtrer
        abs_urls = []
        for u in script_urls:
            u_abs = urljoin(base, u)
            host = (urlparse(u_abs).hostname or "")
            if "sndcdn.com" in host or "soundcloud.com" in host:
                abs_urls.append(u_abs)
        # Un peu de diversité: garde les premiers + uniques
        uniq = []
        for u in abs_urls:
            if u not in uniq:
                uniq.append(u)
        uniq = uniq[:max_js]
        print(f"[SC] scanning {len(uniq)} JS assets for client_id…")

        ids = []
        seen = set()
        for js_url in uniq:
            try:
                r2 = ses.get(js_url, timeout=timeout)
                if not r2.ok or not r2.text:
                    continue
                parts = _sc_extract_client_ids_from_text(r2.text)
                for cid in parts:
                    if cid not in seen:
                        seen.add(cid)
                        ids.append(cid)
                        print(f"[SC] found client_id in {js_url}: {cid[:6]}…")
            except Exception as e:
                print(f"[SC] JS fetch failed ({js_url}): {e}")
        return ids
    except Exception as e:
        print(f"[SC] scraping exception: {e}")
        return []


def _sc_client_ids():
    """
    Lit une liste d'IDs API SoundCloud depuis l'env SOUNDCLOUD_CLIENT_ID,
    séparés par virgule/point-virgule/espace. Si vide, tente un scraping auto.
    Exemple:
        export SOUNDCLOUD_CLIENT_ID="abcd123, efgh456"
    """
    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    ids = []
    if raw:
        ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        print(f"[SC] client_ids from env: {len(ids)}")
    else:
        # auto-scrape si rien en env
        scraped = _sc_scrape_client_ids()
        if scraped:
            print(f"[SC] client_ids scraped: {len(scraped)}")
            # On les place aussi dans l'env pour la durée du process (qualitatif)
            try:
                os.environ["SOUNDCLOUD_CLIENT_ID"] = ",".join(scraped)
            except Exception:
                pass
            ids = scraped
        else:
            print("[SC] no client_id found via scraping; will try yt_dlp fallback")
            ids = []
    random.shuffle(ids)
    return ids


# ------------------------- Resolve / stream selection ------------------------

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
    # Facultatif: certaines configs aiment 'Accept:*/*'
    if "accept" in h:
        out.append(f"Accept: {h['accept']}")
    return "\r\n".join(out)


# --------------------------------- Search -----------------------------------

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


# -------------------------------- Download ----------------------------------

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


# --------------------------------- Stream -----------------------------------

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
        # Dernière chance si env vide et premier scraping n'a rien donné :
        more = _sc_scrape_client_ids()
        if more:
            cids = more
            try:
                os.environ["SOUNDCLOUD_CLIENT_ID"] = ",".join(more)
            except Exception:
                pass

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
                    else:
                        print("[SC] resolve succeeded but no stream_url for chosen transcoding")
                else:
                    print("[SC] resolve failed with provided client_id")
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
