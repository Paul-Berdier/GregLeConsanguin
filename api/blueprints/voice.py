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


def _safe_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _bot_guild_ids(bot) -> list[str]:
    try:
        gs = getattr(bot, "guilds", []) or []
        return [str(g.id) for g in gs]
    except Exception:
        return []


@bp.get("/voice/debug")
def voice_debug():
    """
    Diagnostic endpoint: tells if the Discord bot is alive/ready and sees the guild.
    """
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    bot = getattr(player, "bot", None)
    gid = _gid_from(request)
    gid_i = _safe_int(gid)

    info = {
        "ok": True,
        "has_player": True,
        "has_bot": bool(bot),
        "bot_ready": bool(getattr(bot, "is_ready", lambda: False)()) if bot else False,
        "bot_user": str(getattr(getattr(bot, "user", None), "id", "")) if bot else "",
        "guild_count": len(getattr(bot, "guilds", []) or []) if bot else 0,
        "bot_guild_ids": _bot_guild_ids(bot) if bot else [],
        "requested_guild_id": gid or "",
        "guild_found_in_cache": False,
        "guild_name": None,
    }

    if bot and gid_i:
        g = bot.get_guild(gid_i)
        info["guild_found_in_cache"] = bool(g)
        info["guild_name"] = getattr(g, "name", None) if g else None

    return jsonify(info), 200


@bp.post("/voice/join")
def voice_join():
    """
    Best-effort: try to connect bot to the caller's voice channel.
    Needs: bot alive + guild accessible + voice state cache.

    Common failure you're seeing:
    - GUILD_NOT_FOUND: user selected a guild the BOT is not in (your /guilds endpoint likely returns user guilds, not bot guilds).
    """
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)
    reason = _to_str(data.get("reason") or request.args.get("reason") or "").strip()

    gid_i = _safe_int(gid)
    uid_i = _safe_int(uid)

    if not gid_i or not uid_i:
        return jsonify(
            {
                "ok": False,
                "error": "missing_or_invalid_guild_id/user_id",
                "guild_id": gid or "",
                "user_id": uid or "",
            }
        ), 400

    bot = getattr(player, "bot", None)
    if not bot:
        return jsonify({"ok": False, "error": "BOT_MISSING"}), 503

    bot_ready = bool(getattr(bot, "is_ready", lambda: False)())
    bot_user = getattr(getattr(bot, "user", None), "id", None)
    bot_guild_ids = _bot_guild_ids(bot)
    guild_count = len(getattr(bot, "guilds", []) or [])

    # Try cache first
    g = bot.get_guild(gid_i)

    log.warning(
        "[voice/join] reason=%s gid=%s uid=%s bot_ready=%s bot_user=%s guild_found=%s guild_count=%s",
        reason,
        gid_i,
        uid_i,
        bot_ready,
        bot_user,
        bool(g),
        guild_count,
    )

    if not bot_ready:
        return jsonify(
            {
                "ok": False,
                "error": "BOT_NOT_READY",
                "bot_user": str(bot_user or ""),
                "guild_count": guild_count,
                "bot_guild_ids": bot_guild_ids[:25],
            }
        ), 409

    # If not in cache, try a REST fetch (best-effort).
    # If the bot is NOT in that guild, Discord will typically return Forbidden/NotFound.
    if not g:
        async def _try_fetch():
            try:
                return await bot.fetch_guild(gid_i)
            except Exception as e:
                return e

        fut = asyncio.run_coroutine_threadsafe(_try_fetch(), bot.loop)
        try:
            fetched = fut.result(timeout=8)
        except Exception as e:
            fetched = e

        # Still not usable => return rich debug to immediately see the mismatch
        return jsonify(
            {
                "ok": False,
                "error": "GUILD_NOT_FOUND",
                "requested_guild_id": str(gid_i),
                "bot_user": str(bot_user or ""),
                "guild_count": guild_count,
                "bot_guild_ids": bot_guild_ids[:25],
                "hint": "Le serveur choisi côté WebPlayer n'est probablement PAS un serveur où le bot est présent. Corrige /guilds pour ne proposer que les guilds du bot (intersection user∩bot).",
                "fetch_guild_result": str(fetched)[:200],
            }
        ), 409

    async def _do():
        # 1) Try member cache
        m = g.get_member(uid_i)

        # 2) Determine voice channel:
        ch = None

        # a) Standard path (requires member cached with voice state)
        if m and getattr(m, "voice", None) and getattr(m.voice, "channel", None):
            ch = m.voice.channel

        # b) Fallback: use guild voice states cache (often exists even if member isn't cached)
        if ch is None:
            vs_map = getattr(g, "_voice_states", None)
            if isinstance(vs_map, dict):
                vs = vs_map.get(uid_i)
                # voice state object usually has channel / channel_id
                channel_id = getattr(vs, "channel", None)
                if channel_id is None:
                    channel_id = getattr(vs, "channel_id", None)
                # In some versions, vs.channel is a channel object; in others it's id-like
                if channel_id:
                    if hasattr(channel_id, "id"):
                        ch = channel_id
                    else:
                        try:
                            ch = g.get_channel(int(channel_id)) or bot.get_channel(int(channel_id))
                        except Exception:
                            ch = None

        if not ch:
            return {
                "ok": False,
                "error": "USER_NOT_IN_VOICE_OR_NOT_CACHED",
                "details": {
                    "member_cached": bool(m),
                    "voice_state_cached": bool(getattr(g, "_voice_states", None)),
                },
            }

        # 3) Connect
        ok = await player.ensure_connected(g, ch)
        if not ok:
            return {"ok": False, "error": "VOICE_CONNECT_FAILED"}

        # 4) Autoplay if nothing playing
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
