"""GregBot — Classe principale du bot Discord.

Responsabilités :
- Connexion Discord + chargement des cogs
- Communication avec l'API via Redis pub/sub
- PlayerService intégré (c'est le bot qui a voice_client)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pkgutil

import discord
from discord.ext import commands

from greg_shared.config import settings

from bot.services.player_service import PlayerService
from bot.services.redis_bridge import RedisBridge

logger = logging.getLogger("greg.bot")

INTENTS = discord.Intents.default()
INTENTS.message_content = False
INTENTS.members = True
INTENTS.presences = False
INTENTS.guilds = True
INTENTS.voice_states = True


class GregBot(commands.Bot):
    """Le bot Discord de Greg le Consanguin."""

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            application_id=int(settings.discord_app_id),
        )
        self.player_service: PlayerService = PlayerService(self)
        self.redis_bridge: RedisBridge = RedisBridge(self)

    async def setup_hook(self):
        """Chargement des cogs et sync des commandes."""
        await self._load_cogs("bot.cogs")
        await self.tree.sync()
        logger.info("Slash commands synchronisées.")

        # Démarrer le listener Redis
        asyncio.create_task(self.redis_bridge.start_listening())
        logger.info("Redis bridge démarré.")

    async def _load_cogs(self, package: str):
        """Charge tous les cogs d'un package."""
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        if not os.path.isdir(cogs_dir):
            logger.warning("Dossier cogs introuvable: %s", cogs_dir)
            return

        for _, modname, ispkg in pkgutil.iter_modules([cogs_dir]):
            if ispkg:
                continue
            ext = f"{package}.{modname}"
            try:
                await self.load_extension(ext)
                logger.info("✅ Cog chargé: %s", ext)
            except Exception as e:
                logger.error("❌ Erreur chargement %s: %s", ext, e)

    async def on_ready(self):
        logger.info("====== BOT PRÊT ======")
        logger.info("Connecté en tant que: %s (ID: %s)", self.user, self.user.id)
        logger.info("Guildes: %d", len(self.guilds))

        # Publier l'état initial sur Redis
        await self.redis_bridge.publish_bot_ready()

    def emit_state_update(self, guild_id: int, payload: dict = None):
        """Publie un state update sur Redis pour que l'API le relaye en WebSocket."""
        if payload is None:
            payload = self.player_service.get_state(guild_id)
        asyncio.create_task(
            self.redis_bridge.publish_state_update(guild_id, payload)
        )
