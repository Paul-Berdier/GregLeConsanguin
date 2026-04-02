"""Bot bridge — envoie des commandes au bot via Redis et attend la réponse."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

import redis

from greg_shared.config import settings

logger = logging.getLogger("greg.api.bridge")

CHANNEL_COMMANDS = "greg:commands"
_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=10, socket_timeout=20)
    return _redis_client


def send_command(action: str, guild_id: int, user_id: int = 0, data: dict = None, timeout: float = 15.0) -> Dict[str, Any]:
    """Envoie une commande au bot et attend la réponse.

    Returns:
        Dict avec au minimum {"ok": bool, ...}
    """
    r = _get_redis()
    request_id = str(uuid.uuid4())[:8]
    response_channel = f"greg:response:{request_id}"

    # S'abonner à la réponse AVANT d'envoyer la commande
    pubsub = r.pubsub()
    pubsub.subscribe(response_channel)

    # Envoyer la commande
    command = {
        "action": action,
        "guild_id": guild_id,
        "user_id": user_id,
        "data": data or {},
        "request_id": request_id,
    }
    r.publish(CHANNEL_COMMANDS, json.dumps(command, default=str))

    # Attendre la réponse
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                try:
                    return json.loads(msg["data"])
                except Exception:
                    pass
    finally:
        pubsub.unsubscribe(response_channel)
        pubsub.close()

    return {"ok": False, "error": "TIMEOUT"}


def send_fire_and_forget(action: str, guild_id: int, user_id: int = 0, data: dict = None):
    """Envoie une commande sans attendre de réponse."""
    try:
        r = _get_redis()
        command = {
            "action": action,
            "guild_id": guild_id,
            "user_id": user_id,
            "data": data or {},
            "request_id": "",
        }
        r.publish(CHANNEL_COMMANDS, json.dumps(command, default=str))
    except Exception as e:
        logger.error("Fire-and-forget failed: %s", e)
