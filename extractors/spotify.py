# extractors/spotify.py
# ----------------------------------------------------------------------
# Spotify extractor (SAFE):
# - Recherche & résolution de tracks/albums/playlists via l'API Spotify.
# - Lecture audio: redirection vers YouTube (pas de stream Spotify direct).
# - Garde-fou: lecture réservée aux utilisateurs allowlistés (set_spotify_account).
#   => on expose stream_for_user(user_id, ...) ; stream(...) lève PermissionError.
# ENV requis pour la recherche/résolution:
#   SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
# ----------------------------------------------------------------------
from __future__ import annotations

import os, time, base64
import asyncio
from typing import Dict, List, Optional, Tuple

import requests

from utils import spotify_auth
from . import youtube  # pour la lecture effective (fallback)

_SPOTIFY_TOKEN: Optional[str] = None
_SPOTIFY_EXP: float = 0.0

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("open.spotify.com/" in u) or u.startswith("spotify:")

# =================== Auth (Client Credentials) ======================

def _get_app_token() -> str:
    """
    Récupère/refresh un token d'app (client_credentials).
    """
    global _SPOTIFY_TOKEN, _SPOTIFY_EXP
    now = time.time()
    if _SPOTIFY_TOKEN and now < _SPOTIFY_EXP - 30:
        return _SPOTIFY_TOKEN

    cid = os.getenv("SPOTIFY_CLIENT_ID")
    csec = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        raise RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET manquants")

    auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {auth}"},
        timeout=10,
    )
    if not r.ok:
        raise RuntimeError(f"Spotify auth failed: {r.status_code} {r.text}")
    j = r.json()
    _SPOTIFY_TOKEN = j["access_token"]
    _SPOTIFY_EXP = now + int(j.get("expires_in", 3600))
    return _SPOTIFY_TOKEN

def _sp_get(path: str, params: Dict[str, str] | None = None) -> dict:
    tok = _get_app_token()
    r = requests.get(
        f"https://api.spotify.com/v1/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {tok}"},
        params=params or {},
        timeout=12,
    )
    if not r.ok:
        raise RuntimeError(f"Spotify API GET {path} failed: {r.status_code} {r.text}")
    return r.json()

# =================== Normalisation items ============================

def _first_img(album: dict) -> Optional[str]:
    imgs = (album or {}).get("images") or []
    if imgs:
        return imgs[0].get("url")
    return None

def _artists_str(artists: List[dict]) -> str:
    return ", ".join(a.get("name") for a in (artists or []) if a.get("name"))

def _to_item_from_track(tr: dict) -> dict:
    title = tr.get("name") or "Unknown"
    artists = _artists_str(tr.get("artists") or [])
    dur_ms = tr.get("duration_ms") or 0
    duration = int(round((dur_ms or 0) / 1000.0))
    album = tr.get("album") or {}
    track_id = tr.get("id")
    page = f"https://open.spotify.com/track/{track_id}" if track_id else None
    return {
        "title": title,
        "url": page,
        "webpage_url": page,
        "artist": artists or None,
        "duration": duration or None,
        "thumb": _first_img(album),
        "provider": "spotify",
        "spotify_id": track_id,
    }

# =================== Public: search (tracks) ========================

def search(query: str) -> List[dict]:
    """
    Recherche Spotify (tracks) → 3 premiers résultats (format like autocomplete).
    Nécessite SPOTIFY_CLIENT_ID/SECRET.
    """
    if not query or len(query.strip()) < 2:
        return []
    j = _sp_get("search", params={"q": query, "type": "track", "limit": "3"})
    items = (j.get("tracks") or {}).get("items") or []
    return [_to_item_from_track(tr) for tr in items]

# =================== Public: resolve URLs ===========================

def _parse_spotify_url(url: str) -> Tuple[str, str]:
    """
    Retourne (type, id) → type ∈ {track, album, playlist}
    """
    u = url.split("?")[0]
    parts = u.strip("/").split("/")
    # .../open.spotify.com/track/<id>
    try:
        idx = parts.index("open.spotify.com")
    except ValueError:
        # spotify:track:ID
        if url.startswith("spotify:"):
            seg = url.split(":")
            return seg[1], seg[2]
        raise RuntimeError("URL Spotify invalide")

    typ = parts[idx+1]
    sid = parts[idx+2]
    return typ, sid

def resolve_items(url: str, limit: int = 50) -> List[dict]:
    """
    Résout une URL Spotify en liste d'items normalisés.
    - track → [1 item]
    - album → [tracks...]
    - playlist → [tracks...]
    """
    typ, sid = _parse_spotify_url(url)
    out: List[dict] = []
    if typ == "track":
        tr = _sp_get(f"tracks/{sid}")
        out.append(_to_item_from_track(tr))
    elif typ == "album":
        al = _sp_get(f"albums/{sid}")
        tracks = (al.get("tracks") or {}).get("items") or []
        # enrichir chaque item avec album (pour thumb)
        album_stub = {k: al.get(k) for k in ("images", "name")}
        for t in tracks[:limit]:
            t["album"] = t.get("album") or album_stub
            out.append(_to_item_from_track(t))
    elif typ == "playlist":
        pl = _sp_get(f"playlists/{sid}", params={"fields": "tracks.items(track(name,id,artists,duration_ms,album(images)))"})
        items = ((pl.get("tracks") or {}).get("items") or [])[:limit]
        for it in items:
            tr = it.get("track") or {}
            out.append(_to_item_from_track(tr))
    else:
        raise RuntimeError(f"Type Spotify non supporté: {typ}")
    return out

# =================== Lecture (via YouTube) ==========================

def _to_youtube_query(item: dict) -> str:
    # ex: "Artist1, Artist2 - Title (audio)"
    title = item.get("title") or ""
    artist = item.get("artist") or ""
    return f"{artist} - {title} audio".strip(" -")

async def stream_for_user(user_id: int | str, url_or_query: str, ffmpeg_path: str, cookies_file: str | None = None):
    """
    Lecture réservée aux utilisateurs allowlistés :
    - Si URL Spotify → on résout → on joue le premier morceau via recherche YouTube.
    - Si chaîne 'artist - title' → recherche Spotify d'abord (optionnel), puis YouTube.
    """
    if not spotify_auth.is_allowed(user_id):
        raise PermissionError("Spotify est réservé aux utilisateurs autorisés. Utilisez /set_spotify_account.")

    # Cas URL Spotify
    if is_valid(str(url_or_query)):
        items = resolve_items(str(url_or_query), limit=1)
        if not items:
            raise RuntimeError("Aucun titre dans ce lien Spotify.")
        q = _to_youtube_query(items[0])
        return await youtube.stream(q, ffmpeg_path, cookies_file=cookies_file)

    # Cas texte libre → on tente d'améliorer la requête via Spotify
    try:
        sp = search(str(url_or_query))
        if sp:
            q = _to_youtube_query(sp[0])
        else:
            q = str(url_or_query)
    except Exception:
        q = str(url_or_query)

    return await youtube.stream(q, ffmpeg_path, cookies_file=cookies_file)

async def stream(url_or_query: str, ffmpeg_path: str, cookies_file: str | None = None):
    """
    Protection volontaire : pour éviter l'usage involontaire sans contrôle d'accès,
    cette fonction lève une PermissionError. Utiliser stream_for_user().
    """
    raise PermissionError("Utilisez spotify.stream_for_user(user_id, ...) (usage restreint).")

async def download(url: str, ffmpeg_path: str, cookies_file: str | None = None):
    """
    On ne fournit PAS de téléchargement depuis Spotify (DRM / ToS).
    Si besoin, télécharge via YouTube après résolution (logique à faire côté appelant).
    """
    raise PermissionError("Le téléchargement Spotify n'est pas supporté.")
