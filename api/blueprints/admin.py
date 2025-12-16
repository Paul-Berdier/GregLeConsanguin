# backend/api/blueprints/admin.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth.session import require_login
from ..ws.events import broadcast_playlist_update, socketio_presence_stats

bp = Blueprint("admin", __name__)


@bp.get("/overlays_online")
@require_login
def overlays_online():
    return jsonify({"ok": True, "stats": socketio_presence_stats()})


@bp.post("/jumpscare")
@require_login
def jumpscare():
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "Missing 'guild_id'"}), 400

    # On réutilise la même logique d'émission ciblée
    broadcast_playlist_update(guild_id, {"type": "jumpscare"})
    return jsonify({"ok": True})
