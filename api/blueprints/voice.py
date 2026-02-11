# api/blueprints/voice.py
from __future__ import annotations

import asyncio
from typing import Any, Optional

from flask import Blueprint, jsonify, request, current_app

bp = Blueprint("voice", __name__)


def PLAYER():
    # PlayerService stocké dans app.extensions["player"]
    return current_app.extensions.get("player")


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _gid_from(req, data: Optional[dict] = None) -> Optional[str]:
    if data is None:
        data = req.get_json(silent=True) or {}
    v = req.args.get("guild_id")
    if v is None:
        v = req.headers.get("X-Guild-ID")
    if v is None:
        v = (data or {}).get("guild_id")
    gid = _to_str(v).strip()
    return gid or None


def _uid_from(req, data: Optional[dict] = None) -> Optional[str]:
    if data is None:
        data = req.get_json(silent=True) or {}
    v = (data or {}).get("user_id")
    if v is None:
        v = req.headers.get("X-User-ID")
    uid = _to_str(v).strip()
    return uid or None


@bp.post("/voice/join")
def voice_join():
    """
    POST /api/v1/voice/join
    body (JSON) ou headers:
      - guild_id
      - user_id
    Effet: fait rejoindre Greg le vocal DU user_id (si le user est en vocal).
    """
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    async def _do():
        g = player.bot.get_guild(int(gid))
        if not g:
            return {"ok": False, "error": "GUILD_NOT_FOUND"}

        m = g.get_member(int(uid))
        if not m or not m.voice or not m.voice.channel:
            return {"ok": False, "error": "USER_NOT_IN_VOICE"}

        ok = await player.ensure_connected(g, m.voice.channel)
        if not ok:
            return {"ok": False, "error": "VOICE_CONNECT_FAILED"}

        return {
            "ok": True,
            "guild_id": int(gid),
            "channel_id": int(m.voice.channel.id),
            "channel_name": getattr(m.voice.channel, "name", None),
        }

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(res), 200 if res.get("ok") else 409


@bp.post("/voice/leave")
def voice_leave():
    """
    POST /api/v1/voice/leave
    body (JSON) ou headers:
      - guild_id
    Effet: fait quitter Greg du vocal.
    """
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400

    async def _do():
        g = player.bot.get_guild(int(gid))
        if not g:
            return {"ok": False, "error": "GUILD_NOT_FOUND"}

        vc = g.voice_client
        if not vc:
            return {"ok": False, "error": "NOT_CONNECTED"}

        try:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
        except Exception:
            pass

        try:
            await vc.disconnect(force=True)
        except Exception:
            try:
                await vc.disconnect()
            except Exception as e:
                return {"ok": False, "error": f"DISCONNECT_FAILED:{e}"}

        return {"ok": True, "guild_id": int(gid)}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(res), 200 if res.get("ok") else 409


@bp.get("/voice/state")
def voice_state():
    """
    GET /api/v1/voice/state?guild_id=...
    Retourne l'état vocal actuel (connecté, channel, playing/paused)
    """
    gid = _gid_from(request)
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400

    g = player.bot.get_guild(int(gid))
    if not g:
        return jsonify({"ok": False, "error": "GUILD_NOT_FOUND"}), 404

    vc = g.voice_client
    if not vc or not getattr(vc, "channel", None):
        return jsonify({"ok": True, "connected": False}), 200

    return jsonify({
        "ok": True,
        "connected": True,
        "guild_id": int(gid),
        "channel_id": int(vc.channel.id),
        "channel_name": getattr(vc.channel, "name", None),
        "is_playing": bool(vc.is_playing()),
        "is_paused": bool(vc.is_paused()),
    }), 200
