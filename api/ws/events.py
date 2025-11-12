# api/ws/events.py
from __future__ import annotations

import time
import logging
from typing import Any, Optional, Union

from flask import request as flask_request
from flask_socketio import emit, join_room, leave_room

from api.core.extensions import socketio

log = logging.getLogger(__name__)


def _room_for(gid: Union[str, int]) -> str:
    """Room Socket.IO pour une guilde."""
    return f"guild:{int(gid)}"


# -----------------------------------------------------------------------------
# Événements de base (connexion / déconnexion)

@socketio.on("connect")
def on_connect():
    sid = flask_request.sid
    log.debug("[ws] connect sid=%s ua=%s", sid, flask_request.headers.get("User-Agent", ""))
    # Optionnel: message de bienvenue uniquement au client
    emit("welcome", {"sid": sid, "t": time.time()})


@socketio.on("disconnect")
def on_disconnect():
    sid = flask_request.sid
    log.debug("[ws] disconnect sid=%s", sid)


# -----------------------------------------------------------------------------
# Overlay ↔ serveur (rooms par guild, ping/pong)

@socketio.on("overlay_register")
def on_overlay_register(data: Optional[dict[str, Any]] = None):
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

    # Réponse au client (uniquement à l'émetteur)
    emit("overlay_registered", {"sid": sid, "guild_id": gid, "t": time.time()})


@socketio.on("overlay_subscribe_guild")
def on_overlay_subscribe_guild(data: Optional[dict[str, Any]] = None):
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
def on_overlay_unsubscribe_guild(data: Optional[dict[str, Any]] = None):
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
def on_overlay_ping(data: Optional[dict[str, Any]] = None):
    """Ping depuis le client overlay → renvoie un pong (au même client)."""
    emit("overlay_pong", {"t": time.time()})


# -----------------------------------------------------------------------------
# (Optionnel) Echo pour diagnostics

@socketio.on("echo")
def on_echo(data: Optional[dict[str, Any]] = None):
    """Renvoie les données au seul émetteur (utile en debug)."""
    emit("echo", {"data": data or {}, "t": time.time()})


# -----------------------------------------------------------------------------
# Notes:
# - Les mises à jour serveur → clients se font côté code via:
#       socketio.emit("playlist_update", payload, room=f"guild:{gid}")
#   (voir main.py: emit_fn et PlayerService._emit_playlist_update)
# - Ici, on ne gère pas de registry de présence avec TTL: c’est volontairement minimal.
