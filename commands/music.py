# commands/music.py
#
# Greg le Consanguin — Cog "Music"
# - Slash commands UNIQUEMENT
# - Intégration overlay/web via emit_fn (fournie par main.py)
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


def _infer_provider_from_url(u: str) -> Optional[str]:
    if not isinstance(u, str):
        return None
    if "soundcloud.com" in u or "sndcdn.com" in u:
        return "soundcloud"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return None

def _clean_url(u: Optional[str]) -> Optional[str]:
    if not u:
        return u
    u = str(u).strip()
    # strip quotes & stray semicolons/spaces
    u = u.strip('\'" \t\r\n')
    while u.endswith(';'):
        u = u[:-1]
    return u

class Music(commands.Cog):
    """
    Cog musical unique.
    - Une PlaylistManager PAR guild (persistée en JSON)
    - is_playing/current_song PAR guild
    - emit_fn(optionnel) : fonction injectée par main.py pour pousser l'état à l'overlay via Socket.IO
    """
    def __init__(self, bot, emit_fn=None):
        self.bot = bot
        self.managers = {}        # {guild_id(str): PlaylistManager}  (PlaylistManager reste indexé en str)
        # Etats internes indexés en INT (normalisés)
        self.is_playing = {}      # {guild_id(int): bool}
        self.current_song = {}    # {guild_id(int): dict(title,url,artist?,thumb?,duration?)}
        self.search_results = {}  # {user_id: last_results}
        self.ffmpeg_path = self.detect_ffmpeg()
        self.emit_fn = emit_fn    # set par main.py au démarrage

        # --- Suivi overlay ---
        self.play_start = {}      # {guild_id(int): monotonic()}
        self.paused_since = {}    # {guild_id(int): monotonic() | None}
        self.paused_total = {}    # {guild_id(int): float}
        self.ticker_tasks = {}    # {guild_id(int): asyncio.Task}
        self.current_meta = {}    # {guild_id(int): {"duration": int|None, "thumbnail": str|None}}
        self.repeat_all = {}      # {guild_id(int): bool}
        self.now_playing = {}     # {guild_id(int): dict(title,url,artist,thumb,duration)}

        _greg_print("Initialisation du cog Music… *Quelle joie contenue…*")

    # ---------- Utilitaires ----------

    @staticmethod
    def _gid(v) -> int:
        try:
            return int(v)
        except Exception:
            return int(str(v))

    def _migrate_keys_to_int(self, dct, gid_int):
        """Si une clé str(gid) existe, on la déplace vers gid_int pour unifier."""
        gid_str = str(gid_int)
        if gid_str in dct and gid_int not in dct:
            dct[gid_int] = dct.pop(gid_str)

    def get_pm(self, guild_id):
        gid_str = str(self._gid(guild_id))  # PlaylistManager indexé en str
        if gid_str not in self.managers:
            self.managers[gid_str] = PlaylistManager(gid_str)
            _greg_print(f"Nouvelle PlaylistManager pour la guild {gid_str}.")
        return self.managers[gid_str]

    # ---------- Overlay payload ----------

    def _overlay_payload(self, guild_id: int) -> dict:
        gid = self._gid(guild_id)

        # Unifier les clés avant de lire
        for d in (self.is_playing, self.current_song, self.play_start,
                  self.paused_since, self.paused_total, self.current_meta,
                  self.repeat_all, getattr(self, "now_playing", {})):
            self._migrate_keys_to_int(d, gid)

        pm = self.get_pm(gid)
        data = pm.to_dict()

        # état voice
        try:
            g = self.bot.get_guild(gid)
            vc = g.voice_client if g else None
        except Exception:
            vc = None

        # ✅ source de vérité
        nowp = getattr(self, "now_playing", {})
        current = nowp.get(gid) or self.current_song.get(gid) or data.get("current")
        is_paused = bool(vc and vc.is_paused())

        # Progression
        start = self.play_start.get(gid)
        paused_since = self.paused_since.get(gid)
        paused_total = self.paused_total.get(gid, 0.0)
        elapsed = 0
        if start:
            base = paused_since or time.monotonic()
            elapsed = max(0, int(base - start - paused_total))

        # Meta + miniature
        meta = self.current_meta.get(gid, {})
        duration = meta.get("duration")
        thumb = meta.get("thumbnail")
        if isinstance(current, dict):
            if duration is None and isinstance(current.get("duration"), (int, float)):
                duration = int(current["duration"])
            thumb = thumb or current.get("thumb") or current.get("thumbnail")

        return {
            "queue": data.get("queue", []),
            "current": current,
            "is_paused": is_paused,
            "progress": {"elapsed": elapsed,
                         "duration": int(duration) if duration is not None else None},
            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(gid, False)),
        }

    def emit_playlist_update(self, guild_id):
        gid = self._gid(guild_id)
        if self.emit_fn:
            payload = self._overlay_payload(gid)
            _greg_print(
                f"[EMIT] playlist_update → guild={gid} "
                f"paused={payload.get('is_paused')} "
                f"elapsed={payload.get('progress', {}).get('elapsed')} "
                f"current={bool(payload.get('current'))} "
                f"queue={[it.get('title') for it in payload.get('queue', [])]}"
            )
            self.emit_fn("playlist_update", payload)

    async def _i_send(self, interaction: discord.Interaction, msg: str):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg)
        except Exception:
            _greg_print(f"[WARN] _i_send fallback: {msg}")

    async def _safe_send(self, send_fn, msg: str):
        try:
            res = send_fn(msg)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            _greg_print(f"[WARN] send_fn failed: {e}")

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
    async def slash_play(
        self,
        interaction: discord.Interaction,
        query_or_url: str,
        provider: Optional[app_commands.Choice[str]] = None,
        mode: Optional[app_commands.Choice[str]] = None,
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
            cleaned = _clean_url(query_or_url)
            inferred = _infer_provider_from_url(cleaned)
            chosen_provider = inferred or (prov if prov != "auto" else None)
            await self.add_to_queue(
                interaction,
                {"title": cleaned, "url": cleaned, "provider": chosen_provider, "mode": play_mode},
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
        msg += "\n*Réponds avec un chiffre (1-3) dans le chat.*"
        await interaction.followup.send(msg)

        def check(m):
            return (
                m.author.id == interaction.user.id
                and m.channel.id == interaction.channel.id
                and m.content.isdigit()
                and 1 <= int(m.content) <= len(results[:3])
            )

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30.0)
            idx = int(reply.content) - 1
            selected = self.search_results[interaction.user.id][idx]
            sel_url = _clean_url(selected.get("webpage_url", selected.get("url")))
            await self.add_to_queue(interaction, {
                "title": selected.get("title", "Titre inconnu"),
                "url": sel_url,
                "provider": selected.get("provider"),
                "mode": play_mode,
            })

        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ *Trop lent. Greg retourne maugréer dans sa crypte…*")

    @app_commands.command(name="skip", description="Passe au morceau suivant.")
    async def slash_skip(self, interaction: discord.Interaction):
        await self._do_skip(interaction.guild, lambda m: self._i_send(interaction, m))

    @app_commands.command(name="stop", description="Vide la playlist et stoppe la lecture.")
    async def slash_stop(self, interaction: discord.Interaction):
        await self._do_stop(interaction.guild, lambda m: self._i_send(interaction, m))

    @app_commands.command(name="pause", description="Met la musique en pause.")
    async def slash_pause(self, interaction: discord.Interaction):
        await self._do_pause(interaction.guild, lambda m: self._i_send(interaction, m))

    @app_commands.command(name="resume", description="Reprend la musique.")
    async def slash_resume(self, interaction: discord.Interaction):
        await self._do_resume(interaction.guild, lambda m: self._i_send(interaction, m))

    @app_commands.command(name="playlist", description="Affiche la file d’attente.")
    async def slash_playlist(self, interaction: discord.Interaction):
        pm = self.get_pm(interaction.guild.id)
        queue = await asyncio.get_running_loop().run_in_executor(None, pm.get_queue)
        if not queue:
            return await self._i_send(interaction, "📋 *Playlist vide. Comme ton âme.*")
        lines = "\n".join([f"**{i+1}.** [{it.get('title','?')}]({it.get('url','')})" for i, it in enumerate(queue)])
        await self._i_send(interaction, f"🎶 *Sélection actuelle :*\n{lines}")

    @app_commands.command(name="current", description="Montre le morceau en cours.")
    async def slash_current(self, interaction: discord.Interaction):
        song = self.current_song.get(self._gid(interaction.guild.id))
        if song:
            await self._i_send(interaction, f"🎧 **[{song['title']}]({song['url']})**")
        else:
            await self._i_send(interaction, "❌ *Rien en cours. Le néant musical.*")

    @app_commands.describe(mode="on/off (vide pour basculer)")
    @app_commands.command(name="repeat", description="Active/désactive le repeat ALL (toute la file).")
    async def slash_repeat(self, interaction: discord.Interaction, mode: Optional[str] = None):
        mode = (mode or "").lower().strip()
        if mode not in ("", "on", "off"):
            return await self._i_send(interaction, "⚠️ Utilisation: `/repeat` (toggle) ou `/repeat on|off`")
        state = await self.repeat_for_web(interaction.guild.id, mode if mode else None)
        await self._i_send(interaction, f"🔁 Repeat ALL : **{'ON' if state else 'OFF'}**")

    # =====================================================================
    #                         Actions internes factorisées
    # =====================================================================

    async def add_to_queue(self, interaction_like, item):
        gid = self._gid(interaction_like.guild.id)
        if item and "url" in item:
            item = {**item, "url": _clean_url(item["url"])}
            if not item["title"]:
                item["title"] = item["url"]
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        _greg_print(f"[DEBUG add_to_queue] AVANT reload → queue={len(pm.queue)} items")
        await loop.run_in_executor(None, pm.reload)
        _greg_print(f"[DEBUG add_to_queue] APRES reload → queue={len(pm.queue)} items")
        await loop.run_in_executor(None, pm.add, item)
        _greg_print(f"[DEBUG add_to_queue] AJOUTÉ: {item} → queue={len(pm.queue)} items")

        await interaction_like.followup.send(
            f"🎵 Ajouté : **{item['title']}** ({item['url']}) — "
            f"{(item.get('provider') or 'auto')}/{(item.get('mode') or 'auto')}"
        )
        self.emit_playlist_update(gid)

        if not self.is_playing.get(gid, False):
            _greg_print(f"[DEBUG add_to_queue] Rien ne joue encore, lancement play_next…")
            await self.play_next(interaction_like)

    async def play_next(self, interaction_like):
        """Démarre ou passe au morceau suivant (met aussi à jour now_playing -> overlay)."""
        gid = self._gid(interaction_like.guild.id)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()

        # Toujours recharger depuis disque avant d'agir
        await loop.run_in_executor(None, pm.reload)

        # Récupère le prochain élément ET met pm.now_playing (persisté)
        item = await loop.run_in_executor(None, pm.pop_next)
        if not item:
            self.is_playing[gid] = False
            _greg_print(f"[DEBUG play_next] Queue VIDE → arrêt")
            await interaction_like.followup.send("📍 *Plus rien à jouer. Enfin une pause…*")
            self.current_song.pop(gid, None)
            # reset chrono/meta
            self.play_start.pop(gid, None)
            self.paused_since.pop(gid, None)
            self.paused_total.pop(gid, None)
            self.current_meta.pop(gid, None)
            self.now_playing.pop(gid, None)
            self.emit_playlist_update(gid)
            return

        _greg_print(f"[DEBUG play_next] ITEM sélectionné: {item}")

        # Repeat ALL : on remet IMMÉDIATEMENT la piste en fin de file (repeat queue)
        if self.repeat_all.get(gid):
            await loop.run_in_executor(None, pm.add, item)
            _greg_print("[DEBUG play_next] Repeat ALL actif → remis en fin de file")

        # Marquer "quelque chose joue"
        self.is_playing[gid] = True

        # Préparer l'état courant (provisoire) pour l'overlay AVANT extraction
        url = item.get("url")
        play_mode = (item.get("mode") or "auto").lower()
        self.current_song[gid] = {"title": item.get("title", url), "url": url}
        self.current_meta[gid] = {
            "duration": int(item["duration"]) if isinstance(item.get("duration"), (int, float)) else None,
            "thumbnail": item.get("thumb")
        }
        # now_playing enrichi pour l'UI (utilisé en priorité par _overlay_payload)
        self.now_playing[gid] = {
            "title": item.get("title", url),
            "url": url,
            "artist": item.get("artist"),
            "thumb": item.get("thumb"),
            "duration": self.current_meta[gid]["duration"]
        }

        # Premier emit pour que l’overlay voie tout de suite "current"
        self.emit_playlist_update(gid)

        _greg_print(f"[DEBUG play_next] Lecture via provider={item.get('provider')} mode={play_mode} url={url}")

        # Choix extracteur par URL
        extractor = get_extractor(url)
        if extractor is None:
            await interaction_like.followup.send("❌ *Aucun extracteur ne veut de ta soupe…*")
            return

        vc = interaction_like.guild.voice_client
        if not vc:
            await interaction_like.followup.send("❌ *Pas de connexion vocale active.*")
            return

        # --- Préférence: stream direct quand possible ---
        if play_mode in ("auto", "stream") and hasattr(extractor, "stream"):
            try:
                source, real_title = await extractor.stream(url, self.ffmpeg_path)

                # Mettre à jour les titres/états avec le titre réel
                self.current_song[gid] = {"title": real_title, "url": url}
                self.now_playing[gid].update({"title": real_title})
                # Durée inconnue en stream
                self.current_meta[gid].update({"duration": None})

                if vc.is_playing():
                    vc.stop()

                def _after(e):
                    try:
                        getattr(source, "cleanup", lambda: None)()
                    finally:
                        self.bot.loop.create_task(self.play_next(interaction_like))

                vc.play(source, after=_after)

                # Chrono
                self.play_start[gid] = time.monotonic()
                self.paused_total[gid] = 0.0
                self.paused_since.pop(gid, None)
                self._ensure_ticker(gid)

                await interaction_like.followup.send(f"▶️ *Streaming :* **{real_title}**")
                self.emit_playlist_update(gid)
                return
            except Exception as e:
                if play_mode == "stream":
                    await interaction_like.followup.send(f"⚠️ *Stream KO, je bascule en download…* `{e}`")
                # en "auto", on tentera download juste après

        # --- Fallback: téléchargement puis lecture ---
        try:
            filename, real_title, duration = await extractor.download(
                url,
                ffmpeg_path=self.ffmpeg_path,
                cookies_file="youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
            )

            self.current_song[gid] = {"title": real_title, "url": url}
            dur_int = int(duration) if duration else None
            self.current_meta[gid] = {"duration": dur_int, "thumbnail": item.get("thumb")}
            self.now_playing[gid].update({"title": real_title, "duration": dur_int})

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
            self.play_start[gid] = time.monotonic()
            self.paused_total[gid] = 0.0
            self.paused_since.pop(gid, None)
            self._ensure_ticker(gid)

            await interaction_like.followup.send(f"🎶 *Téléchargé & joué :* **{real_title}** (`{duration}`s)")
            self.emit_playlist_update(gid)
        except Exception as e:
            await interaction_like.followup.send(f"❌ *Même le téléchargement s’écroule…* `{e}`")

    async def _do_skip(self, guild: discord.Guild, send_fn):
        gid = self._gid(guild.id)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        _greg_print(f"[DEBUG skip] Queue avant skip ({len(pm.queue)}): {[it.get('title') for it in pm.queue]}")
        await loop.run_in_executor(None, pm.skip)
        _greg_print(f"[DEBUG skip] Queue après skip ({len(pm.queue)}): {[it.get('title') for it in pm.queue]}")
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.stop()  # déclenche le after → play_next
        await self._safe_send(send_fn, "⏭ *Et que ça saute !*")
        self.emit_playlist_update(gid)

    async def _do_stop(self, guild: discord.Guild, send_fn):
        gid = self._gid(guild.id)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        _greg_print(f"[DEBUG stop] Queue avant STOP ({len(pm.queue)}): {[it.get('title') for it in pm.queue]}")
        await loop.run_in_executor(None, pm.stop)
        _greg_print(f"[DEBUG stop] Queue après STOP ({len(pm.queue)}): {[it.get('title') for it in pm.queue]}")
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        self.current_song.pop(gid, None)
        self.is_playing[gid] = False
        # reset chrono/meta
        self.play_start.pop(gid, None)
        self.paused_since.pop(gid, None)
        self.paused_total.pop(gid, None)
        self.current_meta.pop(gid, None)
        self.now_playing.pop(gid, None)
        await self._safe_send(send_fn, "⏹ *Débranché. Tout s’arrête ici…*")
        self.emit_playlist_update(gid)

    async def _do_pause(self, guild: discord.Guild, send_fn):
        gid = self._gid(guild.id)
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            if not self.paused_since.get(gid):
                self.paused_since[gid] = time.monotonic()
            await self._safe_send(send_fn, "⏸ *Enfin une pause…*")
            self.emit_playlist_update(gid)
        else:
            await self._safe_send(send_fn, "❌ *Rien à mettre en pause, hélas…*")

    async def _do_resume(self, guild: discord.Guild, send_fn):
        gid = self._gid(guild.id)
        vc = guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            ps = self.paused_since.pop(gid, None)
            if ps:
                self.paused_total[gid] = self.paused_total.get(gid, 0.0) + (time.monotonic() - ps)
            await self._safe_send(send_fn, "▶️ *Reprenons ce calvaire sonore…*")
            self.emit_playlist_update(gid)
        else:
            await self._safe_send(send_fn, "❌ *Reprendre quoi ? Le silence ?*")

    # =====================================================================
    #                          API web (overlay/app.py)
    # =====================================================================

    async def play_for_user(self, guild_id, user_id, item):
        gid = self._gid(guild_id)
        _greg_print(f"API play_for_user(guild={gid}, user={user_id}) — {item}")
        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("Serveur introuvable.")
            return
        member = guild.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            _greg_print("Utilisateur pas en vocal.")
            return

        vc = guild.voice_client
        if not vc or not vc.is_connected():
            await member.voice.channel.connect()
            _greg_print(f"Greg rejoint le vocal {member.voice.channel.name}…")

        pm = self.get_pm(gid)
        _greg_print(f"[DEBUG play_for_user] Queue avant ajout ({len(pm.queue)}): {[it.get('title') for it in pm.queue]}")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.add, item)
        _greg_print(f"[DEBUG play_for_user] Queue après ajout ({len(pm.queue)}): {[it.get('title') for it in pm.queue]}")

        class FakeInteraction:
            def __init__(self, g):
                self.guild = g
                self.followup = self
            async def send(self, msg):
                _greg_print(f"[WEB->Discord] {msg}")

        # si rien ne joue → lancer
        if not self.is_playing.get(gid, False):
            await self.play_next(FakeInteraction(guild))

        self.emit_playlist_update(gid)

    async def play_at(self, guild_id, index):
        gid = self._gid(guild_id)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()

        # reload + lecture file
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        if not (0 <= index < len(queue)):
            _greg_print("Index hors playlist. *Viser, ça s’apprend.*")
            return False

        # met l'item demandé en tête
        item = queue.pop(index)
        queue.insert(0, item)
        pm.queue = queue
        await loop.run_in_executor(None, pm.save)

        # rejoue
        guild = self.bot.get_guild(gid)

        class FakeInteraction:
            def __init__(self, g):
                self.guild = g
                self.followup = self
            async def send(self, msg):
                _greg_print(f"[WEB->Discord] {msg}")

        await self.play_next(FakeInteraction(guild))
        self.emit_playlist_update(gid)
        return True

    async def skip_for_web(self, guild_id):
        gid = self._gid(guild_id)
        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("Guild introuvable pour skip (web).")
            return
        await self._do_skip(guild, lambda m: _greg_print(f"[WEB skip] {m}"))

    async def stop_for_web(self, guild_id):
        gid = self._gid(guild_id)
        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("Guild introuvable pour stop (web).")
            return
        await self._do_stop(guild, lambda m: _greg_print(f"[WEB stop] {m}"))

    async def pause_for_web(self, guild_id):
        gid = self._gid(guild_id)
        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("Guild introuvable pour pause (web).")
            return
        await self._do_pause(guild, lambda m: _greg_print(f"[WEB pause] {m}"))

    async def resume_for_web(self, guild_id):
        gid = self._gid(guild_id)
        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("Guild introuvable pour resume (web).")
            return
        await self._do_resume(guild, lambda m: _greg_print(f"[WEB resume] {m}"))

    async def toggle_pause_for_web(self, guild_id):
        gid = self._gid(guild_id)
        guild = self.bot.get_guild(gid)
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
        gid = self._gid(guild_id)
        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("Guild introuvable pour restart (web).")
            return
        song = self.current_song.get(gid)
        if not song:
            _greg_print("Aucun morceau courant à redémarrer.")
            return
        pm = self.get_pm(gid)
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

        self.emit_playlist_update(gid)

    async def repeat_for_web(self, guild_id, mode: Optional[str]):
        """mode: None -> toggle, 'on' -> True, 'off' -> False. Renvoie l'état final."""
        gid = self._gid(guild_id)
        cur = bool(self.repeat_all.get(gid, False))
        if mode is None:
            cur = not cur
        else:
            cur = True if mode == "on" else False
        self.repeat_all[gid] = cur
        self.emit_playlist_update(gid)
        return cur

    # ---------- Ticker ----------
    def _ensure_ticker(self, guild_id: int):
        gid = self._gid(guild_id)
        if self.ticker_tasks.get(gid):
            return
        self.ticker_tasks[gid] = self.bot.loop.create_task(self._ticker(gid))

    async def _ticker(self, guild_id: int):
        gid = self._gid(guild_id)
        try:
            while True:
                g = self.bot.get_guild(gid)
                vc = g.voice_client if g else None
                if not vc or (not vc.is_playing() and not vc.is_paused()):
                    break
                self.emit_playlist_update(gid)
                await asyncio.sleep(1)
        finally:
            self.ticker_tasks.pop(gid, None)


async def setup(bot, emit_fn=None):
    await bot.add_cog(Music(bot, emit_fn))
    _greg_print("✅ Cog 'Music' chargé — overlay enrichi + provider/mode (slash commands only).")
