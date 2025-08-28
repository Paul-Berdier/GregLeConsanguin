# extractors/soundcloud.py
# Stream SoundCloud fiable :
# 1) si URL SoundCloud -> API v2 + progressive MP3 quand dispo (via SOUNDCLOUD_CLIENT_ID)
# 2) sinon -> yt_dlp (download=False). En cas de HLS, on passe les headers à FFmpeg.
# 3) fallback download() si stream échoue
#
# DEBUG: imprime les choix de transcodings, headers, host, formats, etc.

from __future__ import annotations

import asyncio
import functools
import json
import os
import random
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL


# ==============================
# Helpers / Debug
# ==============================

def _dbg(msg: str):
    print(f"[SC] {msg}")


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)

SC_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Referer": "https://soundcloud.com",
    "Origin": "https://soundcloud.com",
}

_SC_CACHE_PATH = Path(".sc_client_ids.json")
_SC_CLIENT_CACHE: List[str] = []  # en mémoire (ordre préféré)
_SC_SCRAPED_ONCE = False          # évite de scraper en boucle


def is_valid(url: str) -> bool:
    return isinstance(url, str) and ("soundcloud.com" in url or "sndcdn.com" in url)


# ==============================
# Client-ID cache / scraping
# ==============================

def _load_sc_cache():
    global _SC_CLIENT_CACHE
    try:
        if _SC_CACHE_PATH.exists():
            data = json.loads(_SC_CACHE_PATH.read_text(encoding="utf-8"))
            ids = list(dict.fromkeys((data.get("client_ids") or []) + ([] if not data.get("last_good") else [data["last_good"]])))
            _SC_CLIENT_CACHE = ids
            _dbg(f"cache loaded: {len(_SC_CLIENT_CACHE)} ids")
    except Exception as e:
        _dbg(f"cache load failed: {e}")


def _save_sc_cache(last_good: Optional[str] = None):
    try:
        payload = {"client_ids": list(_SC_CLIENT_CACHE)}
        if last_good:
            payload["last_good"] = last_good
            # Assure last_good en tête
            if last_good in _SC_CLIENT_CACHE:
                _SC_CLIENT_CACHE.remove(last_good)
            _SC_CLIENT_CACHE.insert(0, last_good)
        _SC_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _dbg(f"cache saved: {len(_SC_CLIENT_CACHE)} ids (last_good={bool(last_good)})")
    except Exception as e:
        _dbg(f"cache save failed: {e}")


def _record_working_client_id(cid: str):
    if not cid:
        return
    if cid in _SC_CLIENT_CACHE:
        _SC_CLIENT_CACHE.remove(cid)
    _SC_CLIENT_CACHE.insert(0, cid)
    _save_sc_cache(last_good=cid)
    _dbg(f"working client_id recorded: {cid[:4]}…")


def _parse_env_client_ids() -> List[str]:
    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    if not raw:
        return []
    ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
    return ids


def _sc_scrape_client_ids(base_url: Optional[str] = None, timeout: float = 8.0) -> List[str]:
    """
    Scrape des JS pour récupérer des client_id (pratique si .env vide / expiré).
    Exportée (utilisable par checkers externes).
    """
    global _SC_SCRAPED_ONCE
    base_url = base_url or "https://soundcloud.com/"
    _dbg("scraping client_id — GET /")

    ses = requests.Session()
    ses.headers.update(SC_HEADERS)

    r = ses.get(base_url, timeout=timeout)
    r.raise_for_status()

    # Récupérer les assets JS (a-v2.sndcdn.com/assets/*.js)
    js_urls = set(re.findall(r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', r.text))
    if not js_urls:
        # fallback: liens 'integrity' / 'crossorigin'
        js_urls = set(re.findall(r'https://a-v2\.sndcdn\.com/assets/[^"\']+\.js', r.text))

    _dbg(f"scanning {len(js_urls)} JS assets for client_id…")

    found: List[str] = []
    patterns = [
        r'client_id\s*[:=]\s*"([a-zA-Z0-9-_]{16,64})"',
        r'"client_id"\s*:\s*"([a-zA-Z0-9-_]{16,64})"',
        r'client_id=([a-zA-Z0-9-_]{16,64})',
    ]

    for jurl in js_urls:
        try:
            j = ses.get(jurl, timeout=timeout)
            if not j.ok:
                continue
            text = j.text
            for pat in patterns:
                for m in re.finditer(pat, text):
                    cid = m.group(1)
                    if cid and cid not in found:
                        found.append(cid)
                        _dbg(f"found client_id in {jurl}: {cid[:6]}…")
        except Exception as e:
            _dbg(f"scrape asset failed: {jurl} -> {e}")

    _SC_SCRAPED_ONCE = True
    return found


def _sc_client_ids() -> List[str]:
    """
    IDs depuis .env + cache + scrape (merge uniques).
    - Préfère last_good (cache)
    - Combine ENV + CACHE + (SCRAPE si pas encore fait ou si aucun id)
    """
    _load_sc_cache()

    env_ids = _parse_env_client_ids()
    if env_ids:
        _dbg(f"client_ids from env: {len(env_ids)}")

    ids = list(_SC_CLIENT_CACHE)  # copy
    # merge ENV
    for cid in env_ids:
        if cid not in ids:
            ids.append(cid)

    # scrape si jamais
    scraped: List[str] = []
    try:
        if not ids or not _SC_SCRAPED_ONCE:
            scraped = _sc_scrape_client_ids()
            for cid in scraped:
                if cid not in ids:
                    ids.append(cid)
            if scraped:
                # persiste ce que l’on a appris
                for cid in scraped:
                    if cid not in _SC_CLIENT_CACHE:
                        _SC_CLIENT_CACHE.append(cid)
                _save_sc_cache()
    except Exception as e:
        _dbg(f"scrape failed: {e}")

    # shuffle un peu, mais gardons l'ordre (last_good déjà en tête si présent)
    # Ici on peut décider de randomiser sauf les 1ers (cache/last_good)
    # Pour faire simple: randomiser tout sauf le tout premier.
    if len(ids) > 1:
        head, tail = ids[0], ids[1:]
        random.shuffle(tail)
        ids = [head] + tail

    _dbg(f"using client_ids: {len(ids)} (env={len(env_ids)} scraped={len(scraped)} cache={len(_SC_CLIENT_CACHE)})")
    return ids


# ==============================
# API v2 resolve + transcodings
# ==============================

def _sc_resolve_track(url: str, client_id: str, timeout: float = 8.0) -> Optional[dict]:
    """
    Resolve v2 -> JSON de track (avec media.transcodings) ou None si échec.
    """
    ses = requests.Session()
    ses.headers.update(SC_HEADERS)
    res_url = "https://api-v2.soundcloud.com/resolve"
    r = ses.get(res_url, params={"url": url, "client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None


def _sc_pick_transcoding(track_json: dict, client_id: str, timeout: float = 8.0) -> Tuple[Optional[str], str, Optional[int], Optional[str]]:
    """
    Choisit le transcoding: progressive > hls. Résout l'URL signée.
    Retourne toujours 4 valeurs: (stream_url, title, duration, protocol)
    """
    title = track_json.get("title") or "Son inconnu"
    duration_ms = track_json.get("duration") or 0
    duration = int(round(duration_ms / 1000)) if duration_ms else None

    media = track_json.get("media") or {}
    transcodings = media.get("transcodings") or []
    # Classement: progressive d'abord
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
    ses.headers.update(SC_HEADERS)
    r = ses.get(chosen["url"], params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None, title, duration, protocol
    j = r.json()
    stream_url = j.get("url")
    if not isinstance(stream_url, str) or not stream_url.startswith("http"):
        return None, title, duration, protocol

    return stream_url, title, duration, protocol


# ==============================
# FFmpeg helpers
# ==============================

def _ffmpeg_headers_str(h: Dict[str, str] | None) -> str:
    """
    Construit les en-têtes CRLF pour FFmpeg -headers.
    On passe au minimum: User-Agent, Referer, Origin (+ Authorization si fournie).
    """
    h = {str(k).lower(): str(v) for k, v in (h or {}).items()}
    ua = h.get("user-agent") or USER_AGENT
    ref = h.get("referer") or "https://soundcloud.com"
    org = h.get("origin") or "https://soundcloud.com"
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    return "\r\n".join(out)


def _is_hls_url(u: str) -> bool:
    u = (u or "").lower()
    return ".m3u8" in u or "/playlist.m3u8" in u or "hls" in u


# ==============================
# Recherche (pour l'UI)
# ==============================

def search(query: str):
    """
    Recherche SoundCloud et renvoie des entrées 'flat' (avec 'webpage_url').
    Parfait pour l’UI et pour remettre l’URL de page dans stream().
    """
    _dbg(f"search: '{query}'")
    ydl_opts = {
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'extract_flat': True,
        'noplaylist': True,
        'cachedir': False,
    }
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        ents = results.get("entries", []) if results else []
        _dbg(f"search results: {len(ents)}")
        return ents


# ==============================
# Download (fallback)
# ==============================

async def download(url: str, ffmpeg_path: str, cookies_file: str | None = None):
    """
    Télécharge en .mp3 (fallback si stream KO).
    Blocage des formats preview.
    """
    _dbg(f"download(): url={url}")
    os.makedirs('downloads', exist_ok=True)

    ydl_opts = {
        # Évite les previews
        'format': (
            'bestaudio[format_note!=preview][ext=mp3]/'
            'bestaudio[format_note!=preview][acodec=mp3]/'
            'bestaudio[format_note!=preview]/'
            'bestaudio/best'
        ),
        'outtmpl': 'downloads/greg_audio.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192',
        }],
        'ffmpeg_location': ffmpeg_path,
        'quiet': False,  # on veut voir passer les formats/étapes
        'nocheckcertificate': True,
        'noplaylist': True,
        'cachedir': False,
        # Ne JAMAIS throttler ici…
        # 'ratelimit': 5.0,
    }
    if cookies_file:
        ydl_opts['cookiefile'] = cookies_file

    loop = asyncio.get_event_loop()

    def _extract():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return ydl, info

    with YoutubeDL(ydl_opts) as _tmp:
        pass  # force import des PP/FFmpeg + garde la conf

    ydl, info = await loop.run_in_executor(None, _extract)
    title = info.get("title", "Son inconnu")
    duration = info.get("duration", 0)
    fmt_note = info.get("format_note")
    fmt_id = info.get("format_id")
    _dbg(f"yt_dlp selected format for download: id={fmt_id}, note={fmt_note}, ext={info.get('ext')}")

    # Lance le download (bloquant dans executor)
    await loop.run_in_executor(None, functools.partial(ydl.download, [url]))
    original = ydl.prepare_filename(info)

    # Si déjà MP3 → on garde tel quel; sinon PP a converti
    if original.endswith(".mp3"):
        filename = original
    else:
        # la PP a déjà fait FFMpegExtractAudio → le .mp3 porte le même nom racine
        filename = str(Path(original).with_suffix(".mp3"))

    if not os.path.exists(filename):
        raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    _dbg(f"download OK: file={filename}, title={title}, dur={duration}")
    return filename, title, duration


# ==============================
# Stream (préféré) + fallback
# ==============================

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
        client_ids = _sc_client_ids()
        for cid in client_ids or []:
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if tr:
                    trans = (tr.get("media", {}) or {}).get("transcodings") or []
                    _dbg(f"resolve → transcodings: {[(t.get('format') or {}).get('protocol') for t in trans]}")
                    stream_url, title, duration, proto = _sc_pick_transcoding(tr, cid)
                    if stream_url:
                        host = urlparse(stream_url).hostname
                        _dbg(f"chosen protocol={proto}, host={host}")
                        _record_working_client_id(cid)

                        hdr = _ffmpeg_headers_str(None)
                        if proto == "progressive" and ".mp3" in (stream_url.split("?")[0].lower()):
                            before = (
                                f"-headers {shlex.quote(hdr)} "
                                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                            )
                        else:
                            # HLS
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
                        return source, (title or "Son inconnu")
            except Exception as e:
                _dbg(f"resolve attempt failed (cid={cid[:4]}…): {e}")
                continue
        _dbg("no API v2 path succeeded; trying yt_dlp fallback…")

    # --- 2) Fallback: yt_dlp stream resolution (may return HLS)
    ydl_opts = {
        # On veut du stream direct si possible, mais surtout PAS de preview
        'format': (
            'bestaudio[format_note!=preview][ext=mp3]/'
            'bestaudio[format_note!=preview][acodec=mp3]/'
            'bestaudio[format_note!=preview]/'
            'bestaudio/best'
        ),
        'quiet': True,
        'default_search': 'scsearch3',
        'nocheckcertificate': True,
        'noplaylist': True,
        'cachedir': False,
    }

    loop = asyncio.get_event_loop()

    def extract():
        with YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url_or_query, download=False)
            return data

    try:
        data = await loop.run_in_executor(None, extract)
        info = data['entries'][0] if 'entries' in data else data
        stream_url = info.get('url')
        title = info.get('title', 'Son inconnu')
        fmt_note = info.get('format_note')
        fmt_id = info.get('format_id')
        host = urlparse(stream_url or "").hostname
        _dbg(f"yt_dlp fallback; host: {host} format_id={fmt_id} note={fmt_note}")

        http_headers = info.get('http_headers') or data.get('http_headers') or {}
        hdr = _ffmpeg_headers_str(http_headers)

        if _is_hls_url(stream_url):
            before = (
                f"-headers {shlex.quote(hdr)} "
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                "-protocol_whitelist file,http,https,tcp,tls,crypto "
                "-allowed_extensions ALL"
            )
        else:
            before = (
                f"-headers {shlex.quote(hdr)} "
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            )

        import discord  # re-import safe
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=before,
            options="-vn",
            executable=ffmpeg_path
        )
        return source, title
    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
