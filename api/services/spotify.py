# api/services/spotify.py

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from flask import abort, current_app, session

SPOTIFY_AUTH = "https://accounts.spotify.com"
SPOTIFY_API = "https://api.spotify.com/v1"


def _check_cfg():
    need = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI")
    missing = [k for k in need if not current_app.config.get(k)]
    if missing:
        abort(501, description=f"Spotify not configured. Missing: {', '.join(missing)}")


def login_url(state: str) -> str:
    _check_cfg()
    cfg = current_app.config
    params = {
        "client_id": cfg["SPOTIFY_CLIENT_ID"],
        "response_type": "code",
        "redirect_uri": cfg["SPOTIFY_REDIRECT_URI"],
        "scope": cfg["SPOTIFY_SCOPES"],
        "state": state,
        "show_dialog": "false",
    }
    return f"{SPOTIFY_AUTH}/authorize?{urlencode(params)}"


def exchange_code(code: str) -> Dict[str, Any]:
    _check_cfg()
    cfg = current_app.config
    token_url = f"{SPOTIFY_AUTH}/api/token"
    auth = base64.b64encode(f"{cfg['SPOTIFY_CLIENT_ID']}:{cfg['SPOTIFY_CLIENT_SECRET']}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["SPOTIFY_REDIRECT_URI"],
    }
    resp = requests.post(token_url, data=data, headers=headers, timeout=20)
    resp.raise_for_status()
    token = resp.json()
    session.setdefault("auth_tokens", {}).update({"spotify": token})
    return token


def _token() -> str:
    tokens = session.get("auth_tokens") or {}
    spotify = tokens.get("spotify")
    if not spotify:
        abort(401, description="Spotify not linked.")
    return spotify["access_token"]


def status() -> Dict[str, Any]:
    linked = "spotify" in (session.get("auth_tokens") or {})
    return {"linked": linked}


def logout() -> Dict[str, Any]:
    tok = (session.get("auth_tokens") or {}).pop("spotify", None)
    return {"linked": False, "was_linked": bool(tok)}


def get_playlists(limit: int = 20) -> Dict[str, Any]:
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{SPOTIFY_API}/me/playlists", params={"limit": limit}, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_playlist_tracks(playlist_id: str, limit: int = 50) -> Dict[str, Any]:
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"{SPOTIFY_API}/playlists/{playlist_id}/tracks", params={"limit": limit}, headers=headers, timeout=20
    )
    resp.raise_for_status()
    return resp.json()


# Ces opérations dépendront de ton PM (lecture en cours) ; ici, on fournit une façade.
def quickplay(spotify_url_or_uri: str) -> Dict[str, Any]:
    from .playlist_manager import enqueue
    return enqueue(spotify_url_or_uri)
