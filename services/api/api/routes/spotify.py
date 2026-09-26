"""Spotify routes — gestion des playlists Spotify via bot bridge.

Le front peut lier Spotify, charger les playlists, ajouter des titres, etc.
Tout passe par le bot bridge Redis pour le moment, sauf le flow OAuth
qui est géré directement par l'API.
"""
from __future__ import annotations

import logging
import os
import traceback

import requests as req
from flask import Blueprint, jsonify, request, session, redirect

from greg_shared.config import settings
from api.routes.player import error_status, play_for_user_response
from api.services.bot_bridge import send_command

logger = logging.getLogger("greg.api.spotify")

bp = Blueprint("spotify", __name__)

_SP_SEARCH_URL = "https://api.spotify.com/v1/search"


def _json_body() -> dict:
    """Corps JSON de la requête — toujours un dict (un JSON non-objet est ignoré)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _to_int(v):
    """int() tolérant : None si la valeur n'est pas un entier valide."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _sp_failed(r):
    """Réponse d'erreur quand Spotify refuse l'appel (token expiré, playlist non possédée…)."""
    logger.warning("Spotify HTTP %s: %s", r.status_code, (getattr(r, "text", "") or "")[:200])
    return jsonify({"ok": False, "error": f"HTTP {r.status_code}"}), 400


def _sp_search_track(h, search_q: str, timeout: int):
    """Recherche Spotify d'un titre — la query est encodée par requests (params=)."""
    return req.get(
        _SP_SEARCH_URL,
        params={"q": search_q, "type": "track", "limit": 1},
        headers=h, timeout=timeout,
    )


def _bot_state(gid: int, timeout: int):
    """État du bot → (state, None) ou (None, réponse d'erreur) si le bot n'a pas répondu."""
    state_res = send_command("get_state", gid, timeout=timeout)
    if not state_res.get("ok"):
        out = {"ok": False, "error": state_res.get("error", "unknown")}
        if state_res.get("message"):
            out["message"] = state_res["message"]
        return None, (jsonify(out), error_status(state_res))
    state = state_res.get("state", state_res)
    return (state if isinstance(state, dict) else {}), None


# ── OAuth ──

@bp.get("/spotify/login")
def spotify_login():
    """Redirige vers l'OAuth Spotify."""
    client_id = settings.spotify_client_id
    redirect_uri = settings.spotify_redirect_uri
    scopes = settings.spotify_scopes or "playlist-read-private playlist-modify-public playlist-modify-private user-read-private"

    if not client_id or not redirect_uri:
        return jsonify({"ok": False, "error": "spotify_not_configured"}), 500

    sid = request.args.get("sid", "")
    state = sid  # On passe le socket ID dans le state pour notifier le client

    url = (
        f"https://accounts.spotify.com/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scopes.replace(' ', '%20')}"
        f"&state={state}"
    )
    return redirect(url)


@bp.get("/spotify/callback")
def spotify_callback():
    """Callback OAuth Spotify."""
    try:
        code = request.args.get("code")
        state = request.args.get("state", "")  # socket_id

        if not code:
            return jsonify({"ok": False, "error": "missing_code"}), 400

        # Exchange code for token
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
            "client_id": settings.spotify_client_id,
            "client_secret": settings.spotify_client_secret,
        }
        r = req.post("https://accounts.spotify.com/api/token", data=data, timeout=20)
        if r.status_code != 200:
            return jsonify({"ok": False, "error": "token_exchange_failed", "details": r.text[:500]}), 400

        token_data = r.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token:
            return jsonify({"ok": False, "error": "no_access_token"}), 400

        # Get Spotify profile
        headers = {"Authorization": f"Bearer {access_token}"}
        me_r = req.get("https://api.spotify.com/v1/me", headers=headers, timeout=10)
        profile = me_r.json() if me_r.ok else {}

        session["spotify_token"] = access_token
        session["spotify_refresh"] = refresh_token
        session["spotify_profile"] = profile

        # Notify socket if state (sid) was provided
        if state:
            try:
                from api import socketio
                socketio.emit("spotify:linked", {"profile": profile}, room=state)
            except Exception:
                pass

        # Close popup
        return """
        <html><body><script>
        if (window.opener) window.opener.focus();
        window.close();
        </script><p>Spotify lié ! Vous pouvez fermer cette fenêtre.</p></body></html>
        """
    except Exception as e:
        logger.error("spotify callback error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Status ──

@bp.get("/spotify/status")
def spotify_status():
    token = session.get("spotify_token")
    profile = session.get("spotify_profile")
    return jsonify({
        "ok": True,
        "linked": bool(token),
        "profile": profile,
    }), 200


@bp.get("/spotify/me")
def spotify_me():
    token = session.get("spotify_token")
    if not token:
        return jsonify({"ok": False, "error": "not_linked"}), 401

    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = req.get("https://api.spotify.com/v1/me", headers=headers, timeout=10)
        if r.ok:
            profile = r.json()
            session["spotify_profile"] = profile
            return jsonify({"ok": True, "profile": profile}), 200
        return jsonify({"ok": False, "error": "fetch_failed"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post("/spotify/logout")
def spotify_logout():
    session.pop("spotify_token", None)
    session.pop("spotify_refresh", None)
    session.pop("spotify_profile", None)
    return jsonify({"ok": True}), 200


# ── Playlists ──

def _sp_headers():
    token = session.get("spotify_token")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@bp.get("/spotify/playlists")
def spotify_playlists():
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    try:
        r = req.get("https://api.spotify.com/v1/me/playlists?limit=50", headers=h, timeout=15)
        if not r.ok:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"}), 400
        data = r.json()
        return jsonify({"ok": True, "items": data.get("items", [])}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.get("/spotify/playlist_tracks")
def spotify_playlist_tracks():
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    pid = request.args.get("playlist_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "missing_playlist_id"}), 400
    try:
        r = req.get(f"https://api.spotify.com/v1/playlists/{pid}/tracks?limit=100", headers=h, timeout=15)
        if not r.ok:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"}), 400
        data = r.json()
        items = data.get("items", [])
        tracks = [it.get("track") for it in items if it.get("track")]
        return jsonify({"ok": True, "tracks": tracks}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post("/spotify/playlist_create")
def spotify_playlist_create():
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    data = _json_body()
    name = data.get("name", "Greg Playlist")
    is_public = data.get("public", True)

    profile = session.get("spotify_profile", {})
    user_id = profile.get("id")
    if not user_id:
        return jsonify({"ok": False, "error": "no_user_id"}), 400

    try:
        r = req.post(
            f"https://api.spotify.com/v1/users/{user_id}/playlists",
            headers=h,
            json={"name": name, "public": is_public, "description": "Playlist créée par Greg le Consanguin"},
            timeout=15,
        )
        if not r.ok:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"}), 400
        return jsonify({"ok": True, **r.json()}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post("/spotify/playlist_delete")
def spotify_playlist_delete():
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    data = _json_body()
    pid = data.get("playlist_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "missing_playlist_id"}), 400
    try:
        r = req.delete(f"https://api.spotify.com/v1/playlists/{pid}/followers", headers=h, timeout=10)
        if not r.ok:
            return _sp_failed(r)
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post("/spotify/playlist_remove_tracks")
def spotify_remove_tracks():
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    data = _json_body()
    pid = data.get("playlist_id", "")
    uris = data.get("track_uris", [])
    if not pid or not uris:
        return jsonify({"ok": False, "error": "missing params"}), 400
    try:
        body = {"tracks": [{"uri": u} for u in uris]}
        r = req.delete(f"https://api.spotify.com/v1/playlists/{pid}/tracks", headers=h, json=body, timeout=10)
        if not r.ok:
            return _sp_failed(r)
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post("/spotify/quickplay")
def spotify_quickplay():
    """Ajoute un titre Spotify à la queue Discord via bot bridge."""
    data = _json_body()
    gid = data.get("guild_id")
    uid = data.get("user_id")
    track = data.get("track", {})
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400
    gid, uid = _to_int(gid), _to_int(uid)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "invalid guild_id/user_id"}), 400
    if not isinstance(track, dict):
        return jsonify({"ok": False, "error": "invalid track"}), 400

    name = str(track.get("name") or track.get("title") or "").strip()
    artists = track.get("artists")
    if isinstance(artists, list):
        names = [a.get("name") if isinstance(a, dict) else a for a in artists]
        artist = ", ".join(str(n).strip() for n in names if n)
    else:
        artist = str(artists or track.get("artist") or "").strip()

    # Texte libre « titre artiste » : le bot le résout lui-même (recherche YouTube)
    search_query = f"{name} {artist}".strip()
    if not search_query:
        return jsonify({"ok": False, "error": "empty_track"}), 400

    duration_ms = _to_int(track.get("duration_ms"))
    thumb = track.get("image")
    if not thumb:
        album = track.get("album")
        images = album.get("images") if isinstance(album, dict) else None
        if isinstance(images, list) and images and isinstance(images[0], dict):
            thumb = images[0].get("url")

    # Même forme d'item que /player/enqueue (le provider est déterminé par le bot)
    item = {
        "url": search_query,
        "title": name or search_query,
        "artist": artist or None,
        "duration": duration_ms // 1000 if duration_ms and duration_ms > 0 else None,
        "thumb": thumb or None,
        "provider": None,
    }
    return play_for_user_response(gid, uid, item)


@bp.post("/spotify/add_current_to_playlist")
def spotify_add_current():
    """Ajoute le titre en cours de lecture à une playlist Spotify."""
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    data = _json_body()
    pid = data.get("playlist_id", "")
    gid = data.get("guild_id", "")
    if not pid or not gid:
        return jsonify({"ok": False, "error": "missing params"}), 400
    gid = _to_int(gid)
    if not gid:
        return jsonify({"ok": False, "error": "invalid guild_id"}), 400

    # Get current track from bot (un timeout n'est PAS « rien en lecture »)
    state, err = _bot_state(gid, timeout=5)
    if err:
        return err
    current = state.get("current") or state.get("now_playing")
    if not isinstance(current, dict) or not current:
        return jsonify({"ok": False, "error": "nothing_playing"}), 400

    title = current.get("title") or ""
    artist = current.get("artist") or ""
    search_q = f"{title} {artist}".strip()

    # Search Spotify for this track
    try:
        r = _sp_search_track(h, search_q, timeout=10)
        if not r.ok:
            return jsonify({"ok": False, "error": "spotify_search_failed"}), 400

        tracks = r.json().get("tracks", {}).get("items", [])
        if not tracks:
            return jsonify({"ok": False, "error": "track_not_found_on_spotify"}), 404

        uri = tracks[0].get("uri")
        if not uri:
            return jsonify({"ok": False, "error": "no_uri"}), 400

        # Add to playlist
        add_r = req.post(
            f"https://api.spotify.com/v1/playlists/{pid}/tracks",
            headers=h, json={"uris": [uri]}, timeout=10,
        )
        if not add_r.ok:
            return _sp_failed(add_r)
        return jsonify({"ok": True, "added_uri": uri}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post("/spotify/add_queue_to_playlist")
def spotify_add_queue():
    """Ajoute les titres de la queue Discord à une playlist Spotify."""
    h = _sp_headers()
    if not h:
        return jsonify({"ok": False, "error": "not_linked"}), 401
    data = _json_body()
    pid = data.get("playlist_id", "")
    gid = data.get("guild_id", "")
    max_items = data.get("max_items", 20)
    if not pid or not gid:
        return jsonify({"ok": False, "error": "missing params"}), 400
    gid = _to_int(gid)
    if not gid:
        return jsonify({"ok": False, "error": "invalid guild_id"}), 400
    max_items = _to_int(max_items)
    if max_items is None:
        return jsonify({"ok": False, "error": "invalid max_items"}), 400
    max_items = max(1, min(max_items, 100))

    # Get queue from bot (un timeout n'est PAS « file vide »)
    state, err = _bot_state(gid, timeout=8)
    if err:
        return err
    queue = state.get("queue") or []
    queue = queue[:max_items] if isinstance(queue, list) else []

    if not queue:
        return jsonify({"ok": False, "error": "queue_empty"}), 400

    added = []
    for item in queue:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        artist = item.get("artist") or ""
        search_q = f"{title} {artist}".strip()
        if not search_q:
            continue
        try:
            r = _sp_search_track(h, search_q, timeout=8)
            if r.ok:
                tracks = r.json().get("tracks", {}).get("items", [])
                if tracks and tracks[0].get("uri"):
                    added.append(tracks[0]["uri"])
        except Exception:
            continue

    if not added:
        return jsonify({"ok": False, "error": "no_tracks_matched"}), 400

    # Add all URIs at once
    try:
        add_r = req.post(
            f"https://api.spotify.com/v1/playlists/{pid}/tracks",
            headers=h, json={"uris": added[:100]}, timeout=15,
        )
        if not add_r.ok:
            return _sp_failed(add_r)
        return jsonify({"ok": True, "added_count": len(added)}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
