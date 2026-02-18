# api/blueprints/playlist.py

from __future__ import annotations

import asyncio
from typing import Any, Optional

from flask import Blueprint, jsonify, request, current_app
from api.ws.events import broadcast_playlist_update

# ✅ NEW: bundle support (playlist/mix)
from extractors import is_bundle_url, expand_bundle

bp = Blueprint("playlist", __name__)


def PLAYER():
    return current_app.extensions.get("player")


def _to_str(v: Any) -> str:
    """
    Normalize any value (int/float/bool/None/str) into a safe string.
    """
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _gid_from(req, data: Optional[dict] = None) -> Optional[str]:
    """
    Accept guild_id from:
      - query string (?guild_id=...)
      - header X-Guild-ID
      - JSON body {"guild_id": ...}  (int or str)
    """
    if data is None:
        data = req.get_json(silent=True) or {}

    v = req.args.get("guild_id")
    if v is None:
        v = req.headers.get("X-Guild-ID")
    if v is None:
        v = (data or {}).get("guild_id")

    gid = _to_str(v).strip()
    return gid or None


def _uid_from(req, data: dict) -> Optional[str]:
    """
    Accept user_id from:
      - JSON body {"user_id": ...}  (int or str)
      - header X-User-ID
    """
    v = (data or {}).get("user_id")
    if v is None:
        v = req.headers.get("X-User-ID")

    uid = _to_str(v).strip()
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
    data = request.get_json(silent=True) or {}

    raw = data.get("query") or data.get("url") or data.get("title")
    raw = _to_str(raw).strip()
    if not raw:
        return jsonify({"ok": False, "error": "missing query"}), 400

    gid = _gid_from(request, data)
    uid = _uid_from(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    before = player.get_state(int(gid)) or {}
    cur = before.get("current")
    was_empty = (len(before.get("queue") or []) == 0) and (not cur or not cur.get("url"))

    # ---------------------------
    # ✅ Helpers: int conversion
    # ---------------------------
    def _to_int(v):
        try:
            if v is None:
                return None
            if isinstance(v, bool):
                return None
            if isinstance(v, (int, float)):
                return int(v)
            s = str(v).strip()
            if not s:
                return None
            if s.isdigit():
                return int(s)
        except Exception:
            return None
        return None

    # ---------------------------
    # ✅ Metadata from front
    # ---------------------------
    url_in = _to_str(data.get("url") or data.get("webpage_url") or "").strip()
    title_in = _to_str(data.get("title") or "").strip()
    artist_in = _to_str(data.get("artist") or "").strip()
    provider_in = _to_str(data.get("provider") or data.get("source") or "").strip() or None
    thumb_in = _to_str(data.get("thumb") or data.get("thumbnail") or "").strip() or None

    duration_in = data.get("duration")
    duration_ms_in = data.get("duration_ms")

    dur = _to_int(duration_in)
    if dur is None:
        dur_ms = _to_int(duration_ms_in)
        if dur_ms is not None:
            dur = int(dur_ms / 1000)

    # ---------------------------
    # ✅ Build item(s)
    # - URL normal: 1 item
    # - URL playlist/mix: expand_bundle -> up to 10 items
    # - Text search: autocomplete -> 1 item
    # ---------------------------
    bundle_info = {
        "is_bundle": False,
        "added": 1,
        "reason": None,
    }

    items_to_add = []

    # ✅ CASE 1: raw is URL
    if _is_url(raw):
        # ✅ playlist / mix support
        if is_bundle_url(raw):
            try:
                bundle_entries = expand_bundle(
                    raw,
                    limit=10,
                    cookies_file=getattr(player, "youtube_cookies_file", None),
                    cookies_from_browser=None,
                ) or []
            except Exception as e:
                bundle_entries = []
                bundle_info["reason"] = f"EXPAND_FAILED:{e}"

            if bundle_entries:
                bundle_info["is_bundle"] = True
                bundle_info["added"] = min(10, len(bundle_entries))

                head = bundle_entries[0] or {}
                # Merge head with front metadata if provided
                head_item = {
                    "url": head.get("url") or raw,
                    "title": head.get("title") or title_in or raw,
                    "artist": head.get("artist") or artist_in or None,
                    "duration": head.get("duration") if head.get("duration") is not None else dur,
                    "thumb": head.get("thumb") or thumb_in,
                    "provider": head.get("provider") or provider_in or "youtube",
                }
                items_to_add.append(head_item)

                # Tail (up to 9 more)
                for e in bundle_entries[1:10]:
                    if not e:
                        continue
                    items_to_add.append({
                        "url": e.get("url") or raw,
                        "title": e.get("title") or (e.get("url") or raw),
                        "artist": e.get("artist") or None,
                        "duration": e.get("duration"),
                        "thumb": e.get("thumb"),
                        "provider": e.get("provider") or "youtube",
                    })
            else:
                # fallback to single URL item if expansion produced nothing
                items_to_add.append({
                    "url": raw,
                    "title": title_in or raw,
                    "artist": artist_in or None,
                    "duration": dur,
                    "thumb": thumb_in,
                    "provider": provider_in,
                })
        else:
            # simple URL
            items_to_add.append({
                "url": raw,
                "title": title_in or raw,
                "artist": artist_in or None,
                "duration": dur,
                "thumb": thumb_in,
                "provider": provider_in,
            })

    # ✅ CASE 2: raw is text -> autocomplete
    else:
        try:
            from api.services.search import autocomplete
            res = autocomplete(raw, limit=1)
            if res:
                top = res[0] or {}
                items_to_add.append({
                    "url": (top.get("url") or url_in or raw),
                    "title": (top.get("title") or title_in or raw),
                    "artist": (top.get("artist") or top.get("uploader") or artist_in or None),
                    "duration": (top.get("duration") if top.get("duration") is not None else dur),
                    "thumb": (top.get("thumbnail") or top.get("thumb") or thumb_in),
                    "provider": (top.get("provider") or provider_in),
                })
            else:
                items_to_add.append({
                    "url": url_in or raw,
                    "title": title_in or raw,
                    "artist": artist_in or None,
                    "duration": dur,
                    "thumb": thumb_in,
                    "provider": provider_in,
                })
        except Exception:
            items_to_add.append({
                "url": url_in or raw,
                "title": title_in or raw,
                "artist": artist_in or None,
                "duration": dur,
                "thumb": thumb_in,
                "provider": provider_in,
            })

    # Safety
    if not items_to_add:
        return jsonify({"ok": False, "error": "NO_ITEM_BUILT"}), 500

    # ---------------------------
    # ✅ Enqueue ALL items in a single coroutine (atomic-ish)
    # ---------------------------
    async def _do_many():
        out = {"ok": True, "results": [], "count": 0}
        for it in items_to_add:
            r = await player.enqueue(int(gid), int(uid), it or {"url": raw})
            out["results"].append(r)
            out["count"] += 1
            # If one fails, stop (keeps behavior deterministic)
            if not (r or {}).get("ok"):
                out["ok"] = False
                out["error"] = (r or {}).get("error") or "ENQUEUE_FAILED"
                break
        return out

    fut = asyncio.run_coroutine_threadsafe(_do_many(), player.bot.loop)
    try:
        res = fut.result(timeout=25) or {}
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # ---------------------------
    # ✅ Autoplay if queue was empty BEFORE
    # (after we added items)
    # ---------------------------
    autoplay = {"attempted": False, "ok": False, "reason": None}

    if was_empty and res.get("ok"):
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
    return jsonify({
        "ok": bool(res.get("ok")),
        "result": res,
        "autoplay": autoplay,
        "bundle": bundle_info,
    }), http_code


@bp.post("/queue/skip")
def skip_track():
    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
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

    try:
        _broadcast(gid)
    except Exception as e:
        print(f"[queue/remove] broadcast failed: {e}")

    return jsonify({"ok": bool(ok)}), 200 if ok else 409


@bp.post("/queue/move")
def move_item():
    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)
    uid = _uid_from(request, data)

    item = {
        "url": data.get("url"),
        "title": data.get("title") or data.get("query") or data.get("url"),
        "artist": data.get("artist"),
        "duration": data.get("duration"),
        "thumb": data.get("thumb"),
        "provider": data.get("provider"),
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
    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request, data)
    mode = str(data.get("mode") or "").strip().lower() or "toggle"

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
