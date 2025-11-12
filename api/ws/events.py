# backend/api/ws/events.py
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from flask import current_app, session
from flask_socketio import emit, join_room, leave_room

from ..core.extensions import socketio
from .presence import PresenceRegistry

log = logging.getLogger(__name__)

# Registre global (in-memory). Pour la prod, envisager Redis pub/sub.
_presence = PresenceRegistry()


@socketio.on("connect")
def on_connect():
    # L'utilisateur peut ne pas être loggé si c'est l'overlay (device flow)
    emit("connected", {"ok": True})


@socketio.on("disconnect")
def on_disconnect():
    sid = _sid()
    _presence.remove(sid)


@socketio.on("overlay_register")
def on_overlay_register(data: Dict[str, Any]):
    """
    data: { "user_id": "...", "guild_id": "...", "meta": {...} }
    """
    user_id = (data or {}).get("user_id")
    guild_id = (data or {}).get("guild_id")
    meta = (data or {}).get("meta") or {}
    if not user_id:
        emit("error", {"message": "user_id required"})
        return

    sid = _sid()
    _presence.register(sid, user_id=user_id, guild_id=guild_id, meta=meta)
    if guild_id:
        join_room(f"guild:{guild_id}")
    emit("overlay_registered", {"ok": True})


@socketio.on("overlay_ping")
def on_overlay_ping():
    _presence.ping(_sid())
    emit("pong", {"ok": True})


def broadcast_playlist_update(guild_id: str, payload: Dict[str, Any]) -> None:
    socketio.emit("playlist_update", payload, to=f"guild:{guild_id}")


def presence_stats() -> dict:
    return _presence.stats()


def start_sweeper_once():
    # Lance un sweep périodique si non lancé.
    if getattr(current_app, "_presence_sweeper_started", False):
        return
    current_app._presence_sweeper_started = True

    def _loop():
        while True:
            try:
                _presence.sweep()
            except Exception as e:
                log.exception("Presence sweep error: %s", e)
            time.sleep(int(current_app.config.get("PRESENCE_SWEEP_SECONDS", 20)))

    t = threading.Thread(target=_loop, name="presence-sweeper", daemon=True)
    t.start()


def _sid() -> str:
    # socketio sid accessible via request.sid mais ici on s'appuie sur le contexte interne
    from flask_socketio import request as sio_request

    return sio_request.sid
