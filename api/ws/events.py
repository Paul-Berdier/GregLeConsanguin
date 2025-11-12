# api/ws/events.py
from __future__ import annotations

import time
import logging
from typing import Any, Optional, Union, Dict

from flask import request as flask_request
from flask_socketio import emit, join_room, leave_room

from api.core.extensions import socketio

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- #
# Helpers & API publique                                                        #
# ----------------------------------------------------------------------------- #

def _room_for(gid: Union[str, int]) -> str:
    """Room Socket.IO pour une guilde."""
    return f"guild:{int(gid)}"


def broadcast_playlist_update(payload: Dict[str, Any], guild_id: Union[str, int, None] = None) -> None:
    """
    Diffuse un 'playlist_update' soit à toute la socket, soit à la room d'une guilde.
    Ex: broadcast_playlist_update({"queue": [...]}, guild_id=1234567890)
    """
    try:
        if guild_id is not None and str(guild_id).strip():
            socketio.emit("playlist_update", payload, room=_room_for(guild_id))
        else:
            socketio.emit("playlist_update", payload)
    except Exception as e:
        log.warning("broadcast_playlist_update failed: %s", e)


def presence_stats() -> Dict[str, Any]:
    """
    Retourne des stats de présence WebSocket (clients, rooms, rooms 'guild:*').
    Robuste selon les implémentations/versions de python-socketio.
    """
    out: Dict[str, Any] = {
        "ok": True,
        "ts": time.time(),
        "clients": 0,
        "rooms_total": 0,
        "guild_count": 0,
        "guild_rooms": {},   # { "guild:123": 4, ... }
        "rooms": {},         # { "<room>": <count>, ... }
    }
    try:
        server = getattr(socketio, "server", None)
        manager = getattr(server, "manager", None)
        if not manager:
            return out

        # manager.rooms est typiquement un dict { namespace: { room: set(sids) } }
        rooms_by_ns = getattr(manager, "rooms", {}) or {}
        ns_rooms = rooms_by_ns.get("/", {}) if isinstance(rooms_by_ns, dict) else {}
        out["rooms_total"] = len(ns_rooms)

        # Agrège le nombre de clients distincts et le nombre de sids par room
        all_sids = set()
        for room, members in ns_rooms.items():
            # members peut être un set de sids ou un dict-like
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

        # Filtre les rooms guild:*
        guild_rooms = {r: c for r, c in out["rooms"].items() if isinstance(r, str) and r.startswith("guild:")}
        out["guild_rooms"] = guild_rooms
        out["guild_count"] = len(guild_rooms)
        return out
    except Exception as e:
        log.debug("presence_stats error: %s", e)
        out["ok"] = False
        out["error"] = str(e)
        return out

# ----------------------------------------------------------------------------- #
# Événements de base (connexion / déconnexion)                                  #
# ----------------------------------------------------------------------------- #

@socketio.on("connect")
def on_connect():
    sid = flask_request.sid
    log.debug("[ws] connect sid=%s ua=%s", sid, flask_request.headers.get("User-Agent", ""))
    emit("welcome", {"sid": sid, "t": time.time()})


@socketio.on("disconnect")
def on_disconnect():
    sid = flask_request.sid
    log.debug("[ws] disconnect sid=%s", sid)

# ----------------------------------------------------------------------------- #
# Overlay ↔ serveur (rooms par guild, ping/pong)                                #
# ----------------------------------------------------------------------------- #

@socketio.on("overlay_register")
def on_overlay_register(data: Optional[Dict[str, Any]] = None):
    """
    data: { guild_id?: int|str }
    S'enregistre côté serveur et, si guild_id fourni, rejoint la room de la guilde.
    """
    data = data or {}
    sid = flask_request.sid
    gid = data.get("guild_id")

    if gid is not None and str(gid).strip():
        room = _room_for(gid)
        join_room(room)
        log.debug("[ws] overlay_register sid=%s → join %s", sid, room)
    else:
        log.debug("[ws] overlay_register sid=%s (no guild)", sid)

    emit("overlay_registered", {"sid": sid, "guild_id": gid, "t": time.time()})


@socketio.on("overlay_subscribe_guild")
def on_overlay_subscribe_guild(data: Optional[Dict[str, Any]] = None):
    """
    data: { guild_id: int|str }
    Rejoint la room de la guilde pour recevoir 'playlist_update' ciblés.
    """
    data = data or {}
    gid = data.get("guild_id")
    if gid is None or not str(gid).strip():
        return emit("overlay_joined", {"ok": False, "error": "missing guild_id"})

    room = _room_for(gid)
    join_room(room)
    log.debug("[ws] subscribe sid=%s → %s", flask_request.sid, room)
    emit("overlay_joined", {"ok": True, "guild_id": gid})


@socketio.on("overlay_unsubscribe_guild")
def on_overlay_unsubscribe_guild(data: Optional[Dict[str, Any]] = None):
    """
    data: { guild_id: int|str }
    Quitte la room de la guilde.
    """
    data = data or {}
    gid = data.get("guild_id")
    if gid is None or not str(gid).strip():
        return emit("overlay_left", {"ok": False, "error": "missing guild_id"})

    room = _room_for(gid)
    leave_room(room)
    log.debug("[ws] unsubscribe sid=%s ← %s", flask_request.sid, room)
    emit("overlay_left", {"ok": True, "guild_id": gid})


@socketio.on("overlay_ping")
def on_overlay_ping(data: Optional[Dict[str, Any]] = None):
    """Ping depuis le client overlay → renvoie un pong (au même client)."""
    emit("overlay_pong", {"t": time.time()})

# ----------------------------------------------------------------------------- #
# (Optionnel) Echo pour diagnostics                                              #
# ----------------------------------------------------------------------------- #

@socketio.on("echo")
def on_echo(data: Optional[Dict[str, Any]] = None):
    """Renvoie les données au seul émetteur (utile en debug)."""
    emit("echo", {"data": data or {}, "t": time.time()})
