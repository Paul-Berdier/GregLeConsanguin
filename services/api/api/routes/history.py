"""History routes — historique et top des morceaux joués."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from api.routes.player import error_status
from api.services.authz import require_session_user, session_user_id
from api.services.bot_bridge import send_command

bp = Blueprint("history", __name__)


def _gid_arg():
    """guild_id (query ou header X-Guild-ID) → (gid, None) ou (None, réponse 400)."""
    gid = request.args.get("guild_id") or request.headers.get("X-Guild-ID") or ""
    if not gid:
        return None, (jsonify({"ok": False, "error": "missing guild_id"}), 400)
    try:
        return int(gid), None
    except (TypeError, ValueError):
        return None, (jsonify({"ok": False, "error": "invalid guild_id"}), 400)


@bp.get("/history")
@bp.get("/history/top")
@require_session_user
def history_top():
    gid, err = _gid_arg()
    if err:
        return err
    mode = request.args.get("mode", "top")
    limit = request.args.get("limit", 20, type=int)
    res = send_command("get_history", gid, session_user_id() or 0,
                       data={"mode": mode, "limit": limit}, timeout=5)
    return jsonify(res), 200 if res.get("ok") else error_status(res)


@bp.get("/history/recent")
@require_session_user
def history_recent():
    gid, err = _gid_arg()
    if err:
        return err
    limit = request.args.get("limit", 20, type=int)
    res = send_command("get_history", gid, session_user_id() or 0,
                       data={"mode": "recent", "limit": limit}, timeout=5)
    return jsonify(res), 200 if res.get("ok") else error_status(res)
