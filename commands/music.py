# commands/music.py
#
# Greg le Consanguin — Cog "Music"
# - Slash commands UNIQUEMENT (pour Discord)
# - Intégration overlay/web via méthodes *_for_web et _overlay_payload
# - Insertion par priorité (rôles/poids), quota par utilisateur
# - Émissions Socket.IO via emit_fn (injectée par main.py)

import os
import time
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import requests
from urllib.parse import urlparse

from extractors import get_extractor, get_search_module
from playlist_manager import PlaylistManager

# Priorités (règles centralisées)
from priority_rules import (
    get_member_weight, PER_USER_CAP, can_bypass_quota, can_user_bump_over
)

# ---------------------------------------------------------------------------

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
    u = u.strip('\'" \t\r\n')
    while u.endswith(';'):
        u = u[:-1]
    return u


# ---------------------------------------------------------------------------

class Music(commands.Cog):
    """
    Cog musical unique.
    - Une PlaylistManager PAR guild (persistée en JSON)
    - is_playing/current_song PAR guild
    - emit_fn(optionnel) : fonction injectée par main.py pour pousser l'état à l'overlay via Socket.IO
    """
    def __init__(self, bot, emit_fn=None):
        self.bot = bot
        self.managers = {}        # {guild_id(str): PlaylistManager} (PlaylistManager indexé en str)
        # Etats internes indexés en INT (normalisés)
        self.is_playing = {}      # {guild_id(int): bool}
        self.current_song = {}    # {guild_id(int): dict}
        self.search_results = {}  # {user_id: last_results}
        self.ffmpeg_path = self.detect_ffmpeg()
        self.emit_fn = emit_fn    # set par main.py au démarrage

        # --- Suivi overlay ---
        self.play_start = {}      # {guild_id(int): monotonic au début de lecture}
        self.paused_since = {}    # {guild_id(int): monotonic quand pause}
        self.paused_total = {}    # {guild_id(int): total pause accumulée (s)}
        self.current_meta = {}    # {guild_id(int): meta courante (duration, thumbnail)}
        self.repeat_all = {}      # {guild_id(int): bool}
        self.now_playing = {}     # {guild_id(int): dict courant}
        self.ticker_tasks = {}    # {guild_id(int): task d'émission périodique overlay}

    # ---------- Utils clefs / migrations d’IDs ----------

    def _gid(self, guild_id: int) -> int:
        return int(guild_id)

    def _migrate_keys_to_int(self, d: dict, gid: int):
        try:
            if d is None:
                return
            for k in list(d.keys()):
                if isinstance(k, str) and k.isdigit():
                    d[int(k)] = d.pop(k)
        except Exception:
            pass

    def get_pm(self, guild_id: int) -> PlaylistManager:
        gid = self._gid(guild_id)
        key = str(gid)
        if key not in self.managers:
            self.managers[key] = PlaylistManager(key)
        return self.managers[key]

    # ---------- Normalisation des items (aligné avec l’API web) ----------

    def _to_seconds(self, v):
        if v is None:
            return None
        try:
            iv = int(v)
            # Heuristique: si > 86400 on suppose des millisecondes
            return iv // 1000 if iv > 86400 else iv
        except Exception:
            pass
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return int(s)
            import re as _re
            if _re.match(r"^\d+:\d{2}$", s):
                m, s2 = s.split(":")
                return int(m) * 60 + int(s2)
        return None

    def _oembed_enrich(self, page_url: str):
        try:
            host = (urlparse(page_url).hostname or "").lower()
            host = host[4:] if host.startswith("www.") else host
            if "soundcloud.com" in host:
                oe = requests.get(
                    "https://soundcloud.com/oembed",
                    params={"format": "json", "url": page_url},
                    timeout=4
                ).json()
                return oe.get("title"), oe.get("author_name"), oe.get("thumbnail_url")
            if "youtube.com" in host or "youtu.be" in host:
                oe = requests.get(
                    "https://www.youtube.com/oembed",
                    params={"format": "json", "url": page_url},
                    timeout=4
                ).json()
                return oe.get("title"), oe.get("author_name"), oe.get("thumbnail_url")
        except Exception:
            pass
        return None, None, None

    def _normalize_like_api(self, item: dict) -> dict:
        if not isinstance(item, dict):
            item = {}
        url = _clean_url(item.get("url"))
        title = (item.get("title") or url or "").strip()
        artist = (item.get("artist") or "").strip() or None
        thumb = (item.get("thumb") or item.get("thumbnail") or "").strip() or None
        duration = self._to_seconds(item.get("duration"))

        if (not title or not artist or not thumb) and url:
            t2, a2, th2 = self._oembed_enrich(url)
            title = title or t2
            artist = artist or a2
            thumb = thumb or th2

        norm = {
            "title": title or (url or "Sans titre"),
            "url": url,
            "artist": artist,
            "thumb": thumb,
            "duration": duration,
        }
        for k in ("provider", "mode"):
            if k in item:
                norm[k] = item[k]
        if "added_by" in item:
            norm["added_by"] = item["added_by"]
        if "priority" in item:
            norm["priority"] = int(item["priority"])
        return norm

    # ---------- Priorités / insertion ordonnée ----------

    def _compute_insert_index(self, queue: list, new_weight: int) -> int:
        """
        Renvoie l'index où insérer un nouvel item pour respecter l'ordre de priorité.
        Règle: devant la première piste dont le poids est STRICTEMENT inférieur.
        """
        if not queue:
            return 0
        # on évite de déplacer l'élément en cours (souvent index 0 pour pm.queue)
        start = 1 if queue else 0
        for i in range(start, len(queue)):
            w = int((queue[i] or {}).get("priority") or 0)
            if new_weight > w:
                return i
        return len(queue)  # append

    def _count_user_in_queue(self, queue: list, user_id: int) -> int:
        uid = str(user_id)
        return sum(1 for it in (queue or []) if str(it.get("added_by")) == uid)

    # =====================================================================
    #                            Slash commands
    # =====================================================================

    @app_commands.command(name="play", description="Ajoute une musique (URL ou recherche).")
    @app_commands.describe(
        query_or_url="URL directe ou terme de recherche",
        provider="Source préférée (auto, youtube, soundcloud)",
        mode="Mode de lecture (auto/stream/download selon extracteur)"
    )
    @app_commands.choices(
        provider=[
            app_commands.Choice(name="auto", value="auto"),
            app_commands.Choice(name="YouTube", value="youtube"),
            app_commands.Choice(name="SoundCloud", value="soundcloud"),
        ],
        mode=[
            app_commands.Choice(name="auto", value="auto"),
            app_commands.Choice(name="stream", value="stream"),
            app_commands.Choice(name="download", value="download"),
        ],
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
        except Exception as e:
            return await interaction.followup.send(f"❌ *Recherche échouée ({chosen}) :* `{e}`")

        # fallback si rien trouvé, on tente l'autre provider
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
            reply = await self.bot.wait_for("message", check=check, timeout=20.0)
            idx = int(reply.content) - 1
            selected = self.search_results[interaction.user.id][idx]
            sel_url = _clean_url(selected.get("webpage_url", selected.get("url")))
            await self.add_to_queue(interaction, {
                "title": selected.get("title", "Titre inconnu"),
                "url": sel_url,
                "artist": selected.get("artist"),
                "duration": selected.get("duration"),
                "thumb": selected.get("thumb") or selected.get("thumbnail"),
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
        gid = self._gid(interaction.guild.id)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()

        # 🔄 aligne avec l’overlay: recharge depuis la source de vérité
        await loop.run_in_executor(None, pm.reload)
        data = await loop.run_in_executor(None, pm.to_dict)

        queue = data.get("queue", []) or []
        current = (getattr(self, "now_playing", {}).get(gid)
                   or self.current_song.get(gid)
                   or data.get("current"))

        if not queue and not current:
            return await self._i_send(interaction, "📋 *Playlist vide. Comme ton âme.*")

        lines = []
        if current:
            lines.append(f"🎧 **En cours :** [{current.get('title', '?')}]({current.get('url', '')})")
        if queue:
            q_lines = [f"**{i + 1}.** [{it.get('title', '?')}]({it.get('url', '')})"
                       for i, it in enumerate(queue)]
            lines.append("\n".join(q_lines))

        await self._i_send(interaction, "🎶 *Sélection actuelle :*\n" + "\n".join(lines))

    @app_commands.command(name="current", description="Montre le morceau en cours.")
    async def slash_current(self, interaction: discord.Interaction):
        song = self.current_song.get(self._gid(interaction.guild.id))
        if song:
            t = song.get("title") or "?"
            u = song.get("url") or ""
            await self._i_send(interaction, f"🎧 **En cours :** [{t}]({u})")
        else:
            await self._i_send(interaction, "⏹️ *Rien en cours.*")

    # =====================================================================
    #                         Actions internes factorisées
    # =====================================================================

    async def add_to_queue(self, interaction_like, item):
        gid = self._gid(interaction_like.guild.id)

        # trace auteur & normalise comme /api/play
        try:
            if interaction_like and getattr(interaction_like, "user", None):
                item["added_by"] = str(interaction_like.user.id)
        except Exception:
            pass
        item = self._normalize_like_api(item)

        # priorité de l'auteur (Discord)
        w = get_member_weight(self.bot, gid, int(item.get("added_by") or 0))
        item["priority"] = int(w)

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        # quota par user (sauf bypass)
        if not can_bypass_quota(self.bot, gid, int(item.get("added_by") or 0)):
            if self._count_user_in_queue(queue, int(item.get("added_by") or 0)) >= PER_USER_CAP:
                return await interaction_like.followup.send(f"⛔ *Quota atteint ({PER_USER_CAP} pistes).*")

        # 1) ajouter en fin…
        await loop.run_in_executor(None, pm.add, item)
        # 2) …puis placer à l'index prioritaire
        new_queue = await loop.run_in_executor(None, pm.get_queue)
        new_idx = len(new_queue) - 1
        target_idx = self._compute_insert_index(new_queue, int(item["priority"]))
        if target_idx != new_idx:
            await loop.run_in_executor(None, pm.move, new_idx, target_idx)

        await interaction_like.followup.send(
            f"🎵 Ajouté : **{item['title']}** ({item['url']}) — "
            f"{(item.get('provider') or 'auto')}/{(item.get('mode') or 'auto')}"
        )
        self.emit_playlist_update(gid)

        # Si rien ne joue et le bot est déjà en vocal → auto-lancer
        await self._autoplay_if_idle(gid)

    async def play_next(self, interaction_like):
        """Démarre ou passe au morceau suivant (met aussi à jour now_playing -> overlay)."""
        gid = self._gid(interaction_like.guild.id)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()

        await loop.run_in_executor(None, pm.reload)
        item = await loop.run_in_executor(None, pm.pop_next)
        if not item:
            self.is_playing[gid] = False
            self.current_song.pop(gid, None)
            self.now_playing.pop(gid, None)
            await interaction_like.followup.send("⏹️ *Playlist terminée.*")
            self.emit_playlist_update(gid)
            return

        # Normalise l'item courant
        item = self._normalize_like_api(item)
        self.current_song[gid] = item
        self.now_playing[gid] = item
        self.current_meta[gid] = {}

        url = item["url"]
        provider = item.get("provider") or _infer_provider_from_url(url) or "auto"
        mode = item.get("mode") or "auto"

        await interaction_like.followup.send(f"▶️ **Lecture :** {item['title']}")
        self.emit_playlist_update(gid)

        # prépare l'extracteur
        try:
            extractor = get_extractor(provider)
        except Exception as e:
            await interaction_like.followup.send(f"❌ *Extracteur introuvable ({provider}) :* `{e}`")
            return

        # fait jouer via voice_client
        vc = interaction_like.guild.voice_client
        if vc is None:
            if interaction_like.user.voice and interaction_like.user.voice.channel:
                vc = await interaction_like.user.voice.channel.connect()
            else:
                return await interaction_like.followup.send("❌ *Personne en vocal pour jouer le morceau.*")

        try:
            source, meta = await extractor.stream_or_download(url, self.ffmpeg_path, mode=mode)
        except Exception as e:
            await interaction_like.followup.send(f"❌ *Échec extraction/stream :* `{e}`")
            return

        # meta: duration / thumbnail (si dispo)
        dur = meta.get("duration")
        if dur is not None:
            try:
                dur = int(dur)
            except Exception:
                pass
        self.current_meta[gid] = {
            "duration": dur,
            "thumbnail": meta.get("thumbnail"),
        }

        def after_play(err):
            if err:
                _greg_print(f"[Voice after] erreur FFmpeg / playback: {err}")
            # enchaîne
            coro = self._autoplay_if_idle(gid)
            fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                _greg_print(f"[Voice after] fut.result error: {e}")

        # démarre le flux
        try:
            vc.play(source, after=after_play)
            self.is_playing[gid] = True
            self.play_start[gid] = time.monotonic()
            self.paused_since.pop(gid, None)
            self.paused_total[gid] = 0.0

            # démarre ticker overlay si pas présent
            if gid not in self.ticker_tasks:
                self.ticker_tasks[gid] = self.bot.loop.create_task(self._ticker(gid))
        except Exception as e:
            await interaction_like.followup.send(f"❌ *Lecture impossible :* `{e}`")
            self.is_playing[gid] = False

    # ---------- Web helpers / auto-play (sans interaction Discord) ----------

    async def _autoplay_if_idle(self, gid: int) -> bool:
        """Démarre la lecture depuis la file si le bot est connecté et qu'aucun flux ne joue."""
        g = self.bot.get_guild(gid)
        vc = g.voice_client if g else None
        if not vc:
            return False
        if self.is_playing.get(gid, False):
            return True

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        item = await loop.run_in_executor(None, pm.pop_next)
        if not item:
            self.is_playing[gid] = False
            self.current_song.pop(gid, None)
            self.now_playing.pop(gid, None)
            self.emit_playlist_update(gid)
            return False

        item = self._normalize_like_api(item)
        self.current_song[gid] = item
        self.now_playing[gid] = item
        self.current_meta[gid] = {}

        url = item["url"]
        provider = item.get("provider") or _infer_provider_from_url(url) or "auto"
        mode = item.get("mode") or "auto"

        try:
            extractor = get_extractor(provider)
            source, meta = await extractor.stream_or_download(url, self.ffmpeg_path, mode=mode)
        except Exception as e:
            _greg_print(f"[autoplay] extraction error: {e} → on passe au suivant")
            return await self._autoplay_if_idle(gid)

        dur = meta.get("duration")
        if dur is not None:
            try:
                dur = int(dur)
            except Exception:
                pass
        self.current_meta[gid] = {"duration": dur, "thumbnail": meta.get("thumbnail")}

        def after_play(err):
            if err:
                _greg_print(f"[autoplay after] playback error: {err}")
            coro = self._autoplay_if_idle(gid)
            fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                _greg_print(f"[autoplay after] fut.result error: {e}")

        vc.play(source, after=after_play)
        self.is_playing[gid] = True
        self.play_start[gid] = time.monotonic()
        self.paused_since.pop(gid, None)
        self.paused_total[gid] = 0.0
        self.emit_playlist_update(gid)
        if gid not in self.ticker_tasks:
            self.ticker_tasks[gid] = self.bot.loop.create_task(self._ticker(gid))
        return True

    # ---------- Web API methods (utilisées par connect/app.py) ----------

    async def play_for_user(self, guild_id: int | str, user_id: int | str, item: dict):
        """Appelé par /api/play — insertion par priorité + autostart si possible."""
        gid = int(guild_id)
        uid = int(user_id)
        loop = asyncio.get_running_loop()
        pm = self.get_pm(gid)

        # enrichir l'item
        weight = get_member_weight(self.bot, gid, uid)
        item = dict(item or {})
        item["added_by"] = str(uid)
        item["priority"] = int(weight)
        item = self._normalize_like_api(item)

        # quota
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not can_bypass_quota(self.bot, gid, uid):
            if self._count_user_in_queue(queue, uid) >= PER_USER_CAP:
                raise PermissionError(f"Quota atteint ({PER_USER_CAP} pistes).")

        # insérer à la bonne place
        await loop.run_in_executor(None, pm.add, item)
        new_queue = await loop.run_in_executor(None, pm.get_queue)
        new_idx = len(new_queue) - 1
        target_idx = self._compute_insert_index(new_queue, int(item["priority"]))
        if target_idx != new_idx:
            await loop.run_in_executor(None, pm.move, new_idx, target_idx)

        # notifier + tenter de lancer si idle
        self.emit_playlist_update(gid)
        await self._autoplay_if_idle(gid)
        return True

    async def play_at_for_web(self, guild_id: int | str, requester_id: int | str, index: int):
        """Reorder sécurisé: déplace l'élément d'index 'index' en tête, si autorisé."""
        gid = int(guild_id)
        rid = int(requester_id)
        loop = asyncio.get_running_loop()
        pm = self.get_pm(gid)

        queue = await loop.run_in_executor(None, pm.get_queue)
        if not (0 <= index < len(queue)):
            raise IndexError("index hors bornes")

        it = queue[index] or {}
        owner_id = int(it.get("added_by") or 0)
        owner_weight = int(it.get("priority") or 0)

        # authorisé si: auteur == demandeur, poids plus élevé, ou admin
        if owner_id != rid and not can_user_bump_over(self.bot, gid, rid, owner_weight):
            raise PermissionError("Priorité insuffisante pour remonter cette piste.")

        ok = await loop.run_in_executor(None, pm.move, index, 0)
        if not ok:
            raise RuntimeError("Déplacement impossible.")

        self.emit_playlist_update(gid)
        return True

    async def pause_for_web(self, guild_id: int | str):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self.paused_since[gid] = time.monotonic()
            self.emit_playlist_update(gid)
            return True
        return False

    async def resume_for_web(self, guild_id: int | str):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_paused():
            vc.resume()
            if gid in self.paused_since:
                self.paused_total[gid] = self.paused_total.get(gid, 0.0) + (time.monotonic() - self.paused_since[gid])
                self.paused_since.pop(gid, None)
            self.emit_playlist_update(gid)
            return True
        return False

    async def stop_for_web(self, guild_id: int | str):
        gid = int(guild_id)
        pm = self.get_pm(gid)
        await asyncio.get_running_loop().run_in_executor(None, pm.clear)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        self.is_playing[gid] = False
        self.current_song.pop(gid, None)
        self.now_playing.pop(gid, None)
        self.emit_playlist_update(gid)
        return True

    async def skip_for_web(self, guild_id: int | str):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    async def toggle_pause_for_web(self, guild_id: int | str):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if not vc:
            return False
        if vc.is_paused():
            return await self.resume_for_web(gid)
        if vc.is_playing():
            return await self.pause_for_web(gid)
        return False

    async def restart_current_for_web(self, guild_id: int | str):
        """Remet la piste actuelle au début (on l’insère devant puis stop)."""
        gid = int(guild_id)
        cur = self.now_playing.get(gid) or self.current_song.get(gid)
        if not cur:
            return False
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        # re-ajoute en tête
        await loop.run_in_executor(None, pm.add, cur)
        q = await loop.run_in_executor(None, pm.get_queue)
        last = len(q) - 1
        if last >= 0:
            await loop.run_in_executor(None, pm.move, last, 0)
        # stop → after() lancera la suivante (qui est la même)
        await self.skip_for_web(gid)
        return True

    async def repeat_for_web(self, guild_id: int | str, mode: Optional[str] = None) -> bool:
        """Toggle/force repeat_all pour l’overlay. Retourne l'état."""
        gid = int(guild_id)
        cur = bool(self.repeat_all.get(gid, False))
        if not mode or mode == "toggle":
            nxt = not cur
        else:
            nxt = mode in ("on", "true", "1", "all")
        self.repeat_all[gid] = bool(nxt)
        self.emit_playlist_update(gid)
        return bool(nxt)

    # =====================================================================
    #                         Command helpers (Discord)
    # =====================================================================

    async def _do_skip(self, guild, send_fn):
        gid = self._gid(guild.id)
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await send_fn("⏭️ *On passe…*")
        else:
            await send_fn("🙄 *Rien à skipper.*")

    async def _do_stop(self, guild, send_fn):
        gid = self._gid(guild.id)
        pm = self.get_pm(gid)
        await asyncio.get_running_loop().run_in_executor(None, pm.clear)
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        self.is_playing[gid] = False
        self.current_song.pop(gid, None)
        self.now_playing.pop(gid, None)
        await send_fn("⏹️ *Tout le monde dehors.*")
        self.emit_playlist_update(gid)

    async def _do_pause(self, guild, send_fn):
        gid = self._gid(guild.id)
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self.paused_since[gid] = time.monotonic()
            await send_fn("⏸️ *Pause. Va boire de l’eau.*")
            self.emit_playlist_update(gid)
        else:
            await send_fn("🤨 *Déjà en pause… ou rien ne joue.*")

    async def _do_resume(self, guild, send_fn):
        gid = self._gid(guild.id)
        vc = guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            if gid in self.paused_since:
                self.paused_total[gid] = self.paused_total.get(gid, 0.0) + (time.monotonic() - self.paused_since[gid])
                self.paused_since.pop(gid, None)
            await send_fn("▶️ *Reprise.*")
            self.emit_playlist_update(gid)
        else:
            await send_fn("🤨 *Pas en pause.*")

    # ---------- Overlay payload / émission ----------

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
            print(f"[EMIT] playlist_update gid={gid} paused={payload.get('is_paused')} "
                  f"elapsed={payload.get('progress', {}).get('elapsed')} title={(payload.get('current') or {}).get('title')}")
            self.emit_fn("playlist_update", payload)

    async def _i_send(self, interaction: discord.Interaction, msg: str):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg)
        except Exception as e:
            _greg_print(f"[WARN] interaction send failed: {e}")

    # ---------- Détection ffmpeg ----------

    def detect_ffmpeg(self):
        FFMPEG_PATHS = [
            "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg",
            "ffmpeg", r"D:\Paul Berdier\ffmpeg\bin\ffmpeg.exe"
        ]
        for p in FFMPEG_PATHS:
            try:
                if os.path.exists(p) or p == "ffmpeg":
                    return p
            except Exception:
                pass
        return "ffmpeg"

    # ---------- Ticker overlay ----------

    async def _ticker(self, gid: int):
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
    _greg_print("✅ Cog 'Music' chargé — overlay enrichi + provider/mode + hiérarchie.")
