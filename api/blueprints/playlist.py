from __future__ import annotations

import asyncio
from typing import Any, Optional

from flask import Blueprint, jsonify, request, current_app
from api.ws.events import broadcast_playlist_update

bp = Blueprint("playlist", __name__)


def PLAYER():
    return current_app.extensions.get("player")


# -----------------------------
# Robust parsing helpers
# -----------------------------
def _as_str(v: Any) -> str:
    """Return a safe string (never None), for strip()/comparisons."""
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _json_dict(req) -> dict:
    data = req.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _gid_from(req, data: Optional[dict] = None) -> Optional[str]:
    """
    Accept guild_id from:
      - query string ?guild_id=...
      - header X-Guild-ID
      - JSON body {guild_id: ...} (int OR str)
    Returns a string guild_id or None.
    """
    if data is None:
        data = _json_dict(req)

    gid = (
        _as_str(req.args.get("guild_id")).strip()
        or _as_str(req.headers.get("X-Guild-ID")).strip()
        or _as_str(data.get("guild_id")).strip()
    )
    return gid or None


def _uid_from(req, data: Optional[dict] = None) -> Optional[str]:
    """
    Accept user_id from:
      - JSON body {user_id: ...} (int OR str)
      - header X-User-ID
    Returns a string user_id or None.
    """
    if data is None:
        data = _json_dict(req)

    uid = (
        _as_str(data.get("user_id")).strip()
        or _as_str(req.headers.get("X-User-ID")).strip()
    )
    return uid or None


def _broadcast(gid: str):
    player = PLAYER()
    if not player or not gid:
        return
    try:
        state = player.get_state(int(gid))
        broadcast_playlist_update({"state": state}, guild_id=str(gid))
    except Exception:
        pass


def _is_url(s: str) -> bool:
    return isinstance(s, str) and s.startswith(("http://", "https://"))


# -----------------------------
# Routes
# -----------------------------
@bp.get("/playlist")
def get_playlist_state():
    gid = _gid_from(request)
    player = PLAYER()
    if not gid or not player:
        return jsonify({"ok": False, "error": "missing guild_id/player"}), 400

    state = player.get_state(int(gid))
    return jsonify({"ok": True, "state": state}), 200


@bp.post("/queue/add")
def add_to_queue():
    data = _json_dict(request)

    gid = _gid_from(request, data)
    uid = _uid_from(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    # compatible inputs: query OR url/webpage_url OR title
    raw = data.get("query") or data.get("url") or data.get("webpage_url") or data.get("title")
    raw = _as_str(raw).strip()
    if not raw:
        return jsonify({"ok": False, "error": "missing query"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    before = player.get_state(int(gid)) or {}
    was_empty = len(before.get("queue") or []) == 0 and not bool(before.get("current"))

    # If client provided url + metadata, keep it.
    url_in = _as_str(data.get("url") or data.get("webpage_url")).strip()
    title_in = _as_str(data.get("title")).strip()
    artist_in = _as_str(data.get("artist")).strip()
    provider_in = _as_str(data.get("provider") or data.get("source")).strip()
    thumb_in = data.get("thumb") or data.get("thumbnail")

    duration_in = data.get("duration")
    # avoid sending None duration to internals
    if duration_in is None:
        pass

    item = None

    if url_in and _is_url(url_in):
        item = {
            "url": url_in,
            "title": title_in or raw,
            "artist": artist_in or None,
            "duration": duration_in,
            "thumb": thumb_in,
            "provider": provider_in or None,
        }
    else:
        # raw is either a URL or search query
        if _is_url(raw):
            item = {"url": raw, "title": title_in or raw, "thumb": thumb_in, "provider": provider_in or None}
        else:
            try:
                from api.services.search import autocomplete
                res = autocomplete(raw, limit=1)
                if res:
                    top = res[0] or {}
                    item = {
                        "url": top.get("url") or raw,
                        "title": top.get("title") or raw,
                        "duration": top.get("duration"),
                        "thumb": top.get("thumbnail") or top.get("thumb"),
                        "provider": top.get("provider") or top.get("source"),
                    }
                else:
                    item = {"url": raw, "title": raw, "provider": provider_in or None}
            except Exception:
                item = {"url": raw, "title": raw, "provider": provider_in or None}

    async def _do():
        return await player.enqueue(int(gid), int(uid), item or {"url": raw, "title": raw})

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12) or {}
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    autoplay = {"attempted": False, "ok": False, "reason": None}

    # Autoplay if queue was empty: join requester's voice + play next
    if was_empty:
        async def _auto_play():
            g = player.bot.get_guild(int(gid))
            if not g:
                return {"ok": False, "reason": "GUILD_NOT_FOUND"}

            m = g.get_member(int(uid))
            ch = m.voice.channel if (m and m.voice) else None
            if not ch:
                return {"ok": False, "reason": "USER_NOT_IN_VOICE"}

            ok = await player.ensure_connected(g, ch)
            if not ok:
                return {"ok": False, "reason": "VOICE_CONNECT_FAILED"}

            await player.play_next(g)
            return {"ok": True, "reason": None}

        fut2 = asyncio.run_coroutine_threadsafe(_auto_play(), player.bot.loop)
        autoplay["attempted"] = True
        try:
            autoplay.update(fut2.result(timeout=12) or {})
        except Exception as e:
            autoplay.update({"ok": False, "reason": f"AUTOPLAY_ERROR:{e}"})

    _broadcast(gid)
    http_code = 200 if res.get("ok") else 409
    return jsonify({"ok": bool(res.get("ok")), "result": res, "autoplay": autoplay}), http_code


@bp.post("/queue/skip")
def skip_track():
    data = _json_dict(request)
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    async def _do():
        return await player.skip(int(gid), requester_id=int(uid))

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        fut.result(timeout=8)
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": True}), 200


@bp.post("/queue/stop")
def stop_playback():
    data = _json_dict(request)
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    async def _do():
        return await player.stop(int(gid), requester_id=int(uid))

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        fut.result(timeout=8)
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": True}), 200


@bp.post("/queue/remove")
def remove_at():
    data = _json_dict(request)
    idx = data.get("index")
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    if idx is None:
        return jsonify({"ok": False, "error": "missing index"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    try:
        ok = player.remove_at(int(gid), int(uid), int(idx))
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool(ok)}), 200 if ok else 409


@bp.post("/queue/move")
def move_item():
    data = _json_dict(request)
    src = data.get("src")
    dst = data.get("dst")
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    if src is None or dst is None:
        return jsonify({"ok": False, "error": "missing src/dst"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    try:
        ok = player.move(int(gid), int(uid), int(src), int(dst))
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool(ok)}), 200 if ok else 409


# ⚠️ Endpoint "mutateur brut" conservé pour compat.
# Ne déclenche pas play_next, ne rejoint pas le vocal.
@bp.post("/queue/next")
def pop_next():
    gid = _gid_from(request)
    player = PLAYER()
    if not gid or not player:
        return jsonify({"ok": False, "error": "missing guild_id/player"}), 400
    try:
        pm = player._get_pm(int(gid))
        pm.reload()
        res = pm.pop_next()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": True, "result": res}), 200


@bp.post("/playlist/play")
def playlist_play():
    data = _json_dict(request)
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    item = {
        "url": data.get("url") or data.get("webpage_url"),
        "title": data.get("title") or data.get("query") or data.get("url") or data.get("webpage_url"),
        "artist": data.get("artist"),
        "duration": data.get("duration"),
        "thumb": data.get("thumb") or data.get("thumbnail"),
        "provider": data.get("provider") or data.get("source"),
    }
    if not (item["url"] or data.get("query") or data.get("title")):
        return jsonify({"ok": False, "error": "missing url/query"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    async def _do():
        return await player.play_for_user(int(gid), int(uid), item)

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12)
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool(res.get("ok")), "result": res}), 200 if res.get("ok") else 409


@bp.post("/playlist/play_at")
def playlist_play_at():
    data = _json_dict(request)
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)
    idx = data.get("index")
    if idx is None:
        return jsonify({"ok": False, "error": "missing index"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    try:
        ok_move = player.move(int(gid), int(uid), int(idx), 0)
        if not ok_move:
            return jsonify({"ok": False, "error": "move failed"}), 409
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": f"move failed: {e}"}), 500

    async def _do():
        g = player.bot.get_guild(int(gid))
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            await player.skip(int(gid), requester_id=int(uid))
            return True
        m = g.get_member(int(uid)) if g else None
        ch = m.voice.channel if (m and m.voice) else None
        if ch and await player.ensure_connected(g, ch):
            await player.play_next(g)
            return True
        return False

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        ok = bool(fut.result(timeout=12))
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": ok}), 200 if ok else 409


@bp.post("/playlist/toggle_pause")
def playlist_toggle_pause():
    data = _json_dict(request)
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    async def _do():
        g = player.bot.get_guild(int(gid))
        vc = g and g.voice_client
        if not vc:
            return {"ok": False, "error": "NO_VOICE"}
        if vc.is_paused():
            ok = await player.resume(int(gid), requester_id=int(uid))
            return {"ok": ok, "action": "resume" if ok else "noop"}
        if vc.is_playing():
            ok = await player.pause(int(gid), requester_id=int(uid))
            return {"ok": ok, "action": "pause" if ok else "noop"}
        return {"ok": False, "error": "NOT_PLAYING"}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=8)
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200 if res.get("ok") else 409


@bp.post("/playlist/repeat")
def playlist_repeat():
    data = _json_dict(request)
    gid = _gid_from(request, data)
    mode = _as_str(data.get("mode")).strip().lower() or "toggle"

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400

    async def _do():
        val = await player.toggle_repeat(int(gid), mode)
        return {"ok": True, "repeat_all": bool(val)}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=8)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200


@bp.post("/playlist/restart")
def playlist_restart():
    data = _json_dict(request)
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

        cur = (player.now_playing.get(int(gid)) or player.current_song.get(int(gid)))
        if not cur:
            return {"ok": False, "error": "NO_CURRENT"}

        res = await player.enqueue(int(gid), int(uid), {
            "url": cur.get("url"),
            "title": cur.get("title"),
            "artist": cur.get("artist"),
            "thumb": cur.get("thumb") or cur.get("thumbnail"),
            "duration": cur.get("duration"),
            "provider": cur.get("provider") or "youtube",
        })
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "ENQUEUE_FAILED"}

        pm = player._get_pm(int(gid))
        pm.reload()
        q = pm.peek_all()
        last = max(0, len(q) - 1)
        player.move(int(gid), int(uid), last, 0)

        await player.skip(int(gid), requester_id=int(uid))
        return {"ok": True}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12)
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200 if res.get("ok") else 409
