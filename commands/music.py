# commands/music.py
#
# Greg le Consanguin — Cog "Music"
# - Slash commands ET commandes texte (prefix: "!")
# - Intégration overlay/web via emit_fn (fourni par main.py)
# - Émissions Socket.IO: état enrichi (queue, current, is_paused, progress, thumbnail, repeat_all)
# - Recherche YouTube/SoundCloud selon le provider choisi

import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import time
from typing import Optional

from extractors import get_extractor, get_search_module
from playlist_manager import PlaylistManager


def _greg_print(msg: str):
    print(f"[GREG/Music] {msg}")


def _infer_provider_from_url(url: str) -> Optional[str]:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u or "music.youtube" in u:
        return "youtube"
    if "soundcloud.com" in u:
        return "soundcloud"
    return None


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

        # --- Suivi overlay ---
        self.play_start = {}      # {guild_id: monotonic()}
        self.paused_since = {}    # {guild_id: monotonic() | None}
        self.paused_total = {}    # {guild_id: float}
        self.ticker_tasks = {}    # {guild_id: asyncio.Task}
        self.current_meta = {}    # {guild_id: {"duration": int|None, "thumbnail": str|None}}
        self.repeat_all = {}      # {guild_id: bool}

        _greg_print("Initialisation du cog Music… *Quelle joie contenue…*")

    # ---------- Utilitaires état / overlay ----------

    def get_pm(self, guild_id):
        gid = str(guild_id)
        if gid not in self.managers:
            self.managers[gid] = PlaylistManager(gid)
            _greg_print(f"Nouvelle PlaylistManager pour la guild {gid}. *Encore du rangement…*")
        return self.managers[gid]

    def _overlay_payload(self, guild_id: int) -> dict:
        pm = self.get_pm(guild_id)
        data = pm.to_dict()
        vc = None
        try:
            g = self.bot.get_guild(int(guild_id))
            vc = g.voice_client if g else None
        except Exception:
            vc = None
        current = self.current_song.get(guild_id) or data.get("current")
        is_paused = bool(vc and vc.is_paused())

        # Progression
        start = self.play_start.get(guild_id)
        paused_since = self.paused_since.get(guild_id)
        paused_total = self.paused_total.get(guild_id, 0.0)
        elapsed = 0
        if start:
            base = time.monotonic()
            if paused_since:
                base = paused_since
            elapsed = max(0, int(base - start - paused_total))

        meta = self.current_meta.get(guild_id, {})
        duration = meta.get("duration")
        thumb = meta.get("thumbnail")

        return {
            "queue": data.get("queue", []),
            "current": current,
            "is_paused": is_paused,
            "progress": {"elapsed": elapsed, "duration": int(duration) if duration else None},
            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(guild_id, False)),
        }

    def emit_playlist_update(self, guild_id):
        if self.emit_fn:
            payload = self._overlay_payload(guild_id)
            _greg_print(
                f"[EMIT] playlist_update → guild={guild_id} — "
                f"paused={payload.get('is_paused')} "
                f"elapsed={payload.get('progress',{}).get('elapsed')}"
            )
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

    @app_commands.describe(
        provider="Source: youtube / soundcloud / auto",
        mode="Mode: stream / download / auto",
        query_or_url="Recherche (titre/artiste) ou URL directe",
    )
    @app_commands.choices(
        provider=[
            app_commands.Choice(name="auto", value="auto"),
            app_commands.Choice(name="youtube", value="youtube"),
            app_commands.Choice(name="soundcloud", value="soundcloud"),
        ],
        mode=[
            app_commands.Choice(name="auto", value="auto"),
            app_commands.Choice(name="stream", value="stream"),
            app_commands.Choice(name="download", value="download"),
        ],
    )
    @app_commands.command(
        name="play",
        description="Joue un son en choisissant la source (YouTube/SoundCloud) et le mode (stream/download)."
    )
    async def play(
        self,
        interaction: discord.Interaction,
        query_or_url: str,
        provider: app_commands.Choice[str] = None,
        mode: app_commands.Choice[str] = None,
    ):
        prov = (provider.value if provider else "auto").lower()
        play_mode = (mode.value if mode else "auto").lower()
        _greg_print(f"/play par {interaction.user} — arg='{query_or_url}', provider={prov}, mode={play_mode}")

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

        # URL directe
        if query_or_url.startswith(("http://", "https://")):
            inferred = _infer_provider_from_url(query_or_url)
            chosen_provider = inferred or (prov if prov != "auto" else None)
            await self.add_to_queue(
                interaction,
                {"title": query_or_url, "url": query_or_url, "provider": chosen_provider, "mode": play_mode},
            )
            return

        # Recherche selon provider (auto -> SC d'abord)
        chosen = prov
        if chosen == "auto":
            chosen = "soundcloud"

        try:
            searcher = get_search_module(chosen)
        except Exception as e:
            return await interaction.followup.send(f"❌ *Module de recherche indisponible ({chosen}) :* `{e}`")

        try:
            results = await loop.run_in_executor(None, searcher.search, query_or_url)
            _greg_print(f"Résultats {chosen} pour '{query_or_url}': {len(results)} items.")
        except Exception as e:
            return await interaction.followup.send(f"❌ *Recherche foirée ({chosen}) :* `{e}`")

        if not results:
            if prov == "auto":
                other = "youtube" if chosen == "soundcloud" else "soundcloud"
                try:
                    other_search = get_search_module(other)
                    results = await loop.run_in_executor(None, other_search.search, query_or_url)
                    chosen = other
                    _greg_print(f"[AUTO] Bascule recherche vers {other}: {len(results)} items.")
                except Exception:
                    results = []
            if not results:
                return await interaction.followup.send("❌ *Rien. Même les rats ont fui cette piste…*")

        # Propose 3 choix
        self.search_results[interaction.user.id] = [{"provider": chosen, **r} for r in results]
        msg = f"**🔍 Résultats {chosen.capitalize()} :**\n"
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
            selected = self.search_results[interaction.user.id][idx]
            await self.add_to_queue(interaction, {
                "title": selected.get("title", "Titre inconnu"),
                "url": selected.get("webpage_url", selected.get("url")),
                "provider": selected.get("provider"),
                "mode": play_mode,
            })
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ *Trop lent. Greg retourne maugréer dans sa crypte…*")

    async def add_to_queue(self, interaction_like, item):
        """
        Ajoute à la file et démarre la lecture si rien ne tourne.
        item = {title, url, provider?, mode?}
        """
        pm = self.get_pm(interaction_like.guild.id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        await loop.run_in_executor(None, pm.add, item)
        await interaction_like.followup.send(
            f"🎵 Ajouté : **{item['title']}** ({item['url']}) — "
            f"{(item.get('provider') or 'auto')}/{(item.get('mode') or 'auto')}"
        )
        self.emit_playlist_update(interaction_like.guild.id)
        if not self.is_playing.get(str(interaction_like.guild.id), False):
            await self.play_next(interaction_like)

    async def play_next(self, interaction_like):
        """Démarre ou passe au morceau suivant."""
        guild_id = interaction_like.guild.id
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)

        queue = await loop.run_in_executor(None, pm.get_queue)
        if not queue:
            self.is_playing[str(guild_id)] = False
            await interaction_like.followup.send("📍 *Plus rien à jouer. Enfin une pause…*")
            self.current_song.pop(guild_id, None)
            # reset chrono/meta
            self.play_start.pop(guild_id, None)
            self.paused_since.pop(guild_id, None)
            self.paused_total.pop(guild_id, None)
            self.current_meta.pop(guild_id, None)
            self.emit_playlist_update(guild_id)
            return

        self.is_playing[str(guild_id)] = True
        item = queue.pop(0)

        # Repeat ALL: remet le morceau joué en fin de file
        if self.repeat_all.get(guild_id):
            queue.append(item)

        pm.queue = queue
        await loop.run_in_executor(None, pm.save)

        url = item['url']
        play_mode = (item.get("mode") or "auto").lower()

        # Choix extracteur par URL
        extractor = get_extractor(url)
        if extractor is None:
            await interaction_like.followup.send("❌ *Aucun extracteur ne veut de ta soupe…*")
            return

        vc = interaction_like.guild.voice_client

        # Préférence: stream direct quand possible
        if play_mode in ("auto", "stream") and hasattr(extractor, "stream"):
            try:
                source, title = await extractor.stream(url, self.ffmpeg_path)
                self.current_song[guild_id] = {"title": title, "url": url}
                self.current_meta[guild_id] = {"duration": None, "thumbnail": item.get("thumb")}
                if vc.is_playing():
                    vc.stop()

                def _after(e):
                    try:
                        getattr(source, "cleanup", lambda: None)()
                    finally:
                        self.bot.loop.create_task(self.play_next(interaction_like))

                vc.play(source, after=_after)

                # Chrono
                self.play_start[guild_id] = time.monotonic()
                self.paused_total[guild_id] = 0.0
                self.paused_since.pop(guild_id, None)
                self._ensure_ticker(guild_id)

                await interaction_like.followup.send(f"▶️ *Streaming :* **{title}**")
                self.emit_playlist_update(guild_id)
                return
            except Exception as e:
                if play_mode == "stream":
                    await interaction_like.followup.send(f"⚠️ *Stream KO, je bascule en download…* `{e}`")
                # en auto, on tente download juste après

        # Fallback: téléchargement puis lecture
        try:
            filename, title, duration = await extractor.download(
                url,
                ffmpeg_path=self.ffmpeg_path,
                cookies_file="youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
            )
            self.current_song[guild_id] = {"title": title, "url": url}
            self.current_meta[guild_id] = {"duration": int(duration) if duration else None, "thumbnail": item.get("thumb")}

            if vc.is_playing():
                vc.stop()

            source = discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path)

            def _after(e):
                try:
                    getattr(source, "cleanup", lambda: None)()
                finally:
                    self.bot.loop.create_task(self.play_next(interaction_like))

            vc.play(source, after=_after)

            # Chrono
            self.play_start[guild_id] = time.monotonic()
            self.paused_total[guild_id] = 0.0
            self.paused_since.pop(guild_id, None)
            self._ensure_ticker(guild_id)

            await interaction_like.followup.send(f"🎶 *Téléchargé & joué :* **{title}** (`{duration}`s)")
            self.emit_playlist_update(guild_id)
        except Exception as e:
            await interaction_like.followup.send(f"❌ *Même le téléchargement s’écroule…* `{e}`")

    # =====================================================================
    #                         COMMANDES TEXTE (!)
    # =====================================================================

    class _CtxProxy:
        def __init__(self, ctx):
            self.guild = ctx.guild
            self._ctx = ctx
            self.followup = self
        async def send(self, msg):
            await self._ctx.reply(msg)

    @commands.command(name="play", help="!play <url|recherche> — Joue un son (SC/YT auto).")
    async def text_play(self, ctx: commands.Context, *, query_or_url: str):
        _greg_print(f"!play par {ctx.author} — arg='{query_or_url}'")
        if ctx.guild.voice_client is None:
            if ctx.author.voice and ctx.author.voice.channel:
                await ctx.author.voice.channel.connect()
                await ctx.reply(f"🎤 *Greg rejoint :* **{ctx.author.voice.channel.name}**")
            else:
                return await ctx.reply("❌ *T’es même pas en vocal, microbe…*")

        # URL → file directe
        if query_or_url.startswith(("http://", "https://")):
            return await self.add_to_queue(Music._CtxProxy(ctx), {
                "title": query_or_url, "url": query_or_url,
                "provider": _infer_provider_from_url(query_or_url), "mode": "auto"
            })

        # Texte → on tente SC puis YT
        for prov in ("soundcloud", "youtube"):
            try:
                searcher = get_search_module(prov)
                results = await asyncio.get_running_loop().run_in_executor(None, searcher.search, query_or_url)
                if results:
                    top = results[0]
                    return await self.add_to_queue(Music._CtxProxy(ctx), {
                        "title": top.get("title", "Titre inconnu"),
                        "url": top.get("webpage_url", top.get("url")),
                        "provider": prov, "mode": "auto"
                    })
            except Exception:
                continue
        await ctx.reply("❌ *Rien trouvé. Même pas un bootleg moisi.*")

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
        # reset chrono/meta
        self.play_start.pop(guild.id, None)
        self.paused_since.pop(guild.id, None)
        self.paused_total.pop(guild.id, None)
        self.current_meta.pop(guild.id, None)
        await send_fn("⏹ *Débranché. Tout s’arrête ici…*")
        self.emit_playlist_update(guild.id)

    async def _do_pause(self, guild: discord.Guild, send_fn):
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            if guild.id not in self.paused_since:
                self.paused_since[guild.id] = time.monotonic()
            await send_fn("⏸ *Enfin une pause…*")
            self.emit_playlist_update(guild.id)
        else:
            await send_fn("❌ *Rien à mettre en pause, hélas…*")

    async def _do_resume(self, guild: discord.Guild, send_fn):
        vc = guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            ps = self.paused_since.pop(guild.id, None)
            if ps:
                self.paused_total[guild.id] = self.paused_total.get(guild.id, 0.0) + (time.monotonic() - ps)
            await send_fn("▶️ *Reprenons ce calvaire sonore…*")
            self.emit_playlist_update(guild.id)
        else:
            await send_fn("❌ *Reprendre quoi ? Le silence ?*")

    # =====================================================================
    #                          API web (overlay/app.py)
    # =====================================================================

    async def play_for_user(self, guild_id, user_id, item):
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

        class FakeInteraction:
            def __init__(self, g):
                self.guild = g
                self.followup = self
            async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")

        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(guild_id)

    async def play_at(self, guild_id, index):
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop().run_in_executor
        await asyncio.get_running_loop().run_in_executor(None, self.get_pm(guild_id).reload)
        queue = await asyncio.get_running_loop().run_in_executor(None, self.get_pm(guild_id).get_queue)
        if not (0 <= index < len(queue)):
            _greg_print("Index hors playlist. *Viser, ça s’apprend.*")
            return False
        item = queue.pop(index)
        queue.insert(0, item)
        self.get_pm(guild_id).queue = queue
        await asyncio.get_running_loop().run_in_executor(None, self.get_pm(guild_id).save)

        guild = self.bot.get_guild(int(guild_id))
        class FakeInteraction:
            def __init__(self, g): self.guild = g; self.followup = self
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

    async def toggle_pause_for_web(self, guild_id):
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Guild introuvable pour toggle_pause (web).")
            return
        vc = guild.voice_client
        if vc and vc.is_paused():
            await self._do_resume(guild, lambda m: _greg_print(f"[WEB toggle -> resume] {m}"))
        else:
            await self._do_pause(guild, lambda m: _greg_print(f"[WEB toggle -> pause] {m}"))

    async def restart_current_for_web(self, guild_id):
        """Replace la piste courante en tête et redémarre (previous simple)."""
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            _greg_print("Guild introuvable pour restart (web).")
            return
        song = self.current_song.get(guild.id)
        if not song:
            _greg_print("Aucun morceau courant à redémarrer.")
            return
        pm = self.get_pm(guild_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        q = await loop.run_in_executor(None, pm.get_queue)
        q.insert(0, {"title": song.get("title"), "url": song.get("url")})
        pm.queue = q
        await loop.run_in_executor(None, pm.save)

        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # déclenche play_next → va relire la même piste
        else:
            class FakeInteraction:
                def __init__(self, g): self.guild = g; self.followup = self
                async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")
            await self.play_next(FakeInteraction(guild))

        self.emit_playlist_update(guild_id)

    async def repeat_for_web(self, guild_id, mode: Optional[str]):
        """mode: None -> toggle, 'on' -> True, 'off' -> False. Renvoie l'état final."""
        cur = bool(self.repeat_all.get(guild_id, False))
        if mode is None:
            cur = not cur
        else:
            cur = True if mode == "on" else False
        self.repeat_all[guild_id] = cur
        self.emit_playlist_update(guild_id)
        return cur

    # ---------- Ticker ----------
    def _ensure_ticker(self, guild_id: int):
        if self.ticker_tasks.get(guild_id):
            return
        self.ticker_tasks[guild_id] = self.bot.loop.create_task(self._ticker(guild_id))

    async def _ticker(self, guild_id: int):
        try:
            while True:
                g = self.bot.get_guild(int(guild_id))
                vc = g.voice_client if g else None
                if not vc or (not vc.is_playing() and not vc.is_paused()):
                    break
                self.emit_playlist_update(guild_id)
                await asyncio.sleep(1)
        finally:
            self.ticker_tasks.pop(guild_id, None)


async def setup(bot, emit_fn=None):
    await bot.add_cog(Music(bot, emit_fn))
    _greg_print("✅ Cog 'Music' chargé — overlay enrichi + provider/mode.")
