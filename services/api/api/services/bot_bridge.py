"""Bot bridge — envoie des commandes au bot via Redis et attend la réponse.

Robustesse connexion :
- health_check_interval : pinge une connexion inactive avant de l'utiliser
  (Railway ferme les sockets TCP idle → sinon BrokenPipeError au publish).
- socket_keepalive : keepalive TCP pour détecter/éviter les sockets morts.
- retry + retry_on_error : redis-py reconstruit et réessaie de façon
  transparente sur ConnectionError / TimeoutError.
- reset-and-retry applicatif : filet de sécurité si le pool renvoie quand
  même une connexion crevée (notamment sur le chemin pubsub).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from greg_shared.config import settings

logger = logging.getLogger("greg.api.bridge")

CHANNEL_COMMANDS = "greg:commands"
_redis_client: Optional[redis.Redis] = None


def _build_client() -> redis.Redis:
    """Construit un client Redis résilient aux connexions idle coupées."""
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=20,
        socket_keepalive=True,          # keepalive TCP
        health_check_interval=30,       # ping avant usage si idle > 30s
        retry=Retry(ExponentialBackoff(cap=3, base=0.2), retries=3),
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
    )


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = _build_client()
    return _redis_client


def _reset_redis() -> None:
    """Ferme et jette le client caché : le prochain _get_redis() en recrée un."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception:
            pass
    _redis_client = None


def send_command(
    action: str,
    guild_id: int,
    user_id: int = 0,
    data: dict = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """Envoie une commande au bot et attend la réponse.

    Returns:
        Dict avec au minimum {"ok": bool, ...}.
        {"ok": False, "error": "TIMEOUT"} si pas de réponse à temps.
        {"ok": False, "error": "REDIS_UNAVAILABLE"} si Redis est injoignable.
    """
    request_id = str(uuid.uuid4())[:8]
    response_channel = f"greg:response:{request_id}"
    command = {
        "action": action,
        "guild_id": guild_id,
        "user_id": user_id,
        "data": data or {},
        "request_id": request_id,
    }

    # ── Phase 1 : subscribe + publish (avec reset-and-retry) ──
    # On ne réessaie QUE cette phase. Si ça casse ici, la commande n'a pas
    # atteint le bot → republier est sûr (aucune double exécution).
    pubsub = None
    for attempt in range(2):
        try:
            r = _get_redis()
            pubsub = r.pubsub()
            # S'abonner à la réponse AVANT d'envoyer la commande
            pubsub.subscribe(response_channel)
            r.publish(CHANNEL_COMMANDS, json.dumps(command, default=str))
            break
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Redis publish échoué (essai %d/2) action=%s: %s — reset client",
                attempt + 1, action, e,
            )
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass
                pubsub = None
            _reset_redis()
    else:
        logger.error("send_command: publish définitivement échoué action=%s", action)
        return {"ok": False, "error": "REDIS_UNAVAILABLE"}

    # ── Phase 2 : attendre la réponse ──
    # Une erreur ici ne re-publie PAS (pour éviter toute double exécution).
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                try:
                    return json.loads(msg["data"])
                except Exception:
                    pass
    except (RedisConnectionError, RedisTimeoutError) as e:
        logger.warning("Redis coupé pendant l'attente de réponse: %s", e)
        _reset_redis()
        return {"ok": False, "error": "REDIS_UNAVAILABLE"}
    finally:
        try:
            pubsub.unsubscribe(response_channel)
            pubsub.close()
        except Exception:
            pass

    return {"ok": False, "error": "TIMEOUT"}


def send_fire_and_forget(
    action: str,
    guild_id: int,
    user_id: int = 0,
    data: dict = None,
) -> None:
    """Envoie une commande sans attendre de réponse (avec reset-and-retry)."""
    command = {
        "action": action,
        "guild_id": guild_id,
        "user_id": user_id,
        "data": data or {},
        "request_id": "",
    }
    for attempt in range(2):
        try:
            r = _get_redis()
            r.publish(CHANNEL_COMMANDS, json.dumps(command, default=str))
            return
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Fire-and-forget échoué (essai %d/2) action=%s: %s — reset client",
                attempt + 1, action, e,
            )
            _reset_redis()
        except Exception as e:
            logger.error("Fire-and-forget failed: %s", e)
            return
    logger.error("Fire-and-forget définitivement échoué action=%s", action)