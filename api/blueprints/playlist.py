# api/blueprints/playlist.py

from __future__ import annotations

import asyncio
from typing import Any, Optional, Callable

from flask import Blueprint, jsonify, request, current_app

from api.ws.events import broadcast_playlist_update

# ✅ NEW: bundle support (playlist/mix)
from extractors import is_bundle_url, expand_bundle

bp = Blueprint("playlist", __name__)


def PLAYER():
    """
    Priority:
      1) app.extensions["player"]  (PlayerService - discord bot mode)
      2) app.extensions["pm"]      (PlayerAPIBridge - API only mode)
    """
    ex = current_app.extensions or {}
    return ex.get("player") or ex.get("pm")


def _to_str(v: Any) -> str:
    """Normalize any value (int/float/bool/None/str) into a safe string."""
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
        if hasattr(player, "get_state"):
            state = player.get_state(int(gid))
        else:
            return
        broadcast_playlist_update({"state": state}, guild_id=str(gid))
    except Exception:
        pass


def _is_url(s: str) -> bool:
    return isinstance(s, str) and s.startswith(("http://", "https://"))


def _to_int(v):
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return int(v)
        if isinstance(v, float):
            return int(v)
        s = str(v).strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        # tolerate "123.0"
        try:
            f = float(s)
            return int(f)
        except Exception:
            return None
    except Exception:
        return None


def _call_player(run_fn: Callable[[], Any], timeout: float = 15.0) -> Any:
    """
    Exécute un appel vers le player en supportant:
      - PlayerService (async via discord loop)
      - PlayerAPIBridge (sync, pas de loop)

    run_fn doit retourner:
      - soit une coroutine
      - soit une valeur directe
    """
    player = PLAYER()
    if not player:
        raise RuntimeError("PLAYER_UNAVAILABLE")

    bot = getattr(player, "bot", None)
    loop = getattr(bot, "loop", None) if bot else None

    out = run_fn()

    if asyncio.iscoroutine(out):
        if loop:
            fut = asyncio.run_coroutine_threadsafe(out, loop)
            return fut.result(timeout=timeout)
        return asyncio.run(out)

    return out


# ==========================
# ✅ NEW: "added by" helpers
# ==========================
def _discord_user_payload(gid: str, uid: str) -> dict:
    """
    Build a stable requester payload:
      requested_by: {id, username, display_name, global_name, avatar_url?}
    Also exposes legacy fields requested_by_id / requested_by_name for compatibility.
    Works best in Discord mode; in API-only mode we fallback to id-only.
    """
    uid_s = _to_str(uid).strip()
    gid_s = _to_str(gid).strip()
    out = {
        "requested_by": {"id": uid_s},
        "requested_by_id": uid_s,
        "requested_by_name": "",
    }

    player = PLAYER()
    bot = getattr(player, "bot", None)
    if not bot:
        return out

    try:
        g = bot.get_guild(int(gid_s)) if gid_s else None
        if not g:
            return out

        m = g.get_member(int(uid_s))
        if not m:
            return out

        # Discord.py: display_name is always available; global_name may not exist depending on version
        display_name = getattr(m, "display_name", "") or ""
        username = getattr(m, "name", "") or ""
        global_name = getattr(m, "global_name", "") or ""

        avatar_url = ""
        try:
            av = getattr(m, "display_avatar", None) or getattr(m, "avatar", None)
            if av:
                avatar_url = str(av.url)
        except Exception:
            avatar_url = ""

        out["requested_by"] = {
            "id": uid_s,
            "username": _to_str(username).strip(),
            "display_name": _to_str(display_name).strip(),
            "global_name": _to_str(global_name).strip(),
            "avatar_url": _to_str(avatar_url).strip(),
        }

        # Prefer display_name for UI
        out["requested_by_name"] = _to_str(display_name or global_name or username).strip()
        return out
    except Exception:
        return out


def _attach_requester(item: dict, gid: str, uid: str) -> dict:
    """
    Mutates + returns item, ensuring requester fields exist.
    Does not override if already present (unless empty).
    """
    if not isinstance(item, dict):
        return item

    meta = _discord_user_payload(gid, uid)

    # If item already has requested_by, keep it (but fill missing id/name if needed)
    rb = item.get("requested_by")
    if isinstance(rb, dict):
        rb_id = _to_str(rb.get("id")).strip()
        if not rb_id:
            rb["id"] = meta["requested_by"]["id"]
        # Fill names if missing
        if not _to_str(rb.get("display_name")).strip() and _to_str(meta["requested_by"].get("display_name")).strip():
            rb["display_name"] = meta["requested_by"]["display_name"]
        if not _to_str(rb.get("username")).strip() and _to_str(meta["requested_by"].get("username")).strip():
            rb["username"] = meta["requested_by"]["username"]
        if not _to_str(rb.get("global_name")).strip() and _to_str(meta["requested_by"].get("global_name")).strip():
            rb["global_name"] = meta["requested_by"]["global_name"]
        if not _to_str(rb.get("avatar_url")).strip() and _to_str(meta["requested_by"].get("avatar_url")).strip():
            rb["avatar_url"] = meta["requested_by"]["avatar_url"]
        item["requested_by"] = rb
    else:
        item["requested_by"] = meta["requested_by"]

    # Legacy compatibility fields (frontends / logs)
    if not _to_str(item.get("requested_by_id")).strip():
        item["requested_by_id"] = meta["requested_by_id"]
    if not _to_str(item.get("requested_by_name")).strip():
        item["requested_by_name"] = meta["requested_by_name"]

    return item


@bp.get("/playlist")
def get_playlist_state():
    gid = _gid_from(request)
    player = PLAYER()
    if not gid or not player:
        return jsonify({"ok": False, "error": "missing guild_id/player"}), 400

    try:
        state = player.get_state(int(gid))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

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

    # state before (autoplay decision)
    try:
        before = player.get_state(int(gid)) or {}
    except Exception:
        before = {}

    cur = before.get("current")
    was_empty = (len(before.get("queue") or []) == 0) and (not cur or not cur.get("url"))

    # metadata
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

    bundle_info = {"is_bundle": False, "added": 1, "reason": None}
    items_to_add: list[dict] = []

    # CASE 1 URL
    if _is_url(raw):
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
                items_to_add.append({
                    "url": head.get("url") or raw,
                    "title": head.get("title") or title_in or raw,
                    "artist": head.get("artist") or artist_in or None,
                    "duration": head.get("duration") if head.get("duration") is not None else dur,
                    "thumb": head.get("thumb") or thumb_in,
                    "provider": head.get("provider") or provider_in or "youtube",
                })

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
                items_to_add.append({
                    "url": raw,
                    "title": title_in or raw,
                    "artist": artist_in or None,
                    "duration": dur,
                    "thumb": thumb_in,
                    "provider": provider_in,
                })
        else:
            items_to_add.append({
                "url": raw,
                "title": title_in or raw,
                "artist": artist_in or None,
                "duration": dur,
                "thumb": thumb_in,
                "provider": provider_in,
            })

    # CASE 2 TEXT search
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

    if not items_to_add:
        return jsonify({"ok": False, "error": "NO_ITEM_BUILT"}), 500

    # ✅ Attach requester info to every item (this is what your frontend needs)
    for it in items_to_add:
        _attach_requester(it, gid, uid)

    def _do_many_sync_or_coro():
        async def _do_many():
            out = {"ok": True, "results": [], "count": 0}
            for it in items_to_add:
                r = await player.enqueue(int(gid), int(uid), it or {"url": raw})
                out["results"].append(r)
                out["count"] += 1
                if not (r or {}).get("ok"):
                    out["ok"] = False
                    out["error"] = (r or {}).get("error") or "ENQUEUE_FAILED"
                    break
            return out

        # bridge sync
        if not asyncio.iscoroutinefunction(getattr(player, "enqueue", None)):
            out = {"ok": True, "results": [], "count": 0}
            for it in items_to_add:
                r = player.enqueue(it or {"url": raw}, user_id=str(uid), guild_id=str(gid))
                out["results"].append(r)
                out["count"] += 1
                if not (r or {}).get("ok"):
                    out["ok"] = False
                    out["error"] = (r or {}).get("error") or "ENQUEUE_FAILED"
                    break
            return out

        return _do_many()

    try:
        res = _call_player(_do_many_sync_or_coro, timeout=25) or {}
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # autoplay if was empty
    autoplay = {"attempted": False, "ok": False, "reason": None}

    if was_empty and res.get("ok"):
        def _auto_play_sync_or_coro():
            async def _auto():
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

            if not getattr(getattr(player, "bot", None), "loop", None):
                return {"ok": False, "reason": "AUTOPLAY_DISABLED_NO_DISCORD"}

            return _auto()

        autoplay["attempted"] = True
        try:
            autoplay.update(_call_player(_auto_play_sync_or_coro, timeout=12) or {})
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

    try:
        if asyncio.iscoroutinefunction(getattr(player, "skip", None)):
            _call_player(lambda: player.skip(int(gid), requester_id=int(uid)), timeout=8)
        else:
            player.skip(guild_id=str(gid))
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

    try:
        if asyncio.iscoroutinefunction(getattr(player, "stop", None)):
            _call_player(lambda: player.stop(int(gid), requester_id=int(uid)), timeout=8)
        else:
            player.stop(guild_id=str(gid))
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
        ok = player.remove_at(int(gid), int(uid), int(idx)) if hasattr(player, "remove_at") else False
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
        ok = player.move(int(gid), int(uid), int(src), int(dst)) if hasattr(player, "move") else False
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
        if hasattr(player, "_get_pm"):
            pm = player._get_pm(int(gid))
            pm.reload()
            res = pm.pop_next()
        else:
            res = player.pop_next(guild_id=str(gid))
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

    # ✅ Ensure requester info exists for "play" too
    _attach_requester(item, gid, uid)

    try:
        if asyncio.iscoroutinefunction(getattr(player, "play_for_user", None)):
            res = _call_player(lambda: player.play_for_user(int(gid), int(uid), item), timeout=12)
        else:
            res = player.enqueue(item, user_id=str(uid), guild_id=str(gid))
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool((res or {}).get("ok")), "result": res}), 200 if (res or {}).get("ok") else 409


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

    if not getattr(getattr(player, "bot", None), "loop", None):
        try:
            ok_move = player.move(int(gid), int(uid), int(idx), 0)
        except PermissionError:
            return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        _broadcast(gid)
        return jsonify({"ok": bool(ok_move), "note": "API-only: moved, no voice autoplay"}), 200 if ok_move else 409

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

    try:
        ok = bool(_call_player(lambda: _do(), timeout=12))
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

    if not getattr(getattr(player, "bot", None), "loop", None):
        return jsonify({"ok": False, "error": "NO_VOICE_IN_API_ONLY_MODE"}), 409

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

    try:
        res = _call_player(lambda: _do(), timeout=8)
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

    try:
        if asyncio.iscoroutinefunction(getattr(player, "toggle_repeat", None)):
            val = _call_player(lambda: player.toggle_repeat(int(gid), mode), timeout=8)
            res = {"ok": True, "repeat_all": bool(val)}
        else:
            res = {"ok": False, "error": "REPEAT_UNSUPPORTED_IN_BRIDGE"}
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200 if res.get("ok") else 409


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

    if not getattr(getattr(player, "bot", None), "loop", None):
        return jsonify({"ok": False, "error": "RESTART_UNSUPPORTED_IN_API_ONLY_MODE"}), 409

    async def _do():
        g = player.bot.get_guild(int(gid))
        if not g:
            return {"ok": False, "error": "GUILD_NOT_FOUND"}

        cur = (player.now_playing.get(int(gid)) or player.current_song.get(int(gid)))
        if not cur:
            return {"ok": False, "error": "NO_CURRENT"}

        item = {
            "url": cur.get("url"),
            "title": cur.get("title"),
            "artist": cur.get("artist"),
            "thumb": cur.get("thumb") or cur.get("thumbnail"),
            "duration": cur.get("duration"),
            "provider": cur.get("provider") or "youtube",
        }

        # ✅ Keep requester attribution on restart (the requester is the one who clicked restart)
        _attach_requester(item, gid, uid)

        res = await player.enqueue(int(gid), int(uid), item)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "ENQUEUE_FAILED"}

        pm = player._get_pm(int(gid))
        pm.reload()
        q = pm.peek_all()
        last = max(0, len(q) - 1)
        player.move(int(gid), int(uid), last, 0)

        await player.skip(int(gid), requester_id=int(uid))
        return {"ok": True}

    try:
        res = _call_player(lambda: _do(), timeout=12)
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200 if res.get("ok") else 409
