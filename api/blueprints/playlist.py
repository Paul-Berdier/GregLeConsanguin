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

def _is_url(s: str) -> bool:
    return isinstance(s, str) and s.startswith(("http://", "https://"))

# --- lecture de l'état -------------------------------------------------------
@bp.get("/playlist")
def get_playlist_state():
    gid = _gid_from(request)
    state = PM().get_state(guild_id=gid)
    return jsonify({"ok": True, "state": state}), 200

# --- ajout avec AUTOPLAY si file vide (PRIORITY/QUOTA via PlayerService) ----
@bp.post("/queue/add")
def add_to_queue():
    data = request.get_json(silent=True) or {}
    # On accepte query / url / title pour rester souple côté overlay
    raw = data.get("query") or data.get("url") or data.get("title")
    if not raw:
        return jsonify({"ok": False, "error": "missing query"}), 400

    gid = _gid_from(request)
    uid = _uid_from(request, data)
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503

    # état avant (pour savoir si 0→1)
    before = PM().get_state(guild_id=gid) or {}
    was_empty = len(before.get("queue") or []) == 0 and not bool(before.get("current"))

    # Construire l'item minimal : si pas URL → tentative de résolution via autocomplete
    item = None
    if _is_url(raw):
        item = {"url": raw}
    else:
        try:
            from api.services.search import autocomplete
            res = autocomplete(raw, limit=1)
            if res:
                top = res[0]
                item = {
                    "url": top.get("url") or raw,
                    "title": top.get("title") or raw,
                    "duration": top.get("duration"),
                    "thumb": top.get("thumbnail"),
                    "provider": top.get("provider"),
                }
        except Exception:
            # si search indisponible, on transfère tel quel
            item = {"url": raw}

    async def _do():
        # applique quota + poids + insert triée via PlayerService.enqueue
        return await player.enqueue(int(gid), int(uid), item or {"url": raw})

    fut = asyncio.run_coroutine_threadsafe(_do(), player.bot.loop)
    try:
        res = fut.result(timeout=12) or {}
    except PermissionError as e:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # autoplay si la file était vide → connexion & play_next
    autoplay = {"attempted": False, "ok": False, "reason": None}

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

            # IMPORTANT: play_next ne démarre pas si vc.is_playing() ou vc.is_paused()
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

# --- skip/stop pilotés par le PlayerService (PRIORITY) -----------------------
@bp.post("/queue/skip")
def skip_track():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
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
    gid = _gid_from(request)
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

# --- gestion queue (remove/move) avec priorité via PlayerService -------------
@bp.post("/queue/remove")
def remove_at():
    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    gid = _gid_from(request)
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
    except IndexError:
        return jsonify({"ok": False, "error": "index out of range"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool(ok)}), 200 if ok else 409

@bp.post("/queue/move")
def move_item():
    data = request.get_json(silent=True) or {}
    src = data.get("src")
    dst = data.get("dst")
    gid = _gid_from(request)
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
    except IndexError:
        return jsonify({"ok": False, "error": "index out of range"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _broadcast(gid)
    return jsonify({"ok": bool(ok)}), 200 if ok else 409

# --- (optionnel) pop_next REST brut : déconseillé côté overlay ----------------
# Conserver pour compat : ne déclenche pas de lecture, pure mutation d'état.
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

# --- lire l’élément i (déplace en tête & joue) — priorité appliquée ---------
@bp.post("/playlist/play_at")
def playlist_play_at():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
    uid = _uid_from(request, data)
    idx = data.get("index")
    if idx is None:
        return jsonify({"ok": False, "error": "missing index"}), 400
    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    # 1) déplacer en tête avec contrôle de priorité
    try:
        ok_move = player.move(int(gid), int(uid), int(idx), 0)
        if not ok_move:
            return jsonify({"ok": False, "error": "move failed"}), 409
    except PermissionError:
        return jsonify({"ok": False, "error": "PRIORITY_FORBIDDEN"}), 403
    except IndexError:
        return jsonify({"ok": False, "error": "index out of range"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"move failed: {e}"}), 500

    # 2) lancer la lecture (skip déclenchera #0)
    async def _do():
        g = player.bot.get_guild(int(gid))
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            await player.skip(int(gid), requester_id=int(uid))
            return True
        # sinon: rejoindre puis play_next
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

# --- pause/reprise bascule (PRIORITY) ---------------------------------------
@bp.post("/playlist/toggle_pause")
def playlist_toggle_pause():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
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

# --- restart: rejouer le morceau courant (sans seek) avec priorité ----------
@bp.post("/playlist/restart")
def playlist_restart():
    data = request.get_json(silent=True) or {}
    gid = _gid_from(request)
    uid = _uid_from(request, data)

    player = PLAYER()
    if not player:
        return jsonify({"ok": False, "error": "PLAYER_UNAVAILABLE"}), 503
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id/user_id"}), 400

    # Stratégie simple et sûre :
    # 1) déplacer le morceau courant en tête de file (si nécessaire),
    # 2) skip (contrôle de priorité) pour le relancer.
    async def _do():
        g = player.bot.get_guild(int(gid))
        cur = (player.now_playing.get(int(gid)) or player.current_song.get(int(gid)))
        if not g or not cur:
            return {"ok": False, "error": "NO_CURRENT"}

        # Ré-enfiler le courant en fin puis remonter en #0 via API service (respecte priorité)
        pm = PM()
        url = cur.get("url")
        title = cur.get("title") or url
        # Enfile « proprement » via PM (état), puis move via service soumis à priorité
        pm.enqueue(url or title, user_id=uid, guild_id=gid)
        q = (pm.get_state(guild_id=gid) or {}).get("queue") or []
        last = max(0, len(q) - 1)
        player.move(int(gid), int(uid), last, 0)  # peut lever PermissionError

        # Skip avec contrôle de priorité → relance la #0
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
