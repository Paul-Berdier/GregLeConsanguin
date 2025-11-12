# backend/api/blueprints/spotify.py
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, request, session

from ..core.security import make_state, verify_state
from ..services import spotify as SP

bp = Blueprint("spotify", __name__)


@bp.get("/spotify/status")
def sp_status():
    return jsonify({"ok": True, "status": SP.status()})


@bp.get("/spotify/login")
def sp_login():
    state = make_state(session.get("_id", "spotify"), "spotify", ttl_seconds=600)
    session["spotify_state"] = state
    return redirect(SP.login_url(state))


@bp.get("/spotify/callback")
def sp_callback():
    state = request.args.get("state") or ""
    if not verify_state(session.get("_id", "spotify"), state):
        return jsonify({"ok": False, "error": "invalid_state"}), 400
    code = request.args.get("code")
    if not code:
        return jsonify({"ok": False, "error": "missing_code"}), 400
    token = SP.exchange_code(code)
    return jsonify({"ok": True, "token": {"scope": token.get("scope"), "expires_in": token.get("expires_in")}})


@bp.post("/spotify/logout")
def sp_logout():
    return jsonify({"ok": True, "status": SP.logout()})


@bp.post("/spotify/quickplay")
def sp_quickplay():
    data = request.get_json(silent=True) or {}
    q = data.get("q")
    if not q:
        return jsonify({"ok": False, "error": "Missing 'q'"}), 400
    return jsonify({"ok": True, "result": SP.quickplay(q)})


@bp.get("/spotify/playlists")
def sp_playlists():
    return jsonify({"ok": True, "data": SP.get_playlists()})


@bp.get("/spotify/playlist_tracks")
def sp_playlist_tracks():
    playlist_id = request.args.get("id")
    if not playlist_id:
        return jsonify({"ok": False, "error": "Missing 'id'"}), 400
    return jsonify({"ok": True, "data": SP.get_playlist_tracks(playlist_id)})
