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
from urllib.parse import urlencode, urlparse
import shlex

# ---------- Constantes / cache persistant ----------
_SC_CACHE_FILE = os.getenv("SC_CACHE_FILE", "cache/soundcloud_ids.json")
_SC_CLIENT_CACHE: list[str] = []
_SC_LAST_WORKING_ID: str | None = None
_SC_CACHE_LOADED = False

def _dbg(msg: str):
    print(f"[SC] {msg}")

def _load_sc_cache():
    """Charge cache disque -> _SC_CLIENT_CACHE + _SC_LAST_WORKING_ID (une seule fois)."""
    global _SC_CACHE_LOADED, _SC_CLIENT_CACHE, _SC_LAST_WORKING_ID
    if _SC_CACHE_LOADED:
        return
    _SC_CACHE_LOADED = True
    try:
        if os.path.exists(_SC_CACHE_FILE):
            with open(_SC_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            pool = list(dict.fromkeys([str(x) for x in (data.get("pool") or []) if x]))
            last = data.get("last") or None
            _SC_CLIENT_CACHE = pool
            _SC_LAST_WORKING_ID = last
            _dbg(f"cache loaded: pool={len(pool)}, last={'yes' if last else 'no'}")
    except Exception as e:
        _dbg(f"cache load failed: {e}")

def _save_sc_cache():
    """Sauve le cache sur disque (créé dossier si besoin)."""
    try:
        d = os.path.dirname(_SC_CACHE_FILE)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        data = {"pool": list(dict.fromkeys(_SC_CLIENT_CACHE)), "last": _SC_LAST_WORKING_ID}
        with open(_SC_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _dbg(f"cache save failed: {e}")

def _sc_mark_working(cid: str):
    """Enregistre un client_id comme fonctionnel (cache mémoire + disque, priorité en tête)."""
    global _SC_LAST_WORKING_ID, _SC_CLIENT_CACHE
    if not cid:
        return
    _SC_LAST_WORKING_ID = cid
    # met en tête du pool
    try:
        if cid in _SC_CLIENT_CACHE:
            _SC_CLIENT_CACHE.remove(cid)
        _SC_CLIENT_CACHE.insert(0, cid)
    except Exception:
        pass
    _save_sc_cache()

# ---------------------------------------------------

def is_valid(url: str) -> bool:
    return "soundcloud.com" in (url or "")

# ---------- Scraping client_id (aucune récursion) ----------

def _sc_scrape_client_ids(timeout: float = 6.0, max_assets: int = 12) -> list[str]:
    """
    Scrape https://soundcloud.com, récupère les JS d'assets, extrait client_id.
    Renvoie une liste dédupliquée (ordre trouvé).
    """
    base = os.getenv("SOUNDCLOUD_SCRAPE_BASE", "https://soundcloud.com").rstrip("/")
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"})

    _dbg("scraping client_id — GET /")
    try:
        r = sess.get(base + "/", timeout=timeout)
        r.raise_for_status()
        html = r.text or ""
    except Exception as e:
        _dbg(f"scraping exception: {e}")
        return []

    # Cherche les assets JS a-v2 (ou équivalents) dans le HTML
    # On tolère <script src="..."> et les inline data-urls
    assets = re.findall(r'<script[^>]+src="([^"]+a-v2[^"]+\.js[^"]*)"', html, flags=re.I)
    # fallback : d’autres bundles
    if not assets:
        assets = re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', html, flags=re.I)

    # normalise URLs & limite
    norm_assets = []
    for a in assets:
        u = a
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = base + u
        if u.startswith("http"):
            norm_assets.append(u)
        if len(norm_assets) >= max_assets:
            break

    _dbg(f"scanning {len(norm_assets)} JS assets for client_id…")
    ids: list[str] = []
    seen = set()

    # RegEx robustes (non récursives)
    # ex: client_id:"abcd123" ou client_id="abcd123" ou "client_id":"abcd"
    rx1 = re.compile(r'client_id\s*[:=]\s*"([a-zA-Z0-9\-_]{8,64})"')
    rx2 = re.compile(r'"client_id"\s*:\s*"([a-zA-Z0-9\-_]{8,64})"')
    rx3 = re.compile(r'client_id\\":\\?"([a-zA-Z0-9\-_]{8,64})\\?"')  # version échappée

    for js_url in norm_assets:
        try:
            js = sess.get(js_url, timeout=timeout).text
        except Exception:
            continue
        for rx in (rx1, rx2, rx3):
            for m in rx.findall(js) or []:
                if m not in seen:
                    seen.add(m)
                    ids.append(m)
                    _dbg(f"found client_id in {js_url}: '{m}'")

    return ids

# ---------- Sources d'IDs (ENV -> cache -> scraping) ----------

def _sc_client_ids() -> list[str]:
    """
    Lit une liste d'IDs depuis l'env SOUNDCLOUD_CLIENT_ID,
    sinon tente cache, sinon scraping (puis met en cache).
    """
    _load_sc_cache()

    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    if raw:
        ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        random.shuffle(ids)
        _dbg(f"client_ids from env: {len(ids)}")
        return ids

    # Utilise cache si dispo
    if _SC_CLIENT_CACHE:
        return list(_SC_CLIENT_CACHE)

    # Sinon: scrape maintenant
    try:
        ids = _sc_scrape_client_ids()
        if ids:
            # met de côté
            for cid in ids:
                if cid not in _SC_CLIENT_CACHE:
                    _SC_CLIENT_CACHE.append(cid)
            _save_sc_cache()
            _dbg(f"client_ids scraped: {len(ids)}")
            return list(_SC_CLIENT_CACHE)
    except Exception as e:
        _dbg(f"scrape failed: {e}")

    return []

# ---------- API v2 resolve / transcodings ----------

def _sc_resolve_track(url: str, client_id: str, timeout: float = 8.0):
    """
    Resolve v2 -> JSON de track (avec media.transcodings).
    Retourne le JSON ou None si échec.
    """
    ses = requests.Session()
    ses.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
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

def _sc_try_resolve(url: str, timeout: float = 6.0):
    """
    Teste : last_working -> env/cache -> scraped ⇒ retourne (track_json, cid) ou (None, None).
    Pas de récursion, juste une boucle avec set() anti-doublons.
    """
    _load_sc_cache()
    ids = []
    if _SC_LAST_WORKING_ID:
        ids.append(_SC_LAST_WORKING_ID)
    ids.extend(_sc_client_ids())
    seen = set()
    for cid in ids:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        try:
            tr = _sc_resolve_track(url, cid, timeout=timeout)
            if tr:
                _dbg(f"✅ working client_id={cid[:8]}…")
                _sc_mark_working(cid)
                return tr, cid
        except Exception as e:
            _dbg(f"❌ client_id {cid[:8]}… failed: {e}")
            continue
    return None, None

# ---------- FFmpeg headers ----------

def _ffmpeg_headers_str(h: dict | None) -> str:
    """
    Construit les en-têtes CRLF que FFmpeg attend avec -headers.
    On passe au minimum: User-Agent, Referer, Origin (+ Authorization si fournie).
    IMPORTANT: on ajoute un CRLF terminal.
    """
    h = {str(k).lower(): str(v) for k, v in (h or {}).items()}
    ua = h.get("user-agent") or "Mozilla/5.0"
    ref = h.get("referer") or "https://soundcloud.com"
    org = h.get("origin") or "https://soundcloud.com"
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    # Trailing CRLF indispensable pour éviter l’avertissement de FFmpeg
    return "\r\n".join(out) + "\r\n"

# ---------- Recherche / Download ----------

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

# ---------- Stream ----------

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
        tr, cid = _sc_try_resolve(url_or_query)
        if tr and cid:
            trans = (tr.get("media", {}) or {}).get("transcodings") or []
            _dbg("resolve → transcodings: " + str([(t.get("format") or {}).get("protocol") for t in trans]))
            stream_url, title, duration, proto = _sc_pick_progressive_stream(tr, cid)
            if stream_url:
                host = urlparse(stream_url).hostname
                _dbg(f"chosen protocol={proto}, host={host}")
                hdrs = _ffmpeg_headers_str(None)

                if proto == "progressive" and ".mp3" in stream_url.split("?", 1)[0].lower():
                    before = (
                        f"-headers {shlex.quote(hdrs)} "
                        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                    )
                    source = discord.FFmpegPCMAudio(
                        stream_url,
                        before_options=before,
                        options="-vn",
                        executable=ffmpeg_path
                    )
                    return source, (title or "Son inconnu")

                # HLS signé via resolve → on tente avec headers complets
                before = (
                    f"-headers {shlex.quote(hdrs)} "
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

        # Passer les headers yt_dlp à FFmpeg (vital pour SC HLS/opus)
        http_headers = info.get('http_headers') or data.get('http_headers') or {}
        hdr = _ffmpeg_headers_str(http_headers)
        host = urlparse(stream_url).hostname
        _dbg(f"yt_dlp fallback; headers: {bool(http_headers)} host: {host}")

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
