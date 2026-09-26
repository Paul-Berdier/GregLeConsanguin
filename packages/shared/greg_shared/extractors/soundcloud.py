# extractors/soundcloud.py
# ----------------------------------------------------------------------
#  SoundCloud extractor (Greg le Consanguin) — Parité avec YouTube
#  - STREAM prioritaire via API v2 (progressive MP3 quand dispo), sinon HLS
#  - Fallback yt_dlp (download=False) avec headers → FFmpeg
#  - Client IDs: ENV + cache persistant + scraping a-v2.sndcdn.com/assets/*.js
#  - Tests CLI: env | search | resolve | stream | download
#  - Proxy/IPv4: respecte HTTP(S)_PROXY / ALL_PROXY / SC_FORCE_IPV4
#  - Debug: SC_DEBUG=1 pour traces verbeuses
#  - Sets/albums (/sets/) : is_playlist_url + expand_bundle (permaliens)
#  - Liens courts on.soundcloud.com : redirection suivie avant stream/expand
#  - HTTP bloquant (client_id, resolve, transcoding) exécuté hors boucle asyncio
#  - CLI : python -m greg_shared.extractors.soundcloud <cmd>
# ----------------------------------------------------------------------

from __future__ import annotations

import asyncio
import base64
import functools
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL

# ============================== DEBUG / ENV ===============================

_SCDBG = os.getenv("SC_DEBUG", "0").lower() not in ("", "0", "false", "no")
_FORCE_IPV4 = os.getenv("SC_FORCE_IPV4", "1").lower() not in ("", "0", "false", "no")
_HTTP_PROXY = os.getenv("YTDLP_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

def _dbg(*args):
    if _SCDBG:
        print("[SCDBG]", *args)

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
    """Construit les en-têtes CRLF que FFmpeg attend avec -headers."""
    base = _headers_default()
    h = {str(k).lower(): str(v) for k, v in (h or {}).items()}
    ua = h.get("user-agent") or base["User-Agent"]
    ref = h.get("referer") or base["Referer"]
    org = h.get("origin") or base["Origin"]
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    return "\r\n".join(out)

# ------------------------ FFmpeg path helpers ------------------------

def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Résout le binaire FFmpeg à exécuter ET le dossier à donner à yt-dlp (pour ffprobe).
    Retourne (ffmpeg_exec, ffmpeg_location_dir|None).
    """
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    def _abs(p: str) -> str:
        return os.path.abspath(os.path.expanduser(p))

    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        if which:
            return which, os.path.dirname(which)
        return "ffmpeg", None

    if not os.path.dirname(ffmpeg_hint):
        # Nom nu ("ffmpeg") : c'est le PATH qui fait foi, pas le CWD
        which = shutil.which(ffmpeg_hint)
        if which:
            return which, os.path.dirname(which)

    p = _abs(ffmpeg_hint)
    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand):
            return cand, p
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2):
            return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans le dossier: {p}")
    if os.path.isfile(p):
        return p, os.path.dirname(p)
    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)
    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")

# ============================ Client IDs ============================

from pathlib import Path as _Path
_SC_CACHE_FILE = _Path(".sc_client_ids.json")
_SC_CLIENT_CACHE: List[str] = []
_SC_MAX_CACHE = 20
_SC_CACHE_LOCK = threading.Lock()  # le resolve tourne désormais dans des threads

_CLIENT_ID_REGEXES = [
    re.compile(r'client_id\s*[:=]\s*"([A-Za-z0-9-_]{16,64})"'),
    re.compile(r'client_id=([A-Za-z0-9-_]{16,64})'),
]

def _load_sc_cache():
    global _SC_CLIENT_CACHE
    try:
        if _SC_CACHE_FILE.exists():
            data = json.loads(_SC_CACHE_FILE.read_text("utf-8"))
            if isinstance(data, list):
                with _SC_CACHE_LOCK:
                    _SC_CLIENT_CACHE = [str(x) for x in data if x]
                _dbg("cache load:", _SC_CLIENT_CACHE[:3], f"(total {len(_SC_CLIENT_CACHE)})")
    except Exception as e:
        _dbg("cache load failed:", e)

def _save_sc_cache():
    try:
        _SC_CACHE_FILE.write_text(json.dumps(list(dict.fromkeys(_SC_CLIENT_CACHE))[:_SC_MAX_CACHE]), "utf-8")
    except Exception as e:
        _dbg("cache save failed:", e)

def _push_good_client_id(cid: str):
    if not cid:
        return
    with _SC_CACHE_LOCK:
        if cid in _SC_CLIENT_CACHE:
            _SC_CLIENT_CACHE.remove(cid)
        _SC_CLIENT_CACHE.insert(0, cid)
        while len(_SC_CLIENT_CACHE) > _SC_MAX_CACHE:
            _SC_CLIENT_CACHE.pop()
        _save_sc_cache()
    _dbg(f"mark good client_id: {cid[:4]}… (cache={len(_SC_CLIENT_CACHE)})")

def _requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_headers_default())
    if _HTTP_PROXY:
        s.proxies.update({"http": _HTTP_PROXY, "https": _HTTP_PROXY})
    return s

def _sc_scrape_client_ids(max_assets: int = 12, timeout: float = 8.0) -> List[str]:
    """Scrape des client_id depuis la home + assets JS."""
    ids: List[str] = []
    ses = _requests_session()
    _dbg("scraping client_id — GET /")
    r = ses.get("https://soundcloud.com/", timeout=timeout)
    r.raise_for_status()

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
    - env: SOUNDCLOUD_CLIENT_ID (séparés par , ; espace)
    - cache: .sc_client_ids.json
    - scraping: si rien → tente maintenant
    """
    _load_sc_cache()

    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    env_ids: List[str] = []
    if raw:
        env_ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        _dbg(f"client_ids from env: {len(env_ids)}")

    cache_ids = list(_SC_CLIENT_CACHE)

    scraped_ids: List[str] = []
    if not (env_ids or cache_ids):
        try:
            scraped_ids = _sc_scrape_client_ids()
        except Exception as e:
            _dbg("scraping failed:", e)

    merged = list(dict.fromkeys([*cache_ids, *env_ids, *scraped_ids]))
    random.shuffle(merged)
    for good in reversed(cache_ids):
        if good in merged:
            merged.remove(good)
            merged.insert(0, good)
    return merged

# ======================== API v2 Resolve / Streams ===================

def _sc_resolve_track(page_url: str, client_id: str, timeout: float = 8.0) -> Optional[dict]:
    """Resolve API v2 -> JSON de track (avec media.transcodings)."""
    ses = _requests_session()
    r = ses.get("https://api-v2.soundcloud.com/resolve",
                params={"url": page_url, "client_id": client_id},
                timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None

def _sc_resolve(page_url: str, client_id: str, timeout: float = 8.0) -> Tuple[int, Optional[dict]]:
    """Resolve API v2 générique (track, playlist…) → (status HTTP, JSON|None)."""
    ses = _requests_session()
    r = ses.get("https://api-v2.soundcloud.com/resolve",
                params={"url": page_url, "client_id": client_id},
                timeout=timeout)
    if not r.ok:
        return r.status_code, None
    data = r.json()
    return r.status_code, (data if isinstance(data, dict) else None)

def _is_preview_transcoding(t: dict) -> bool:
    """Extrait Go+ de 30 s (yt-dlp : `snipped` ou '/preview/' dans l'URL)."""
    return bool(t.get("snipped")) or "/preview/" in str(t.get("url") or "")

def _pick_transcodings(track_json: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """Retourne (progressive, hls) s'ils existent (jamais un extrait Go+)."""
    media = (track_json or {}).get("media") or {}
    trans = media.get("transcodings") or []
    progressive = None
    hls = None
    for t in trans:
        if _is_preview_transcoding(t):
            continue
        proto = ((t.get("format") or {}).get("protocol") or "").lower()
        if proto == "progressive" and not progressive:
            progressive = t
        elif proto == "hls" and not hls:
            hls = t
    return progressive, hls

def _resolve_stream_url(transcoding: dict, client_id: str, timeout: float = 8.0) -> Optional[str]:
    """Appelle l'endpoint de transcoding pour obtenir l'URL signée finale."""
    if not transcoding or not transcoding.get("url"):
        return None
    ses = _requests_session()
    u = transcoding["url"]
    r = ses.get(u, params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    j = r.json()
    url = j.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None

# ======================= Public: sets / playlists =====================

_SC_SET_PATH_RE = re.compile(r"^/[^/]+/sets/[^/]+", re.IGNORECASE)
_SC_BUNDLE_MARGIN = 5

def is_playlist_url(url: str) -> bool:
    """Set / album SoundCloud (/<user>/sets/<slug>). Seul le chemin compte :
    `…/track?in=user/sets/x` reste un titre."""
    if not isinstance(url, str):
        return False
    s = url.strip()
    if s and "://" not in s:
        s = "https://" + s
    try:
        u = urlparse(s)
    except Exception:
        return False
    host = (u.hostname or "").lower()
    if host not in ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"):
        return False
    return bool(_SC_SET_PATH_RE.match(u.path or ""))

def _sc_canonical_page(url: str) -> str:
    s = url.strip()
    if "://" not in s:
        s = "https://" + s
    u = urlparse(s)
    return f"https://soundcloud.com{u.path.rstrip('/')}"

_SC_SHORT_HOSTS = ("on.soundcloud.com",)
_SC_PAGE_HOSTS = ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com")

def is_short_link(url: str) -> bool:
    """Lien de partage de l'appli mobile (https://on.soundcloud.com/AbCd) :
    titre OU set, on ne le sait qu'après la redirection (hors ligne ici)."""
    if not isinstance(url, str):
        return False
    s = url.strip()
    if s and "://" not in s:
        s = "https://" + s
    try:
        return (urlparse(s).hostname or "").lower() in _SC_SHORT_HOSTS
    except Exception:
        return False

def resolve_short_link(url: str, timeout: float = 8.0) -> str:
    """on.soundcloud.com/… → permalien canonique (redirection 302 suivie, HEAD).

    SYNCHRONE (réseau) : à lancer dans un thread. Pas un lien court → inchangé,
    sans réseau. Échec → lien d'origine inchangé.
    """
    if not is_short_link(url):
        return url
    s = url.strip()
    if "://" not in s:
        s = "https://" + s
    try:
        r = _requests_session().head(s, allow_redirects=True, timeout=timeout)
        final = str(getattr(r, "url", "") or "")
        host = (urlparse(final).hostname or "").lower()
        if getattr(r, "ok", False) and host in _SC_PAGE_HOSTS:
            page = _sc_canonical_page(final)
            _dbg(f"lien court {s} → {page}")
            return page
        _dbg(f"lien court {s} non résolu (status={getattr(r, 'status_code', '?')}, final={final})")
    except Exception as e:
        _dbg(f"lien court {s} : résolution impossible: {e}")
    return url

def _sc_track_playable(t: dict) -> bool:
    if not isinstance(t, dict) or not t.get("permalink_url"):
        return False
    if t.get("streamable") is False:
        return False
    # BLOCK = bloqué ici ; SNIP = extrait Go+ de 30 s seulement
    return str(t.get("policy") or "").upper() not in ("BLOCK", "SNIP")

def _sc_track_item(t: dict) -> dict:
    url = str(t.get("permalink_url"))
    thumb = t.get("artwork_url") or ((t.get("user") or {}).get("avatar_url"))
    if isinstance(thumb, str):
        thumb = thumb.replace("-large.", "-t500x500.")
    dur_ms = t.get("full_duration") or t.get("duration")
    return {
        "title": t.get("title") or url,
        "url": url,
        "webpage_url": url,
        "artist": (t.get("user") or {}).get("username"),
        "thumb": thumb,
        "duration": int(dur_ms / 1000) if isinstance(dur_ms, (int, float)) and dur_ms > 0 else None,
        "provider": "soundcloud",
    }

def _sc_tracks_by_ids(ids: List[int], client_id: str, timeout: float = 8.0) -> Dict[int, dict]:
    """Complète les « stubs » d'un set (au-delà des ~5 premiers titres)."""
    out: Dict[int, dict] = {}
    ses = _requests_session()
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = ses.get("https://api-v2.soundcloud.com/tracks",
                    params={"ids": ",".join(str(x) for x in chunk), "client_id": client_id},
                    timeout=timeout)
        if not r.ok:
            continue
        for t in r.json() or []:
            if isinstance(t, dict) and t.get("id") is not None:
                out[t["id"]] = t
    return out

def _expand_with_ytdlp(page_url: str, limit: int) -> List[dict]:
    """Repli : listing flat yt-dlp (titres parfois absents → URL en titre)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": limit + _SC_BUNDLE_MARGIN,
        "ignoreerrors": False,
        "socket_timeout": 10,
    }
    if _HTTP_PROXY:
        opts["proxy"] = _HTTP_PROXY
    if _FORCE_IPV4:
        opts["source_address"] = "0.0.0.0"
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(page_url, download=False)
    out = []
    for e in (info or {}).get("entries") or []:
        url = (e or {}).get("url") or (e or {}).get("webpage_url")
        if not url:
            continue
        out.append({
            "title": e.get("title") or url,
            "url": url,
            "webpage_url": url,
            "artist": e.get("uploader"),
            "thumb": e.get("thumbnail"),
            "duration": int(e["duration"]) if isinstance(e.get("duration"), (int, float)) else None,
            "provider": "soundcloud",
        })
    return out[:limit]

def expand_bundle(url: str, *, limit: int = 10, cookies_file: Optional[str] = None,
                  cookies_from_browser: Optional[str] = None) -> List[dict]:
    """Liste les titres d'un set/album SoundCloud (SYNCHRONE, rapide).

    API v2 resolve (+ /tracks?ids= pour les stubs), repli yt-dlp flat.
    Lien court on.soundcloud.com : résolu d'abord (set → ses titres,
    titre → ce seul titre).
    Entrées : permaliens canoniques `https://soundcloud.com/<user>/<titre>`.
    Lève BundleError (PLAYLIST_UNAVAILABLE / PLAYLIST_EMPTY).
    """
    from . import BundleError  # import tardif : le module reste lançable en CLI

    N = max(1, int(limit or 10))
    if is_short_link(url):
        resolved = resolve_short_link(url)
        if is_short_link(resolved):
            raise BundleError("PLAYLIST_UNAVAILABLE",
                              "Impossible d'ouvrir ce lien court SoundCloud (on.soundcloud.com).")
        url = resolved
    page = _sc_canonical_page(url)
    data: Optional[dict] = None
    good_cid: Optional[str] = None
    for cid in _sc_client_ids() or []:
        try:
            status, data = _sc_resolve(page, cid)
        except Exception as e:
            _dbg(f"set resolve failed ({cid[:4]}…): {e}")
            data = None
            continue
        if status == 404:
            raise BundleError("PLAYLIST_UNAVAILABLE",
                              "Cette playlist SoundCloud est introuvable ou privée.")
        if data:
            good_cid = cid
            break

    if data is None:
        try:
            out = _expand_with_ytdlp(page, N)
        except Exception as e:
            _dbg(f"set yt-dlp fallback failed: {e}")
            raise BundleError("PLAYLIST_UNAVAILABLE",
                              "Impossible de lire cette playlist SoundCloud pour le moment.") from e
    else:
        _push_good_client_id(good_cid)
        if data.get("kind") == "track":
            tracks = [data]
        else:
            tracks = [t for t in (data.get("tracks") or []) if isinstance(t, dict)]
        window = tracks[:N + _SC_BUNDLE_MARGIN]
        stub_ids = [t["id"] for t in window if not t.get("permalink_url") and t.get("id") is not None]
        if stub_ids:
            try:
                full = _sc_tracks_by_ids(stub_ids, good_cid)
                window = [full.get(t.get("id"), t) for t in window]
            except Exception as e:
                _dbg(f"tracks?ids failed: {e}")
        out = [_sc_track_item(t) for t in window if _sc_track_playable(t)][:N]

    if not out:
        raise BundleError("PLAYLIST_EMPTY",
                          "Cette playlist SoundCloud est vide ou ne contient aucun titre lisible.")
    return out

# =========================== Public: search ==========================

def search(query: str):
    """Recherche SoundCloud (flat entries avec webpage_url)."""
    ydl_opts = {
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,
    }
    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []

# =========================== Public: download ========================

async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge en .mp3 (postproc FFmpeg 192 kbps / 48 kHz).
    Reste async pour compat avec ton code actuel.
    """
    from pathlib import Path as _Path
    os.makedirs("downloads", exist_ok=True)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best",
        "outtmpl": "downloads/greg_audio.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "postprocessor_args": ["-ar", "48000"],
        "ffmpeg_location": ff_loc or os.path.dirname(ff_exec),
        "quiet": False,
        "nocheckcertificate": True,
        "sleep_interval_requests": 0,
        "prefer_ffmpeg": True,
        "force_generic_extractor": False,
        "retries": 5,
        "fragment_retries": 5,
    }
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY
    if _FORCE_IPV4:
        ydl_opts["source_address"] = "0.0.0.0"

    loop = asyncio.get_running_loop()

    def _extract_and_download():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            ydl.download([url])
            return info, ydl

    info, ydl = await loop.run_in_executor(None, _extract_and_download)
    title = (info or {}).get("title", "Son inconnu")
    duration = (info or {}).get("duration", 0)

    original = ydl.prepare_filename(info)
    filename = Path(original).with_suffix(".mp3")
    if not os.path.exists(filename):
        candidates = list(Path("downloads").glob("greg_audio*.mp3"))
        if candidates:
            filename = candidates[0]
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    return str(filename), title, duration

# ============================ Public: stream =========================

def _api_v2_resolve_stream(page_url: str) -> Optional[Tuple[str, str, bool]]:
    """Partie API v2 de stream(), SYNCHRONE (lancée via asyncio.to_thread) :
    client_ids (+ scraping), resolve, transcoding → (stream_url, title, is_hls).
    None → repli yt-dlp ; TrackUnavailable si le titre est bloqué / extrait Go+."""
    from . import TrackUnavailable  # import tardif : le module reste lançable en CLI

    cids = _sc_client_ids()
    _dbg("client_ids available:", len(cids))
    for cid in cids or [None]:
        if not cid:
            _dbg("no client_id available → skip resolve, go yt_dlp fallback")
            break
        try:
            status, tr = _sc_resolve(page_url, cid)
            if status == 404:
                return None  # introuvable pour tous les client_id : repli yt_dlp direct
            if not tr:
                continue
            if tr.get("kind") == "playlist":
                # Un set résolu comme « titre » : jamais son 1er morceau en silence
                raise TrackUnavailable(
                    "Lien de playlist SoundCloud : il doit être ajouté comme playlist, pas comme un titre."
                )
            if tr.get("kind") != "track" and "media" not in tr:
                _dbg(f"resolve kind={tr.get('kind')} → pas un titre, repli yt_dlp")
                return None

            title = tr.get("title") or "Son inconnu"
            policy = str(tr.get("policy") or "").upper()
            if tr.get("access", "").lower() == "blocked" or policy == "BLOCK":
                _dbg("access=blocked → cannot stream via API")
                raise TrackUnavailable("Titre SoundCloud bloqué dans ce pays.")
            progressive, hls = _pick_transcodings(tr)
            _dbg("resolve → transcodings:",
                 [((t or {}).get("format", {}) or {}).get("protocol") for t in [progressive, hls] if t])

            chosen = progressive or hls
            if not chosen:
                trans = ((tr.get("media") or {}).get("transcodings") or [])
                if policy == "SNIP" or (trans and all(_is_preview_transcoding(t) for t in trans)):
                    raise TrackUnavailable(
                        "Titre SoundCloud Go+ : seul un extrait de 30 s est disponible."
                    )
                continue
            stream_url = _resolve_stream_url(chosen, cid)
            if stream_url:
                _push_good_client_id(cid)
                proto = ((chosen.get("format") or {}).get("protocol") or "").lower()
                is_hls = proto == "hls" or stream_url.lower().endswith(".m3u8")
                return stream_url, title, is_hls
        except TrackUnavailable:
            raise
        except Exception as e:
            _dbg(f"resolve attempt failed ({cid[:4]}…): {e}")
            continue
    return None

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    afilter: Optional[str] = None,  # ★ nouveau: filtre audio optionnel
):
    """
    Stream SoundCloud :
    1) URL SoundCloud → API v2 (progressive prioritaire, sinon HLS) → FFmpeg
    2) Sinon → yt_dlp (download=False) → FFmpeg avec headers
    Retourne (discord.FFmpegPCMAudio, title)
    """
    import discord  # import tardif pour éviter charge côté outils CLI

    from . import TrackUnavailable

    if isinstance(url_or_query, str) and is_short_link(url_or_query):
        # Lien court de l'appli (titre ou set ?) : redirection suivie (HTTP → thread)
        url_or_query = await asyncio.to_thread(resolve_short_link, url_or_query)

    if isinstance(url_or_query, str) and is_playlist_url(url_or_query):
        # Un set passé comme titre : jamais résolu en entier ici
        raise TrackUnavailable(
            f"Lien de playlist SoundCloud ({_sc_canonical_page(url_or_query)}) : "
            "il doit être ajouté comme playlist, pas comme un titre."
        )

    ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_path)

    # Build sortie FFmpeg (commune) : 48 kHz + stéréo + faible latence + filtre éventuel
    def _out_opts(base: str = "") -> str:
        opts = "-vn -ar 48000 -ac 2 -fflags nobuffer -flags low_delay"
        if base:
            opts = base + " " + opts
        if afilter:
            opts += f" -af {shlex.quote(afilter)}"
        _dbg("FFMPEG out_options:", opts)
        return opts

    # --- 1) Progressive/HLS via API v2 si URL SoundCloud (HTTP bloquant → thread)
    if isinstance(url_or_query, str) and "soundcloud.com" in url_or_query:
        resolved = await asyncio.to_thread(_api_v2_resolve_stream, url_or_query)
        if resolved:
            stream_url, title, is_hls = resolved

            before = f"-headers {shlex.quote(_ffmpeg_headers_str(None))} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            if _HTTP_PROXY:
                before += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
            if _FORCE_IPV4:
                before += " -protocol_whitelist file,http,https,tcp,tls,crypto"
            if is_hls:
                before += " -protocol_whitelist file,http,https,tcp,tls,crypto -allowed_extensions ALL"

            out = _out_opts()  # ★ applique -ar 48k, -ac 2 et -af si présent
            _dbg("FFMPEG before_options:", before)

            source = discord.FFmpegPCMAudio(
                stream_url,
                before_options=before,
                options=out,
                executable=ff_exec
            )
            return source, title

    # --- 2) Fallback: yt_dlp (peut renvoyer HLS)
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "scsearch3",
        "noplaylist": True,
        "playlist_items": "1",  # un set (ex. lien court) n'est jamais résolu en entier
        "nocheckcertificate": True,
        "retries": 5,
        "fragment_retries": 5,
    }
    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY
    if _FORCE_IPV4:
        ydl_opts["source_address"] = "0.0.0.0"

    loop = asyncio.get_running_loop()

    def _extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    try:
        data = await loop.run_in_executor(None, _extract) or {}
        if data.get("_type") == "playlist" and is_playlist_url(str(data.get("webpage_url") or "")):
            # ex. lien court non résolu que yt-dlp a suivi jusqu'à un set
            raise TrackUnavailable(
                f"Lien de playlist SoundCloud ({_sc_canonical_page(str(data['webpage_url']))}) : "
                "il doit être ajouté comme playlist, pas comme un titre."
            )
        entries = [e for e in (data.get("entries") or []) if e] if "entries" in data else [data]
        if not entries or not entries[0].get("url"):
            raise RuntimeError("aucun flux audio")
        info = entries[0]
        stream_url = info["url"]
        if "/preview/" in stream_url or "preview" in str(info.get("format_id") or ""):
            raise TrackUnavailable("Titre SoundCloud Go+ : seul un extrait de 30 s est disponible.")
        title = info.get("title", "Son inconnu")
        http_headers = info.get("http_headers") or data.get("http_headers") or {}
        is_hls = ".m3u8" in stream_url.lower()

        before = f"-headers {shlex.quote(_ffmpeg_headers_str(http_headers))} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        if _HTTP_PROXY:
            before += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
        if is_hls:
            before += " -protocol_whitelist file,http,https,tcp,tls,crypto -allowed_extensions ALL"

        out = _out_opts()
        _dbg("FFMPEG before_options:", before)

        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=before,
            options=out,
            executable=ff_exec
        )
        return source, title

    except TrackUnavailable:
        raise
    except Exception as e:
        if re.search(r"\bdrm\b", str(e), re.IGNORECASE):
            # Flux uniquement chiffrés (DRM) : définitif, inutile de réessayer
            raise TrackUnavailable("Titre SoundCloud protégé par DRM : lecture impossible.") from e
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")

# ======================== Helpers de test (CLI) =======================

def _print_env_summary():
    print("\n=== SC ENV SUMMARY ===")
    print(f"FORCE_IPV4: {_FORCE_IPV4}")
    print(f"PROXY: {_HTTP_PROXY or 'none'}")
    print(f"SC_DEBUG: {_SCDBG}")
    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID") or "").strip()
    print(f"SOUNDCLOUD_CLIENT_ID: {'set' if raw else 'unset'}")
    cache_count = 0
    try:
        if _SC_CACHE_FILE.exists():
            cache_count = len(json.loads(_SC_CACHE_FILE.read_text('utf-8')) or [])
    except Exception:
        pass
    print(f"Cache file: {_SC_CACHE_FILE} (ids={cache_count})")
    print("======================\n")

def _ffmpeg_pull_test(url: str, headers_blob: str, ffmpeg_path: str, seconds: int = 3, is_hls: bool = False) -> int:
    ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_path)
    before = [
        "-nostdin",
        "-headers", headers_blob,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-probesize", "32k", "-analyzeduration", "0",
        "-fflags", "nobuffer", "-flags", "low_delay",
    ]
    if _HTTP_PROXY:
        before += ["-http_proxy", _HTTP_PROXY]
    if is_hls:
        before += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-allowed_extensions", "ALL"]
    cmd = [ff_exec] + before + ["-i", url, "-t", str(seconds), "-f", "null", "-"]
    print("[CLI] ffmpeg test cmd:", " ".join(shlex.quote(c) for c in cmd))
    cp = subprocess.run(cmd, text=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    print("[CLI] ffmpeg exit:", cp.returncode)
    if cp.stdout:
        print(cp.stdout[-1200:])
    return cp.returncode

# =============================== CLI =================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("SoundCloud extractor debug CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="Afficher le résumé d'environnement")

    p_search = sub.add_parser("search", help="Recherche scsearch3")
    p_search.add_argument("query")

    p_res = sub.add_parser("resolve", help="Resolve API v2 (transcodings, stream URL)")
    p_res.add_argument("url")

    p_stream = sub.add_parser("stream", help="Tester un pull FFmpeg (API v2 progressive/HLS sinon yt-dlp)")
    p_stream.add_argument("url")
    p_stream.add_argument("--ffmpeg", required=True, help="Chemin vers ffmpeg (exe OU dossier)")
    p_stream.add_argument("--seconds", type=int, default=3)

    p_dl = sub.add_parser("download", help="Télécharger et convertir (mp3)")
    p_dl.add_argument("url")
    p_dl.add_argument("--ffmpeg", required=False, default=shutil.which("ffmpeg") or "ffmpeg",
                      help="Chemin vers ffmpeg (exe OU dossier)")

    args = parser.parse_args()
    _print_env_summary()

    if args.cmd == "env":
        sys.exit(0)

    elif args.cmd == "search":
        res = search(args.query)
        print(f"Results: {len(res)}")
        for i, e in enumerate(res or [], 1):
            t = e.get("title") or "?"
            u = e.get("webpage_url") or e.get("url") or "?"
            print(f" {i}. {t} — {u}")

    elif args.cmd == "resolve":
        ids = _sc_client_ids()
        print(f"Trying {len(ids)} client_id(s)…")
        for cid in ids or [None]:
            if not cid:
                print("no client_id available.")
                break
            tr = _sc_resolve_track(args.url, cid)
            if not tr:
                continue
            prog, hls = _pick_transcodings(tr)
            print("title:", tr.get("title"))
            print("transcodings:", [((t or {}).get("format", {}) or {}).get("protocol") for t in [prog, hls] if t])
            chosen = prog or hls
            if chosen:
                su = _resolve_stream_url(chosen, cid)
                print("resolved stream host:", urlparse(su).hostname if su else None)
                if su:
                    print("OK (first resolved).")
                    sys.exit(0)
        print("No stream resolved via API v2.")
        sys.exit(2)

    elif args.cmd == "stream":
        # 1) Essai API v2
        ids = _sc_client_ids()
        ok = False
        if "soundcloud.com" in args.url:
            for cid in ids or [None]:
                if not cid:
                    break
                tr = _sc_resolve_track(args.url, cid)
                if not tr:
                    continue
                prog, hls = _pick_transcodings(tr)
                chosen = prog or hls
                if not chosen:
                    continue
                su = _resolve_stream_url(chosen, cid)
                if not su:
                    continue
                proto = ((chosen.get("format") or {}).get("protocol") or "").lower()
                is_hls = proto == "hls" or su.lower().endswith(".m3u8")
                hdr_blob = _ffmpeg_headers_str(None)
                code = _ffmpeg_pull_test(su, hdr_blob, args.ffmpeg, seconds=args.seconds, is_hls=is_hls)
                sys.exit(code)
        # 2) Fallback yt-dlp
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "default_search": "scsearch3",
            "nocheckcertificate": True,
            "retries": 3,
            "fragment_retries": 3,
        }
        if _HTTP_PROXY:
            ydl_opts["proxy"] = _HTTP_PROXY
        if _FORCE_IPV4:
            ydl_opts["source_address"] = "0.0.0.0"
        with YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(args.url, download=False)
        info = data["entries"][0] if "entries" in data else data
        su = info["url"]
        is_hls = ".m3u8" in su.lower()
        hdr_blob = _ffmpeg_headers_str(info.get("http_headers") or data.get("http_headers") or {})
        code = _ffmpeg_pull_test(su, hdr_blob, args.ffmpeg, seconds=args.seconds, is_hls=is_hls)
        sys.exit(code)

    elif args.cmd == "download":
        try:
            path, title, dur = asyncio.run(download(args.url, args.ffmpeg))
            print(f"OK: {path} | {title} | {dur}")
            sys.exit(0)
        except Exception as e:
            print(f"DOWNLOAD ERROR: {e}")
            sys.exit(3)
