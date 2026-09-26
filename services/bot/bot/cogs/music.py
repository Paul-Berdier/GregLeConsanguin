"""Cog Music — commandes slash pour la musique."""
from __future__ import annotations

import os
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from greg_shared.constants import greg_says
from greg_shared.extractors import is_url, normalize_link
from greg_shared.priority import get_per_user_cap

from bot.services.player_service import PlayerService

# Discord refuse les messages > 2000 caractères : marge pour la ligne « … et N de plus ».
_PLAYLIST_MSG_BUDGET = 1900


def _is_url(s: str) -> bool:
    # Reconnaît aussi les liens sans schéma (www.youtube.com/…, youtu.be/…, <lien>).
    return is_url(s)


def _track_link(it: dict, max_title: int = 80) -> str:
    """Ligne « [titre](<url>) » courte : titre tronqué, crochets neutralisés, sans aperçu."""
    title = str(it.get("title") or "?").replace("[", "(").replace("]", ")")
    if len(title) > max_title:
        title = title[: max_title - 1] + "…"
    title = discord.utils.escape_markdown(title)
    url = str(it.get("url") or "")
    if url.startswith(("http://", "https://")):
        return f"[{title}](<{url}>)"
    return title


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
    @app_commands.guild_only()
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
    @app_commands.guild_only()
    @app_commands.describe(query_or_url="Recherche (titre/artiste) ou URL YouTube/playlist/mix")
    async def play(self, inter: discord.Interaction, query_or_url: str):
        await inter.response.defer()
        if await self._deny_if_locked(inter):
            return

        # Lien (même sans https://) → normalisé ; texte libre → le PlayerService
        # fait la recherche YouTube dans un thread (jamais sur la boucle asyncio)
        # et répond NO_RESULTS s'il ne trouve rien (plus de texte brut en file).
        query = (query_or_url or "").strip()
        item = {"url": normalize_link(query)} if _is_url(query) else {"url": query, "title": query}

        out = await self.svc.play_for_user(inter.guild_id, inter.user.id, item)
        if not out.get("ok"):
            code = out.get("error", "ERROR")
            error_map = {
                "GUILD_NOT_FOUND": "error_guild_not_found",
                "USER_NOT_IN_VOICE": "error_not_in_voice",
                "VOICE_CONNECT_FAILED": "error_voice_connect",
                "NO_RESULTS": "play_not_found",
            }
            if code == "QUOTA_EXCEEDED":
                cap = out.get("cap") or get_per_user_cap()
                count = out.get("count") if out.get("count") is not None else cap
                return await inter.followup.send(
                    greg_says("error_quota", user=inter.user.mention, count=count, cap=cap)
                )
            if out.get("transient") and out.get("message"):
                # Recherche lente/échouée : pas « ça existe pas », sinon personne ne réessaie.
                return await inter.followup.send(f"❌ {out['message']}")
            key = error_map.get(code)
            if key:
                return await inter.followup.send(greg_says(key, user=inter.user.mention))
            if out.get("message"):
                return await inter.followup.send(f"❌ {out['message']}")
            return await inter.followup.send(greg_says("error_generic", user=inter.user.mention))

        added = int(out.get("added") or 0)
        if out.get("playlist"):
            txt = greg_says("play_bundle", user=inter.user.mention, count=added)
        else:
            txt = greg_says("play_success", user=inter.user.mention)
            if out.get("title"):
                txt += f"\n🎵 **{discord.utils.escape_markdown(str(out['title']))[:200]}**"
        if out.get("truncated") == "quota":
            txt += f"\n⚠️ Limité par ton quota ({get_per_user_cap()} morceaux max en file)."
        elif out.get("truncated") == "limit":
            txt += f"\n⚠️ Playlist tronquée aux {added} premiers titres."
        if out.get("playlist_error") and out.get("message"):
            # Lien watch?v=…&list=… dont la playlist est illisible : seule la vidéo est ajoutée.
            txt += f"\n⚠️ {out['message']}"
        await inter.followup.send(txt)

    @app_commands.command(name="skip", description="Passe au morceau suivant.")
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
        size = 0
        if cur:
            line = f"🎧 **En cours :** {_track_link(cur)}"
            lines.append(line)
            size += len(line) + 1
        shown = 0
        for i, it in enumerate(q[:15]):
            line = f"**{i+1}.** {_track_link(it)}"
            if size + len(line) + 1 > _PLAYLIST_MSG_BUDGET:
                break
            lines.append(line)
            size += len(line) + 1
            shown += 1
        if len(q) > shown:
            lines.append(f"… et {len(q) - shown} de plus")
        await inter.followup.send("\n".join(lines))

    @app_commands.command(name="current", description="Montre le morceau en cours.")
    @app_commands.guild_only()
    async def current(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        cur = self.svc.now_playing.get(int(inter.guild_id))
        if not cur:
            return await inter.followup.send("❌ Rien en cours.", ephemeral=True)
        await inter.followup.send(greg_says("current_playing", title=cur["title"], user=inter.user.mention))

    @app_commands.command(name="repeat", description="Active/désactive le repeat.")
    @app_commands.guild_only()
    @app_commands.describe(mode="on/off (vide pour basculer)")
    async def repeat(self, inter: discord.Interaction, mode: Optional[str] = None):
        await inter.response.defer(ephemeral=True)
        if await self._deny_if_locked(inter):
            return
        state = await self.svc.toggle_repeat(inter.guild_id, mode)
        key = "repeat_on" if state else "repeat_off"
        await inter.followup.send(greg_says(key, user=inter.user.mention), ephemeral=True)

    @app_commands.command(name="remove", description="Supprime un item de la file (index 1-based).")
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
