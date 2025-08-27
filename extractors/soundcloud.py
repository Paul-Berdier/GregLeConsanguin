# extractors/soundcloud.py
# Stream SoundCloud fiable :
# 1) si URL SoundCloud -> API v2 + progressive MP3 quand dispo (via SOUNDCLOUD_CLIENT_ID)
# 2) sinon -> yt_dlp (download=False). HLS: options adaptées ; preview MP3: options simples.
# 3) fallback download() si stream échoue
#
# DEBUG: imprime les choix de transcodings, headers, host, etc.

import asyncio
import functools
import os
import json
import random
import time
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL


# ----------------------- utils généraux -----------------------

def is_valid(url: str) -> bool:
    return isinstance(url, str) and "soundcloud.com" in url


def _dbg(msg: str):
    print(f"[SC] {msg}")


def _ffmpeg_headers_str(h: dict | None) -> str:
    """
    Construit les en-têtes CRLF que FFmpeg attend avec -headers.
    Ajoute un CRLF terminal (FFmpeg râle sinon).
    """
    base = {k.lower(): str(v) for k, v in (h or {}).items()}
    ua = base.get("user-agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
    ref = base.get("referer") or "https://soundcloud.com"
    org = base.get("origin") or "https://soundcloud.com"
    lines = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if base.get("authorization"):
        lines.append(f"Authorization: {base['authorization']}")
    # CRLF final :
    return "\r\n".join(lines) + "\r\n"


def _is_hls(url: str) -> bool:
    u = (url or "").lower()
    return ".m3u8" in u


def _is_preview_mp3(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.hostname and "cf-preview-media.sndcdn.com" in p.hostname:
            return True
        path = (p.path or "").lower()
        return "/preview/" in path or path.endswith(".mp3")
    except Exception:
        return False


# ----------------------- client_id: env + cache + scraping -----------------------

_CACHE_DIR = ".cache"
_CACHE_FILE = os.path.join(_CACHE_DIR, "sc_ids.json")
_SC_CLIENT_CACHE: list[str] = []
_SC_CLIENT_LAST_GOOD: str | None = None


def _load_sc_cache():
    global _SC_CLIENT_CACHE, _SC_CLIENT_LAST_GOOD
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            _SC_CLIENT_CACHE = list(dict.fromkeys(data.get("ids", []) or []))
            _SC_CLIENT_LAST_GOOD = data.get("last_good") or None
    except Exception as e:
        _dbg(f"cache load failed: {e}")


def _save_sc_cache():
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ids": _SC_CLIENT_CACHE, "last_good": _SC_CLIENT_LAST_GOOD}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _dbg(f"cache save failed: {e}")


def _sc_scrape_client_ids() -> list[str]:
    """
    Scrape des client_id depuis la page d'accueil + assets JS.
    Pas d'appel à _sc_client_ids() ici (évite toute récursion).
    """
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        _dbg("scraping client_id — GET /")
        r = sess.get("https://soundcloud.com/", timeout=8)
        r.raise_for_status()
        html = r.text
        import re
        script_urls = re.findall(r'<script[^>]+src="([^"]+a-v2\.sndcdn\.com[^"]+\.js)"', html)
        script_urls = list(dict.fromkeys(script_urls))
        _dbg(f"scanning {len(script_urls)} JS assets for client_id…")
        found = []
        for url in script_urls:
            try:
                js = sess.get(url, timeout=8).text
                # motifs fréquents: client_id:"xxxxx" / client_id:"xxxxx",
                for m in re.finditer(r'client_id\s*:\s*"([a-zA-Z0-9]{16,40})"', js):
                    found.append(m.group(1))
                for m in re.finditer(r'client_id\s*=\s*"([a-zA-Z0-9]{16,40})"', js):
                    found.append(m.group(1))
            except Exception:
                continue
        found = list(dict.fromkeys(found))
        if found:
            _dbg(f"found {len(found)} client_id(s) in assets")
        return found
    except Exception as e:
        _dbg(f"scraping exception: {e}")
        return []


def _sc_client_ids() -> list[str]:
    """
    Fusionne: ENV + cache + scraping. Déduplique et mélange.
    """
    _load_sc_cache()

    env_raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    env_ids = [x.strip() for x in env_raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
    if env_ids:
        _dbg(f"client_ids from env: {len(env_ids)}")

    scraped = _sc_scrape_client_ids()
    if scraped:
        # merge dans le cache
        for cid in scraped:
            if cid not in _SC_CLIENT_CACHE:
                _SC_CLIENT_CACHE.append(cid)
        _save_sc_cache()

    # union : env en priorité, puis cache (qui contient déjà scraped/last_good)
    all_ids = list(dict.fromkeys(env_ids + (_SC_CLIENT_CACHE or []) + scraped))
    random.shuffle(all_ids)
    return all_ids


def _sc_mark_last_good(cid: str):
    global _SC_CLIENT_LAST_GOOD
    if not cid:
        return
    _SC_CLIENT_LAST_GOOD = cid
    if cid not in _SC_CLIENT_CACHE:
        _SC_CLIENT_CACHE.append(cid)
    _save_sc_cache()


# ----------------------- API v2 resolve / transcodings -----------------------

def _sc_resolve_track(url: str, client_id: str, timeout: float = 8.0):
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0"})
    res_url = "https://api-v2.soundcloud.com/resolve"
    r = sess.get(res_url, params={"url": url, "client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None


def _sc_pick_progressive_stream(track_json: dict, client_id: str, timeout: float = 8.0):
    """
    Retourne toujours (stream_url, title, duration_seconds, protocol|None)
    protocol ∈ {"progressive","hls"} ou None si rien.
    """
    title = track_json.get("title") or "Son inconnu"
    dur_ms = track_json.get("duration") or 0
    duration = int(round(dur_ms / 1000)) if dur_ms else None

    media = track_json.get("media") or {}
    trans = media.get("transcodings") or []
    progressive = None
    hls = None
    for t in trans:
        fmt = (t.get("format") or {}).get("protocol")
        if fmt == "progressive" and not progressive:
            progressive = t
        elif fmt == "hls" and not hls:
            hls = t
    chosen = progressive or hls
    protocol = (chosen and (chosen.get("format") or {}).get("protocol")) or None
    if not chosen or not chosen.get("url"):
        return None, title, duration, protocol

    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0"})
    r = sess.get(chosen["url"], params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None, title, duration, protocol
    j = r.json()
    stream_url = j.get("url")
    if not isinstance(stream_url, str) or not stream_url.startswith("http"):
        return None, title, duration, protocol

    return stream_url, title, duration, protocol


# ----------------------- recherche / download fallback -----------------------

def search(query: str):
    ydl_opts = {
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []


async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    os.makedirs("downloads", exist_ok=True)
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best",
        "outtmpl": "downloads/greg_audio.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "ffmpeg_location": ffmpeg_path,
        "quiet": False,
        "nocheckcertificate": True,
        "ratelimit": 5.0,
        "sleep_interval_requests": 1,
        "prefer_ffmpeg": True,
        "force_generic_extractor": False
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
            filename = str(Path(original).with_suffix(".mp3"))

        if not os.path.exists(filename):
            raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")
    return filename, title, duration


# ----------------------- stream principal -----------------------

async def stream(url_or_query: str, ffmpeg_path: str):
    """
    1) Si URL de page SC → API v2 : progressive > hls (avec probe court si HLS)
    2) Sinon → yt_dlp (download=False) : headers vers FFmpeg
       - preview .mp3 : before_options simples
       - HLS m3u8 : whitelist/protocols, pas d'allowed_extensions !
    """
    import discord

    # --- 1) Chemin API SoundCloud quand on a une URL de page
    if isinstance(url_or_query, str) and "soundcloud.com" in url_or_query:
        ids = _sc_client_ids()
        _dbg(f"using client_ids: {len(ids) if ids else 0}")
        for cid in ids or [None]:
            if not cid:
                _dbg("no client_id → skip resolve, fall back to yt_dlp")
                break
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if not tr:
                    continue
                trans = (tr.get("media", {}) or {}).get("transcodings") or []
                _dbg("resolve → transcodings: " + str([(t.get("format") or {}).get("protocol") for t in trans]))
                stream_url, title, duration, proto = _sc_pick_progressive_stream(tr, cid)
                if not stream_url:
                    continue

                host = urlparse(stream_url).hostname
                _dbg(f"chosen protocol={proto}, host={host}")

                # Progressive MP3 → plus simple
                if proto == "progressive" and _is_preview_mp3(stream_url):
                    before = f"-headers '{_ffmpeg_headers_str(None)}' -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                    source = discord.FFmpegPCMAudio(stream_url, before_options=before, options="-vn", executable=ffmpeg_path)
                    _sc_mark_last_good(cid)
                    return source, (title or "Son inconnu")

                # HLS signé par resolve → on tente avec les opts HLS
                if _is_hls(stream_url):
                    before = (
                        f"-headers '{_ffmpeg_headers_str(None)}' "
                        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                        "-protocol_whitelist file,http,https,tcp,tls,crypto"
                    )
                    source = discord.FFmpegPCMAudio(stream_url, before_options=before, options="-vn", executable=ffmpeg_path)
                    _sc_mark_last_good(cid)
                    return source, (title or "Son inconnu")

                # Autre URL directe (rare) → tenter simple
                before = f"-headers '{_ffmpeg_headers_str(None)}' -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                source = discord.FFmpegPCMAudio(stream_url, before_options=before, options="-vn", executable=ffmpeg_path)
                _sc_mark_last_good(cid)
                return source, (title or "Son inconnu")

            except Exception as e:
                _dbg(f"resolve attempt failed (cid={cid[:4]}…): {e}")
                continue

    # --- 2) Fallback yt_dlp (download=False)
    _dbg("fallback: yt_dlp download=False")
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
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
        http_headers = info.get("http_headers") or data.get("http_headers") or {}

        host = urlparse(stream_url).hostname
        _dbg(f"yt_dlp → stream host: {host} headers: {bool(http_headers)}")

        if _is_preview_mp3(stream_url):
            # MP3 direct
            before = f"-headers '{_ffmpeg_headers_str(http_headers)}' -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        elif _is_hls(stream_url):
            # HLS : pas d'allowed_extensions !
            before = (
                f"-headers '{_ffmpeg_headers_str(http_headers)}' "
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                "-protocol_whitelist file,http,https,tcp,tls,crypto"
            )
        else:
            # Autre cas
            before = f"-headers '{_ffmpeg_headers_str(http_headers)}' -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

        # NB: on laisse FFmpeg démuxer ; si ça échoue, le caller passera en download()
        source = discord.FFmpegPCMAudio(stream_url, before_options=before, options="-vn", executable=ffmpeg_path)
        return source, title

    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
