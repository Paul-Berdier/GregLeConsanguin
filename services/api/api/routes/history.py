"""History routes — historique et top des morceaux joués."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from api.services.bot_bridge import send_command

bp = Blueprint("history", __name__)


@bp.get("/history")
@bp.get("/history/top")
def history_top():
    gid = request.args.get("guild_id") or request.headers.get("X-Guild-ID") or ""
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    mode = request.args.get("mode", "top")
    limit = request.args.get("limit", 20, type=int)
    res = send_command("get_history", int(gid), data={"mode": mode, "limit": limit}, timeout=5)
    return jsonify(res), 200 if res.get("ok") else 409


@bp.get("/history/recent")
def history_recent():
    gid = request.args.get("guild_id") or request.headers.get("X-Guild-ID") or ""
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    limit = request.args.get("limit", 20, type=int)
    res = send_command("get_history", int(gid), data={"mode": "recent", "limit": limit}, timeout=5)
    return jsonify(res), 200 if res.get("ok") else 409
