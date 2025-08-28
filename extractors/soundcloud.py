# extractors/soundcloud.py
# ----------------------------------------------------------------------
#  Stream SoundCloud fiable (Discord/FFmpeg)
#  1) Si URL SoundCloud: API v2 + progressive MP3 quand dispo (via SOUNDCLOUD_CLIENT_ID)
#  2) Sinon: yt_dlp (download=False). En cas de HLS, on passe les headers à FFmpeg.
#  3) Fallback download() si le stream échoue ; et on marque le client_id "bon".
#  + Scraping automatique de client_id côté front (a-v2.sndcdn.com/assets/*.js)
#  + Cache persistant des client_id (fichier .sc_client_ids.json)
#  + DEBUG verbeux via env SC_DEBUG=1
# ----------------------------------------------------------------------

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
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse, urlencode

import requests
from yt_dlp import YoutubeDL


# ============================== Utils ===============================

_SC_CACHE_FILE = Path(".sc_client_ids.json")
_SC_CLIENT_CACHE: List[str] = []
_SC_MAX_CACHE = 20


def _dbg(*args):
    if os.getenv("SC_DEBUG", "0") not in ("", "0", "false", "False"):
        print("[SC]", *args)


def is_valid(url: str) -> bool:
    return isinstance(url, str) and ("soundcloud.com" in url or "sndcdn.com" in url)


def _headers_default() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": "https://soundcloud.com",
        "Origin": "https://soundcloud.com",
        "Accept": "*/*",
    }


def _ffmpeg_headers_str(h: dict | None) -> str:
    """
    Construit les en-têtes CRLF que FFmpeg attend avec -headers.
    On passe au minimum: User-Agent, Referer, Origin (+ Authorization si fournie).
    """
    base = _headers_default()
    h = {str(k).lower(): str(v) for k, v in (h or {}).items()}
    ua = h.get("user-agent") or base["User-Agent"]
    ref = h.get("referer") or base["Referer"]
    org = h.get("origin") or base["Origin"]
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    return "\r\n".join(out)


# ============================ Client IDs ============================

def _load_sc_cache():
    global _SC_CLIENT_CACHE
    try:
        if _SC_CACHE_FILE.exists():
            data = json.loads(_SC_CACHE_FILE.read_text("utf-8"))
            if isinstance(data, list):
                _SC_CLIENT_CACHE = [str(x) for x in data if x]
                _dbg(f"cache load: {_SC_CLIENT_CACHE}")
    except Exception as e:
        _dbg(f"cache load failed: {e}")


def _save_sc_cache():
    try:
        _SC_CACHE_FILE.write_text(json.dumps(list(dict.fromkeys(_SC_CLIENT_CACHE))[:_SC_MAX_CACHE]), "utf-8")
    except Exception as e:
        _dbg(f"cache save failed: {e}")


def _push_good_client_id(cid: str):
    """Met en tête l'ID qui a fonctionné, et persiste."""
    if not cid:
        return
    if cid in _SC_CLIENT_CACHE:
        _SC_CLIENT_CACHE.remove(cid)
    _SC_CLIENT_CACHE.insert(0, cid)
    while len(_SC_CLIENT_CACHE) > _SC_MAX_CACHE:
        _SC_CLIENT_CACHE.pop()
    _save_sc_cache()
    _dbg(f"mark good client_id: {cid[:4]}… -> cache={len(_SC_CLIENT_CACHE)}")


_CLIENT_ID_REGEXES = [
    re.compile(r'client_id\s*[:=]\s*"([A-Za-z0-9-_]{16,64})"'),
    re.compile(r'client_id=([A-Za-z0-9-_]{16,64})'),
]


def _sc_scrape_client_ids(max_assets: int = 12, timeout: float = 8.0) -> List[str]:
    """
    Scrape des client_id depuis https://soundcloud.com :
    - On récupère la home puis les <script src="https://a-v2.sndcdn.com/assets/...">
    - On scanne quelques assets JS à la recherche de client_id
    """
    ids: List[str] = []

    ses = requests.Session()
    ses.headers.update(_headers_default())

    _dbg("scraping client_id — GET /")
    r = ses.get("https://soundcloud.com/", timeout=timeout)
    r.raise_for_status()

    # Collecte d'URLs de scripts
    assets = set()
    for m in re.finditer(r'src="(https://[^"]+?/assets/[^"]+?\.js)"', r.text):
        assets.add(m.group(1))
    assets = list(assets)[:max_assets]
    _dbg(f"scanning {len(assets)} JS assets for client_id…")

    for url in assets:
        try:
            js = ses.get(url, timeout=timeout).text
        except Exception:
            continue
        for rx in _CLIENT_ID_REGEXES:
            for m in rx.finditer(js):
                cid = m.group(1)
                if cid and cid not in ids:
                    ids.append(cid)
                    _dbg(f"found client_id in {url}: {cid[:4]}…")

    return ids


def _sc_client_ids() -> List[str]:
    """
    IDs depuis l'env **+** cache **+** scraping.
    - env: SOUNDCLOUD_CLIENT_ID (séparé par , ; espace)
    - cache: .sc_client_ids.json
    - scraping: si rien en cache et env vide, tente maintenant
    """
    _load_sc_cache()

    # 1) Env
    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    env_ids: List[str] = []
    if raw:
        env_ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        _dbg(f"client_ids from env: {len(env_ids)}")

    # 2) Cache
    cache_ids = list(_SC_CLIENT_CACHE)

    # 3) Scrape si nécessaire (ou si env/ cache très pauvre)
    scraped_ids: List[str] = []
    if not (env_ids or cache_ids):
        try:
            scraped_ids = _sc_scrape_client_ids()
        except Exception as e:
            _dbg(f"scraping failed: {e}")

    # Fusion en gardant l'ordre : bons (cache en tête) > env > scraped
    merged = list(dict.fromkeys([*cache_ids, *env_ids, *scraped_ids]))
    random.shuffle(merged)  # on shuffle pour répartir un peu la charge
    # … mais on remet les "bons" (cache) en tête
    for good in reversed(cache_ids):
        if good in merged:
            merged.remove(good)
            merged.insert(0, good)

    return merged


# ======================== API v2 Resolve / Streams ===================

def _sc_resolve_track(page_url: str, client_id: str, timeout: float = 8.0) -> Optional[dict]:
    """
    Resolve API v2 -> JSON de track (avec media.transcodings)
    """
    ses = requests.Session()
    ses.headers.update(_headers_default())
    res_url = "https://api-v2.soundcloud.com/resolve"
    r = ses.get(res_url, params={"url": page_url, "client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None


def _pick_transcodings(track_json: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Retourne (progressive, hls) s'ils existent (peu importe l'ordre fourni).
    """
    media = (track_json or {}).get("media") or {}
    trans = media.get("transcodings") or []
    progressive = None
    hls = None
    for t in trans:
        proto = ((t.get("format") or {}).get("protocol") or "").lower()
        if proto == "progressive" and not progressive:
            progressive = t
        elif proto == "hls" and not hls:
            hls = t
    return progressive, hls


def _resolve_stream_url(transcoding: dict, client_id: str, timeout: float = 8.0) -> Optional[str]:
    """
    Appel l'endpoint de transcoding pour obtenir l'URL signée finale.
    """
    if not transcoding or not transcoding.get("url"):
        return None
    ses = requests.Session()
    ses.headers.update(_headers_default())
    u = transcoding["url"]
    r = ses.get(u, params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    j = r.json()
    url = j.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None


# =========================== Public: search ==========================

def search(query: str):
    """
    Recherche SoundCloud et renvoie des entrées 'flat' (avec 'webpage_url').
    """
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


# =========================== Public: download ========================

async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge en .mp3 (fallback si stream KO).
    """
    import os as _os
    from pathlib import Path as _Path
    _os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best",
        "outtmpl": "downloads/greg_audio.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "ffmpeg_location": ffmpeg_path,
        "quiet": False,
        "nocheckcertificate": True,
        "ratelimit": 5.0,
        "sleep_interval_requests": 1,
        "prefer_ffmpeg": True,
        "force_generic_extractor": False,
    }
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    loop = asyncio.get_event_loop()

    def _extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False), ydl

    info, ydl = await loop.run_in_executor(None, _extract)
    title = info.get("title", "Son inconnu")
    duration = info.get("duration", 0)

    # Téléchargement (yt-dlp gère la conversion MP3 via postprocessor)
    await loop.run_in_executor(None, functools.partial(ydl.download, [url]))

    original = ydl.prepare_filename(info)
    # S’assure que l’extension finale est .mp3
    filename = _Path(original).with_suffix(".mp3")
    if not _os.path.exists(filename):
        # Si postproc a déjà fait la conversion, il peut avoir un autre nom
        candidates = list(_Path("downloads").glob("greg_audio*.mp3"))
        if candidates:
            filename = candidates[0]
    if not _os.path.exists(filename):
        raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    return str(filename), title, duration


# ============================ Public: stream =========================

async def stream(url_or_query: str, ffmpeg_path: str):
    """
    Stream SoundCloud de façon fiable :
    1) si c’est une URL de page SC → tente progressive MP3 via API v2 (client_id)
    2) sinon → yt_dlp (download=False) et récupère le stream résolu (fallback)
    3) si flux HLS seulement → passe headers à FFmpeg ; sinon le caller basculera en download()
    """
    import discord  # import tardif pour ne pas charger Discord côté web/app.py

    # --- 1) Progressive via API v2 si URL SoundCloud
    if isinstance(url_or_query, str) and "soundcloud.com" in url_or_query:
        cids = _sc_client_ids()
        _dbg("using client_ids:", len(cids))
        for cid in cids or [None]:
            if not cid:
                _dbg("no client_id available → skip resolve, go yt_dlp fallback")
                break
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if not tr:
                    continue

                title = tr.get("title") or "Son inconnu"
                duration_ms = tr.get("duration") or 0
                duration = int(round(duration_ms / 1000)) if duration_ms else None

                # Accès preview/blocked ?
                access = tr.get("access") or ""
                if access.lower() == "blocked":
                    _dbg("access=blocked → cannot stream via API")
                # Choix transcoding
                progressive, hls = _pick_transcodings(tr)
                _dbg("resolve → transcodings:",
                     [((t or {}).get("format", {}) or {}).get("protocol") for t in [progressive, hls] if t])

                # Progressive d'abord
                chosen = progressive or hls
                if chosen:
                    stream_url = _resolve_stream_url(chosen, cid)
                    if stream_url:
                        _push_good_client_id(cid)
                        host = urlparse(stream_url).hostname
                        proto = ((chosen.get("format") or {}).get("protocol") or "").lower()
                        _dbg(f"resolve chosen protocol={proto}, host={host}")

                        # Options FFmpeg
                        if proto == "progressive" and ".mp3" in stream_url.split("?")[0].lower():
                            # MP3 direct → pas d'options HLS
                            before = (
                                f"-headers {shlex.quote(_ffmpeg_headers_str(None))} "
                                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                            )
                        else:
                            # HLS → whitelist/protocols OK
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
                _dbg(f"resolve attempt with client_id failed ({cid[:4]}…): {e}")
                continue

    # --- 2) Fallback: yt_dlp stream resolution (may return HLS or preview)
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        # 'extract_flat': False
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

        host = urlparse(stream_url).hostname or ""
        _dbg("yt_dlp → stream host:", host, "headers:", bool(http_headers))

        # Détecte HLS vs MP3 preview/progressive
        is_hls = ".m3u8" in stream_url.lower()
        before = f"-headers {shlex.quote(_ffmpeg_headers_str(http_headers))} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        if is_hls:
            before += " -protocol_whitelist file,http,https,tcp,tls,crypto -allowed_extensions ALL"

        # !!! IMPORTANT: n'ajouter -allowed_extensions QUE pour HLS (sinon "Option not found" possible)
        import discord
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=before,
            options="-vn",
            executable=ffmpeg_path
        )
        return source, title

    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")
