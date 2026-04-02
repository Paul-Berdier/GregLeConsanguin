"""WebSocket events — Socket.IO handlers."""
from __future__ import annotations

import logging

from flask_socketio import emit, join_room, leave_room

from api import socketio

logger = logging.getLogger("greg.api.ws")


@socketio.on("connect")
def on_connect():
    logger.debug("Client connected: %s", "ok")


@socketio.on("disconnect")
def on_disconnect():
    logger.debug("Client disconnected")


@socketio.on("join_guild")
def on_join_guild(data):
    """Client rejoint la room d'une guild pour recevoir les updates."""
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        join_room(room)
        logger.debug("Client joined room %s", room)
        emit("joined", {"guild_id": guild_id, "room": room})


@socketio.on("leave_guild")
def on_leave_guild(data):
    guild_id = str(data.get("guild_id", ""))
    if guild_id:
        room = f"guild:{guild_id}"
        leave_room(room)
        logger.debug("Client left room %s", room)


@socketio.on("request_state")
def on_request_state(data):
    """Client demande l'état courant d'une guild."""
    guild_id = str(data.get("guild_id", ""))
    if not guild_id:
        return

    from api.services.bot_bridge import send_command
    try:
        res = send_command("get_state", int(guild_id), timeout=5)
        if res.get("ok") and res.get("state"):
            emit("playlist_update", res["state"])
    except Exception as e:
        logger.error("request_state failed: %s", e)
