# commands/music.py
#
# Greg le Consanguin — Cog "Music"
# - Slash commands UNIQUEMENT (Discord)
# - Intégration overlay/web via emit_fn (fournie par main.py)
# - Émissions Socket.IO: état enrichi (queue, current, is_paused, progress, thumbnail, repeat_all)
# - Recherche YouTube/SoundCloud selon provider choisi (UI)
# - Extracteur auto par URL au moment de LIRE (robuste)
# - Priorités/quota + insertion ordonnée (priority_rules)

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
        self.managers = {}        # {guild_id(str): PlaylistManager}  (PlaylistManager indexé en str)
        # Etats internes indexés en INT (normalisés)
        self.is_playing = {}      # {guild_id(int): bool}
        self.current_song = {}    # {guild_id(int): dict(title,url,artist?,thumb?,duration?,added_by?,priority?)}
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
        self.now_playing = {}     # {guild_id(int): dict(title,url,artist,thumb,duration,added_by,priority)}

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
        if dct is None:
            return
        if gid_str in dct and gid_int not in dct:
            dct[gid_int] = dct.pop(gid_str)

    def get_pm(self, guild_id):
        gid_str = str(self._gid(guild_id))  # PlaylistManager indexé en str
        if gid_str not in self.managers:
            self.managers[gid_str] = PlaylistManager(gid_str)
            _greg_print(f"Nouvelle PlaylistManager pour la guild {gid_str}.")
        return self.managers[gid_str]

    # ---------- Normalisation/enrichissement des items ----------

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
        """Nettoie + complète les champs pour coller à l’API web/app.py."""
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
        # On conserve provider/mode si fournis (pour UI)
        for k in ("provider", "mode"):
            if k in item:
                norm[k] = item[k]
        # Champs overlay utiles
        for k in ("added_by", "priority", "ts"):
            if k in item:
                norm[k] = item[k]
        return norm

    # ---------- Priorités / insertion ordonnée ----------

    def _compute_insert_index(self, queue: list, new_weight: int) -> int:
        """
        Index d'insertion pour respecter l'ordre de priorité.
        Règle: devant la première piste dont le poids est STRICTEMENT inférieur.
        (Queue NE contient PAS la piste en cours → on parcourt depuis 0)
        """
        if not queue:
            return 0
        for i in range(len(queue)):
            try:
                w = int((queue[i] or {}).get("priority") or 0)
            except Exception:
                w = 0
            if new_weight > w:
                return i
        return len(queue)  # append à la fin

    def _count_user_in_queue(self, queue: list, user_id: int) -> int:
        uid = str(user_id)
        return sum(1 for it in (queue or []) if str(it.get("added_by")) == uid)

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

        # ✅ source de vérité : now_playing (Cog) > current_song (Cog) > pm.current (persisté)
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

        payload = {
            "queue": data.get("queue", []),
            "current": current,
            "is_paused": is_paused,
            "progress": {"elapsed": elapsed,
                         "duration": int(duration) if duration is not None else None},
            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(gid, False)),
        }
        return payload

    def emit_playlist_update(self, guild_id):
        gid = self._gid(guild_id)
        if self.emit_fn:
            payload = self._overlay_payload(gid)
            print(f"[EMIT] playlist_update gid={gid} paused={payload.get('is_paused')} "
                  f"elapsed={(payload.get('progress', {}) or {}).get('elapsed')} title={(payload.get('current') or {}).get('title')}")
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
            try:
                if path == "ffmpeg":
                    continue
                if os.path.exists(path) and os.access(path, os.X_OK):
                    _greg_print(f"🔥 FFmpeg détecté : {path}")
                    return path
            except Exception:
                pass
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
            chosen_provider = _infer_provider_from_url(cleaned) or (prov if prov != "auto" else None)
            # on garde provider/mode pour info UI, mais l'extracteur sera choisi par URL
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
                "artist": selected.get("artist") or selected.get("uploader"),
                "duration": selected.get("duration"),
                "thumb": selected.get("thumb") or selected.get("thumbnail"),
                "provider": selected.get("provider"),  # pour UI
                "mode": play_mode,                      # pour UI
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
        if 0 <= target_idx < len(new_queue) and target_idx != new_idx:
            ok = await loop.run_in_executor(None, pm.move, new_idx, target_idx)
            if not ok:
                _greg_print(f"[PlaylistManager {gid}] ❌ move invalide: src={new_idx}, dst={target_idx}, n={len(new_queue)}")

        await interaction_like.followup.send(
            f"🎵 Ajouté : **{item['title']}** ({item['url']}) — "
            f"{(item.get('provider') or 'auto')}/{(item.get('mode') or 'auto')}"
        )
        self.emit_playlist_update(gid)

        # Si rien ne joue → lancement play_next…
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
        # Sauvegarde d'un minimum d'infos (title/url) + méta (artist/thumb/duration/added_by/priority)
        self.current_song[gid] = {
            "title": item.get("title", url),
            "url": url,
            "artist": item.get("artist"),
            "thumb": item.get("thumb"),
            "duration": item.get("duration"),
            "added_by": item.get("added_by"),
            "priority": item.get("priority"),
        }
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
            "duration": self.current_meta[gid]["duration"],
            "added_by": item.get("added_by"),
            "priority": item.get("priority"),
        }

        # Premier emit pour que l’overlay voie tout de suite "current"
        self.emit_playlist_update(gid)

        _greg_print(f"[DEBUG play_next] Lecture via URL (extracteur auto) mode={play_mode} url={url}")

        # Choix extracteur par URL (robuste)
        extractor = get_extractor(url)
        print(f"extractor = {extractor}")
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
                self.current_song[gid]["title"] = real_title
                self.now_playing[gid]["title"] = real_title
                # Durée inconnue en stream
                self.current_meta[gid].update({"duration": None})

                if vc.is_playing():
                    vc.stop()

                def _after(e):
                    try:
                        getattr(source, "cleanup", lambda: None)()
                    finally:
                        # Enchaîne sur la suivante
                        self.bot.loop.create_task(self.play_next(interaction_like))

                try:
                    vc.play(source, after=_after)
                except Exception as e:
                    # Fallback direct si ffmpeg/stream choke (HLS, etc.)
                    _greg_print(f"[DEBUG play_next] vc.play(stream) KO → fallback download: {e}")
                    getattr(source, "cleanup", lambda: None)()
                    raise RuntimeError(e)

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
            # Cookies YT si dispo (ok pour YouTube; SoundCloud ignore ce paramètre)
            cookies = "youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None

            filename, real_title, duration = await extractor.download(
                url,
                ffmpeg_path=self.ffmpeg_path,
                cookies_file=cookies
            )

            self.current_song[gid]["title"] = real_title
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
        vc = guild.voice_client

        # ❗ Ne manipule pas la playlist ici. play_next() lira le prochain via pm.pop_next().
        await self._safe_send(send_fn, "⏭ *Et que ça saute !*")

        if vc and (vc.is_playing() or vc.is_paused()):
            # Cela déclenche l'after → play_next() → pm.pop_next()
            vc.stop()
        else:
            # Rien ne joue : on démarre simplement le prochain titre s'il y en a un.
            class FakeInteraction:
                def __init__(self, g):
                    self.guild = g
                    self.followup = self

                async def send(self, msg):
                    _greg_print(f"[WEB->Discord] {msg}")

            await self.play_next(FakeInteraction(guild))

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
            _greg_print(f"Greg rejoint le vocal {member.voice.channel.name} (via web API).")

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()

        # enrichir + normaliser + priorité/quotas
        item = dict(item or {})
        item["added_by"] = str(user_id)
        item = self._normalize_like_api(item)
        item["priority"] = int(get_member_weight(self.bot, gid, int(user_id)))

        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not can_bypass_quota(self.bot, gid, int(user_id)):
            if self._count_user_in_queue(queue, int(user_id)) >= PER_USER_CAP:
                _greg_print(f"[PlaylistManager {gid}] quota atteint ({PER_USER_CAP}) pour user={user_id}")
                return

        _greg_print(f"[DEBUG play_for_user] Queue avant ajout ({len(queue)}): {[it.get('title') for it in queue]}")
        await loop.run_in_executor(None, pm.add, item)
        new_queue = await loop.run_in_executor(None, pm.get_queue)
        _greg_print(f"[DEBUG play_for_user] Queue après ajout ({len(new_queue)}): {[it.get('title') for it in new_queue]}")

        # Repositionner selon la priorité
        new_idx = len(new_queue) - 1
        target_idx = self._compute_insert_index(new_queue, int(item["priority"]))
        if 0 <= target_idx < len(new_queue) and target_idx != new_idx:
            ok = await loop.run_in_executor(None, pm.move, new_idx, target_idx)
            if not ok:
                _greg_print(f"[PlaylistManager {gid}] ❌ move invalide: src={new_idx}, dst={target_idx}, n={len(new_queue)}")

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

        # autorisé si: auteur == demandeur, poids plus élevé, ou admin
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
        """Replace la piste courante en tête et redémarre (previous simple)."""
        gid = int(guild_id)
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
        q.insert(0, {
            "title": song.get("title"),
            "url": song.get("url"),
            "artist": song.get("artist"),
            "thumb": song.get("thumb"),
            "duration": song.get("duration"),
            "added_by": song.get("added_by"),
            "priority": song.get("priority"),
        })
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

    async def repeat_for_web(self, guild_id: int | str, mode: Optional[str] = None) -> bool:
        """mode: None -> toggle, 'on' -> True, 'off' -> False. Renvoie l'état final."""
        gid = int(guild_id)
        cur = bool(self.repeat_all.get(gid, False))
        if mode is None or mode == "" or mode == "toggle":
            nxt = not cur
        else:
            nxt = (mode in ("on", "true", "1", "all"))
        self.repeat_all[gid] = bool(nxt)
        self.emit_playlist_update(gid)
        return bool(nxt)

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
    _greg_print("✅ Cog 'Music' chargé — overlay enrichi + provider/mode + priorités (stream→download, extracteur auto par URL).")
