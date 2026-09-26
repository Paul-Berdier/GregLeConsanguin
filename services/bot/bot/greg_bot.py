"""GregBot — Classe principale du bot Discord.

Responsabilités :
- Connexion Discord + chargement des cogs
- Communication avec l'API via Redis pub/sub
- PlayerService intégré (c'est le bot qui a voice_client)
- Handler global des erreurs de slash commands (plus de « Greg réfléchit… » infini)
- Publication de la présence par serveur (`greg:bot:guilds`) pour l'API/web
"""
from __future__ import annotations

import asyncio
import logging
import os
import pkgutil

import discord
from discord import app_commands
from discord.ext import commands

from greg_shared.config import settings
from greg_shared.constants import greg_says

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
        # Greg n'utilise QUE des slash commands. On utilise `when_mentioned`
        # comme préfixe — ça évite le warning discord.py "Privileged message
        # content intent is missing" tout en gardant compatible un éventuel
        # `@Greg ping` mention-based.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=INTENTS,
            application_id=int(settings.discord_app_id),
            help_command=None,
            # Titres YouTube/SoundCloud affichés tels quels : un « @everyone » ou une
            # mention de rôle dans un titre ne doit jamais pinger le serveur.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
        )
        self.player_service: PlayerService = PlayerService(self)
        self.redis_bridge: RedisBridge = RedisBridge(self)
        self._listener_task: asyncio.Task | None = None

    async def setup_hook(self):
        """Chargement des cogs et sync des commandes."""
        # Handler global : discord.py route les erreurs de slash commands vers
        # CommandTree.on_error (qui ne fait que logguer) — sans lui, une exception
        # après defer() laisse l'utilisateur sur « réfléchit… » jusqu'à expiration.
        self.tree.error(self._on_app_command_error)

        await self._load_cogs("bot.cogs")
        await self.tree.sync()
        logger.info("Slash commands synchronisées.")

        # Démarrer le listener Redis
        self._listener_task = asyncio.create_task(self.redis_bridge.start_listening())
        logger.info("Redis bridge démarré.")

    async def _on_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        """Répond TOUJOURS quelque chose à l'utilisateur (éphémère), puis journalise."""
        cmd = getattr(getattr(interaction, "command", None), "qualified_name", "?")
        if isinstance(error, app_commands.CheckFailure):
            logger.info("Slash /%s refusée: %s", cmd, error)
            if isinstance(error, app_commands.NoPrivateMessage):
                msg = "⛔ Cette commande ne marche que sur un serveur, pas en message privé."
            else:
                msg = "⛔ T'as pas le droit de faire ça ici."
        else:
            original = getattr(error, "original", error)
            logger.error("Erreur slash /%s: %s", cmd, original,
                         exc_info=(type(original), original, original.__traceback__))
            user = getattr(getattr(interaction, "user", None), "mention", "")
            msg = greg_says("error_generic", user=user)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:  # interaction expirée / déjà répondue
            logger.debug("Réponse d'erreur impossible pour /%s: %s", cmd, e)

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
        await self.redis_bridge.publish_bot_guilds()

    async def on_guild_join(self, guild: discord.Guild):
        logger.info("Greg ajouté au serveur %s (%s)", getattr(guild, "name", "?"), guild.id)
        await self.redis_bridge.publish_bot_guilds()

    async def on_guild_remove(self, guild: discord.Guild):
        logger.info("Greg retiré du serveur %s (%s)", getattr(guild, "name", "?"), guild.id)
        await self.redis_bridge.publish_bot_guilds()

    def emit_state_update(self, guild_id: int, payload: dict = None):
        """Publie un state update sur Redis pour que l'API le relaye en WebSocket."""
        if payload is None:
            payload = self.player_service.get_state(guild_id)
        asyncio.create_task(
            self.redis_bridge.publish_state_update(guild_id, payload)
        )
