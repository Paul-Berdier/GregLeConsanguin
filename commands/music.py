# commands/music.py
import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
from playlist_manager import PlaylistManager
from extractors import get_extractor
from urllib.parse import urlparse
import re

class Music(commands.Cog):
    def __init__(self, bot, overlay_emit=None):
        self.bot = bot
        self.managers = {}       # {guild_id: PlaylistManager}
        self.is_playing = {}     # {guild_id: bool}
        self.current_song = {}   # {guild_id: {"title":..., "url":...}}
        self.ffmpeg_path = self.detect_ffmpeg()
        self.overlay_emit = overlay_emit

    # ---------- UTILS ----------
    def detect_ffmpeg(self):
        paths = [
            "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg",
            "ffmpeg", r"D:\ffmpeg\bin\ffmpeg.exe"
        ]
        for path in paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé.")
        return "ffmpeg"

    def get_pm(self, guild_id):
        gid = str(guild_id)
        if gid not in self.managers:
            self.managers[gid] = PlaylistManager(gid)
        return self.managers[gid]

    def emit_overlay(self, guild_id):
        """Envoie la playlist et la musique en cours à l’overlay."""
        if self.overlay_emit:
            pm = self.get_pm(guild_id)
            data = {
                "queue": pm.get_queue(),
                "current": self.current_song.get(guild_id)
            }
            self.overlay_emit("playlist_update", data)

    # ---------- COMMANDES ----------
    @app_commands.command(name="play", description="Ajoute un son, une playlist ou un mix à la file d'attente.")
    async def play(self, interaction: discord.Interaction, source: str):
        """source peut être : URL YouTube/SoundCloud, mix/playlist, texte à chercher, ou plusieurs liens séparés par espace."""
        await interaction.response.defer()
        pm = self.get_pm(interaction.guild.id)

        if interaction.guild.voice_client is None:
            if interaction.user.voice and interaction.user.voice.channel:
                await interaction.user.voice.channel.connect()
            else:
                return await interaction.followup.send("❌ *Tu n’es même pas en vocal, gueux.*")

        urls = self.parse_sources(source)
        if not urls:
            return await interaction.followup.send("❌ Rien à ajouter.")

        added_titles = []
        for url in urls:
            extractor = get_extractor(url)
            if extractor:
                # Playlist / mix complet
                if "playlist" in url or "mix" in url:
                    playlist_items = extractor.get_playlist(url)
                    for item in playlist_items:
                        pm.add({"title": item["title"], "url": item["url"]})
                        added_titles.append(item["title"])
                else:
                    pm.add({"title": url, "url": url})
                    added_titles.append(url)
            else:
                await interaction.followup.send(f"⚠️ Aucun extracteur trouvé pour {url}")

        self.emit_overlay(interaction.guild.id)
        await interaction.followup.send(f"🎵 Ajouté : {len(added_titles)} morceau(x).")
        if not self.is_playing.get(str(interaction.guild.id), False):
            await self.play_next(interaction)

    @app_commands.command(name="skip", description="Passe au morceau suivant.")
    async def skip(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        pm.pop_first()  # ← avance la queue
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()  # déclenche play_next()
            await interaction.response.send_message("⏭ *Prochain supplice…*")
        else:
            # rien ne joue : lance directement
            await self.play_next(interaction)
            await interaction.response.send_message("⏭ *On avance.*")

    @app_commands.command(name="stop", description="Arrête la lecture et vide la playlist.")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
        pm = self.get_pm(interaction.guild.id)
        pm.stop()
        self.emit_overlay(interaction.guild.id)
        await interaction.response.send_message("⏹ *Le silence, enfin.*")

    @app_commands.command(name="pause", description="Met en pause.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Pause.")
        else:
            await interaction.response.send_message("❌ Rien à mettre en pause.")

    @app_commands.command(name="resume", description="Reprend après pause.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Reprise.")
        else:
            await interaction.response.send_message("❌ Rien à reprendre.")

    @app_commands.command(name="playlist", description="Affiche la playlist.")
    async def playlist(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        queue = pm.get_queue()
        if not queue:
            return await interaction.response.send_message("📋 Playlist vide.")
        msg = "\n".join([f"**{i+1}.** {x['title']}" for i, x in enumerate(queue)])
        await interaction.response.send_message(f"🎶 Playlist :\n{msg}")

    @app_commands.command(name="current", description="Affiche le morceau actuel.")
    async def current(self, interaction: discord.Interaction):
        song = self.current_song.get(interaction.guild.id)
        if song:
            await interaction.response.send_message(f"🎧 Actuellement : **{song['title']}**")
        else:
            await interaction.response.send_message("❌ Aucun son en cours.")

    # ---------- LECTURE ----------
    async def play_next(self, interaction):
        pm = self.get_pm(interaction.guild.id)

        item = pm.pop_first()  # ← retire de la playlist réelle
        if not item:
            self.is_playing[str(interaction.guild.id)] = False
            self.emit_overlay(interaction.guild.id)
            return

        self.is_playing[str(interaction.guild.id)] = True
        extractor = get_extractor(item["url"])
        if not extractor:
            await interaction.followup.send(f"❌ Impossible de lire : {item['title']}")
            return

        try:
            source, title = await extractor.stream(item["url"], self.ffmpeg_path)
            self.current_song[interaction.guild.id] = {"title": title, "url": item["url"]}
            vc = interaction.guild.voice_client
            if vc.is_playing():
                vc.stop()
            vc.play(source, after=lambda e: self.bot.loop.create_task(self.play_next(interaction)))
            self.emit_overlay(interaction.guild.id)
            await interaction.followup.send(f"▶️ Lecture : **{title}**")
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur lecture : {e}")

    # ---------- HELPERS ----------
    def parse_sources(self, text: str):
        urls = []
        if os.path.isfile(text) and text.endswith(".txt"):
            with open(text, "r", encoding="utf-8") as f:
                urls = [l.strip() for l in f if l.strip()]
        else:
            parts = text.split()
            for part in parts:
                if re.match(r"https?://", part):
                    urls.append(part)
        return urls


async def setup(bot, overlay_emit=None):
    await bot.add_cog(Music(bot, overlay_emit))
    print("✅ Cog 'Music' chargé.")
