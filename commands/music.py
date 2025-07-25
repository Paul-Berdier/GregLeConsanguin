# commands/music.py

import discord
from discord import app_commands
from discord.ext import commands
from extractors import get_extractor, get_search_module
import yt_dlp
import os
import asyncio
import json

PLAYLIST_FILE = "playlist.json"

def load_playlist():
    if not os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "w") as f:
            json.dump([], f)
    with open(PLAYLIST_FILE, "r") as f:
        return json.load(f)

def save_playlist(playlist):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(playlist, f)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.is_playing = False
        self.current_song = None
        self.search_results = {}
        self.ffmpeg_path = self.detect_ffmpeg()

    def detect_ffmpeg(self):
        """Détecte ffmpeg automatiquement."""
        FFMPEG_PATHS = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "ffmpeg"]
        for path in FFMPEG_PATHS:
            if os.path.exists(path) and os.access(path, os.X_OK):
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé.")
        return "ffmpeg"

    @app_commands.command(name="play", description="Joue un son depuis une URL ou une recherche.")
    async def play(self, interaction: discord.Interaction, query_or_url: str):
        await interaction.response.defer()

        if interaction.guild.voice_client is None:
            if interaction.user.voice and interaction.user.voice.channel:
                await interaction.user.voice.channel.connect()
                await interaction.followup.send(f"🎤 *Greg rejoint le canal vocal :* {interaction.user.voice.channel.name}")
            else:
                return await interaction.followup.send("❌ *Tu n'es même pas en vocal, vermine...*")

        await interaction.followup.send("🎵 *Encore une demande musicale, Majesté ? Quel supplice...*")

        if "http://" in query_or_url or "https://" in query_or_url:
            await self.ask_play_mode(interaction, query_or_url)
            return

        extractor = get_search_module("soundcloud")
        results = extractor.search(query_or_url)

        if not results:
            return await interaction.followup.send("❌ *Rien trouvé, même les rats ont fui cette piste...*")

        self.search_results[interaction.user.id] = results

        msg = "**🔍 Résultats Soundcloud :**\n"
        for i, item in enumerate(results[:3], 1):
            msg += f"**{i}.** [{item['title']}]({item['url']})\n"
        msg += "\n*Choisissez un chiffre (1-3) en réponse.*"

        await interaction.followup.send(msg)

        def check(m):
            return m.author.id == interaction.user.id and m.content.isdigit() and 1 <= int(m.content) <= len(results[:3])

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30.0)
            selected_url = results[int(reply.content) - 1]["url"]
            await self.ask_play_mode(interaction, selected_url)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ *Trop lent. Greg retourne râler dans sa crypte...*")

    async def ask_play_mode(self, interaction, url):
        await interaction.followup.send(
            "**📦 Dois-je souffrir en le téléchargeant ou simplement le vomir dans vos oreilles ?**\n"
            "**1.** Télécharger puis jouer\n"
            "**2.** Lecture directe (stream)"
        )

        def check(m):
            return m.author.id == interaction.user.id and m.content in ["1", "2"]

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=30.0)
            if msg.content == "1":
                await self.add_to_queue(interaction, url)
            else:
                extractor = get_extractor(url)
                if not extractor or not hasattr(extractor, "stream"):
                    return await interaction.followup.send("❌ *Impossible de streamer ce son, même les démons refusent.*")

                source, title = await extractor.stream(url, self.ffmpeg_path)

                vc = interaction.guild.voice_client
                if vc.is_playing():
                    vc.stop()

                vc.play(source, after=lambda e: print(f"▶️ Fin du stream : {title} ({e})" if e else f"🎶 Fin lecture : {title}"))
                self.current_song = title
                await interaction.followup.send(f"▶️ *Votre ignoble sélection est lancée en streaming :* **{title}**")

        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ *Trop lent. Greg se pend avec un câble MIDI...*")

    async def add_to_queue(self, interaction, url):
        await interaction.followup.send(f"🎵 Ajouté à la playlist : {url}")
        self.queue.append(url)

        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", url)
            except Exception:
                title = url

        playlist = load_playlist()
        playlist.append({"title": title, "url": url})
        save_playlist(playlist)

        if not self.is_playing:
            await self.play_next(interaction)

    async def play_next(self, interaction):
        if not self.queue:
            self.is_playing = False
            await interaction.followup.send("📍 *Plus rien à jouer. Enfin une pause pour Greg...*")
            return

        self.is_playing = True
        url = self.queue.pop(0)

        extractor = get_extractor(url)
        if extractor is None:
            await interaction.followup.send("❌ *Aucun extracteur trouvé. Quelle misère...*")
            return

        filename, title, duration = await extractor.download(
            url,
            ffmpeg_path=self.ffmpeg_path,
            cookies_file="youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
        )

        self.current_song = title

        vc = interaction.guild.voice_client
        vc.play(discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),
                after=lambda e: self.bot.loop.create_task(self.play_next(interaction)))

        await interaction.followup.send(f"🎶 *Majesté, voici votre requête :* **{title}** (`{duration}` sec)")

    @app_commands.command(name="skip", description="Passe à la piste suivante.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()

            playlist = load_playlist()
            if playlist:
                playlist.pop(0)
                save_playlist(playlist)

            await interaction.response.send_message("⏭ *Et que ça saute !*")
        else:
            await interaction.response.send_message("❌ *Rien à zapper... pitoyable...*")

    @app_commands.command(name="stop", description="Stoppe tout et vide la playlist.")
    async def stop(self, interaction: discord.Interaction):
        self.queue.clear()
        save_playlist([])

        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()

        await interaction.response.send_message("⏹ *Majesté l’a décidé : tout s’arrête ici...*")

    @app_commands.command(name="pause", description="Met en pause la musique actuelle.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ *Soupir de soulagement... enfin une pause.*")
        else:
            await interaction.response.send_message("❌ *Ah ! Pauvre fou, rien n’est en train de jouer...*")

    @app_commands.command(name="resume", description="Reprend la lecture après une pause.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ *Et c’est reparti pour le calvaire sonore...*")
        else:
            await interaction.response.send_message("❌ *Reprendre quoi ? Le silence ? Quelle noble idée.*")

    @app_commands.command(name="playlist", description="Affiche les morceaux en attente.")
    async def playlist(self, interaction: discord.Interaction):
        if not self.queue:
            return await interaction.response.send_message("📋 *Playlist vide. Rien. Nada. Comme votre inspiration musicale.*")

        lines = "\n".join([f"**{i+1}.** {url}" for i, url in enumerate(self.queue)])
        await interaction.response.send_message(f"🎶 *Voici votre précieuse sélection :*\n{lines}")

    @app_commands.command(name="current", description="Affiche le morceau actuellement joué.")
    async def current(self, interaction: discord.Interaction):
        if self.current_song:
            await interaction.response.send_message(f"🎧 *Musique actuelle :* **{self.current_song}**")
        else:
            await interaction.response.send_message("❌ *Rien en cours. Profitez du silence, il vous va si bien.*")


async def setup(bot):
    await bot.add_cog(Music(bot))
    print("✅ Cog 'Music' chargé avec slash commands.")
