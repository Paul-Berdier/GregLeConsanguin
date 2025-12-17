# api/ws/events.py
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Union

from flask import current_app, request as flask_request
from flask_socketio import emit, join_room, leave_room

from api.core.extensions import socketio

log = logging.getLogger(__name__)

__all__ = [
    "broadcast_playlist_update",
    "socketio_presence_stats",
]

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def PM():
    """Même adaptateur que pour les routes HTTP."""
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
# Diagnostics présence                                                         #
# --------------------------------------------------------------------------- #

def socketio_presence_stats() -> Dict[str, Any]:
    """
    Stats basées sur l'état interne Flask-SocketIO/engineio.
    Ne dépend pas d'un registre custom => robuste en prod.
    """
    out: Dict[str, Any] = {
        "ok": True,
        "ts": time.time(),
        "clients": 0,
        "rooms_total": 0,
        "guild_count": 0,
        "guild_rooms": {},
        "rooms": {},
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
    log.debug("[ws] connect sid=%s ua=%s", sid, flask_request.headers.get("User-Agent", ""))
    emit("welcome", {"sid": sid, "t": time.time()})

@socketio.on("disconnect")
def on_disconnect():
    sid = flask_request.sid
    log.debug("[ws] disconnect sid=%s", sid)

# --------------------------------------------------------------------------- #
# Overlay : abonnement à une guilde                                            #
# --------------------------------------------------------------------------- #

@socketio.on("overlay_register")
def on_overlay_register(data: Optional[Dict[str, Any]] = None):
    data = data or {}
    sid = flask_request.sid
    gid = _safe_gid(data.get("guild_id"))

    if gid is not None:
        room = _room_for(gid)
        join_room(room)
        log.debug("[ws] overlay_register sid=%s → join %s", sid, room)
    else:
        log.debug("[ws] overlay_register sid=%s (no guild)", sid)

    emit("overlay_registered", {"sid": sid, "guild_id": gid, "t": time.time()})

@socketio.on("overlay_subscribe_guild")
def on_overlay_subscribe_guild(data: Optional[Dict[str, Any]] = None):
    data = data or {}
    gid = _safe_gid(data.get("guild_id"))
    if gid is None:
        return emit("overlay_joined", {"ok": False, "error": "missing guild_id"})
    room = _room_for(gid)
    join_room(room)
    log.debug("[ws] subscribe sid=%s → %s", flask_request.sid, room)
    emit("overlay_joined", {"ok": True, "guild_id": gid})

@socketio.on("overlay_unsubscribe_guild")
def on_overlay_unsubscribe_guild(data: Optional[Dict[str, Any]] = None):
    data = data or {}
    gid = _safe_gid(data.get("guild_id"))
    if gid is None:
        return emit("overlay_left", {"ok": False, "error": "missing guild_id"})
    room = _room_for(gid)
    leave_room(room)
    log.debug("[ws] unsubscribe sid=%s ← %s", flask_request.sid, room)
    emit("overlay_left", {"ok": True, "guild_id": gid})

@socketio.on("overlay_ping")
def on_overlay_ping(data: Optional[Dict[str, Any]] = None):
    emit("overlay_pong", {"t": time.time()})

# --------------------------------------------------------------------------- #
# Contrôle temps réel (ACK immédiat + broadcast)                               #
# --------------------------------------------------------------------------- #

@socketio.on("ctrl")
def ws_ctrl(data: Optional[Dict[str, Any]] = None):
    """
    data: { "guild_id": str|int, "action": str, "payload": dict }
    """
    try:
        data = data or {}
        gid = _safe_gid(data.get("guild_id"))
        if gid is None:
            return {"ok": False, "error": "missing guild_id"}

        action = (data.get("action") or "").strip().lower()
        payload = data.get("payload") or {}

        pm = PM()
        res = None

        if action == "queue_add":
            q = payload.get("url") or payload.get("query") or payload.get("title")
            if not q:
                return {"ok": False, "error": "missing query"}
            uid = payload.get("user_id")
            res = pm.enqueue(q, user_id=uid, guild_id=gid)

        elif action == "skip":
            res = pm.skip(guild_id=gid)

        elif action == "stop":
            res = pm.stop(guild_id=gid)

        elif action == "move":
            src = payload.get("src")
            dst = payload.get("dst")
            if src is None or dst is None:
                return {"ok": False, "error": "missing src/dst"}
            res = pm.move(int(src), int(dst), guild_id=gid)

        elif action == "remove":
            idx = payload.get("index")
            if idx is None:
                return {"ok": False, "error": "missing index"}
            res = pm.remove_at(int(idx), guild_id=gid)

        elif action == "next":
            res = pm.pop_next(guild_id=gid)

        else:
            return {"ok": False, "error": "unknown_action"}

        state = pm.get_state(guild_id=gid)
        broadcast_playlist_update({"state": state}, guild_id=gid)

        return {"ok": True, "result": res}

    except Exception as e:
        log.exception("ws_ctrl failed")
        return {"ok": False, "error": str(e)}
