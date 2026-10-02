"""WebSocket events — Socket.IO handlers du front Next.js.

Les noms `overlay_*` sont historiques : le front web les utilise toujours pour
s'abonner aux mises à jour d'une guild et pour le keep-alive.

Sécurité (SEC-C4) : une room `guild:<id>` ne se rejoint qu'avec une session
Discord ET un accès confirmé par le bot (membre du serveur) ; sinon le client
reçoit `guild_join_error` {guild_id, error, message, retry}.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from flask import request as flask_request
from flask_socketio import emit, join_room, leave_room

from api import socketio
from api.services import bot_bridge
from api.services.authz import MSG_NOT_AUTHENTICATED, ROOM_AUTHENTICATED, session_user_id
from api.services.relay_clock import now_ms, with_relay_at

logger = logging.getLogger("greg.api.ws")

_GUILD_ID_RE = re.compile(r"^[0-9]{1,20}$")

# Échecs passagers : le front réessaie de s'abonner un peu plus tard.
_RETRYABLE = frozenset({"TIMEOUT", "BOT_OFFLINE", "REDIS_UNAVAILABLE", "MEMBER_CHECK_FAILED"})
_MSG_JOIN_FAILED = "Impossible de suivre ce serveur pour l'instant."
_MSG_BRIDGE_ERROR = "Greg est injoignable pour le moment, nouvelle tentative bientôt."


def _payload(data) -> dict:
    """Payload d'un event — toujours un dict (payload absent ou non-objet → {})."""
    return data if isinstance(data, dict) else {}


def _guild_id(data: dict) -> Optional[int]:
    """guild_id valide (entier > 0) ou None — jamais d'appel au bot sur une valeur douteuse."""
    raw = data.get("guild_id")
    if isinstance(raw, bool) or raw is None:
        return None
    s = str(raw).strip()
    if not _GUILD_ID_RE.match(s):
        return None
    gid = int(s)
    return gid if gid > 0 else None


def _deny(gid: int, error: str, message: Optional[str], retry: bool) -> None:
    leave_room(f"guild:{gid}")
    emit("guild_join_error", {
        "guild_id": str(gid),
        "error": error,
        "message": message or _MSG_JOIN_FAILED,
        "retry": retry,
    })


def _subscribe(gid: int) -> bool:
    """Rejoint `guild:<gid>` si l'utilisateur de la session y a accès, et envoie l'état."""
    uid = session_user_id()
    if uid is None:
        _deny(gid, "NOT_AUTHENTICATED", MSG_NOT_AUTHENTICATED, False)
        return False
    try:
        res = bot_bridge.send_command("get_state", gid, uid, timeout=5)
    except Exception as e:
        logger.error("Abonnement guild %s impossible: %s", gid, e)
        _deny(gid, "REDIS_UNAVAILABLE", _MSG_BRIDGE_ERROR, True)
        return False
    at_ms = now_ms()  # réception de la réponse du bot (synchro son/vidéo)
    if not isinstance(res, dict) or not res.get("ok"):
        res = res if isinstance(res, dict) else {}
        err = str(res.get("error") or "UNKNOWN")
        _deny(gid, err, res.get("message"), err in _RETRYABLE)
        return False

    room = f"guild:{gid}"
    join_room(room)
    logger.debug("Client %s joined room %s", flask_request.sid, room)
    state = res.get("state", res)
    emit("playlist_update", with_relay_at(state, at_ms) if isinstance(state, dict) else state)
    return True


# ── Connection ──

@socketio.on("connect")
def on_connect():
    # Room des sockets connectés à Discord (bot_status : liste des serveurs du bot).
    if session_user_id() is not None:
        join_room(ROOM_AUTHENTICATED)
    logger.debug("Client connected: sid=%s", flask_request.sid)


@socketio.on("disconnect")
def on_disconnect():
    logger.debug("Client disconnected: sid=%s", flask_request.sid)


# ── Guild rooms ──

@socketio.on("join_guild")
def on_join_guild(data=None):
    gid = _guild_id(_payload(data))
    if gid is not None and _subscribe(gid):
        emit("joined", {"guild_id": str(gid), "room": f"guild:{gid}"})


@socketio.on("leave_guild")
def on_leave_guild(data=None):
    gid = _guild_id(_payload(data))
    if gid is not None:
        leave_room(f"guild:{gid}")
        logger.debug("Client %s left room guild:%s", flask_request.sid, gid)


@socketio.on("overlay_register")
def on_overlay_register(data=None):
    """Le front s'enregistre (et s'abonne à sa guild si fournie)."""
    gid = _guild_id(_payload(data))
    emit("overlay_ack", {"status": "ok", "sid": flask_request.sid})
    if gid is not None:
        _subscribe(gid)


@socketio.on("overlay_subscribe_guild")
def on_overlay_subscribe(data=None):
    gid = _guild_id(_payload(data))
    if gid is not None:
        _subscribe(gid)


@socketio.on("overlay_unsubscribe_guild")
def on_overlay_unsubscribe(data=None):
    gid = _guild_id(_payload(data))
    if gid is not None:
        leave_room(f"guild:{gid}")
        logger.debug("Client %s unsubscribed from guild:%s", flask_request.sid, gid)


@socketio.on("overlay_ping")
def on_overlay_ping(data=None):
    """Keep-alive ping."""
    data = _payload(data)
    emit("overlay_pong", {"t": data.get("t"), "sid": flask_request.sid})


@socketio.on("time_sync")
def on_time_sync(data=None):
    """Synchro d'horloge du site (spec synchro §3) : {t0} → accusé {t0, ts}, ts = horloge murale de l'API (ms).

    Aucune donnée sensible, aucune autorisation au-delà du socket ; t0 renvoyé tel quel, même non numérique.
    """
    return {"t0": _payload(data).get("t0"), "ts": time.time() * 1000}


# ── State request ──

@socketio.on("request_state")
def on_request_state(data=None):
    """Client demande l'état courant d'une guild (même contrôle d'accès qu'un abonnement)."""
    gid = _guild_id(_payload(data))
    if gid is not None:
        _subscribe(gid)
