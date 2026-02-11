# api/blueprints/voice.py
from __future__ import annotations

import asyncio
from typing import Any, Optional

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("voice", __name__)


def PLAYER():
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
    Best-effort voice join.
    IMPORTANT: pour le web player, on évite volontairement les 4xx/5xx bruyants.
    - 200 JSON si on a effectivement (re)joint un salon.
    - 204 No Content si:
        * déjà connecté au bon salon
        * user pas en vocal
        * guild introuvable / player indispo
        * échec de join (best effort)
    """
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player or not gid or not uid:
        return ("", 204)

    async def _do():
        g = player.bot.get_guild(int(gid))
        if not g:
            return {"action": "noop", "reason": "GUILD_NOT_FOUND"}

        m = g.get_member(int(uid))
        ch = m.voice.channel if (m and m.voice) else None
        if not ch:
            return {"action": "noop", "reason": "USER_NOT_IN_VOICE"}

        vc = g.voice_client
        if vc and getattr(vc, "channel", None) == ch and getattr(vc, "is_connected", lambda: True)():
            return {"action": "noop", "reason": "ALREADY_CONNECTED"}

        ok = await player.ensure_connected(g, ch)
        if ok:
            return {"action": "joined", "channel_id": getattr(ch, "id", None)}
        return {"action": "noop", "reason": "VOICE_CONNECT_FAILED"}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12) or {}
    except Exception:
        # best effort => silencieux
        return ("", 204)

    if res.get("action") == "joined":
        return jsonify({"ok": True, "joined": True, "channel_id": res.get("channel_id")}), 200

    # Tout le reste => no-op silencieux
    return ("", 204)
