# api/blueprints/voice.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from flask import Blueprint, jsonify, request, current_app

bp = Blueprint("voice", __name__)
log = logging.getLogger(__name__)


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


@bp.get("/voice/debug")
def voice_debug():
    """
    Diagnostic endpoint: tells if the Discord bot is alive/ready and sees the guild.
    """
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    gid = _gid_from(request)
    bot = getattr(player, "bot", None)

    info = {
        "ok": True,
        "has_player": True,
        "has_bot": bool(bot),
        "bot_ready": bool(getattr(bot, "is_ready", lambda: False)()),
        "bot_user": str(getattr(getattr(bot, "user", None), "id", "")) if bot else "",
        "guild_count": len(getattr(bot, "guilds", []) or []) if bot else 0,
        "guild_ids_sample": [str(g.id) for g in (getattr(bot, "guilds", []) or [])[:10]] if bot else [],
        "requested_guild_id": gid or "",
        "guild_found_in_cache": False,
    }

    if bot and gid:
        g = bot.get_guild(int(gid))
        info["guild_found_in_cache"] = bool(g)
        info["guild_name"] = getattr(g, "name", None) if g else None

    return jsonify(info), 200


@bp.post("/voice/join")
def voice_join():
    """
    Best-effort: try to connect bot to the caller's voice channel.
    Needs: bot alive + guild accessible + voice state cache.
    """
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)
    reason = _to_str(data.get("reason") or request.args.get("reason") or "").strip()

    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    bot = getattr(player, "bot", None)
    if not bot:
        return jsonify({"ok": False, "error": "BOT_MISSING"}), 503

    bot_ready = bool(getattr(bot, "is_ready", lambda: False)())
    g = bot.get_guild(int(gid))

    log.warning(
        "[voice/join] reason=%s gid=%s uid=%s bot_ready=%s bot_user=%s guild_found=%s guild_count=%s",
        reason, gid, uid, bot_ready,
        getattr(getattr(bot, "user", None), "id", None),
        bool(g),
        len(getattr(bot, "guilds", []) or []),
    )

    if not bot_ready:
        return jsonify({"ok": False, "error": "BOT_NOT_READY"}), 409

    if not g:
        # This is exactly your current failure
        return jsonify({"ok": False, "error": "GUILD_NOT_FOUND"}), 409

    async def _do():
        # Find member + voice channel (cache-based)
        m = g.get_member(int(uid))
        ch = m.voice.channel if (m and m.voice) else None
        if not ch:
            return {"ok": False, "error": "USER_NOT_IN_VOICE_OR_NOT_CACHED"}

        ok = await player.ensure_connected(g, ch)
        if not ok:
            return {"ok": False, "error": "VOICE_CONNECT_FAILED"}

        # If nothing is playing, try to start
        try:
            vc = g.voice_client
            if vc and not (vc.is_playing() or vc.is_paused()):
                await player.play_next(g)
        except Exception as e:
            return {"ok": False, "error": f"PLAY_NEXT_FAILED:{e}"}

        return {"ok": True, "channel_id": getattr(ch, "id", None), "channel_name": getattr(ch, "name", None)}

    fut = asyncio.run_coroutine_threadsafe(_do(), bot.loop)
    try:
        res = fut.result(timeout=12) or {}
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(res), 200 if res.get("ok") else 409
