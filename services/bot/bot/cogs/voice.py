"""Cog Voice — join/leave/auto-disconnect."""
from __future__ import annotations

import asyncio
import os
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from greg_shared.constants import greg_says

DEFAULT_AUTODC = int(os.getenv("GREG_AUTODC_TIMEOUT", "120"))


class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.autodc_tasks: Dict[int, asyncio.Task] = {}
        self.autodc_timeout: Dict[int, int] = {}

    def _get_timeout(self, gid: int) -> int:
        return self.autodc_timeout.get(gid, DEFAULT_AUTODC)

    @staticmethod
    def _humans_in(ch: Optional[discord.VoiceChannel]) -> int:
        return sum(1 for m in (ch.members if ch else []) if not m.bot)

    def _schedule_autodc(self, guild: discord.Guild):
        if not guild or not guild.voice_client or not guild.voice_client.channel:
            return
        if self.autodc_tasks.get(guild.id):
            return
        if self._humans_in(guild.voice_client.channel) > 0:
            return

        delay = self._get_timeout(guild.id)

        async def _run():
            try:
                elapsed = 0
                while elapsed < delay:
                    await asyncio.sleep(5)
                    elapsed += 5
                    if not guild.voice_client or self._humans_in(guild.voice_client.channel) > 0:
                        return
                if guild.voice_client:
                    try:
                        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
                            guild.voice_client.stop()
                    except Exception:
                        pass
                    await guild.voice_client.disconnect(force=True)
            finally:
                self.autodc_tasks.pop(guild.id, None)

        self.autodc_tasks[guild.id] = self.bot.loop.create_task(_run())

    def _cancel_autodc(self, gid: int):
        t = self.autodc_tasks.pop(gid, None)
        if t and not t.cancelled():
            t.cancel()

    @app_commands.command(name="join", description="Fait rejoindre Greg dans votre vocal.")
    async def join(self, inter: discord.Interaction):
        if not inter.user.voice or not inter.user.voice.channel:
            return await inter.response.send_message(
                greg_says("error_not_in_voice", user=inter.user.mention), ephemeral=True
            )
        ch = inter.user.voice.channel
        try:
            if inter.guild.voice_client is None:
                await ch.connect(timeout=10)
                await inter.response.send_message(greg_says("join_voice", channel=ch.name, user=inter.user.mention))
            else:
                await inter.guild.voice_client.move_to(ch)
                await inter.response.send_message(greg_says("move_voice", channel=ch.name, user=inter.user.mention))
            self._cancel_autodc(inter.guild.id)
        except asyncio.TimeoutError:
            await inter.response.send_message(greg_says("error_voice_connect", user=inter.user.mention))
        except Exception as e:
            await inter.response.send_message(greg_says("error_generic", user=inter.user.mention))

    @app_commands.command(name="leave", description="Fait quitter Greg du vocal.")
    async def leave(self, inter: discord.Interaction):
        vc = inter.guild.voice_client
        if vc:
            try:
                if vc.is_playing() or vc.is_paused():
                    vc.stop()
            except Exception:
                pass
            await vc.disconnect()
            await inter.response.send_message(greg_says("leave_voice", user=inter.user.mention))
            self._cancel_autodc(inter.guild.id)
        else:
            await inter.response.send_message(
                "❌ Je suis même pas en vocal, {user}. Vérifie tes lunettes.".format(user=inter.user.mention),
                ephemeral=True,
            )

    @app_commands.command(name="autodc", description="Affiche ou modifie le délai d'auto-déconnexion.")
    @app_commands.describe(seconds="Nouveau délai en secondes (vide pour afficher)")
    async def autodc(self, inter: discord.Interaction, seconds: Optional[int] = None):
        gid = inter.guild.id
        if seconds is None:
            cur = self._get_timeout(gid)
            return await inter.response.send_message(f"⏲️ Auto-disconnect actuel : **{cur}s**")
        if seconds < 10:
            return await inter.response.send_message("⚠️ Minimum 10 secondes.")
        self.autodc_timeout[gid] = seconds
        self._cancel_autodc(gid)
        await inter.response.send_message(f"✅ Auto-disconnect défini à **{seconds}s**.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        guild = member.guild
        vc = guild.voice_client
        if not vc or not vc.channel:
            return
        ch = vc.channel
        if after.channel and after.channel.id == ch.id and not member.bot:
            self._cancel_autodc(guild.id)
            return
        if before.channel and before.channel.id == ch.id and not member.bot:
            if self._humans_in(ch) == 0:
                self._schedule_autodc(guild)


async def setup(bot):
    await bot.add_cog(Voice(bot))
