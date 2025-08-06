# commands/music.py

import discord
from discord import app_commands
from discord.ext import commands
from extractors import get_extractor, get_search_module
import os
import asyncio

from playlist_manager import PlaylistManager

class Music(commands.Cog):
    def __init__(self, bot, emit_fn=None):
        self.bot = bot
        self.managers = {}  # {guild_id: PlaylistManager}
        self.is_playing = {}  # {guild_id: bool}
        self.current_song = {}  # {guild_id: str}
        self.search_results = {}
        self.ffmpeg_path = self.detect_ffmpeg()
        self.emit_fn = emit_fn

    def get_pm(self, guild_id):
        gid = str(guild_id)
        if gid not in self.managers:
            self.managers[gid] = PlaylistManager(gid)
        return self.managers[gid]

    def emit_playlist_update(self, guild_id):
        if self.emit_fn:
            pm = self.get_pm(guild_id)
            print(f"[Music][EMIT] Emission playlist_update pour {guild_id}")
            self.emit_fn("playlist_update", pm.to_dict(), broadcast=True)

    def detect_ffmpeg(self):
        FFMPEG_PATHS = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "ffmpeg", r"D:\Paul Berdier\ffmpeg\bin\ffmpeg.exe"]
        for path in FFMPEG_PATHS:
            if os.path.exists(path) and os.access(path, os.X_OK):
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé.")
        return "ffmpeg"

    @app_commands.command(name="play", description="Joue un son depuis une URL ou une recherche.")
    async def play(self, interaction: discord.Interaction, query_or_url: str):
        print("[DEBUG][MUSIC] /play appelé par", interaction.user, "avec:", query_or_url)
        pm = self.get_pm(interaction.guild.id)  # Direct, PAS dans un thread !
        loop = asyncio.get_running_loop()
        print("[DEBUG] Reload playlist manager pour guild:", interaction.guild.id)
        await loop.run_in_executor(None, pm.reload)
        print("[DEBUG] Defer interaction.response")
        await interaction.response.defer()

        print("[DEBUG] Vérification de la connexion vocale...")
        if interaction.guild.voice_client is None:
            print("[DEBUG] Greg n'est PAS dans le vocal.")
            if interaction.user.voice and interaction.user.voice.channel:
                print("[DEBUG] L'utilisateur est en vocal dans :", interaction.user.voice.channel.name)
                await interaction.user.voice.channel.connect()
                print("[DEBUG] Greg vient de rejoindre le canal vocal.")
                await interaction.followup.send(
                    f"🎤 *Greg rejoint le canal vocal :* {interaction.user.voice.channel.name}")
            else:
                print("[DEBUG] L'utilisateur N'EST PAS en vocal.")
                return await interaction.followup.send("❌ *Tu n'es même pas en vocal, vermine...*")
        else:
            print("[DEBUG] Greg est déjà connecté au vocal.")

        print("[DEBUG] Envoi du message de supplice à Sa Majesté.")
        await interaction.followup.send("🎵 *Encore une demande musicale, Majesté ? Quel supplice...*")

        print("[DEBUG] Test si l'entrée est une URL directe...")
        if "http://" in query_or_url or "https://" in query_or_url:
            print("[DEBUG] Ajout direct à la queue :", query_or_url)
            await self.add_to_queue(interaction, query_or_url)
            return

        print("[DEBUG] Recherche SoundCloud...")
        extractor = get_search_module("soundcloud")
        try:
            results = await loop.run_in_executor(None, extractor.search, query_or_url)
            print(f"[DEBUG] Résultats de recherche SoundCloud pour '{query_or_url}': {results}")
        except Exception as e:
            print(f"[DEBUG][ERREUR] Recherche SoundCloud plantée : {e}")
            return await interaction.followup.send(f"❌ *Erreur lors de la recherche :* `{e}`")

        if not results:
            print("[DEBUG] Aucun résultat trouvé sur SoundCloud.")
            return await interaction.followup.send("❌ *Rien trouvé, même les rats ont fui cette piste...*")

        self.search_results[interaction.user.id] = results
        msg = "**🔍 Résultats Soundcloud :**\n"
        for i, item in enumerate(results[:3], 1):
            print(f"[DEBUG] Option {i} : {item['title']} ({item['url']})")
            msg += f"**{i}.** [{item['title']}]({item['url']})\n"
        msg += "\n*Choisissez un chiffre (1-3) en réponse.*"
        print("[DEBUG] Envoi du message de sélection à l'utilisateur.")
        await interaction.followup.send(msg)

        def check(m):
            print(f"[DEBUG][WAIT_FOR] Reçu : {m.content} de {m.author.id}")
            return m.author.id == interaction.user.id and m.content.isdigit() and 1 <= int(m.content) <= len(results[:3])

        try:
            print("[DEBUG] Attente de la réponse de l'utilisateur pour le choix du son...")
            reply = await self.bot.wait_for("message", check=check, timeout=30.0)
            print(f"[DEBUG] L'utilisateur a choisi : {reply.content}")
            selected_url = results[int(reply.content) - 1]["url"]
            print(f"[DEBUG] Appel de ask_play_mode avec l'URL : {selected_url}")
            await self.ask_play_mode(interaction, selected_url)
        except asyncio.TimeoutError:
            print("[DEBUG] Timeout d'attente du choix utilisateur.")
            await interaction.followup.send("⏳ *Trop lent. Greg retourne râler dans sa crypte...*")

    async def ask_play_mode(self, interaction, url):
        extractor = get_extractor(url)
        if not extractor or not hasattr(extractor, "stream"):
            return await interaction.followup.send("❌ *Impossible de streamer ce son, même les démons refusent.*")
        source, title = await extractor.stream(url, self.ffmpeg_path)
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.stop()
        vc.play(source, after=lambda e: print(f"▶️ Fin du stream : {title} ({e})" if e else f"🎶 Fin lecture : {title}"))
        self.current_song[interaction.guild.id] = title
        await interaction.followup.send(f"▶️ *Votre ignoble sélection est lancée en streaming (direct) :* **{title}**")
        self.emit_playlist_update(interaction.guild.id)

    async def add_to_queue(self, interaction, url):
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.add, url)
        await interaction.followup.send(f"🎵 Ajouté à la playlist : {url}")
        self.emit_playlist_update(interaction.guild.id)
        if not self.is_playing.get(str(interaction.guild.id), False):
            await self.play_next(interaction)

    async def play_next(self, interaction):
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
        url = queue.pop(0)
        pm.queue = queue
        await loop.run_in_executor(None, pm.save)
        extractor = get_extractor(url)
        if extractor is None:
            await interaction.followup.send("❌ *Aucun extracteur trouvé. Quelle misère...*")
            return
        vc = interaction.guild.voice_client
        if hasattr(extractor, "stream"):
            try:
                source, title = await extractor.stream(url, self.ffmpeg_path)
                self.current_song[interaction.guild.id] = title
                if vc.is_playing():
                    vc.stop()
                vc.play(source, after=lambda e: self.bot.loop.create_task(self.play_next(interaction)))
                await interaction.followup.send(f"▶️ *Streaming direct :* **{title}**")
                self.emit_playlist_update(interaction.guild.id)
                return
            except Exception as e:
                await interaction.followup.send(f"⚠️ *Échec du stream, je tente le téléchargement...* `{e}`")
        try:
            filename, title, duration = await extractor.download(
                url,
                ffmpeg_path=self.ffmpeg_path,
                cookies_file="youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
            )
            self.current_song[interaction.guild.id] = title
            vc.play(
                discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),
                after=lambda e: self.bot.loop.create_task(self.play_next(interaction))
            )
            await interaction.followup.send(f"🎶 *Téléchargé et joué :* **{title}** (`{duration}` sec)")
            self.emit_playlist_update(interaction.guild.id)
        except Exception as e:
            await interaction.followup.send(f"❌ *Même le téléchargement échoue, Majesté...* `{e}`")

    @app_commands.command(name="skip", description="Passe à la piste suivante.")
    async def skip(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.skip)
        await interaction.response.send_message("⏭ *Et que ça saute !*")
        self.emit_playlist_update(interaction.guild.id)

    @app_commands.command(name="stop", description="Stoppe tout et vide la playlist.")
    async def stop(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.stop)
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        await interaction.response.send_message("⏹ *Majesté l’a décidé : tout s’arrête ici...*")
        self.emit_playlist_update(interaction.guild.id)

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
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not queue:
            return await interaction.response.send_message("📋 *Playlist vide. Rien. Nada. Comme votre inspiration musicale.*")
        lines = "\n".join([f"**{i+1}.** {url}" for i, url in enumerate(queue)])
        await interaction.response.send_message(f"🎶 *Voici votre précieuse sélection :*\n{lines}")

    @app_commands.command(name="current", description="Affiche le morceau actuellement joué.")
    async def current(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        current = await loop.run_in_executor(None, pm.get_current)
        if current:
            await interaction.response.send_message(f"🎧 *Musique actuelle :* **{current}**")
        else:
            await interaction.response.send_message("❌ *Rien en cours. Profitez du silence, il vous va si bien.*")

    async def play_for_user(self, guild_id, user_id, url):
        print(f"[DEBUG][MUSIC] play_for_user: guild_id={guild_id}, user_id={user_id}, url={url}")
        guild = self.bot.get_guild(int(guild_id))
        print(f"[DEBUG][MUSIC] Guild récupéré: {guild} (ID: {guild_id})")
        if not guild:
            print("[Music] Serveur introuvable")
            return
        print(f"[DEBUG][MUSIC] Membres du serveur: {[m.id for m in guild.members]}")
        member = guild.get_member(int(user_id))
        print(f"[DEBUG][MUSIC] Member: {member} (ID: {user_id})")
        if member:
            print(f"[DEBUG][MUSIC] member.voice: {member.voice}, channel: {getattr(member.voice, 'channel', None)}")
        if not member or not member.voice or not member.voice.channel:
            print("[Music] Utilisateur non connecté en vocal ou introuvable")
            return
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.add, url)
        class FakeInteraction:
            def __init__(self, guild): self.guild = guild; self.followup = self
            async def send(self, msg): print("[FakeInteraction]", msg)
            async def response(self): pass
        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)

    async def play_at(self, guild_id, index):
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not (0 <= index < len(queue)):
            print("[Music] Index de lecture hors playlist")
            return False
        url = queue.pop(index)
        queue.insert(0, url)
        pm.queue = queue
        await loop.run_in_executor(None, pm.save)
        guild = self.bot.get_guild(int(guild_id))
        class FakeInteraction:
            def __init__(self, guild): self.guild = guild; self.followup = self
            async def send(self, msg): print("[FakeInteraction]", msg)
            async def response(self): pass
        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)
        return True

    def move_top(self, guild_id, index):
        pm = self.get_pm(guild_id)
        pm.reload()
        queue = pm.get_queue()
        if not (0 <= index < len(queue)):
            print("[Music] Index move_top hors playlist")
            return False
        song = queue.pop(index)
        queue.insert(0, song)
        pm.queue = queue
        pm.save()
        self.emit_playlist_update(guild_id)
        return True

async def setup(bot, emit_fn=None):
    await bot.add_cog(Music(bot, emit_fn))
    print("✅ Cog 'Music' chargé avec slash commands.")
