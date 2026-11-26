"""Redis listener — reçoit les state updates du bot et les relaye en WebSocket.

Utilise get_message() en polling au lieu de listen() (pas de socket_timeout,
reconnexion simple). Tourne dans un thread OS natif : les socketio.emit sont
sûrs car l'API est en async_mode="threading".
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

import redis

from greg_shared.config import settings

from api.services.authz import ROOM_AUTHENTICATED
from api.services.relay_clock import now_ms, with_relay_at

logger = logging.getLogger("greg.api.redis")

CHANNEL_STATE = "greg:player:state"
CHANNEL_PROGRESS = "greg:player:progress"
CHANNEL_BOT_STATUS = "greg:bot:status"
CHANNEL_PLAYER_EVENT = "greg:player:event"
CHANNELS = (CHANNEL_STATE, CHANNEL_PROGRESS, CHANNEL_BOT_STATUS, CHANNEL_PLAYER_EVENT)

# Activité relayée en `player_event` (spec §3.6) : les actions que le bot publie, rien d'autre.
PLAYER_EVENT_ACTIONS = frozenset({"add", "skip", "stop", "pause", "resume", "remove", "move", "play_at", "repeat", "restart"})


def start_redis_listener(socketio):
    """Écoute les channels Redis et relaye en Socket.IO."""
    while True:
        try:
            r = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_keepalive=True,        # keepalive TCP (idle sockets)
                health_check_interval=30,     # ping si la connexion stagne
                # PAS de socket_timeout ici — on gère le polling nous-mêmes
            )
            pubsub = r.pubsub()
            pubsub.subscribe(*CHANNELS)
            logger.info("Redis listener connected, listening on %s", list(CHANNELS))

            # Polling loop au lieu de listen() bloquant
            while True:
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    continue
                if msg["type"] != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    channel = msg["channel"]
                    _handle_message(socketio, channel, data)
                except Exception as e:
                    logger.error("Error handling Redis message: %s", e)

        except redis.ConnectionError as e:
            logger.warning("Redis connection lost: %s — retrying in 3s", e)
            time.sleep(3)
        except Exception as e:
            logger.error("Redis listener error: %s — retrying in 5s", e)
            time.sleep(5)


def _id_str(v) -> str:
    """Id Discord en chaîne décimale exacte (texte ou entier), "" sinon."""
    return "" if isinstance(v, bool) or not isinstance(v, (str, int)) else str(v).strip()


def _player_event(data: dict) -> Optional[dict]:
    """Activité d'un membre réduite à `{guild_id, action, actor: {id, display_name}, title, at_ms}`.

    Ids en chaînes (au-delà de 2^53, un nombre JSON serait arrondi côté JS). Action inconnue,
    `guild_id` vide ou `actor` illisible → None (rien n'est relayé).
    """
    gid = _id_str(data.get("guild_id"))
    action = data.get("action")
    actor = data.get("actor")
    if not gid or not isinstance(action, str) or action not in PLAYER_EVENT_ACTIONS or not isinstance(actor, dict):
        return None
    actor_id = _id_str(actor.get("id"))
    if not actor_id:
        return None
    name = actor.get("display_name")
    title = data.get("title")
    at_ms = data.get("at_ms")
    return {
        "guild_id": gid,
        "action": action,
        "actor": {"id": actor_id, "display_name": name if isinstance(name, str) and name else actor_id},
        "title": title if isinstance(title, str) else None,
        "at_ms": at_ms if isinstance(at_ms, int) and not isinstance(at_ms, bool) else now_ms(),
    }


def _handle_message(socketio, channel: str, data: dict):
    guild_id = str(data.get("guild_id", ""))
    room = f"guild:{guild_id}" if guild_id else None
    relay_at_ms = now_ms()  # réception : le site se cale sur l'horloge de l'API (synchro son/vidéo)

    if channel == CHANNEL_STATE:
        state = data.get("state", data)
        if isinstance(state, dict):
            state = with_relay_at(state, relay_at_ms)
        # Jamais de diffusion globale : seuls les membres (room guild:<id>) reçoivent l'état.
        if room:
            socketio.emit("playlist_update", state, room=room)

    elif channel == CHANNEL_PROGRESS:
        payload = {
            "only_elapsed": True,
            "paused": data.get("paused", False),
            "is_paused": data.get("paused", False),
            "position": data.get("position", 0),
            "duration": data.get("duration"),
            "progress": {
                "elapsed": data.get("position", 0),
                "duration": data.get("duration"),
            },
            "relay_at_ms": relay_at_ms,
            "guild_id": guild_id,  # l'appli écarte les ticks d'un autre serveur pendant un changement
        }
        if isinstance(data.get("clock"), dict):
            payload["clock"] = data["clock"]  # position réellement lue par le bot, horodatée
        if room:
            socketio.emit("playlist_update", payload, room=room)

    elif channel == CHANNEL_PLAYER_EVENT:
        event = _player_event(data)
        if event:
            socketio.emit("player_event", event, room=f"guild:{event['guild_id']}")

    elif channel == CHANNEL_BOT_STATUS:
        # Contient la liste des serveurs du bot : réservé aux sockets connectés à Discord.
        socketio.emit("bot_status", data, room=ROOM_AUTHENTICATED)