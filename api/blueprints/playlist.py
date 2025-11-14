from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app
from api.ws.events import broadcast_playlist_update

bp = Blueprint("playlist", __name__)

def PM():
    # APIPMAdapter déjà initialisé dans app.extensions["pm"]
    return current_app.extensions["pm"]

def _gid_from(req):
    return (
        (req.args.get("guild_id") or "").strip()
        or (req.headers.get("X-Guild-ID") or "").strip()
        or ((req.json or {}).get("guild_id") or "").strip()
    ) or None

@bp.get("/playlist")
def get_playlist_state():
    gid = _gid_from(request)
    state = PM().get_state(guild_id=gid)
    return jsonify({"ok": True, "state": state}), 200

@bp.post("/queue/add")
def add_to_queue():
    data = request.get_json(silent=True) or {}
    # On accepte query / url / title pour rester souple côté overlay
    query = data.get("query") or data.get("url") or data.get("title")
    if not query:
        return jsonify({"ok": False, "error": "missing query"}), 400

    gid = _gid_from(request)
    uid = data.get("user_id") or request.headers.get("X-User-ID")

    res = PM().enqueue(query, user_id=uid, guild_id=gid)

    # Diffuse l'état à la room de la guilde (payload: {"state": ...})
    state = PM().get_state(guild_id=gid)
    broadcast_playlist_update({"state": state}, guild_id=gid)

    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/skip")
def skip_track():
    gid = _gid_from(request)
    res = PM().skip(guild_id=gid)

    state = PM().get_state(guild_id=gid)
    broadcast_playlist_update({"state": state}, guild_id=gid)

    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/stop")
def stop_playback():
    gid = _gid_from(request)
    res = PM().stop(guild_id=gid)

    state = PM().get_state(guild_id=gid)
    broadcast_playlist_update({"state": state}, guild_id=gid)

    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/remove")
def remove_at():
    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    if idx is None:
        return jsonify({"ok": False, "error": "missing index"}), 400
    gid = _gid_from(request)
    res = PM().remove_at(int(idx), guild_id=gid)

    state = PM().get_state(guild_id=gid)
    broadcast_playlist_update({"state": state}, guild_id=gid)

    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/move")
def move_item():
    data = request.get_json(silent=True) or {}
    src = data.get("src")
    dst = data.get("dst")
    if src is None or dst is None:
        return jsonify({"ok": False, "error": "missing src/dst"}), 400
    gid = _gid_from(request)
    res = PM().move(int(src), int(dst), guild_id=gid)

    state = PM().get_state(guild_id=gid)
    broadcast_playlist_update({"state": state}, guild_id=gid)

    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/next")
def pop_next():
    gid = _gid_from(request)
    res = PM().pop_next(guild_id=gid)

    state = PM().get_state(guild_id=gid)
    broadcast_playlist_update({"state": state}, guild_id=gid)

    return jsonify({"ok": True, "result": res}), 200
