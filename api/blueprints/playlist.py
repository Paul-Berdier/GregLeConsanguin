# api/routes/playlist.py
from __future__ import annotations

import asyncio
from flask import Blueprint, jsonify, request, current_app
from api.ws.events import broadcast_playlist_update

bp = Blueprint("playlist", __name__)

# --- helpers -----------------------------------------------------------------
def PM():
    # APIPMAdapter déjà initialisé dans app.extensions["pm"]
    return current_app.extensions["pm"]

def PLAYER():
    # PlayerService est enregistré dans app.extensions["player"]
    return current_app.extensions.get("player")

def _gid_from(req):
    # ordre: ?guild_id=... → X-Guild-ID → body.guild_id
    return (
        (req.args.get("guild_id") or "").strip()
        or (req.headers.get("X-Guild-ID") or "").strip()
        or ((req.json or {}).get("guild_id") or "").strip()
    ) or None

def _uid_from(req, data: dict):
    return (data.get("user_id") or req.headers.get("X-User-ID") or "").strip() or None

def _broadcast(gid):
    try:
        state = PM().get_state(guild_id=gid)
        broadcast_playlist_update({"state": state}, guild_id=gid)
    except Exception:
        pass

# --- lecture de l'état -------------------------------------------------------
@bp.get("/playlist")
def get_playlist_state():
    gid = _gid_from(request)
    state = PM().get_state(guild_id=gid)
    return jsonify({"ok": True, "state": state}), 200

# --- ajout avec AUTOPLAY si file vide ---------------------------------------
@bp.post("/queue/add")
def add_to_queue():
    data = request.get_json(silent=True) or {}
    # On accepte query / url / title pour rester souple côté overlay
    query = data.get("query") or data.get("url") or data.get("title")
    if not query:
        return jsonify({"ok": False, "error": "missing query"}), 400

    gid = _gid_from(request)
    uid = _uid_from(request, data)

    # état avant (pour savoir si 0→1)
    before = PM().get_state(guild_id=gid) or {}
    was_empty = len(before.get("queue") or []) == 0 and not bool(before.get("current"))

    # enqueue (APIPMAdapter)
    res = PM().enqueue(query, user_id=uid, guild_id=gid)

    # autoplay si la file était vide et qu'on connaît l'utilisateur (pour le channel vocal)
    player = PLAYER()
    if player and was_empty and uid and gid:
        async def _auto_play():
            g = player.bot.get_guild(int(gid)) if gid else None
            m = g.get_member(int(uid)) if g and uid else None
            ch = m.voice.channel if (m and m.voice) else None
            if not (g and ch):
                return
            ok = await player.ensure_connected(g, ch)
            if ok:
                await player.play_next(g)
        try:
            asyncio.run_coroutine_threadsafe(_auto_play(), player.bot.loop)
        except Exception:
            pass

    _broadcast(gid)
    return jsonify({"ok": True, "result": res}), 200

# --- skip/stop pilotés par le PlayerService ---------------------------------
@bp.post("/queue/skip")
def skip_track():
    gid = _gid_from(request)
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    async def _do():
        return await player.skip(int(gid))
    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        fut.result(timeout=8)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    _broadcast(gid)
    return jsonify({"ok": True}), 200

@bp.post("/queue/stop")
def stop_playback():
    gid = _gid_from(request)
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    async def _do():
        return await player.stop(int(gid))
    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        fut.result(timeout=8)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    _broadcast(gid)
    return jsonify({"ok": True}), 200

# --- gestion queue (remove/move/next) via PM (état pur) ----------------------
@bp.post("/queue/remove")
def remove_at():
    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    if idx is None:
        return jsonify({"ok": False, "error": "missing index"}), 400
    gid = _gid_from(request)
    res = PM().remove_at(int(idx), guild_id=gid)
    _broadcast(gid)
    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/move")
def move_item():
    data = request.get_json(silent=True) or {}
    src = data.get("src")
    dst = data.get("dst")
    if src is None or dst is None:
        return jsonify({"ok": False, "error": "missing src/dst"}), 400
    gid = _gid_from(request)
    res = PM().move(int(src), int(dst), guild_id=gid)
    _broadcast(gid)
    return jsonify({"ok": True, "result": res}), 200

@bp.post("/queue/next")
def pop_next():
    gid = _gid_from(request)
    res = PM().pop_next(guild_id=gid)
    _broadcast(gid)
    return jsonify({"ok": True, "result": res}), 200

# --- lecture directe: enqueue + join + play ---------------------------------
@bp.post("/playlist/play")
def playlist_play():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
    uid = _uid_from(request, data)

    # accepte URL/suggestion
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
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool(res.get("ok")), "result": res}), 200 if res.get("ok") else 409

# --- lire l’élément i (déplace en tête & joue) -------------------------------
@bp.post("/playlist/play_at")
def playlist_play_at():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
    uid = _uid_from(request, data)
    idx = data.get("index")
    if idx is None:
        return jsonify({"ok": False, "error": "missing index"}), 400

    # déplace l’élément voulu en tête
    try:
        # on place à 0 même si priorité — l’overlay a déjà validé la move
        q = (PM().get_state(guild_id=gid) or {}).get("queue") or []
        last = len(q) - 1
        if not (0 <= int(idx) <= last):
            return jsonify({"ok": False, "error": "index out of range"}), 400
        PM().move(int(idx), 0, guild_id=gid)
    except Exception as e:
        return jsonify({"ok": False, "error": f"move failed: {e}"}), 500

    player = PLAYER()
    if not player:
        _broadcast(gid)
        return jsonify({"ok": True, "note": "moved only (no player)"}), 200

    async def _do():
        g = player.bot.get_guild(int(gid)) if gid else None
        # si qlq chose joue déjà → skip lancera le #0
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            await player.skip(int(gid))
            return True
        # sinon on doit rejoindre puis play_next
        if uid:
            m = g.get_member(int(uid)) if g else None
            ch = m.voice.channel if (m and m.voice) else None
            if ch and await player.ensure_connected(g, ch):
                await player.play_next(g)
                return True
        return False

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        ok = bool(fut.result(timeout=12))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": ok}), 200 if ok else 409

# --- pause/reprise bascule ---------------------------------------------------
@bp.post("/playlist/toggle_pause")
def playlist_toggle_pause():
    gid = _gid_from(request)
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    async def _do():
        g = player.bot.get_guild(int(gid)) if gid else None
        vc = g and g.voice_client
        if not vc:
            return {"ok": False, "error": "NO_VOICE"}
        if vc.is_paused():
            ok = await player.resume(int(gid))
            return {"ok": ok, "action": "resume" if ok else "noop"}
        if vc.is_playing():
            ok = await player.pause(int(gid))
            return {"ok": ok, "action": "pause" if ok else "noop"}
        return {"ok": False, "error": "NOT_PLAYING"}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=8)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200 if res.get("ok") else 409

# --- repeat all on/off/toggle -----------------------------------------------
@bp.post("/playlist/repeat")
def playlist_repeat():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
    mode = (data.get("mode") or "").strip().lower() or "toggle"  # "toggle" | "on" | "off"
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

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

# --- restart: rejouer le morceau courant (sans seek) -------------------------
@bp.post("/playlist/restart")
def playlist_restart():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    # stratégie:
    # 1) ré-enfiler le morceau courant en fin
    # 2) le déplacer en tête
    # 3) skip pour lancer celui-ci
    async def _do():
        g = player.bot.get_guild(int(gid)) if gid else None
        cur = (player.now_playing.get(int(gid)) or player.current_song.get(int(gid))) if player else None
        if not g or not cur:
            return {"ok": False, "error": "NO_CURRENT"}

        url = cur.get("url")
        title = cur.get("title") or url
        item = {"url": url, "title": title, "artist": cur.get("artist"), "thumb": cur.get("thumb"),
                "duration": cur.get("duration"), "provider": cur.get("provider")}

        # 1) enqueue
        pm = PM()
        pm.enqueue(item.get("url") or item.get("title"), user_id=uid, guild_id=gid)
        q = (pm.get_state(guild_id=gid) or {}).get("queue") or []
        last = max(0, len(q) - 1)

        # 2) déplacer en tête
        pm.move(last, 0, guild_id=gid)

        # 3) skip pour jouer le #0
        await player.skip(int(gid))
        return {"ok": True}

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify(res), 200 if res.get("ok") else 409
