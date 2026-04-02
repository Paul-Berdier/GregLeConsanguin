"""Player routes — contrôle du lecteur de musique via Redis bridge."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from api.services.bot_bridge import send_command

bp = Blueprint("player", __name__)


def _gid(req, data=None) -> int:
    if data is None:
        data = req.get_json(silent=True) or {}
    v = req.args.get("guild_id") or req.headers.get("X-Guild-ID") or data.get("guild_id")
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _uid(req, data=None) -> int:
    if data is None:
        data = req.get_json(silent=True) or {}
    v = data.get("user_id") or req.headers.get("X-User-ID")
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


@bp.get("/player/state")
def get_state():
    gid = _gid(request)
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400

    res = send_command("get_state", gid, timeout=8)

    if res.get("ok"):
        return jsonify(res), 200

    return jsonify({
        "ok": True,
        "current": None,
        "queue": [],
        "is_paused": True,
        "repeat_all": False,
        "progress": {"elapsed": 0, "duration": 0},
        "backend_error": res.get("error", "unknown"),
    }), 200


@bp.post("/player/enqueue")
def enqueue():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    query = (data.get("query") or data.get("url") or data.get("title") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "missing query"}), 400

    item = {
        "url": data.get("url") or query,
        "title": data.get("title") or query,
        "artist": data.get("artist"),
        "duration": data.get("duration"),
        "thumb": data.get("thumb") or data.get("thumbnail"),
        "provider": data.get("provider"),
    }

    res = send_command("play_for_user", gid, uid, data={"item": item}, timeout=20)
    code = 200 if res.get("ok") else (403 if res.get("error") == "PRIORITY_FORBIDDEN" else 409)
    return jsonify(res), code


@bp.post("/player/skip")
def skip():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400
    res = send_command("skip", gid, uid, timeout=8)
    code = 200 if res.get("ok") else (403 if "PRIORITY" in str(res.get("error", "")) else 500)
    return jsonify(res), code


@bp.post("/player/stop")
def stop():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400
    res = send_command("stop", gid, uid, timeout=8)
    code = 200 if res.get("ok") else (403 if "PRIORITY" in str(res.get("error", "")) else 500)
    return jsonify(res), code


@bp.post("/player/pause")
def toggle_pause():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400
    res = send_command("toggle_pause", gid, uid, timeout=8)
    code = 200 if res.get("ok") else (403 if "PRIORITY" in str(res.get("error", "")) else 409)
    return jsonify(res), code


@bp.post("/player/repeat")
def repeat():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    mode = str(data.get("mode", "toggle")).strip().lower()
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("repeat", gid, data={"mode": mode}, timeout=8)
    return jsonify(res), 200 if res.get("ok") else 409


@bp.post("/player/move")
def move():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    src = data.get("src")
    dst = data.get("dst")
    if not gid or not uid or src is None or dst is None:
        return jsonify({"ok": False, "error": "missing params"}), 400
    res = send_command("move", gid, uid, data={"src": int(src), "dst": int(dst)}, timeout=8)
    code = 200 if res.get("ok") else (403 if "PRIORITY" in str(res.get("error", "")) else 409)
    return jsonify(res), code


@bp.delete("/player/queue/<int:index>")
def remove_at(index: int):
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400
    res = send_command("remove", gid, uid, data={"index": index}, timeout=8)
    code = 200 if res.get("ok") else (403 if "PRIORITY" in str(res.get("error", "")) else 409)
    return jsonify(res), code


# ── Compat routes (ancien front) ──

@bp.post("/queue/add")
def queue_add_compat():
    return enqueue()


@bp.post("/queue/skip")
def queue_skip_compat():
    return skip()


@bp.post("/queue/stop")
def queue_stop_compat():
    return stop()


@bp.post("/queue/remove")
def queue_remove_compat():
    data = request.get_json(silent=True) or {}
    idx = data.get("index", 0)
    data["guild_id"] = data.get("guild_id") or request.args.get("guild_id")
    return remove_at(int(idx))


@bp.get("/playlist")
def playlist_state_compat():
    return get_state()


@bp.post("/playlist/toggle_pause")
def playlist_pause_compat():
    return toggle_pause()


@bp.post("/playlist/repeat")
def playlist_repeat_compat():
    return repeat()


@bp.post("/voice/join")
def voice_join():
    data = request.get_json(silent=True) or {}
    gid = _gid(request, data)
    uid = _uid(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400
    res = send_command("join", gid, uid, timeout=12)
    return jsonify(res), 200 if res.get("ok") else 409
