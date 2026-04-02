"""Cog Music — commandes slash pour la musique."""
from __future__ import annotations

import os
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from greg_shared.constants import greg_says
from greg_shared.priority import get_per_user_cap

from bot.services.player_service import PlayerService


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


class Music(commands.Cog):
    """Cog musique — délègue tout au PlayerService."""

    def __init__(self, bot: commands.Bot, service: Optional[PlayerService] = None):
        self.bot = bot
        self.svc: PlayerService = service or getattr(bot, "player_service", None) or PlayerService(bot)
        if not getattr(bot, "player_service", None):
            bot.player_service = self.svc
        self._discord_lock: Dict[int, bool] = {}
        self._owner_id = os.getenv("GREG_OWNER_ID", "")

    def _is_owner(self, user: discord.abc.User) -> bool:
        try:
            return self._owner_id and str(user.id) == str(int(self._owner_id))
        except Exception:
            return False

    def _is_locked(self, gid: int) -> bool:
        return bool(self._discord_lock.get(gid, False))

    async def _deny_if_locked(self, inter: discord.Interaction) -> bool:
        gid = int(inter.guild_id) if inter.guild_id else None
        if gid and self._is_locked(gid) and not self._is_owner(inter.user):
            await inter.followup.send(greg_says("discord_lock_on", user=inter.user.mention), ephemeral=True)
            return True
        return False

    # ─── Commands ───

    @app_commands.command(name="discordlock", description="(OWNER) Lock/unlock les commandes musique Discord.")
    @app_commands.describe(mode="on/off (vide pour basculer)")
    async def discordlock(self, inter: discord.Interaction, mode: Optional[str] = None):
        await inter.response.defer(ephemeral=True)
        if not self._is_owner(inter.user):
            return await inter.followup.send("⛔ Réservé au Greg Owner.", ephemeral=True)
        gid = int(inter.guild_id) if inter.guild_id else None
        if not gid:
            return await inter.followup.send("❌ Pas de serveur.", ephemeral=True)
        cur = self._is_locked(gid)
        new = {"on": True, "true": True, "1": True, "off": False, "false": False, "0": False}.get(mode, not cur)
        self._discord_lock[gid] = new
        key = "discord_lock_on" if new else "discord_lock_off"
        await inter.followup.send(greg_says(key, user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="play", description="Joue un son (YouTube). URL ou recherche.")
    @app_commands.describe(query_or_url="Recherche (titre/artiste) ou URL YouTube/playlist/mix")
    async def play(self, inter: discord.Interaction, query_or_url: str):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return

        if _is_url(query_or_url):
            item = {"url": query_or_url}
        else:
            try:
                from greg_shared.extractors.youtube import search as yt_search
                res = yt_search(query_or_url, limit=1) if hasattr(yt_search, '__call__') else []
            except Exception:
                res = []
            if not res:
                # Fallback: passe la query directement, le PlayerService gèrera
                item = {"url": query_or_url}
            else:
                top = res[0] if isinstance(res, list) else res
                item = {
                    "url": top.get("url", query_or_url),
                    "title": top.get("title"),
                    "duration": top.get("duration"),
                    "thumb": top.get("thumbnail"),
                }

        out = await self.svc.play_for_user(inter.guild_id, inter.user.id, item)
        if not out.get("ok"):
            code = out.get("error", "ERROR")
            error_map = {
                "GUILD_NOT_FOUND": "error_guild_not_found",
                "USER_NOT_IN_VOICE": "error_not_in_voice",
                "VOICE_CONNECT_FAILED": "error_voice_connect",
            }
            key = error_map.get(code, "error_generic")
            if "Quota" in str(code):
                key = "error_quota"
                cap = get_per_user_cap()
                return await inter.followup.send(greg_says(key, user=inter.user.mention, count="?", cap=cap))
            return await inter.followup.send(greg_says(key, user=inter.user.mention))

        await inter.followup.send(greg_says("play_success", user=inter.user.mention))

    @app_commands.command(name="skip", description="Passe au morceau suivant.")
    async def skip(self, inter: discord.Interaction):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return
        try:
            await self.svc.skip(inter.guild_id, requester_id=inter.user.id)
            await inter.followup.send(greg_says("skip", user=inter.user.mention))
        except PermissionError:
            await inter.followup.send(greg_says("error_priority", user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="stop", description="Stoppe la lecture et vide la file.")
    async def stop(self, inter: discord.Interaction):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return
        try:
            await self.svc.stop(inter.guild_id, requester_id=inter.user.id)
            await inter.followup.send(greg_says("stop", user=inter.user.mention))
        except PermissionError:
            await inter.followup.send(greg_says("error_priority", user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="pause", description="Met la musique en pause.")
    async def pause(self, inter: discord.Interaction):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return
        try:
            ok = await self.svc.pause(inter.guild_id, requester_id=inter.user.id)
            await inter.followup.send(greg_says("pause", user=inter.user.mention) if ok else "❌ Rien à pauser.")
        except PermissionError:
            await inter.followup.send(greg_says("error_priority", user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="resume", description="Reprend la musique.")
    async def resume(self, inter: discord.Interaction):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return
        try:
            ok = await self.svc.resume(inter.guild_id, requester_id=inter.user.id)
            await inter.followup.send(greg_says("resume", user=inter.user.mention) if ok else "❌ Rien à reprendre.")
        except PermissionError:
            await inter.followup.send(greg_says("error_priority", user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="playlist", description="Affiche la file d'attente.")
    async def playlist(self, inter: discord.Interaction):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return
        data = self.svc.get_state(int(inter.guild_id))
        q = data.get("queue") or []
        cur = data.get("current")
        if not q and not cur:
            return await inter.followup.send(greg_says("empty_queue", user=inter.user.mention))
        lines = []
        if cur:
            lines.append(f"🎧 **En cours :** [{cur.get('title', '?')}]({cur.get('url', '')})")
        if q:
            for i, it in enumerate(q[:15]):
                lines.append(f"**{i+1}.** [{it.get('title', '?')}]({it.get('url', '')})")
            if len(q) > 15:
                lines.append(f"… et {len(q) - 15} de plus")
        await inter.followup.send("\n".join(lines))

    @app_commands.command(name="current", description="Montre le morceau en cours.")
    async def current(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        cur = self.svc.now_playing.get(int(inter.guild_id))
        if not cur:
            return await inter.followup.send("❌ Rien en cours.", ephemeral=True)
        await inter.followup.send(greg_says("current_playing", title=cur["title"], user=inter.user.mention))

    @app_commands.command(name="repeat", description="Active/désactive le repeat.")
    @app_commands.describe(mode="on/off (vide pour basculer)")
    async def repeat(self, inter: discord.Interaction, mode: Optional[str] = None):
        await inter.response.defer(ephemeral=True)
        if await self._deny_if_locked(inter):
            return
        state = await self.svc.toggle_repeat(inter.guild_id, mode)
        key = "repeat_on" if state else "repeat_off"
        await inter.followup.send(greg_says(key, user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="remove", description="Supprime un item de la file (index 1-based).")
    @app_commands.describe(index="Index dans /playlist (1, 2, 3…)")
    async def remove(self, inter: discord.Interaction, index: int):
        await inter.response.defer(ephemeral=True)
        if await self._deny_if_locked(inter):
            return
        if index <= 0:
            return await inter.followup.send("❌ Index invalide.")
        try:
            ok = self.svc.remove_at(inter.guild_id, inter.user.id, index - 1)
            await inter.followup.send("🗑️ Supprimé." if ok else "❌ Index hors limites.")
        except PermissionError:
            await inter.followup.send(greg_says("error_priority", user=inter.user.mention))

    @app_commands.command(name="move", description="Déplace un item (src→dst, 1-based).")
    @app_commands.describe(src="Index source", dst="Nouvelle position")
    async def move(self, inter: discord.Interaction, src: int, dst: int):
        await inter.response.defer(ephemeral=True)
        if await self._deny_if_locked(inter):
            return
        if src <= 0 or dst <= 0:
            return await inter.followup.send("❌ Index invalides.")
        try:
            ok = self.svc.move(inter.guild_id, inter.user.id, src - 1, dst - 1)
            await inter.followup.send("🔀 Déplacé." if ok else "❌ Impossible.")
        except PermissionError:
            await inter.followup.send(greg_says("error_priority", user=inter.user.mention))

    @app_commands.command(name="musicmode", description="Rendu audio 'musique' (EQ/limiter).")
    @app_commands.describe(mode="on/off (vide pour basculer)")
    async def musicmode(self, inter: discord.Interaction, mode: Optional[str] = None):
        await inter.response.defer(ephemeral=True)
        if await self._deny_if_locked(inter):
            return
        on = await self.svc.set_music_mode(inter.guild_id, mode)
        key = "music_mode_on" if on else "music_mode_off"
        await inter.followup.send(greg_says(key, user=inter.user.mention), ephemeral=True)


async def setup(bot):
    svc = getattr(bot, "player_service", None) or PlayerService(bot)
    bot.player_service = svc
    await bot.add_cog(Music(bot, service=svc))
