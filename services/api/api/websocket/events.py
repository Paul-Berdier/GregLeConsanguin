"""WebSocket events — Socket.IO handlers du front Next.js.

Les noms `overlay_*` sont historiques : le front web les utilise toujours pour
s'abonner aux mises à jour d'une guild et pour le keep-alive.

Sécurité (SEC-C4) : une room `guild:<id>` ne se rejoint qu'avec une identité
(session Discord, ou jeton de l'appli encore valide) ET un accès confirmé par le
bot (membre du serveur) ; sinon le client reçoit `guild_join_error`
{guild_id, error, message, retry}.

Appli Overwolf (spec 2026-11-25 §3.5) : le jeton porteur voyage dans `auth.token`
du paquet CONNECT, jamais dans une URL. Ses sockets sont notés dans un registre
`{tid: sids}` : la révocation du jeton les déconnecte (`disconnect_token`).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from flask import request as flask_request
from flask import session
from flask_socketio import ConnectionRefusedError, emit, join_room, leave_room

from api import socketio
from api.services import bot_bridge
from api.services import overlay_tokens as ot
from api.services.authz import MSG_NOT_AUTHENTICATED, ROOM_AUTHENTICATED, current_identity, session_user_id
from api.services.relay_clock import now_ms, with_relay_at

logger = logging.getLogger("greg.api.ws")

_GUILD_ID_RE = re.compile(r"^[0-9]{1,20}$")

# Échecs passagers : le front réessaie de s'abonner un peu plus tard.
_RETRYABLE = frozenset({"TIMEOUT", "BOT_OFFLINE", "REDIS_UNAVAILABLE", "MEMBER_CHECK_FAILED"})
_MSG_JOIN_FAILED = "Impossible de suivre ce serveur pour l'instant."
_MSG_BRIDGE_ERROR = "Greg est injoignable pour le moment, nouvelle tentative bientôt."

# Registre des sockets ouverts avec un jeton de l'appli (tid → sids, et l'inverse). Verrou non réentrant : rien de
# ce qui s'exécute sous lui ne le reprend (voir disconnect_token).
_REGISTRY_LOCK = threading.Lock()
_TOKEN_SIDS: dict[str, set[str]] = {}
_SID_TOKEN: dict[str, str] = {}


def register_token_sid(tid: str, sid: str) -> None:
    """Note le socket `sid`, ouvert avec le jeton `tid`."""
    with _REGISTRY_LOCK:
        _TOKEN_SIDS.setdefault(tid, set()).add(sid)
        _SID_TOKEN[sid] = tid


def forget_sid(sid: str) -> None:
    """Retire le socket `sid` du registre (déconnexion) ; un sid absent n'est pas une erreur."""
    with _REGISTRY_LOCK:
        tid = _SID_TOKEN.pop(sid, None)
        if tid is None:
            return
        sids = _TOKEN_SIDS.get(tid)
        if sids is not None:
            sids.discard(sid)
            if not sids:
                del _TOKEN_SIDS[tid]


def disconnect_token(tid: str) -> int:
    """Déconnecte les sockets ouverts avec le jeton `tid` (révoqué) ; rend leur nombre.

    L'entrée du registre est retirée sous le verrou, puis les sockets sont déconnectés hors de lui, sur cette copie :
    en mode threading, `socketio.server.disconnect` exécute on_disconnect (donc forget_sid) sur le fil appelant, ce
    qui interbloquerait sous le verrou ; et parcourir l'ensemble vivant pendant que forget_sid le modifie lèverait
    RuntimeError.
    """
    with _REGISTRY_LOCK:
        sids = _TOKEN_SIDS.pop(tid, set())
        for sid in sids:
            _SID_TOKEN.pop(sid, None)
    for sid in sids:
        socketio.server.disconnect(sid, namespace="/")
    return len(sids)


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
    """Rejoint `guild:<gid>` si l'identité du socket y a accès, et envoie l'état.

    Socket à jeton : le jeton est revérifié avant tout appel au bot (une révocation sans déconnexion, ou un jeton
    échu, ne rejoint plus rien) ; Redis injoignable → refus passager REDIS_UNAVAILABLE.
    """
    ident = current_identity()
    if ident is None:
        _deny(gid, "NOT_AUTHENTICATED", MSG_NOT_AUTHENTICATED, False)
        return False
    if ident.via == "overlay":
        try:
            live = ident.tid is not None and ot.is_live(ident.uid, ident.tid)
        except ot.OverlayError:
            _deny(gid, "REDIS_UNAVAILABLE", _MSG_BRIDGE_ERROR, True)
            return False
        if not live:
            _deny(gid, "NOT_AUTHENTICATED", MSG_NOT_AUTHENTICATED, False)
            return False
    try:
        res = bot_bridge.send_command("get_state", gid, ident.uid, timeout=5)
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

def _connect_with_token(token: object) -> None:
    """Connexion de l'appli : jeton non textuel ou invalide → NOT_AUTHENTICATED, sans repli sur le cookie ; Redis
    injoignable → STORAGE_UNAVAILABLE, jamais NOT_AUTHENTICATED (l'appli effacerait son jeton).

    L'identité va dans la copie de session propre à ce socket (Flask-SocketIO ne la réécrit jamais dans un cookie).
    """
    try:
        rec = ot.resolve(token) if isinstance(token, str) else None
    except ot.OverlayError:
        raise ConnectionRefusedError("STORAGE_UNAVAILABLE") from None
    if rec is None:
        raise ConnectionRefusedError("NOT_AUTHENTICATED")
    session["_ident"] = {"via": "overlay", "uid": rec.uid, "tid": rec.tid}
    register_token_sid(rec.tid, flask_request.sid)
    join_room(ROOM_AUTHENTICATED)


@socketio.on("connect")
def on_connect(auth=None):
    """`auth` : données du paquet CONNECT ; avec une clé `token`, le socket est celui de l'appli, sinon la session."""
    if isinstance(auth, dict) and "token" in auth:
        _connect_with_token(auth["token"])
    elif session_user_id() is not None:
        # Room des sockets connectés à Discord (bot_status : liste des serveurs du bot).
        join_room(ROOM_AUTHENTICATED)
    logger.debug("Client connected: sid=%s", flask_request.sid)


@socketio.on("disconnect")
def on_disconnect():
    forget_sid(flask_request.sid)
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
