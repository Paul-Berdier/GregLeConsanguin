# api/ws/events.py

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Union

from flask import current_app, request as flask_request
from flask_socketio import emit, join_room, leave_room

from api.core.extensions import socketio
from api.ws.presence import presence

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def PM():
    """
    Adaptateur unique.
    IMPORTANT:
      - Ici "pm" doit être ton service central (idéalement PlayerService)
      - Il doit exposer:
          - get_state(guild_id)
          - (async) enqueue(guild_id, user_id, item) OU play_for_user(...)
          - (async) skip/stop/pause/resume... (optionnel)
          - move/remove_at (sync) (optionnel)
    """
    return current_app.extensions["pm"]


def _room_for(gid: Union[str, int]) -> str:
    return f"guild:{int(gid)}"


def _safe_gid(v: Any) -> Optional[int]:
    try:
        s = str(v).strip()
        if not s:
            return None
        return int(s)
    except Exception:
        return None


def _safe_uid(v: Any) -> Optional[int]:
    try:
        s = str(v).strip()
        if not s:
            return None
        return int(s)
    except Exception:
        return None


def _is_url(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    ss = s.strip()
    return ss.startswith("http://") or ss.startswith("https://")


def _maybe_get_state(pm, gid: int) -> Optional[dict]:
    try:
        fn = getattr(pm, "get_state", None) or getattr(pm, "get_state", None)
        if fn:
            return fn(guild_id=gid) if "guild_id" in fn.__code__.co_varnames else fn(gid)
    except Exception:
        pass
    return None


def _run_on_bot_loop(pm, coro, timeout: float = 12.0):
    """
    Exécute un coroutine sur la loop Discord (si pm expose pm.bot.loop).
    Fallback: asyncio.run si pas de loop (moins idéal).
    """
    bot = getattr(pm, "bot", None)
    loop = getattr(bot, "loop", None) if bot else None
    if loop:
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)
    # fallback (dev/test)
    return asyncio.run(coro)


async def _call_async_or_thread(fn, *args, **kwargs):
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


def _broadcast_state(pm, gid: int) -> Optional[dict]:
    state = None
    try:
        state = _maybe_get_state(pm, gid)
        if state is not None:
            broadcast_playlist_update({"state": state}, guild_id=gid)
    except Exception:
        pass
    return state


# --------------------------------------------------------------------------- #
# Broadcast helper (utilisé aussi par les blueprints)                          #
# --------------------------------------------------------------------------- #

def broadcast_playlist_update(payload: Dict[str, Any], guild_id: Union[str, int, None] = None) -> None:
    """
    Diffuse un 'playlist_update' (payload arbitraire, tip: {"state": ...})
    - à toute la socket si guild_id est None
    - à la room d'une guilde sinon
    """
    try:
        if guild_id is not None and str(guild_id).strip():
            socketio.emit("playlist_update", payload, room=_room_for(guild_id))
        else:
            socketio.emit("playlist_update", payload)
    except Exception as e:
        log.warning("broadcast_playlist_update failed: %s", e)


# --------------------------------------------------------------------------- #
# Diagnostics présence (rooms Socket.IO)                                       #
# --------------------------------------------------------------------------- #

def presence_stats() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "ts": time.time(),
        "clients": 0,
        "rooms_total": 0,
        "guild_count": 0,
        "guild_rooms": {},
        "rooms": {},
        "presence": presence.stats(),
    }
    try:
        server = getattr(socketio, "server", None)
        manager = getattr(server, "manager", None)
        if not manager:
            return out
        rooms_by_ns = getattr(manager, "rooms", {}) or {}
        ns_rooms = rooms_by_ns.get("/", {}) if isinstance(rooms_by_ns, dict) else {}
        out["rooms_total"] = len(ns_rooms)

        all_sids = set()
        for room, members in ns_rooms.items():
            try:
                members_set = set(members)
            except Exception:
                try:
                    members_set = set(getattr(members, "keys", lambda: [])())
                except Exception:
                    members_set = set()
            out["rooms"][str(room)] = len(members_set)
            all_sids |= members_set

        out["clients"] = len(all_sids)
        guild_rooms = {r: c for r, c in out["rooms"].items() if isinstance(r, str) and r.startswith("guild:")}
        out["guild_rooms"] = guild_rooms
        out["guild_count"] = len(guild_rooms)
        return out
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
        return out


# --------------------------------------------------------------------------- #
# Events basiques                                                              #
# --------------------------------------------------------------------------- #

@socketio.on("connect")
def on_connect():
    sid = flask_request.sid
    ua = flask_request.headers.get("User-Agent", "")
    log.debug("[ws] connect sid=%s ua=%s", sid, ua)
    presence.register(sid=sid, meta={"ua": ua})
    emit("welcome", {"sid": sid, "t": time.time()})


@socketio.on("disconnect")
def on_disconnect():
    sid = flask_request.sid
    log.debug("[ws] disconnect sid=%s", sid)
    presence.remove(sid)


# --------------------------------------------------------------------------- #
# Overlay : abonnement à une guilde                                            #
# --------------------------------------------------------------------------- #

@socketio.on("overlay_register")
def on_overlay_register(data: Optional[Dict[str, Any]] = None):
    """
    data: { guild_id?, user_id?, meta? }
    """
    data = data or {}
    sid = flask_request.sid
    gid = _safe_gid(data.get("guild_id"))
    uid = _safe_uid(data.get("user_id"))
    meta = data.get("meta") or {}

    if gid is not None:
        room = _room_for(gid)
        join_room(room)
        log.debug("[ws] overlay_register sid=%s → join %s", sid, room)
        presence.update(sid, user_id=str(uid) if uid is not None else None, guild_id=str(gid), meta=meta)
    else:
        log.debug("[ws] overlay_register sid=%s (no guild)", sid)
        presence.update(sid, user_id=str(uid) if uid is not None else None, guild_id=None, meta=meta)

    emit("overlay_registered", {"sid": sid, "guild_id": gid, "user_id": uid, "t": time.time()})

    # ✅ Envoie l'état tout de suite si guild donnée
    if gid is not None:
        try:
            pm = PM()
            state = _maybe_get_state(pm, gid)
            if state is not None:
                emit("playlist_update", {"state": state})
        except Exception:
            pass


@socketio.on("overlay_subscribe_guild")
def on_overlay_subscribe_guild(data: Optional[Dict[str, Any]] = None):
    data = data or {}
    gid = _safe_gid(data.get("guild_id"))
    if gid is None:
        return emit("overlay_joined", {"ok": False, "error": "missing guild_id"})
    room = _room_for(gid)
    join_room(room)
    presence.update(flask_request.sid, guild_id=str(gid))
    log.debug("[ws] subscribe sid=%s → %s", flask_request.sid, room)
    emit("overlay_joined", {"ok": True, "guild_id": gid})

    # ✅ push state direct
    try:
        pm = PM()
        state = _maybe_get_state(pm, gid)
        if state is not None:
            emit("playlist_update", {"state": state})
    except Exception:
        pass


@socketio.on("overlay_unsubscribe_guild")
def on_overlay_unsubscribe_guild(data: Optional[Dict[str, Any]] = None):
    data = data or {}
    gid = _safe_gid(data.get("guild_id"))
    if gid is None:
        return emit("overlay_left", {"ok": False, "error": "missing guild_id"})
    room = _room_for(gid)
    leave_room(room)
    presence.update(flask_request.sid, guild_id=None)
    log.debug("[ws] unsubscribe sid=%s ← %s", flask_request.sid, room)
    emit("overlay_left", {"ok": True, "guild_id": gid})


@socketio.on("overlay_ping")
def on_overlay_ping(_data: Optional[Dict[str, Any]] = None):
    sid = flask_request.sid
    presence.ping(sid)
    presence.sweep()
    emit("overlay_pong", {"t": time.time(), "presence": presence.stats()})


@socketio.on("presence_stats")
def on_presence_stats():
    """Debug: renvoie stats room SocketIO + registry TTL."""
    return presence_stats()


# --------------------------------------------------------------------------- #
# Contrôle temps réel (ACK immédiat + broadcast)                               #
# --------------------------------------------------------------------------- #

@socketio.on("ctrl")
def ws_ctrl(data: Optional[Dict[str, Any]] = None):
    """
    data: { "guild_id": str|int, "action": str, "payload": dict }
    Actions supportées (robustes):
      - queue_add  (payload: {url|query|title, user_id?, autoplay?=True, ...})
      - skip       (payload: {user_id?})
      - stop       (payload: {user_id?})
      - move       (payload: {src:int, dst:int, user_id?})
      - remove     (payload: {index:int, user_id?})
      - next       (alias skip)
      - state      (renvoie l'état)
    Retour: { ok: bool, ... } (ACK)
    """
    try:
        data = data or {}
        gid = _safe_gid(data.get("guild_id"))
        if gid is None:
            return {"ok": False, "error": "missing guild_id"}

        action = (data.get("action") or "").strip().lower()
        payload = data.get("payload") or {}

        pm = PM()
        res: Any = None

        # Toujours utile de connaître le requester
        uid = _safe_uid(payload.get("user_id") or data.get("user_id"))

        if action in ("state", "get_state"):
            state = _broadcast_state(pm, gid) or _maybe_get_state(pm, gid)
            return {"ok": True, "state": state}

        if action == "queue_add":
            q = payload.get("url") or payload.get("query") or payload.get("title")
            if not q:
                return {"ok": False, "error": "missing query"}

            autoplay = payload.get("autoplay")
            if autoplay is None:
                autoplay = True  # par défaut: comportement “web déclenche vocal” (comme tu le voulais)

            # Construire un item propre (url ou résultat recherche)
            item: Dict[str, Any] = {}
            if _is_url(q):
                item = {
                    "url": str(q).strip(),
                    "title": payload.get("title"),
                    "artist": payload.get("artist"),
                    "duration": payload.get("duration"),
                    "thumb": payload.get("thumb"),
                    "provider": payload.get("provider"),
                }
            else:
                # Si c'est une query texte, tente autocomplete si dispo
                try:
                    from api.services.search import autocomplete
                    top = (autocomplete(str(q), limit=1) or [None])[0]
                    if top:
                        item = {
                            "url": top.get("url") or str(q),
                            "title": top.get("title") or str(q),
                            "artist": top.get("artist"),
                            "duration": top.get("duration"),
                            "thumb": top.get("thumbnail") or top.get("thumb"),
                            "provider": top.get("provider"),
                        }
                    else:
                        item = {"url": str(q)}
                except Exception:
                    item = {"url": str(q)}

            # Deux modes:
            # - autoplay=True => play_for_user (join vocal + enqueue + start si besoin)
            # - autoplay=False => enqueue seulement
            if autoplay:
                if uid is None:
                    return {"ok": False, "error": "missing user_id for autoplay"}
                play_for_user = getattr(pm, "play_for_user", None)
                if not play_for_user:
                    return {"ok": False, "error": "pm has no play_for_user()"}
                # async
                res = _run_on_bot_loop(pm, play_for_user(gid, uid, item), timeout=15)
            else:
                enqueue = getattr(pm, "enqueue", None)
                if not enqueue:
                    return {"ok": False, "error": "pm has no enqueue()"}
                if uid is None:
                    return {"ok": False, "error": "missing user_id"}
                res = _run_on_bot_loop(pm, enqueue(gid, uid, item), timeout=15)

        elif action in ("skip", "next"):
            fn = getattr(pm, "skip", None)
            if not fn:
                return {"ok": False, "error": "pm has no skip()"}
            if asyncio.iscoroutinefunction(fn):
                res = _run_on_bot_loop(pm, fn(gid, requester_id=uid) if uid is not None else fn(gid), timeout=10)
            else:
                res = fn(guild_id=gid) if "guild_id" in fn.__code__.co_varnames else fn(gid)

        elif action == "stop":
            fn = getattr(pm, "stop", None)
            if not fn:
                return {"ok": False, "error": "pm has no stop()"}
            if asyncio.iscoroutinefunction(fn):
                res = _run_on_bot_loop(pm, fn(gid, requester_id=uid) if uid is not None else fn(gid), timeout=10)
            else:
                res = fn(guild_id=gid) if "guild_id" in fn.__code__.co_varnames else fn(gid)

        elif action == "move":
            src = payload.get("src")
            dst = payload.get("dst")
            if src is None or dst is None:
                return {"ok": False, "error": "missing src/dst"}
            fn = getattr(pm, "move", None)
            if not fn:
                return {"ok": False, "error": "pm has no move()"}
            # move est généralement sync et peut vérifier la priorité
            if uid is None:
                # si ton move nécessite user_id (priorité), il faut le fournir
                try:
                    res = fn(int(gid), int(src), int(dst))  # legacy
                except TypeError:
                    return {"ok": False, "error": "missing user_id for move()"}
            else:
                try:
                    # style PlayerService: move(guild_id, requester_id, src, dst)
                    res = fn(int(gid), int(uid), int(src), int(dst))
                except TypeError:
                    # legacy: move(src, dst, guild_id=gid)
                    res = fn(int(src), int(dst), guild_id=gid)

        elif action == "remove":
            idx = payload.get("index")
            if idx is None:
                return {"ok": False, "error": "missing index"}
            fn = getattr(pm, "remove_at", None)
            if not fn:
                return {"ok": False, "error": "pm has no remove_at()"}
            if uid is None:
                try:
                    res = fn(int(gid), int(idx))  # legacy
                except TypeError:
                    return {"ok": False, "error": "missing user_id for remove_at()"}
            else:
                try:
                    # style PlayerService: remove_at(guild_id, requester_id, index)
                    res = fn(int(gid), int(uid), int(idx))
                except TypeError:
                    # legacy: remove_at(index, guild_id=gid)
                    res = fn(int(idx), guild_id=gid)

        else:
            return {"ok": False, "error": "unknown_action"}

        # Broadcast du nouvel état à la room de la guilde
        state = _broadcast_state(pm, gid)

        return {"ok": True, "result": res, "state": state}

    except PermissionError as e:
        # typiquement PRIORITY_FORBIDDEN
        return {"ok": False, "error": str(e) or "forbidden"}
    except Exception as e:
        log.exception("ws_ctrl failed")
        return {"ok": False, "error": str(e)}
