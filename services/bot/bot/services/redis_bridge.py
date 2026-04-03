"""Redis bridge — communication entre le Bot et l'API.

Le bot :
- Écoute `greg:commands` (commandes envoyées par l'API)
- Publie sur `greg:player:state` (state updates)
- Publie sur `greg:player:progress` (ticks de progression)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import redis.asyncio as aioredis

from greg_shared.config import settings

logger = logging.getLogger("greg.redis")

CHANNEL_COMMANDS = "greg:commands"
CHANNEL_STATE = "greg:player:state"
CHANNEL_PROGRESS = "greg:player:progress"
CHANNEL_BOT_STATUS = "greg:bot:status"


class RedisBridge:
    """Pont Redis pour la communication inter-services."""

    def __init__(self, bot):
        self.bot = bot
        self._redis: Optional[aioredis.Redis] = None
        self._redis_sub: Optional[aioredis.Redis] = None
        self._pubsub = None

    async def _get_redis(self) -> aioredis.Redis:
        """Redis pour publish/commandes (avec timeout)."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=10,
            )
        return self._redis

    async def _get_redis_sub(self) -> aioredis.Redis:
        """Redis dédié au pubsub (SANS socket_timeout pour éviter la boucle de timeout)."""
        if self._redis_sub is None:
            self._redis_sub = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=10,
                health_check_interval=30,
                # PAS de socket_timeout — pubsub doit bloquer indéfiniment
            )
        return self._redis_sub

    async def start_listening(self):
        """Écoute les commandes de l'API sur Redis."""
        while True:
            try:
                r = await self._get_redis_sub()
                self._pubsub = r.pubsub()
                await self._pubsub.subscribe(CHANNEL_COMMANDS)
                logger.info("Redis: écoute sur %s", CHANNEL_COMMANDS)

                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        await self._handle_command(data)
                    except Exception as e:
                        logger.error("Redis: erreur traitement commande: %s", e)
            except asyncio.CancelledError:
                logger.info("Redis listener cancelled")
                break
            except Exception as e:
                logger.error("Redis: connexion perdue: %s — retry dans 5s", e)
                # Reset sub connection so it reconnects fresh
                self._redis_sub = None
                self._pubsub = None
                await asyncio.sleep(5)

    async def _handle_command(self, data: Dict[str, Any]):
        """Traite une commande reçue de l'API."""
        action = data.get("action", "")
        guild_id = int(data.get("guild_id", 0))
        user_id = int(data.get("user_id", 0))
        request_id = data.get("request_id", "")
        cmd_data = data.get("data", {})

        logger.info("Redis CMD: action=%s guild=%s user=%s", action, guild_id, user_id)

        svc = self.bot.player_service
        result = {"ok": False, "error": "UNKNOWN_ACTION"}

        try:
            if action == "enqueue":
                item = cmd_data.get("item", {})
                result = await svc.enqueue(guild_id, user_id, item)

            elif action == "play_for_user":
                item = cmd_data.get("item", {})
                result = await svc.play_for_user(guild_id, user_id, item)

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
                        ok = await svc.ensure_connected(g, ch)
                        if ok and not svc.is_playing.get(guild_id, False):
                            await svc.play_next(g)
                        result = {"ok": ok}

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

        # Publier le state update
        self.bot.emit_state_update(guild_id)

    async def publish_state_update(self, guild_id: int, state: dict):
        """Publie un state update pour que l'API le relaye en WebSocket."""
        await self._publish(CHANNEL_STATE, {
            "guild_id": guild_id,
            "state": state,
        })

    async def publish_progress(self, guild_id: int, position: int, duration: Optional[int], paused: bool):
        """Publie un tick de progression."""
        await self._publish(CHANNEL_PROGRESS, {
            "guild_id": guild_id,
            "position": position,
            "duration": duration,
            "paused": paused,
        })

    async def publish_bot_ready(self):
        """Signale que le bot est prêt."""
        guilds = [{"id": str(g.id), "name": g.name} for g in self.bot.guilds]
        await self._publish(CHANNEL_BOT_STATUS, {
            "status": "ready",
            "user_id": str(self.bot.user.id) if self.bot.user else "",
            "guilds": guilds,
        })

    async def _publish(self, channel: str, data: dict):
        try:
            r = await self._get_redis()
            await r.publish(channel, json.dumps(data, default=str))
        except Exception as e:
            logger.error("Redis publish failed on %s: %s", channel, e)
