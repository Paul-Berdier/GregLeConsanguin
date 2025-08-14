# commands/voice.py
#
# Cog "Voice" — uniquement des SLASH COMMANDS
# - /join : rejoindre le vocal de l'utilisateur
# - /leave : quitter le vocal
# - /restart : redémarrer le bot
# - /autodc [seconds?] : afficher/modifier le délai d'auto-déconnexion
# - Auto-disconnect : si Greg reste seul dans le canal, il quitte après un délai
#
# Notes:
# - Délai par défaut configurable via env: GREG_AUTODC_TIMEOUT (seconds, ex. 120)
# - Annule le timer si un humain rejoint le canal
# - Émet un event emit_fn("vocal_event", {...}) si fourni par main.py

import discord
from discord.ext import commands
from discord import app_commands
import sys
import os
import asyncio
from typing import Optional, Dict

DEFAULT_AUTODC = int(os.getenv("GREG_AUTODC_TIMEOUT", "120"))  # secondes


class Voice(commands.Cog):
    def __init__(self, bot, emit_fn=None):
        self.bot = bot
        self.emit_fn = emit_fn  # Pour informer l'overlay/web (optionnel)

        # timers d'auto-déconnexion par guild
        self.autodc_tasks: Dict[int, asyncio.Task] = {}
        # délais par guild (modifiable via /autodc)
        self.autodc_timeout: Dict[int, int] = {}

    # -------- utilitaires --------

    def _get_timeout(self, guild_id: int) -> int:
        return self.autodc_timeout.get(guild_id, DEFAULT_AUTODC)

    @staticmethod
    def _humans_in_channel(channel: Optional[discord.VoiceChannel]) -> int:
        if not channel:
            return 0
        return sum(1 for m in channel.members if not m.bot)

    def _schedule_autodc(self, guild: discord.Guild):
        """Programme un départ si Greg est seul dans son vocal."""
        if not guild or not guild.voice_client:
            return

        vc = guild.voice_client
        if not vc.channel:
            return

        # si un timer existe déjà, ne pas dupliquer
        if self.autodc_tasks.get(guild.id):
            return

        # s'assure qu'il n'y a bien que Greg (ou des bots)
        if self._humans_in_channel(vc.channel) > 0:
            return

        delay = self._get_timeout(guild.id)
        async def _run():
            try:
                # petite boucle pour réévaluer régulièrement (si qlq'un revient, on sort)
                elapsed = 0
                while elapsed < delay:
                    await asyncio.sleep(5)
                    elapsed += 5
                    # si plus seul → on annule
                    if not guild.voice_client or self._humans_in_channel(guild.voice_client.channel) > 0:
                        return
                # toujours seul → on part
                if guild.voice_client:
                    try:
                        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
                            guild.voice_client.stop()
                    except Exception:
                        pass
                    await guild.voice_client.disconnect(force=True)
                    if self.emit_fn:
                        self.emit_fn("vocal_event", {"guild_id": guild.id, "action": "auto_leave"})
            finally:
                # nettoyage
                self.autodc_tasks.pop(guild.id, None)

        self.autodc_tasks[guild.id] = self.bot.loop.create_task(_run())

    def _cancel_autodc(self, guild_id: int):
        task = self.autodc_tasks.pop(guild_id, None)
        if task and not task.cancelled():
            task.cancel()

    # -------- slash commands --------

    @app_commands.command(name="join", description="Fait rejoindre Greg dans votre salon vocal misérable.")
    async def join(self, interaction: discord.Interaction):
        """Slash command pour rejoindre le vocal."""
        print(f"[Voice] /join par {interaction.user.display_name} sur {interaction.guild.name}")
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "❌ *Par tous les Saints ! Vous osez me convoquer alors que vous n’êtes même pas en vocal ? Quelle audace !*",
                ephemeral=True
            )

        channel = interaction.user.voice.channel
        try:
            if interaction.guild.voice_client is None:
                await channel.connect(timeout=10)
                await interaction.response.send_message(
                    f"👑 *Greg le Consanguin daigne honorer **{channel.name}** de sa présence...*"
                )
            else:
                await interaction.guild.voice_client.move_to(channel)
                await interaction.response.send_message(
                    f"👑 *Majesté, Greg change de taudis pour **{channel.name}**.*"
                )

            # quelqu’un est là → on annule un éventuel timer
            self._cancel_autodc(interaction.guild.id)

            if self.emit_fn:
                self.emit_fn("vocal_event", {
                    "guild_id": interaction.guild.id,
                    "action": "join",
                    "channel": channel.name
                })
        except asyncio.TimeoutError:
            await interaction.response.send_message(
                "⏱️ *Greg a tenté de se connecter, mais le Royaume du Vocal est en grève…*"
            )
        except Exception as e:
            print(f"[Voice][ERROR] Exception join: {e}")
            await interaction.response.send_message(
                f"❌ *Un obstacle infernal m'empêche de rejoindre le vocal…* `{e}`"
            )

    @app_commands.command(name="leave", description="Fait quitter Greg du vocal, enfin libéré de vous.")
    async def leave(self, interaction: discord.Interaction):
        print(f"[Voice] /leave par {interaction.user.display_name} sur {interaction.guild.name}")
        vc = interaction.guild.voice_client
        if vc:
            # Stoppe proprement la lecture avant de quitter
            try:
                if vc.is_playing() or vc.is_paused():
                    vc.stop()  # tue le player FFmpeg immédiatement
            except Exception:
                pass
            await vc.disconnect()
            await interaction.response.send_message("👋 *Greg s’en va... Enfin un instant de répit.*")
            self._cancel_autodc(interaction.guild.id)
            if self.emit_fn:
                self.emit_fn("vocal_event", {"guild_id": interaction.guild.id, "action": "leave"})
        else:
            await interaction.response.send_message(
                "❌ *Ah, quelle ironie… Vous exigez mon départ alors que je ne suis même pas là !*",
                ephemeral=True
            )

    @app_commands.command(name="restart", description="Redémarre Greg le Consanguin.")
    async def restart(self, interaction: discord.Interaction):
        """Slash command pour redémarrer le bot."""
        print(f"[Voice] /restart par {interaction.user.display_name} sur {interaction.guild.name}")
        await interaction.response.send_message(
            "🔁 *Greg... Greg meurt... pour mieux revenir hanter vos canaux vocaux...*"
        )
        await self.bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    @app_commands.describe(seconds="Nouveau délai en secondes (laisser vide pour afficher)")
    @app_commands.command(name="autodc", description="Affiche ou modifie le délai d'auto-déconnexion quand Greg est seul.")
    async def autodc(self, interaction: discord.Interaction, seconds: Optional[int] = None):
        gid = interaction.guild.id
        if seconds is None:
            cur = self._get_timeout(gid)
            return await interaction.response.send_message(
                f"⏲️ *Auto-disconnect actuel :* **{cur} s** (env `GREG_AUTODC_TIMEOUT` ou override serveur)."
            )
        if seconds < 10:
            return await interaction.response.send_message("⚠️ Minimum 10 secondes, restons réalistes.")
        self.autodc_timeout[gid] = seconds
        self._cancel_autodc(gid)  # on repartira proprement si besoin
        await interaction.response.send_message(f"✅ *Auto-disconnect défini à* **{seconds} s** *pour ce serveur.*")

    # -------- listeners (détection départ/arrivée) --------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        Sur chaque mouvement vocal, on vérifie si Greg reste seul :
        - Si oui → on programme une auto-déconnexion avec délai
        - Si quelqu’un revient dans le canal de Greg → on annule le timer
        """
        guild = member.guild
        vc = guild.voice_client
        if not vc or not vc.channel:
            return

        channel = vc.channel

        # si un humain rejoint le canal de Greg → annule timer
        if after.channel and after.channel.id == channel.id and not member.bot:
            self._cancel_autodc(guild.id)
            return

        # si un humain quitte/déplace depuis le canal de Greg → peut-être seul ?
        if before.channel and before.channel.id == channel.id and not member.bot:
            if self._humans_in_channel(channel) == 0:
                # Greg seul → programme auto-deco
                self._schedule_autodc(guild)

    # -------- API interne (si tu veux déclencher depuis le player) --------

    async def notify_possible_autodc(self, guild: discord.Guild):
        """
        À appeler depuis un autre Cog (ex: Music) quand la lecture se termine
        pour déclencher un départ si plus personne n'est là.
        """
        if not guild.voice_client or not guild.voice_client.channel:
            return
        if self._humans_in_channel(guild.voice_client.channel) == 0:
            self._schedule_autodc(guild)


async def setup(bot, emit_fn=None):
    await bot.add_cog(Voice(bot, emit_fn))
    print("✅ Cog 'Voice' chargé avec auto-disconnect quand Greg est seul.")
