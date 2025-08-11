# commands/music.py
#
# Greg le Consanguin — Cog "Music"
# - Slash commands ET commandes texte (prefix: "!")
# - Intégration overlay/web via emit_fn (fourni par main.py)
# - Émissions Socket.IO: état enrichi (queue, current, is_paused)
# - Recherche SoundCloud si on donne du texte, sinon URL directe
#
# 🎭 VOIX DE GREG DANS LES PRINTS :
#    Un larbin insupportable, sarcastique, qui obéit en soufflant.

import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio

from extractors import get_extractor, get_search_module
from playlist_manager import PlaylistManager


def _greg_print(msg: str):
    # Petits logs uniformes pour bien retrouver Greg dans la console
    print(f"[GREG/Music] {msg}")


class Music(commands.Cog):
    """
    Cog musical unique.
    - Une PlaylistManager PAR guild (persistée en JSON)
    - is_playing/current_song PAR guild
    - emit_fn(optionnel) : fonction injectée par main.py pour pousser l'état à l'overlay via Socket.IO
    """
    def __init__(self, bot, emit_fn=None):
        self.bot = bot
        self.managers = {}        # {guild_id: PlaylistManager}
        self.is_playing = {}      # {guild_id: bool}
        self.current_song = {}    # {guild_id: dict(title, url)}
        self.search_results = {}  # {user_id: last_results}
        self.ffmpeg_path = self.detect_ffmpeg()
        self.emit_fn = emit_fn    # set par main.py au démarrage

        _greg_print("Initialisation du cog Music… *Quelle joie contenue…*")

    # ---------- Utilitaires état / overlay ----------

    def get_pm(self, guild_id):
        gid = str(guild_id)
        if gid not in self.managers:
            self.managers[gid] = PlaylistManager(gid)
            _greg_print(f"Nouvelle PlaylistManager pour la guild {gid}. *Encore du rangement…*")
        return self.managers[gid]

    def _overlay_payload(self, guild_id: int) -> dict:
        """
        Construit l'état envoyé au web/overlay.
        Contient: queue (PM), current (selon notre suivi), is_paused (voice_client).
        """
        pm = self.get_pm(guild_id)
        data = pm.to_dict()  # queue + current (premier de la file)
        vc = None
        try:
            g = self.bot.get_guild(int(guild_id))
            vc = g.voice_client if g else None
        except Exception:
            vc = None
        # On préfère la vérité du lecteur courant si connue:
        current = self.current_song.get(guild_id) or data.get("current")
        is_paused = bool(vc and vc.is_paused())
        return {"queue": data.get("queue", []), "current": current, "is_paused": is_paused}

    def emit_playlist_update(self, guild_id):
        """
        Émet un événement 'playlist_update' vers Socket.IO si emit_fn est branchée.
        """
        if self.emit_fn:
            payload = self._overlay_payload(guild_id)
            _greg_print(f"[EMIT] playlist_update → guild={guild_id} — paused={payload.get('is_paused')}")
            self.emit_fn("playlist_update", payload)

    # ---------- Détection ffmpeg ----------

    def detect_ffmpeg(self):
        FFMPEG_PATHS = [
            "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg",
            "ffmpeg", r"D:\Paul Berdier\ffmpeg\bin\ffmpeg.exe"
        ]
        for path in FFMPEG_PATHS:
            if os.path.exists(path) and os.access(path, os.X_OK):
                _greg_print(f"🔥 FFmpeg détecté : {path}")
                return path
        _greg_print("❌ Aucun ffmpeg trouvé. *Formidable, on bricolera…*")
        return "ffmpeg"

    # =====================================================================
    #                           SLASH COMMANDS
    # =====================================================================

    @app_commands.command(name="play", description="Joue un son depuis une URL ou une recherche.")
    async def play(self, interaction: discord.Interaction, query_or_url: str):
        _greg_print(f"/play par {interaction.user} — arg='{query_or_url}'")
        pm = self.get_pm(interaction.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await interaction.response.defer()

        # Assure la connexion vocale
        if interaction.guild.voice_client is None:
            if interaction.user.voice and interaction.user.voice.channel:
                await interaction.user.voice.channel.connect()
                await interaction.followup.send(
                    f"🎤 *Greg rejoint le bouge :* **{interaction.user.voice.channel.name}**"
                )
            else:
                return await interaction.followup.send("❌ *Tu n'es même pas en vocal, vermine…*")

        await interaction.followup.send("🎵 *Encore une supplique musicale ? Soupir…*")

        # URL directe → on pousse
        if "http://" in query_or_url or "https://" in query_or_url:
            await self.add_to_queue(interaction, {"title": query_or_url, "url": query_or_url})
            return

        # Sinon recherche SoundCloud
        extractor = get_search_module("soundcloud")
        try:
            results = await loop.run_in_executor(None, extractor.search, query_or_url)
            _greg_print(f"Résultats SC pour '{query_or_url}': {len(results)} trouvailles misérables.")
        except Exception as e:
            return await interaction.followup.send(f"❌ *Recherche foirée :* `{e}`")

        if not results:
            return await interaction.followup.send("❌ *Rien. Même les rats ont fui cette piste…*")

        self.search_results[interaction.user.id] = results
        msg = "**🔍 Résultats SoundCloud :**\n"
        for i, item in enumerate(results[:3], 1):
            title = item.get("title", "Titre inconnu")
            url = item.get("webpage_url") or item.get("url") or ""
            msg += f"**{i}.** [{title}]({url})\n"
        msg += "\n*Réponds avec un chiffre (1-3).*"
        await interaction.followup.send(msg)

        def check(m):
            return m.author.id == interaction.user.id and m.content.isdigit() and 1 <= int(m.content) <= len(results[:3])

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30.0)
            idx = int(reply.content) - 1
            selected = results[idx]
            await self.add_to_queue(interaction, {
                "title": selected.get("title", "Titre inconnu"),
                "url": selected.get("webpage_url", selected.get("url"))
            })
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ *Trop lent. Greg retourne maugréer dans sa crypte…*")

    async def add_to_queue(self, interaction_like, item):
        """
        Ajoute à la file et démarre la lecture si rien ne tourne.
        interaction_like: doit exposer .guild et .followup.send(str)
        """
        pm = self.get_pm(interaction_like.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.add, item)  # item = {title, url}
        await interaction_like.followup.send(f"🎵 Ajouté : **{item['title']}** ({item['url']})")
        self.emit_playlist_update(interaction_like.guild.id)
        if not self.is_playing.get(str(interaction_like.guild.id), False):
            await self.play_next(interaction_like)

    async def play_next(self, interaction_like):
        """
        Démarre ou passe au morceau suivant.
        interaction_like: doit exposer .guild et .followup.send(str)
        """
        guild_id = interaction_like.guild.id
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)

        queue = await loop.run_in_executor(None, pm.get_queue)
        if not queue:
            self.is_playing[str(guild_id)] = False
            await interaction_like.followup.send("📍 *Plus rien à jouer. Enfin une pause…*")
            self.current_song.pop(guild_id, None)  # plus de courant
            self.emit_playlist_update(guild_id)
            return

        self.is_playing[str(guild_id)] = True
        item = queue.pop(0)
        pm.queue = queue
        await loop.run_in_executor(None, pm.save)

        extractor = get_extractor(item['url'])
        if extractor is None:
            await interaction_like.followup.send("❌ *Aucun extracteur ne veut de ta soupe…*")
            return

        vc = interaction_like.guild.voice_client

        # Préférence: stream direct quand possible
        if hasattr(extractor, "stream"):
            try:
                source, title = await extractor.stream(item['url'], self.ffmpeg_path)
                self.current_song[guild_id] = {"title": title, "url": item['url']}
                if vc.is_playing():
                    vc.stop()
                vc.play(source, after=lambda e: self.bot.loop.create_task(self.play_next(interaction_like)))
                await interaction_like.followup.send(f"▶️ *Streaming :* **{title}**")
                self.emit_playlist_update(guild_id)
                return
            except Exception as e:
                await interaction_like.followup.send(f"⚠️ *Échec stream, on télécharge…* `{e}`")

        # Fallback: téléchargement puis lecture
        try:
            filename, title, duration = await extractor.download(
                item['url'],
                ffmpeg_path=self.ffmpeg_path,
                cookies_file="youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
            )
            self.current_song[guild_id] = {"title": title, "url": item['url']}
            vc.play(
                discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),
                after=lambda e: self.bot.loop.create_task(self.play_next(interaction_like))
            )
            await interaction_like.followup.send(f"🎶 *Téléchargé & joué :* **{title}** (`{duration}`s)")
            self.emit_playlist_update(guild_id)
        except Exception as e:
            await interaction_like.followup.send(f"❌ *Même le téléchargement s’écroule…* `{e}`")

    @app_commands.command(name="skip", description="Passe à la piste suivante.")
    async def slash_skip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._do_skip(interaction.guild, lambda m: interaction.followup.send(m))

    @app_commands.command(name="stop", description="Stoppe tout et vide la playlist.")
    async def slash_stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._do_stop(interaction.guild, lambda m: interaction.followup.send(m))

    @app_commands.command(name="pause", description="Met en pause la musique actuelle.")
    async def slash_pause(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._do_pause(interaction.guild, lambda m: interaction.followup.send(m))

    @app_commands.command(name="resume", description="Reprend la lecture après une pause.")
    async def slash_resume(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._do_resume(interaction.guild, lambda m: interaction.followup.send(m))

    @app_commands.command(name="playlist", description="Affiche les morceaux en attente.")
    async def slash_playlist(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        queue = await asyncio.get_running_loop().run_in_executor(None, pm.get_queue)
        if not queue:
            return await interaction.response.send_message("📋 *Playlist vide. Rien. Nada.*")
        lines = "\n".join([f"**{i+1}.** [{it['title']}]({it['url']})" for i, it in enumerate(queue)])
        await interaction.response.send_message(f"🎶 *Votre précieuse sélection :*\n{lines}")

    @app_commands.command(name="current", description="Affiche le morceau actuellement joué.")
    async def slash_current(self, interaction: discord.Interaction):
        song = self.current_song.get(interaction.guild.id)
        if song:
            await interaction.response.send_message(f"🎧 **[{song['title']}]({song['url']})**")
        else:
            await interaction.response.send_message("❌ *Rien en cours. Savourez le silence.*")

    # =====================================================================
    #                         COMMANDES TEXTE (!)
    # =====================================================================

    # Adaptateur minimal pour réutiliser les mêmes méthodes que les slash
    class _CtxProxy:
        def __init__(self, ctx):
            self.guild = ctx.guild
            self._ctx = ctx
            self.followup = self  # on expose send()

        async def send(self, msg):
            await self._ctx.reply(msg)

    @commands.command(name="play", help="!play <url|recherche> — Joue un son (SoundCloud si recherche).")
    async def text_play(self, ctx: commands.Context, *, query_or_url: str):
        _greg_print(f"!play par {ctx.author} — arg='{query_or_url}'")
        # Connexion vocale si nécessaire
        if ctx.guild.voice_client is None:
            if ctx.author.voice and ctx.author.voice.channel:
                await ctx.author.voice.channel.connect()
                await ctx.reply(f"🎤 *Greg rejoint :* **{ctx.author.voice.channel.name}**")
            else:
                return await ctx.reply("❌ *T’es même pas en vocal, microbe…*")

        # URL directe ?
        if "http://" in query_or_url or "https://" in query_or_url:
            return await self.add_to_queue(Music._CtxProxy(ctx), {"title": query_or_url, "url": query_or_url})

        # Sinon recherche SoundCloud (top 1 direct pour la commande texte, plus rapide)
        extractor = get_search_module("soundcloud")
        try:
            results = await asyncio.get_running_loop().run_in_executor(None, extractor.search, query_or_url)
        except Exception as e:
            return await ctx.reply(f"❌ *Recherche foirée :* `{e}`")

        if not results:
            return await ctx.reply("❌ *Rien trouvé. Même pas un bootleg moisi.*")

        top = results[0]
        await self.add_to_queue(Music._CtxProxy(ctx), {
            "title": top.get("title", "Titre inconnu"),
            "url": top.get("webpage_url", top.get("url"))
        })

    @commands.command(name="skip", help="!skip — Passe au suivant.")
    async def text_skip(self, ctx: commands.Context):
        await self._do_skip(ctx.guild, lambda m: ctx.reply(m))

    @commands.command(name="stop", help="!stop — Vide la playlist et stoppe la lecture.")
    async def text_stop(self, ctx: commands.Context):
        await self._do_stop(ctx.guild, lambda m: ctx.reply(m))

    @commands.command(name="pause", help="!pause — Met la musique en pause.")
    async def text_pause(self, ctx: commands.Context):
        await self._do_pause(ctx.guild, lambda m: ctx.reply(m))

    @commands.command(name="resume", help="!resume — Reprend la musique.")
    async def text_resume(self, ctx: commands.Context):
        await self._do_resume(ctx.guild, lambda m: ctx.reply(m))

    @commands.command(name="playlist", help="!playlist — Affiche la file d’attente.")
    async def text_playlist(self, ctx: commands.Context):
        pm = self.get_pm(ctx.guild.id)
        queue = await asyncio.get_running_loop().run_in_executor(None, pm.get_queue)
        if not queue:
            return await ctx.reply("📋 *Playlist vide. Comme ton âme.*")
        lines = "\n".join([f"**{i+1}.** [{it['title']}]({it['url']})" for i, it in enumerate(queue)])
        await ctx.reply(f"🎶 *Sélection actuelle :*\n{lines}")

    @commands.command(name="current", help="!current — Montre le morceau en cours.")
    async def text_current(self, ctx: commands.Context):
        song = self.current_song.get(ctx.guild.id)
        if song:
            await ctx.reply(f"🎧 **[{song['title']}]({song['url']})**")
        else:
            await ctx.reply("❌ *Rien en cours. Le néant musical.*")

    # =====================================================================
    #                         Actions internes factorisées
    # =====================================================================

    async def _do_skip(self, guild: discord.Guild, send_fn):
        pm = self.get_pm(guild.id)
        await asyncio.get_running_loop().run_in_executor(None, pm.reload)
        await asyncio.get_running_loop().run_in_executor(None, pm.skip)
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.stop()  # déclenche le after → play_next
        await send_fn("⏭ *Et que ça saute !*")
        self.emit_playlist_update(guild.id)

    async def _do_stop(self, guild: discord.Guild, send_fn):
        pm = self.get_pm(guild.id)
        await asyncio.get_running_loop().run_in_executor(None, pm.reload)
        await asyncio.get_running_loop().run_in_executor(None, pm.stop)
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        self.current_song.pop(guild.id, None)
        self.is_playing[str(guild.id)] = False
        await send_fn("⏹ *Débranché. Tout s’arrête ici…*")
        self.emit_playlist_update(guild.id)

    async def _do_pause(self, guild: discord.Guild, send_fn):
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await send_fn("⏸ *Enfin une pause…*")
            self.emit_playlist_update(guild.id)
        else:
            await send_fn("❌ *Rien à mettre en pause, hélas…*")

    async def _do_resume(self, guild: discord.Guild, send_fn):
        vc = guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await send_fn("▶️ *Reprenons ce calvaire sonore…*")
            self.emit_playlist_update(guild.id)
        else:
            await send_fn("❌ *Reprendre quoi ? Le silence ?*")

    # =====================================================================
    #                          API web (overlay/app.py)
    # =====================================================================

    async def play_for_user(self, guild_id, user_id, item):
        """
        Appelée par l'API web (/api/play) depuis app.py via run_coroutine_threadsafe.
        Rejoint le vocal de l'utilisateur si besoin, pousse dans la file et lance la lecture.
        """
        _greg_print(f"API play_for_user(guild={guild_id}, user={user_id}) — {item}")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Serveur introuvable. *On marche les yeux fermés ici ?*")
            return
        member = guild.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            _greg_print("Utilisateur pas en vocal. *Je lis dans le vide ?*")
            return

        vc = guild.voice_client
        if not vc or not vc.is_connected():
            await member.voice.channel.connect()
            _greg_print(f"Greg rejoint le vocal {member.voice.channel.name} pour obéir, encore…")

        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.add, item)

        # Interaction factice pour réutiliser play_next
        class FakeInteraction:
            def __init__(self, g):
                self.guild = g
                self.followup = self
            async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")

        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)

    async def play_at(self, guild_id, index):
        """
        Force la piste 'index' à passer en tête, puis enchaîne play_next.
        Utilisé par le webpanel si besoin.
        """
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not (0 <= index < len(queue)):
            _greg_print("Index hors playlist. *Viser, ça s’apprend.*")
            return False
        item = queue.pop(index)
        queue.insert(0, item)
        pm.queue = queue
        await loop.run_in_executor(None, pm.save)

        guild = self.bot.get_guild(int(guild_id))

        class FakeInteraction:
            def __init__(self, g):
                self.guild = g
                self.followup = self
            async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")

        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)
        return True

    async def skip_for_web(self, guild_id):
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Guild introuvable pour skip (web).")
            return
        await self._do_skip(guild, lambda m: _greg_print(f"[WEB skip] {m}"))

    async def stop_for_web(self, guild_id):
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Guild introuvable pour stop (web).")
            return
        await self._do_stop(guild, lambda m: _greg_print(f"[WEB stop] {m}"))

    async def pause_for_web(self, guild_id):
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Guild introuvable pour pause (web).")
            return
        await self._do_pause(guild, lambda m: _greg_print(f"[WEB pause] {m}"))

    async def resume_for_web(self, guild_id):
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Guild introuvable pour resume (web).")
            return
        await self._do_resume(guild, lambda m: _greg_print(f"[WEB resume] {m}"))


async def setup(bot, emit_fn=None):
    await bot.add_cog(Music(bot, emit_fn))
    _greg_print("✅ Cog 'Music' chargé — slash + texte. *Vous allez encore m’user…*")
