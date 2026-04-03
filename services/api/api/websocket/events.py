"""WebSocket events — Socket.IO handlers.

Handles both the new Next.js frontend events AND the old player.js overlay events.
"""
from __future__ import annotations

import logging

from flask import request as flask_request
from flask_socketio import emit, join_room, leave_room

from api import socketio

logger = logging.getLogger("greg.api.ws")


# ── Connection ──

@socketio.on("connect")
def on_connect():
    logger.debug("Client connected: sid=%s", flask_request.sid)


@socketio.on("disconnect")
def on_disconnect():
    logger.debug("Client disconnected: sid=%s", flask_request.sid)


# ── Guild rooms (new frontend) ──

@socketio.on("join_guild")
def on_join_guild(data):
    """Client rejoint la room d'une guild."""
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        join_room(room)
        logger.debug("Client %s joined room %s", flask_request.sid, room)
        emit("joined", {"guild_id": guild_id, "room": room})


@socketio.on("leave_guild")
def on_leave_guild(data):
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        leave_room(room)
        logger.debug("Client %s left room %s", flask_request.sid, room)


# ── Overlay events (player.js compat) ──

@socketio.on("overlay_register")
def on_overlay_register(data):
    """Le front s'enregistre comme overlay web player."""
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        join_room(room)
        logger.debug("Overlay registered: sid=%s guild=%s", flask_request.sid, guild_id)
    emit("overlay_ack", {"status": "ok", "sid": flask_request.sid})


@socketio.on("overlay_subscribe_guild")
def on_overlay_subscribe(data):
    """L'overlay s'abonne aux updates d'une guild."""
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        join_room(room)
        logger.debug("Overlay subscribed: sid=%s guild=%s", flask_request.sid, guild_id)


@socketio.on("overlay_unsubscribe_guild")
def on_overlay_unsubscribe(data):
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        leave_room(room)
        logger.debug("Overlay unsubscribed: sid=%s guild=%s", flask_request.sid, guild_id)


@socketio.on("overlay_ping")
def on_overlay_ping(data):
    """Keep-alive ping."""
    emit("overlay_pong", {"t": data.get("t"), "sid": flask_request.sid})


# ── State request ──

@socketio.on("request_state")
def on_request_state(data):
    """Client demande l'état courant d'une guild."""
    guild_id = str(data.get("guild_id", ""))
    if not guild_id:
        return

    from api.services.bot_bridge import send_command
    try:
        res = send_command("get_state", int(guild_id), timeout=5)
        if res.get("ok"):
            state = res.get("state", res)
            emit("playlist_update", state)
    except Exception as e:
        logger.error("request_state failed: %s", e)
