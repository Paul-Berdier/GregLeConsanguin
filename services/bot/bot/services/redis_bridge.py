"""Redis bridge — communication entre le Bot et l'API.

Le bot :
- Écoute `greg:commands` (commandes envoyées par l'API)
- Publie sur `greg:player:state` (state updates)
- Publie sur `greg:player:progress` (ticks de progression)
- Écrit `greg:bot:guilds` (liste JSON des serveurs où Greg est présent)

Robustesse (v2.2) :
- Chaque commande est traitée dans SA propre tâche : une commande lente
  (playlist, connexion vocale…) ne bloque plus l'écoute. Les commandes qui
  modifient l'état d'une même guild restent sérialisées (verrou par guild,
  ordre d'arrivée) ; get_state / get_history n'attendent jamais.
- Échéance : une commande restée en file au-delà de son `timeout` (posé par
  l'API, relatif à la réception) est abandonnée (EXPIRED) au lieu d'être exécutée
  en retard ; play_for_user reçoit le budget restant (timeout − attente − marge).
- guild_id où Greg n'est pas → GUILD_NOT_FOUND, sans créer de verrou ni d'état.
- Connexions Redis résilientes (comme l'API) : keepalive TCP, health checks,
  retry avec backoff ; l'abonné lit avec get_message(timeout) + un ping de
  surveillance, et se reconnecte (en fermant l'ancienne connexion) si Redis
  ne répond plus.

Sécurité :
- SEC-C2 — le bot fait autorité sur l'appartenance : sur une guild qu'il connaît,
  l'utilisateur doit en être membre (cache, sinon fetch_member auprès de Discord)
  avant toute commande, lectures comprises → NOT_GUILD_MEMBER / MEMBER_CHECK_FAILED.
- SEC-C3 — une commande n'est exécutée que par UNE instance du bot :
  SET greg:req:<request_id> NX EX 120 avant d'exécuter ; clé déjà posée → une autre
  instance s'en charge (aucune réponse). Redis en erreur → exécutée quand même.
- Ces vérifications tournent dans la tâche de la commande (l'écoute ne bloque
  jamais), jamais derrière le verrou de la guild, et sans changer l'ordre
  d'arrivée des commandes d'une même guild.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from typing import Any, Dict, Optional, Set

import discord
import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from greg_shared.config import settings

logger = logging.getLogger("greg.redis")

CHANNEL_COMMANDS = "greg:commands"
CHANNEL_STATE = "greg:player:state"
CHANNEL_PROGRESS = "greg:player:progress"
CHANNEL_BOT_STATUS = "greg:bot:status"
KEY_BOT_GUILDS = "greg:bot:guilds"
# SEC-C3 : réservation d'une commande par une instance (SET NX EX).
KEY_REQUEST_PREFIX = "greg:req:"
_REQUEST_CLAIM_TTL = 120
# Au-delà, Redis est jugé indisponible pour la réservation : on exécute quand même.
_CLAIM_TIMEOUT = 2.0
# SEC-C2 : délai max de fetch_member (au-delà → MEMBER_CHECK_FAILED, réessayable).
_MEMBER_CHECK_TIMEOUT = 5.0

# Commandes en lecture seule : jamais sérialisées derrière une commande lente.
_READ_ONLY_ACTIONS = frozenset({"get_state", "get_history"})

# Échéance des commandes : l'API pose `timeout` (s, relatif à la réception) = le
# temps qu'elle attend la réponse. Une commande restée en file au-delà est abandonnée
# (l'API a déjà répondu TIMEOUT : l'exécuter en retard = skip/stop surprise, double
# ajout au 2e essai). Marge : on n'exécute pas ce que l'API va déclarer expiré.
_EXPIRY_MARGIN = 0.5
# play_for_user doit répondre AVANT que l'API abandonne : budget = timeout − attente − marge.
_PLAY_RESPONSE_MARGIN = 3.0

_MSG_EXPIRED = "Greg était occupé avec une autre demande sur ce serveur : réessaie."
_MSG_GUILD_NOT_FOUND = "Greg n'est pas (ou plus) sur ce serveur."
_MSG_NOT_GUILD_MEMBER = "Tu n'es pas membre de ce serveur."
_MSG_MEMBER_CHECK_FAILED = "Vérification impossible, réessaie dans un instant."


def _command_timeout(data: Dict[str, Any]) -> Optional[float]:
    """`timeout` de la commande (s) ou None (fire-and-forget, ancienne API)."""
    try:
        t = float(data.get("timeout"))
    except (TypeError, ValueError):
        return None
    return t if t > 0 else None

# Surveillance de l'abonnement : sans aucun message depuis _WATCHDOG_PING_EVERY s,
# on envoie un PING ; sans rien reçu depuis _WATCHDOG_DEAD_AFTER s, la connexion
# est considérée morte (socket à moitié ouvert) et on se reconnecte.
_WATCHDOG_PING_EVERY = 20.0
_WATCHDOG_DEAD_AFTER = 60.0
_WATCHDOG_MESSAGE = "greg-watchdog"
_POLL_TIMEOUT = 1.0

# Backoff de reconnexion de l'abonné (1er essai quasi immédiat).
_RECONNECT_BACKOFF_MIN = 0.5
_RECONNECT_BACKOFF_MAX = 5.0


def _keepalive_options() -> Dict[int, int]:
    """Keepalive TCP agressif (les valeurs noyau par défaut = 2 h d'inactivité)."""
    opts: Dict[int, int] = {}
    for name, value in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
        if hasattr(socket, name):
            opts[getattr(socket, name)] = value
    return opts


def _retry_kwargs() -> Dict[str, Any]:
    return {
        "retry": Retry(ExponentialBackoff(cap=3, base=0.2), 3),
        "retry_on_error": [RedisConnectionError, RedisTimeoutError],
    }


class RedisBridge:
    """Pont Redis pour la communication inter-services."""

    def __init__(self, bot):
        self.bot = bot
        self._redis: Optional[aioredis.Redis] = None
        self._redis_sub: Optional[aioredis.Redis] = None
        self._pubsub = None
        # Verrou par guild pour les commandes qui modifient l'état (ordre d'arrivée).
        self._cmd_locks: Dict[int, asyncio.Lock] = {}
        # Références des tâches de commandes en cours (évite leur collecte par le GC).
        self._tasks: Set[asyncio.Task] = set()
        # Identifiant de cette instance du bot (valeur de greg:req:<request_id>, SEC-C3).
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    async def _get_redis(self) -> aioredis.Redis:
        """Redis pour publish/commandes (avec timeout, keepalive et retry)."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=10,
                socket_keepalive=True,
                socket_keepalive_options=_keepalive_options(),
                health_check_interval=30,
                **_retry_kwargs(),
            )
        return self._redis

    async def _get_redis_sub(self) -> aioredis.Redis:
        """Redis dédié au pubsub.

        Pas de socket_timeout global : la lecture se fait par get_message(timeout=…)
        (qui renvoie None sans erreur quand rien n'arrive), ce qui laisse passer
        les health checks et le ping de surveillance.
        """
        if self._redis_sub is None:
            self._redis_sub = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_keepalive=True,
                socket_keepalive_options=_keepalive_options(),
                health_check_interval=15,
                **_retry_kwargs(),
            )
        return self._redis_sub

    async def _close_sub(self) -> None:
        """Ferme l'abonnement et le client abonné (sinon fuite de sockets à chaque reconnexion)."""
        pubsub, client = self._pubsub, self._redis_sub
        self._pubsub = None
        self._redis_sub = None
        for obj in (pubsub, client):
            if obj is None:
                continue
            try:
                closer = getattr(obj, "aclose", None) or getattr(obj, "close", None)
                if closer is not None:
                    await closer()
            except Exception:
                pass

    async def start_listening(self):
        """Écoute les commandes de l'API sur Redis."""
        backoff = _RECONNECT_BACKOFF_MIN
        while True:
            try:
                r = await self._get_redis_sub()
                self._pubsub = r.pubsub(ignore_subscribe_messages=True)
                await self._pubsub.subscribe(CHANNEL_COMMANDS)
                logger.info("Redis: écoute sur %s", CHANNEL_COMMANDS)
                backoff = _RECONNECT_BACKOFF_MIN
                await self._listen_loop(self._pubsub)
            except asyncio.CancelledError:
                logger.info("Redis listener cancelled")
                await self._close_sub()
                break
            except Exception as e:
                logger.error("Redis: connexion perdue: %s — reconnexion dans %.1fs", e, backoff)
                await self._close_sub()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)

    async def _listen_loop(self, pubsub) -> None:
        loop = asyncio.get_running_loop()
        last_rx = loop.time()
        last_ping = last_rx
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=_POLL_TIMEOUT)
            now = loop.time()
            if message is not None:
                last_rx = now
                if message.get("type") == "message":
                    self._on_raw_command(message.get("data"))
                continue
            if now - last_rx > _WATCHDOG_DEAD_AFTER:
                raise RedisConnectionError(f"aucune réponse de Redis depuis {now - last_rx:.0f}s (watchdog)")
            if now - last_rx > _WATCHDOG_PING_EVERY and now - last_ping > _WATCHDOG_PING_EVERY:
                last_ping = now
                await pubsub.ping(_WATCHDOG_MESSAGE)

    def _on_raw_command(self, raw: Any) -> None:
        try:
            data = json.loads(raw)
        except Exception as e:
            logger.error("Redis: commande illisible: %s", e)
            return
        if not isinstance(data, dict):
            logger.error("Redis: commande ignorée (pas un objet JSON): %r", data)
            return
        self._dispatch(data)

    def _cmd_lock(self, gid: int) -> asyncio.Lock:
        if gid not in self._cmd_locks:
            self._cmd_locks[gid] = asyncio.Lock()
        return self._cmd_locks[gid]

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _dispatch(self, data: Dict[str, Any]) -> asyncio.Task:
        """Traite la commande dans sa propre tâche : l'écoute ne bloque jamais."""
        received = asyncio.get_running_loop().time()
        return self._spawn(self._run_command(data, received))

    async def _reply(self, data: Dict[str, Any], result: Dict[str, Any]) -> None:
        request_id = data.get("request_id", "")
        if request_id:
            await self._publish(f"greg:response:{request_id}", {"request_id": request_id, **result})

    async def _claim(self, data: Dict[str, Any]) -> bool:
        """SEC-C3 : réserve la commande pour CETTE instance (SET NX EX).

        False = une autre instance l'a déjà prise → ne rien faire (pas de réponse).
        Redis en erreur ou muet → journalisé, et la commande est exécutée (fail open).
        """
        request_id = str(data.get("request_id") or "")
        if not request_id:
            return True
        try:
            r = await self._get_redis()
            claimed = await asyncio.wait_for(
                r.set(f"{KEY_REQUEST_PREFIX}{request_id}", self.instance_id, nx=True, ex=_REQUEST_CLAIM_TTL),
                timeout=_CLAIM_TIMEOUT,
            )
        except Exception as e:
            logger.warning("Redis: réservation de la commande %s impossible (%r) — exécutée quand même.", request_id, e)
            return True
        if not claimed:
            logger.info("Redis CMD %s déjà prise par une autre instance : ignorée.", request_id)
            return False
        return True

    async def _check_member(self, guild, raw_user_id: Any) -> Optional[Dict[str, Any]]:
        """SEC-C2 : None si l'utilisateur est membre de `guild`, sinon la réponse d'erreur."""
        try:
            uid = int(raw_user_id or 0)
        except (TypeError, ValueError):
            uid = 0
        not_member = {"ok": False, "error": "NOT_GUILD_MEMBER", "message": _MSG_NOT_GUILD_MEMBER}
        if uid <= 0:
            return not_member
        try:
            if guild.get_member(uid) is not None:
                return None
            # Absent du cache (cache pas encore rempli, membre jamais vu…) : on demande à Discord.
            await asyncio.wait_for(guild.fetch_member(uid), timeout=_MEMBER_CHECK_TIMEOUT)
            return None
        except discord.NotFound:
            return not_member
        except Exception as e:
            logger.warning("Vérification d'appartenance impossible (guild=%s user=%s): %r", guild.id, uid, e)
            return {"ok": False, "error": "MEMBER_CHECK_FAILED", "message": _MSG_MEMBER_CHECK_FAILED}

    async def _admit(self, data: Dict[str, Any], guild) -> bool:
        """SEC-C3 puis SEC-C2 : True si CETTE instance doit exécuter la commande.

        Le refus d'un non-membre est répondu ici, tout de suite ; une commande prise
        par une autre instance est ignorée sans réponse. Guild inconnue (guild=None) :
        pas de vérification d'appartenance, comportement inchangé.
        """
        if not await self._claim(data):
            return False
        if guild is None:
            return True
        err = await self._check_member(guild, data.get("user_id"))
        if err is not None:
            await self._reply(data, err)
            return False
        return True

    async def _run_command(self, data: Dict[str, Any], received: Optional[float] = None) -> None:
        try:
            loop = asyncio.get_running_loop()
            if received is None:
                received = loop.time()
            action = str(data.get("action", ""))
            try:
                gid = int(data.get("guild_id") or 0)
            except (TypeError, ValueError):
                gid = 0
            guild = self.bot.get_guild(gid) if gid else None
            if action in _READ_ONLY_ACTIONS:
                # Aucun verrou : vérifications puis lecture, sans attendre personne.
                if await self._admit(data, guild):
                    await self._handle_command(data)
                return
            if guild is None:
                # Guild où Greg n'est pas : ni verrou ni état créés pour un guild_id arbitraire.
                if await self._claim(data):
                    await self._reply(data, {"ok": False, "error": "GUILD_NOT_FOUND", "message": _MSG_GUILD_NOT_FOUND})
                return
            # Vérifications lancées tout de suite, EN PARALLÈLE de l'attente du verrou : un
            # refus part sans attendre son tour, et la place dans la file est prise avant
            # tout `await` (une réponse Redis/Discord plus rapide ne double pas la précédente).
            admission = self._spawn(self._admit(data, guild))
            # Même guild → une commande à la fois, dans l'ordre d'arrivée
            # (asyncio.Lock réveille ses waiters en FIFO).
            async with self._cmd_lock(gid):
                if not await admission:
                    return
                waited = loop.time() - received
                timeout = _command_timeout(data)
                if timeout is not None and waited >= timeout - _EXPIRY_MARGIN:
                    logger.warning(
                        "Redis CMD abandonnée: action=%s guild=%s (attente %.1fs ≥ timeout API %.0fs)",
                        action, gid, waited, timeout,
                    )
                    await self._reply(data, {"ok": False, "error": "EXPIRED", "message": _MSG_EXPIRED})
                    return
                await self._handle_command(data, waited=waited)
        except Exception as e:
            logger.error("Redis: erreur traitement commande: %s", e)

    async def _handle_command(self, data: Dict[str, Any], waited: float = 0.0):
        """Traite une commande reçue de l'API (`waited` = attente de son tour, en s)."""
        action = data.get("action", "")
        request_id = data.get("request_id", "")
        cmd_data = data.get("data", {}) or {}
        guild_id = 0

        svc = self.bot.player_service
        result = {"ok": False, "error": "UNKNOWN_ACTION"}

        try:
            guild_id = int(data.get("guild_id", 0) or 0)
            user_id = int(data.get("user_id", 0) or 0)
            logger.info("Redis CMD: action=%s guild=%s user=%s", action, guild_id, user_id)

            if action == "enqueue":
                item = cmd_data.get("item", {})
                result = await svc.enqueue(guild_id, user_id, item)

            elif action == "play_for_user":
                item = cmd_data.get("item", {})
                timeout = _command_timeout(data)
                kw = {}
                if timeout is not None:
                    # Répondre avant que l'API abandonne, même après avoir attendu son tour.
                    kw["budget"] = timeout - waited - _PLAY_RESPONSE_MARGIN
                result = await svc.play_for_user(guild_id, user_id, item, **kw)

            elif action == "skip":
                await svc.skip(guild_id, requester_id=user_id)
                result = {"ok": True}

            elif action == "stop":
                await svc.stop(guild_id, requester_id=user_id)
                result = {"ok": True}

            elif action == "pause":
                ok = await svc.pause(guild_id, requester_id=user_id)
                result = {"ok": ok}

            elif action == "resume":
                ok = await svc.resume(guild_id, requester_id=user_id)
                result = {"ok": ok}

            elif action == "toggle_pause":
                g = self.bot.get_guild(guild_id)
                vc = g and g.voice_client
                if vc and vc.is_paused():
                    ok = await svc.resume(guild_id, requester_id=user_id)
                    result = {"ok": ok, "action": "resume"}
                elif vc and vc.is_playing():
                    ok = await svc.pause(guild_id, requester_id=user_id)
                    result = {"ok": ok, "action": "pause"}
                else:
                    result = {"ok": False, "error": "NOT_PLAYING"}

            elif action == "repeat":
                mode = cmd_data.get("mode", "toggle")
                val = await svc.toggle_repeat(guild_id, mode)
                result = {"ok": True, "repeat_all": val}

            elif action == "remove":
                index = int(cmd_data.get("index", -1))
                ok = svc.remove_at(guild_id, user_id, index)
                result = {"ok": ok}

            elif action == "move":
                src = int(cmd_data.get("src", -1))
                dst = int(cmd_data.get("dst", -1))
                ok = svc.move(guild_id, user_id, src, dst)
                result = {"ok": ok}

            elif action == "get_state":
                state = svc.get_state(guild_id)
                result = {"ok": True, "state": state}

            elif action == "play_at":
                index = int(cmd_data.get("index", 0))
                ok = await svc.play_at(guild_id, user_id, index)
                result = {"ok": ok}

            elif action == "restart":
                ok = await svc.restart(guild_id, requester_id=user_id)
                result = {"ok": ok}

            elif action == "get_history":
                mode = cmd_data.get("mode", "top")
                limit = int(cmd_data.get("limit", 20))
                result = svc.get_history(guild_id, mode=mode, limit=limit)

            elif action == "join":
                g = self.bot.get_guild(guild_id)
                if not g:
                    result = {"ok": False, "error": "GUILD_NOT_FOUND"}
                else:
                    m = g.get_member(user_id)
                    ch = m.voice.channel if (m and m.voice) else None
                    if not ch:
                        result = {"ok": False, "error": "USER_NOT_IN_VOICE"}
                    else:
                        # Politique C7 : on n'arrache pas Greg d'un salon où il joue pour
                        # quelqu'un (re-vérifiée après une éventuelle reconnexion Discord).
                        err = await svc.connect_for_user(g, ch)
                        if err:
                            result = err
                        else:
                            # Lecture relancée en tâche de fond (jamais attendue ici).
                            svc.ensure_playing(g)
                            result = {"ok": True}

            else:
                result = {"ok": False, "error": f"UNKNOWN_ACTION:{action}"}

        except PermissionError:
            result = {"ok": False, "error": "PRIORITY_FORBIDDEN"}
        except Exception as e:
            logger.exception("Redis CMD error: %s", e)
            result = {"ok": False, "error": str(e)}

        # Publier la réponse
        if request_id:
            await self._publish(f"greg:response:{request_id}", {
                "request_id": request_id,
                **result,
            })

        # Publier le state update (inutile pour les lectures seules)
        if guild_id and action not in _READ_ONLY_ACTIONS:
            try:
                self.bot.emit_state_update(guild_id)
            except Exception as e:
                logger.error("emit_state_update failed: %s", e)

    async def publish_state_update(self, guild_id: int, state: dict):
        """Publie un state update pour que l'API le relaye en WebSocket."""
        await self._publish(CHANNEL_STATE, {
            "guild_id": guild_id,
            "state": state,
        })

    async def publish_progress(self, guild_id: int, position: int, duration: Optional[int], paused: bool,
                               clock: Optional[dict] = None):
        """Publie un tick de progression (+ bloc `clock` de la synchro son/vidéo, si fourni)."""
        data = {
            "guild_id": guild_id,
            "position": position,
            "duration": duration,
            "paused": paused,
        }
        if clock is not None:
            data["clock"] = clock
        await self._publish(CHANNEL_PROGRESS, data)

    async def publish_bot_ready(self):
        """Signale que le bot est prêt."""
        guilds = [{"id": str(g.id), "name": g.name} for g in self.bot.guilds]
        await self._publish(CHANNEL_BOT_STATUS, {
            "status": "ready",
            "user_id": str(self.bot.user.id) if self.bot.user else "",
            "guilds": guilds,
        })

    async def publish_bot_guilds(self):
        """Écrit `greg:bot:guilds` = JSON des IDs (str) des serveurs où Greg est présent.

        Lu par l'API (/guilds → bot_present). Un échec est seulement journalisé.
        """
        try:
            ids = [str(g.id) for g in (self.bot.guilds or [])]
            r = await self._get_redis()
            await r.set(KEY_BOT_GUILDS, json.dumps(ids))
            logger.info("Redis: %s mis à jour (%d serveurs).", KEY_BOT_GUILDS, len(ids))
        except Exception as e:
            logger.error("Redis: écriture de %s impossible: %s", KEY_BOT_GUILDS, e)

    async def _publish(self, channel: str, data: dict):
        try:
            r = await self._get_redis()
            await r.publish(channel, json.dumps(data, default=str))
        except Exception as e:
            logger.error("Redis publish failed on %s: %s", channel, e)
