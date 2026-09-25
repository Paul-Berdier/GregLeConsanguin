"""Bot bridge — envoie des commandes au bot via Redis et attend la réponse.

Robustesse connexion :
- health_check_interval : pinge une connexion inactive avant de l'utiliser
  (Railway ferme les sockets TCP idle → sinon BrokenPipeError au publish).
- socket_keepalive : keepalive TCP pour détecter/éviter les sockets morts.
- retry + retry_on_error : redis-py reconstruit et réessaie de façon
  transparente sur ConnectionError / TimeoutError.
- reset-and-retry applicatif : filet de sécurité si le pool renvoie quand
  même une connexion crevée (notamment sur le chemin pubsub).
- PUBLISH renvoie le nombre d'abonnés : 0 → le bot n'écoute pas (redémarrage,
  crash) → BOT_OFFLINE immédiat au lieu d'attendre tout le timeout.
- Chaque commande porte `timeout` (secondes, relatif à sa réception) : le temps
  que l'API attend la réponse, et la même échéance en absolu : `sent_at` (epoch)
  et `deadline` = sent_at + timeout. Le bot sérialise les commandes d'une guild ;
  au-delà de ce délai l'API a déjà répondu TIMEOUT → le bot peut abandonner la
  commande au lieu de l'exécuter en retard (ex. double skip), ou répondre plus
  tôt (EXPAND_TIMEOUT) si l'attente du verrou a mangé le budget de play_for_user.
  Les commandes fire-and-forget n'en portent pas (personne n'attend de réponse).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

import redis
from redis.backoff import ExponentialBackoff, NoBackoff
from redis.retry import Retry
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from greg_shared.config import settings

logger = logging.getLogger("greg.api.bridge")

CHANNEL_COMMANDS = "greg:commands"
# Clé écrite par le bot (JSON : liste des ids de guilds, en str) — contrat C5
BOT_GUILDS_KEY = "greg:bot:guilds"

# Messages FR renvoyés au front (champ `message`) pour les erreurs du pont lui-même
MSG_TIMEOUT = "Greg met trop de temps à répondre…"
MSG_BOT_OFFLINE = "Greg est hors ligne (redémarrage en cours ?) — réessaie dans quelques secondes."
MSG_REDIS_UNAVAILABLE = "Impossible de joindre Greg pour le moment (Redis injoignable)."

_redis_client: Optional[redis.Redis] = None
_redis_fast: redis.Redis | None = None


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


def _get_redis_fast() -> redis.Redis:
    """Client Redis à timeouts courts et SANS retry, pour les lectures annexes
    (ex. présence du bot dans /guilds) qui ne doivent jamais ralentir une route."""
    global _redis_fast
    if _redis_fast is None:
        _redis_fast = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        )
    return _redis_fast


def get_bot_guild_ids() -> set[str] | None:
    """Ids (str) des guilds où le bot est présent, lus dans `greg:bot:guilds`.

    Renvoie None si la clé est absente, illisible ou si Redis ne répond pas
    (l'appelant omet alors l'info — jamais d'échec à cause de ça).
    """
    try:
        raw = _get_redis_fast().get(BOT_GUILDS_KEY)
    except (redis.RedisError, OSError, ValueError) as e:
        logger.warning("Lecture de %s impossible: %s", BOT_GUILDS_KEY, e)
        return None
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("%s illisible (JSON invalide)", BOT_GUILDS_KEY)
        return None
    if not isinstance(data, list):
        logger.warning("%s illisible (liste attendue, reçu %s)", BOT_GUILDS_KEY, type(data).__name__)
        return None
    return {str(x) for x in data if x is not None}


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
        {"ok": False, "error": "TIMEOUT", "message": ...} si pas de réponse à temps.
        {"ok": False, "error": "BOT_OFFLINE", "message": ...} si aucun bot n'écoute.
        {"ok": False, "error": "REDIS_UNAVAILABLE", "message": ...} si Redis est injoignable.
    """
    request_id = str(uuid.uuid4())[:8]
    response_channel = f"greg:response:{request_id}"
    sent_at = time.time()
    command = {
        "action": action,
        "guild_id": guild_id,
        "user_id": user_id,
        "data": data or {},
        "request_id": request_id,
        # Durée d'attente de l'API (relative : pas de souci d'horloges décalées
        # entre conteneurs). Passé ce délai, la réponse n'est plus attendue.
        "timeout": float(timeout),
        # Même échéance en absolu (epoch, secondes) : deadline = sent_at + timeout.
        "sent_at": sent_at,
        "deadline": sent_at + float(timeout),
    }

    # ── Phase 1 : subscribe + publish (avec reset-and-retry) ──
    # On ne réessaie QUE cette phase. Si ça casse ici, la commande n'a pas
    # atteint le bot → republier est sûr (aucune double exécution).
    pubsub = None
    receivers = None
    for attempt in range(2):
        try:
            r = _get_redis()
            pubsub = r.pubsub()
            # S'abonner à la réponse AVANT d'envoyer la commande
            pubsub.subscribe(response_channel)
            receivers = r.publish(CHANNEL_COMMANDS, json.dumps(command, default=str))
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
        return {"ok": False, "error": "REDIS_UNAVAILABLE", "message": MSG_REDIS_UNAVAILABLE}

    if isinstance(receivers, int) and receivers > 1:
        logger.warning("send_command: %d abonnés à %s (plusieurs instances du bot ?) action=%s",
                       receivers, CHANNEL_COMMANDS, action)

    # ── Phase 2 : attendre la réponse ──
    # Une erreur ici ne re-publie PAS (pour éviter toute double exécution).
    deadline = time.monotonic() + timeout
    try:
        # Personne n'écoute greg:commands → inutile d'attendre la réponse.
        if receivers == 0:
            logger.warning("send_command: aucun bot abonné à %s (action=%s) → BOT_OFFLINE",
                           CHANNEL_COMMANDS, action)
            return {"ok": False, "error": "BOT_OFFLINE", "message": MSG_BOT_OFFLINE}
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
        return {"ok": False, "error": "REDIS_UNAVAILABLE", "message": MSG_REDIS_UNAVAILABLE}
    finally:
        try:
            pubsub.unsubscribe(response_channel)
            pubsub.close()
        except Exception:
            pass

    logger.warning("send_command: pas de réponse du bot en %.0fs (action=%s)", timeout, action)
    return {"ok": False, "error": "TIMEOUT", "message": MSG_TIMEOUT}


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
            n = r.publish(CHANNEL_COMMANDS, json.dumps(command, default=str))
            if n == 0:
                logger.warning("Fire-and-forget: aucun bot abonné, commande perdue action=%s", action)
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