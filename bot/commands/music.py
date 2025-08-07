"""Music cog for Greg refonte.

This cog implements slash commands and helper methods to manage music
playback.  It supports playing tracks from SoundCloud and YouTube via
the extractors defined in :mod:`greg_refonte.extractors`.  It also exposes
methods for the web panel to control playback without requiring a
Discord interaction context.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from greg_refonte.bot.playlist_manager import PlaylistManager
from greg_refonte.extractors import get_extractor, get_search_module


class Music(commands.Cog):
    """Discord cog to manage music playback on a per‑guild basis."""

    def __init__(self, bot: commands.Bot, emit_fn: Optional[callable] = None) -> None:
        self.bot = bot
        self.emit_fn = emit_fn
        # One playlist manager per guild ID
        self.managers: Dict[str, PlaylistManager] = {}
        # Flags and state per guild
        self.is_playing: Dict[str, bool] = {}
        self.current_song: Dict[str, Dict[str, Any]] = {}
        self.search_results: Dict[int, list] = {}
        self.ffmpeg_path = self.detect_ffmpeg()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def get_pm(self, guild_id: str | int) -> PlaylistManager:
        """Return the :class:`PlaylistManager` for this guild, creating it if necessary."""
        gid = str(guild_id)
        if gid not in self.managers:
            self.managers[gid] = PlaylistManager(gid)
        return self.managers[gid]

    def emit_playlist_update(self, guild_id: str | int) -> None:
        """Emit a ``playlist_update`` event via the provided emit function (if any)."""
        if self.emit_fn:
            pm = self.get_pm(guild_id)
            self.emit_fn("playlist_update", pm.to_dict())

    def detect_ffmpeg(self) -> str:
        """Locate the FFmpeg binary.

        Returns a path string that can be passed to :class:`discord.FFmpegPCMAudio`.
        """
        candidates = [
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/bin/ffmpeg",
            "ffmpeg",
            r"D:\\Paul Berdier\\ffmpeg\\bin\\ffmpeg.exe",
        ]
        for path in candidates:
            if os.path.exists(path) and os.access(path, os.X_OK):
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé.")
        return "ffmpeg"

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------
    @app_commands.command(name="play", description="Joue un son depuis une URL ou une recherche.")
    async def play(self, interaction: discord.Interaction, query_or_url: str) -> None:
        """Slash command to search or play a track by URL.

        This method handles both direct URLs and free‑form search terms.  For
        search terms the user is prompted to pick from the top results on
        SoundCloud.  The selected track is added to the playlist and played
        immediately if nothing is currently playing.
        """
        print("[DEBUG][MUSIC] /play appelé par", interaction.user, "avec:", query_or_url)
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        # Reload playlist in case it was modified by the web panel or another process
        await loop.run_in_executor(None, pm.reload)
        # Defer the initial response to avoid the 3 s acknowledgement timeout
        await interaction.response.defer()

        # Ensure the bot is in a voice channel
        if interaction.guild.voice_client is None:
            if interaction.user.voice and interaction.user.voice.channel:
                await interaction.user.voice.channel.connect()
                await interaction.followup.send(
                    f"🎤 *Greg rejoint le canal vocal :* {interaction.user.voice.channel.name}"
                )
            else:
                await interaction.followup.send("❌ *Tu n'es même pas en vocal, vermine...*")
                return

        await interaction.followup.send("🎵 *Encore une demande musicale, Majesté ? Quel supplice...*")

        # Direct link: add to queue immediately
        if "http://" in query_or_url or "https://" in query_or_url:
            await self.add_to_queue(interaction, {"title": query_or_url, "url": query_or_url})
            return

        # Otherwise search SoundCloud
        extractor = get_search_module("soundcloud")
        try:
            results = await loop.run_in_executor(None, extractor.search, query_or_url)
            print(f"[DEBUG] Résultats de recherche SoundCloud pour '{query_or_url}': {results}")
        except Exception as e:
            await interaction.followup.send(f"❌ *Erreur lors de la recherche :* `{e}`")
            return
        if not results:
            await interaction.followup.send("❌ *Rien trouvé, même les rats ont fui cette piste...*")
            return

        # Save search results for this user so we can look them up later
        self.search_results[interaction.user.id] = results
        msg = "**🔍 Résultats Soundcloud :**\n"
        for i, item in enumerate(results[:3], 1):
            msg += f"**{i}.** [{item['title']}]({item['webpage_url']})\n"
        msg += "\n*Choisissez un chiffre (1-3) en réponse.*"
        await interaction.followup.send(msg)

        def check(m: discord.Message) -> bool:
            return m.author.id == interaction.user.id and m.content.isdigit() and 1 <= int(m.content) <= len(results[:3])

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30.0)
            idx = int(reply.content) - 1
            selected = results[idx]
            await self.add_to_queue(
                interaction,
                {
                    "title": selected.get("title", "Titre inconnu"),
                    "url": selected.get("webpage_url") or selected.get("url"),
                },
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ *Trop lent. Greg retourne râler dans sa crypte...*")

    async def add_to_queue(self, interaction: discord.Interaction, item: Dict[str, Any]) -> None:
        """Add a track to the playlist and start playback if nothing is playing."""
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.add, item)
        await interaction.followup.send(f"🎵 Ajouté à la playlist : {item['title']} ({item['url']})")
        self.emit_playlist_update(interaction.guild.id)
        # If nothing is currently playing on this guild start playback
        if not self.is_playing.get(str(interaction.guild.id), False):
            await self.play_next(interaction)

    async def play_next(self, interaction: discord.Interaction) -> None:
        """Play the next song in the queue for this guild."""
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not queue:
            self.is_playing[str(interaction.guild.id)] = False
            await interaction.followup.send("📍 *Plus rien à jouer. Enfin une pause pour Greg...*")
            self.emit_playlist_update(interaction.guild.id)
            return
        self.is_playing[str(interaction.guild.id)] = True
        item = queue.pop(0)
        pm.queue = queue  # update internal queue
        await loop.run_in_executor(None, pm.save)
        extractor = get_extractor(item['url'])
        if extractor is None:
            await interaction.followup.send("❌ *Aucun extracteur trouvé. Quelle misère...*")
            return
        vc = interaction.guild.voice_client
        if hasattr(extractor, "stream"):
            try:
                source, title = await extractor.stream(item['url'], self.ffmpeg_path)
                self.current_song[interaction.guild.id] = {"title": title, "url": item['url']}
                if vc.is_playing():
                    vc.stop()
                # When playback finishes schedule the next track on the bot loop
                vc.play(
                    source,
                    after=lambda e: self.bot.loop.create_task(self.play_next(interaction)),
                )
                await interaction.followup.send(f"▶️ *Streaming direct :* **{title}**")
                self.emit_playlist_update(interaction.guild.id)
                return
            except Exception as e:
                await interaction.followup.send(f"⚠️ *Échec du stream, je tente le téléchargement...* `{e}`")
        # Fallback to download
        try:
            filename, title, duration = await extractor.download(
                item['url'], ffmpeg_path=self.ffmpeg_path
            )
            self.current_song[interaction.guild.id] = {"title": title, "url": item['url']}
            vc.play(
                discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),
                after=lambda e: self.bot.loop.create_task(self.play_next(interaction)),
            )
            await interaction.followup.send(
                f"🎶 *Téléchargé et joué :* **{title}** (`{duration}` sec)"
            )
            self.emit_playlist_update(interaction.guild.id)
        except Exception as e:
            await interaction.followup.send(f"❌ *Même le téléchargement échoue, Majesté...* `{e}`")

    @app_commands.command(name="skip", description="Passe à la piste suivante.")
    async def skip(self, interaction: discord.Interaction) -> None:
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.skip)
        await interaction.response.send_message("⏭ *Et que ça saute !*")
        self.emit_playlist_update(interaction.guild.id)
        # Immediately start next track if one exists
        await self.play_next(interaction)

    @app_commands.command(name="stop", description="Stoppe tout et vide la playlist.")
    async def stop(self, interaction: discord.Interaction) -> None:
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.stop)
        vc = interaction.guild.voice_client
        if vc and vc.is_connected():
            if vc.is_playing() or vc.is_paused():
                vc.stop()
        await interaction.response.send_message("⏹ *Majesté l’a décidé : tout s’arrête ici...*")
        self.emit_playlist_update(interaction.guild.id)

    @app_commands.command(name="pause", description="Met en pause la musique actuelle.")
    async def pause(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ *Soupir de soulagement... enfin une pause.*")
        else:
            await interaction.response.send_message("❌ *Ah ! Pauvre fou, rien n’est en train de jouer...*")

    @app_commands.command(name="resume", description="Reprend la lecture après une pause.")
    async def resume(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ *Et c’est reparti pour le calvaire sonore...*")
        else:
            await interaction.response.send_message("❌ *Reprendre quoi ? Le silence ? Quelle noble idée.*")

    @app_commands.command(name="playlist", description="Affiche les morceaux en attente.")
    async def playlist(self, interaction: discord.Interaction) -> None:
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not queue:
            await interaction.response.send_message(
                "📋 *Playlist vide. Rien. Nada. Comme votre inspiration musicale.*"
            )
            return
        lines = "\n".join([
            f"**{i+1}.** [{item['title']}]({item['url']})" for i, item in enumerate(queue)
        ])
        await interaction.response.send_message(f"🎶 *Voici votre précieuse sélection :*\n{lines}")

    @app_commands.command(name="current", description="Affiche le morceau actuellement joué.")
    async def current(self, interaction: discord.Interaction) -> None:
        song = self.current_song.get(interaction.guild.id)
        if song:
            await interaction.response.send_message(
                f"🎧 *Musique actuelle :* **[{song['title']}]({song['url']})**"
            )
        else:
            await interaction.response.send_message(
                "❌ *Rien en cours. Profitez du silence, il vous va si bien.*"
            )

    # ------------------------------------------------------------------
    # Web panel helper methods
    # ------------------------------------------------------------------
    async def play_for_user(self, guild_id: str | int, user_id: str | int, item: Dict[str, Any]) -> None:
        """Play a track on behalf of a specific user via the web panel.

        If the bot is not connected to a voice channel it will join the
        requesting user's channel.  The provided ``item`` should contain
        ``title`` and ``url`` keys.
        """
        print(
            f"[DEBUG][MUSIC] play_for_user: guild_id={guild_id}, user_id={user_id}, item={item}"
        )
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            print("[Music] Serveur introuvable")
            return
        member = guild.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            print("[Music] Utilisateur non connecté en vocal ou introuvable")
            return

        # Ensure the bot is connected
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            await member.voice.channel.connect()
            print(
                f"[Music] Greg vient de rejoindre le vocal {member.voice.channel.name}"
            )

        # Add the track and start playback if needed
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.add, item)
        # Build a fake interaction for play_next
        class FakeInteraction:
            def __init__(self, guild):
                self.guild = guild
                self.followup = self
            async def send(self, msg): print("[FakeInteraction]", msg)
            async def response(self): pass
        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)

    async def skip_for_web(self, guild_id: str | int) -> None:
        """Skip the current track via the web panel and play the next one."""
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            print("[Music] Guild introuvable pour skip")
            return
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not queue:
            return
        # Remove first track
        await loop.run_in_executor(None, pm.skip)
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        class FakeInteraction:
            def __init__(self, guild):
                self.guild = guild
                self.followup = self
            async def send(self, msg): print("[FakeInteraction]", msg)
            async def response(self): pass
        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)

    async def stop_for_web(self, guild_id: str | int) -> None:
        """Clear the playlist and stop playback via the web panel."""
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            print("[Music] Guild introuvable pour stop")
            return
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.stop)
        vc = guild.voice_client
        if vc and vc.is_connected():
            if vc.is_playing() or vc.is_paused():
                vc.stop()
        self.is_playing[str(guild_id)] = False
        self.emit_playlist_update(guild_id)

    async def pause_for_web(self, guild_id: str | int) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            print("[Music] Guild introuvable pour pause")
            return
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            print("[Music] Pause demandée par le webpanel.")

    async def resume_for_web(self, guild_id: str | int) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            print("[Music] Guild introuvable pour resume")
            return
        vc = guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            print("[Music] Resume demandée par le webpanel.")


async def setup(bot: commands.Bot, emit_fn: Optional[callable] = None) -> None:
    """Load the Music cog into the bot."""
    await bot.add_cog(Music(bot, emit_fn))
    print("✅ Cog 'Music' chargé avec slash commands.")