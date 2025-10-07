# commands/music.py
#
# Greg le Consanguin — Cog "Music"
# - Slash commands UNIQUEMENT (Discord)
# - Intégration overlay/web via emit_fn (fournie par main.py)
# - Émissions Socket.IO: état enrichi (queue, current, is_paused, progress, thumbnail, repeat_all)
# - Recherche YouTube/SoundCloud selon provider choisi (UI)
# - Extracteur auto par URL au moment de LIRE (robuste)
# - Priorités/quota + insertion ordonnée (priority_rules)
#
import os
import time
import asyncio
import inspect
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import requests
from urllib.parse import urlparse

from extractors import get_extractor, get_search_module, is_bundle_url, expand_bundle
from utils.playlist_manager import PlaylistManager

# Priorités (règles centralisées)
from utils.priority_rules import (
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
    u = u.strip('\'" \t\r\n')
    while u.endswith(';'):
        u = u[:-1]
    return u

# ---- Presets d'égalisation (FFmpeg -af) ----
# "music" = basses + normalisation dynamique + limiteur doux
AUDIO_EQ_PRESETS = {
    "off":   None,

    # Hip-hop / Phonk — EQ statique, aucun ride de volume
    # - highpass : enlève le sub (<30–35 Hz) qui déclenche le pumping
    # - volume -6 dB : crée de la marge pour le boost de basses (évite que le limiteur travaille)
    # - bass +4 dB vers 95 Hz : plus de coffre sans baver
    # - alimiter : attrape seulement un pic rarissime (attaque/release courts pour rester transparent)
    "music": "highpass=f=32,volume=-6dB,bass=g=4:f=95:w=1.0,alimiter=limit=0.98:attack=5:release=50",
}


# === JOIN SFX ===
# MP3 joué automatiquement à CHAQUE connexion au vocal
JOIN_SFX_CANDIDATES = [
    os.path.join("assets", "Ouais_c’est_greg.mp3"),     # avec apostrophe typographique
    os.path.join("assets", "Ouais_c'est_greg.mp3"),     # apostrophe ASCII
    os.path.join("assets", "Ouais_cest_greg.mp3"),      # sans apostrophe
]
JOIN_SFX_ENV = os.getenv("GREG_JOIN_SFX")  # permet de surcharger le chemin si besoin
JOIN_SFX_VOLUME = float(os.getenv("GREG_JOIN_SFX_VOLUME", "1.6"))  # 1.0=normal, 1.6≈+4 dB, 2.0≈+6 dB
JOIN_SFX_DELAY  = float(os.getenv("GREG_JOIN_SFX_DELAY", "4"))     # secondes

class Music(commands.Cog):
    """
    Cog musical unique.
    - Une PlaylistManager PAR guild (persistée en JSON)
    - is_playing/current_song PAR guild
    - emit_fn(optionnel) : fonction injectée par main.py pour pousser l'état à l'overlay via Socket.IO
    """
    def __init__(self, bot, emit_fn=None):
        self.bot = bot
        self.managers = {}        # {guild_id(str): PlaylistManager}
        self.is_playing = {}      # {guild_id(int): bool}
        self.current_song = {}    # {guild_id(int): dict(title,url,artist?,thumb?,duration?,added_by?,priority?)}
        self._locks = {}          # {guild_id:int -> asyncio.Lock} (anti double play_next)
        self.search_results = {}  # {user_id: last_results}
        self.audio_mode = {}      # {guild_id:int -> "music" | "off"}
        self.ffmpeg_path = self.detect_ffmpeg()
        self.emit_fn = emit_fn

        # --- Suivi overlay ---
        self.play_start = {}
        self.paused_since = {}
        self.paused_total = {}
        self.ticker_tasks = {}
        self.current_meta = {}
        self.repeat_all = {}
        self.now_playing = {}
        self.current_source = {}   # {guild_id: FFmpegPCMAudio} (pour tuer un stream en cours)

        # Ticker de progression par guilde (évite doublons)
        self._progress_task = {}  # {gid: asyncio.Task}

        # --- Cookies YouTube ---
        # Sur Railway on s'appuie sur le fichier déposé par /yt_cookies_update
        self.cookies_from_browser = None  # (optionnel en local)
        self.youtube_cookies_file = (
                os.getenv("YTDLP_COOKIES_FILE")
                or ("youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None)
        )

        # --- yt-dlp rate limit (optionnel, ENV) ---
        try:
            self.yt_ratelimit = int(os.getenv("YTDLP_LIMIT_BPS", "2500000"))
        except Exception:
            self.yt_ratelimit = 2_500_000

        _greg_print(f"[YT cookies] file={self.youtube_cookies_file or 'none'}")
        _greg_print("Initialisation du cog Music… *Quelle joie contenue…*")

    # ---------- Utilitaires ----------

    @staticmethod
    def _gid(v) -> int:
        try:
            return int(v)
        except Exception:
            return int(str(v))

    def _migrate_keys_to_int(self, dct, gid_int):
        gid_str = str(gid_int)
        if dct is None:
            return
        if gid_str in dct and gid_int not in dct:
            dct[gid_int] = dct.pop(gid_str)

    def get_pm(self, guild_id):
        gid_str = str(self._gid(guild_id))
        if gid_str not in self.managers:
            self.managers[gid_str] = PlaylistManager(gid_str)
            _greg_print(f"Nouvelle PlaylistManager pour la guild {gid_str}.")
        return self.managers[gid_str]

    def _get_current_owner_id(self, gid: int) -> int:
        try:
            cur = (self.current_song.get(gid) or {})  # source de vérité côté web
            return int(cur.get("added_by") or 0)
        except Exception:
            return 0

    def _get_audio_mode(self, guild_id: int) -> str:
        gid = self._gid(guild_id)
        # défaut = "music" (mode musique activé)
        return self.audio_mode.get(gid, "music")

    def _afilter_for(self, guild_id: int) -> str | None:
        return AUDIO_EQ_PRESETS.get(self._get_audio_mode(guild_id))

    # ---------- Normalisation/enrichissement des items ----------

    def _to_seconds(self, v):
        if v is None:
            return None
        try:
            iv = int(v)
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
        for k in ("added_by", "priority", "ts"):
            if k in item:
                norm[k] = item[k]
        return norm

    # ---------- Priorités / insertion ordonnée ----------

    def _compute_insert_index(self, queue: list, new_weight: int) -> int:
        if not queue:
            return 0
        for i in range(len(queue)):
            try:
                w = int((queue[i] or {}).get("priority") or 0)
            except Exception:
                w = 0
            if new_weight > w:
                return i
        return len(queue)

    def _count_user_in_queue(self, queue: list, user_id: int) -> int:
        uid = str(user_id)
        return sum(1 for it in (queue or []) if str(it.get("added_by")) == uid)

    def _compute_elapsed(self, gid: int) -> int:
        start = self.play_start.get(gid)
        if not start:
            return 0
        paused_since = self.paused_since.get(gid)
        paused_total = self.paused_total.get(gid, 0.0)
        base = paused_since or time.monotonic()
        return max(0, int(base - start - paused_total))

    # ---------- TICKER (progress) ----------
    def _ticker_running(self, gid: int) -> bool:
        t = self._progress_task.get(gid)
        return bool(t and not t.done())

    def _cancel_ticker(self, gid: int):
        t = self._progress_task.pop(gid, None)
        if t and not t.done():
            t.cancel()

    def _ensure_ticker(self, gid: int):
        if self._ticker_running(gid):
            return

        async def _runner():
            try:
                while True:
                    g = self.bot.get_guild(int(gid))
                    vc = g.voice_client if g else None
                    if not vc or (not vc.is_playing() and not vc.is_paused()):
                        break

                    # Envoie un payload *minimal* pour ne mettre à jour que la progression côté overlay
                    try:
                        # Calcul d'elapsed depuis play_start / paused_since / paused_total
                        start = self.play_start.get(gid)
                        paused_since = self.paused_since.get(gid)
                        paused_total = self.paused_total.get(gid, 0.0)
                        if start:
                            base = paused_since or time.monotonic()
                            elapsed = max(0, int(base - start - paused_total))
                        else:
                            elapsed = 0

                        # Durée depuis les métadonnées connues
                        duration = None
                        meta = self.current_meta.get(gid, {}) or {}
                        if isinstance(meta.get("duration"), (int, float)):
                            duration = int(meta["duration"])
                        else:
                            cur = self.current_song.get(gid) or {}
                            d = cur.get("duration")
                            if isinstance(d, (int, float)):
                                duration = int(d)

                        g = self.bot.get_guild(int(gid))
                        vc = g.voice_client if g else None

                        payload = {
                            "guild_id": gid,
                            "only_elapsed": True,
                            "is_paused": bool(vc and vc.is_paused()),
                            "progress": { "elapsed": elapsed, "duration": duration },
                        }

                        if self.emit_fn:
                            try:
                                self.emit_fn("playlist_update", payload, guild_id=gid)
                            except TypeError:
                                self.emit_fn("playlist_update", payload)
                    except Exception:
                        pass

                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass
            finally:
                self._progress_task.pop(gid, None)

        self._progress_task[gid] = asyncio.create_task(_runner())

    # ---------- Overlay payload ----------

    def _overlay_payload(self, guild_id: int) -> dict:
        """
        Source de vérité pour l'overlay.
        - N'EXCLUT plus 'current' quand le vocal n'a pas encore démarré, si on sait
          qu'un play est en cours/pending (is_playing/current_song/now_playing).
        - Progression calculée avec play_start / paused_since / paused_total.
        - Métadonnées fusionnées avec current_meta si dispo.
        """
        gid = self._gid(guild_id)

        # Harmonise les clés sur int
        for d in (
                self.is_playing, self.current_song, self.play_start,
                self.paused_since, self.paused_total, self.current_meta,
                self.repeat_all, getattr(self, "now_playing", {})
        ):
            self._migrate_keys_to_int(d, gid)

        pm = self.get_pm(gid)
        data = pm.to_dict()

        # État du voice client
        try:
            g = self.bot.get_guild(gid)
            vc = g.voice_client if g else None
        except Exception:
            vc = None

        is_paused_vc = bool(vc and vc.is_paused())
        is_playing_vc = bool(vc and vc.is_playing())
        voice_active = is_paused_vc or is_playing_vc

        # Candidat "current" (ordre: now_playing → current_song → PM)
        nowp = getattr(self, "now_playing", {})
        current = nowp.get(gid) or self.current_song.get(gid) or data.get("current")

        # Nouveau critère: on montre 'current' si on a une intention claire de jouer,
        # pas uniquement quand le voice est actif.
        should_show_current = (
                voice_active
                or bool(self.is_playing.get(gid, False))
                or bool(self.current_song.get(gid))
                or bool(nowp.get(gid))
        )

        if not should_show_current:
            # vocal inactif ET pas d'intention → pas de current
            current = None
            elapsed = 0
            duration = None
            thumb = None
        else:
            # Progression
            start = self.play_start.get(gid)
            paused_since = self.paused_since.get(gid)
            paused_total = self.paused_total.get(gid, 0.0)
            elapsed = 0
            if start:
                base = paused_since or time.monotonic()
                elapsed = max(0, int(base - start - paused_total))

            # Métadonnées
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
            "is_paused": is_paused_vc,
            "progress": {
                "elapsed": elapsed,
                "duration": int(duration) if duration is not None else None
            },
            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(gid, False)),
        }
        return payload

    # === JOIN SFX ===
    def _find_join_sfx_path(self) -> Optional[str]:
        """
        Résout le chemin du SFX de join :
        - variable d'env GREG_JOIN_SFX prioritaire
        - sinon on teste plusieurs variantes dans assets/
        """
        cand = []
        if JOIN_SFX_ENV:
            cand.append(JOIN_SFX_ENV)
        cand.extend(JOIN_SFX_CANDIDATES)
        for p in cand:
            try:
                if p and os.path.exists(p) and os.path.isfile(p):
                    return p
            except Exception:
                pass
        return None

    async def _play_join_sfx(self, guild: discord.Guild):
        try:
            vc = guild.voice_client
            if not vc or not vc.is_connected():
                return

            sfx = self._find_join_sfx_path()
            if not sfx:
                _greg_print("[JOIN SFX] aucun fichier trouvé (configuré ou assets/).")
                return

            # --- Délai avant de jouer (par ex. 4 s)
            if JOIN_SFX_DELAY > 0:
                await asyncio.sleep(JOIN_SFX_DELAY)
                # Entre-temps, de la musique a peut-être démarré → on ne force pas
                vc = guild.voice_client
                if not vc or not vc.is_connected() or vc.is_playing() or vc.is_paused():
                    _greg_print("[JOIN SFX] ignoré après délai: lecture déjà en cours.")
                    return

            # Options FFmpeg "propres" pour Discord
            opts = "-vn -ar 48000 -ac 2"
            try:
                base = discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=sfx, options=opts)
            except Exception as e:
                _greg_print(f"[JOIN SFX] FFmpegPCMAudio KO: {e}")
                return

            # --- Gain (1.0=normal). 1.6 ≈ +4 dB ; 2.0 ≈ +6 dB
            source = discord.PCMVolumeTransformer(base, volume=JOIN_SFX_VOLUME)
            gid = self._gid(guild.id)

            def _after(e: Exception | None):
                async def _resume():
                    try:
                        pm = self.get_pm(gid)
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, pm.reload)
                        q = await loop.run_in_executor(None, pm.get_queue)
                        if q and not self.is_playing.get(gid, False):
                            class FakeInteraction:
                                def __init__(self, g): self.guild = g; self.followup = self

                                async def send(self, msg): _greg_print(f"[JOIN SFX→Discord] {msg}")

                            await self.play_next(FakeInteraction(guild))
                    except Exception as ex2:
                        _greg_print(f"[JOIN SFX] resume fail: {ex2}")

                try:
                    # ✅ planifie la reprise sur l'event loop du bot depuis ce thread
                    fut = asyncio.run_coroutine_threadsafe(_resume(), self.bot.loop)

                    # (optionnel) log en cas d’exception dans la task:
                    def _done(f):
                        ex = f.exception()
                        if ex:
                            _greg_print(f"[JOIN SFX] resume task raised: {ex}")

                    fut.add_done_callback(_done)
                except Exception as ex_sched:
                    _greg_print(f"[JOIN SFX] schedule fail: {ex_sched}")

            vc.play(source, after=_after)
            _greg_print(f"[JOIN SFX] playing (vol={JOIN_SFX_VOLUME}, delay={JOIN_SFX_DELAY}s): {sfx}")
        except Exception as e:
            _greg_print(f"[JOIN SFX] erreur: {e}")

    async def _enqueue_bundle_after_first(self, interaction_like, first_item: dict, bundle: list[dict]):
        """
        Ajoute 'first_item' via le chemin normal (quota + insertion par priorité),
        puis pousse le reste du bundle à la suite (en respectant le quota restant).
        """
        gid = self._gid(interaction_like.guild.id)
        uid = int((getattr(interaction_like, "user", None) or getattr(interaction_like, "author", None)).id)

        # Ajout de la 1ère (logique habituelle)
        await self.add_to_queue(interaction_like, first_item)

        # Si rien d’autre → fini
        extras = (bundle or [])[1:]
        if not extras:
            return

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        # Quota restant
        if not can_bypass_quota(self.bot, gid, uid):
            already = self._count_user_in_queue(queue, uid)
            remaining = max(0, PER_USER_CAP - already)
            if remaining <= 0:
                return
            extras = extras[:remaining]

        # Pose le même poids sur chaque item avant add_many
        w = get_member_weight(self.bot, gid, uid)
        for it in extras:
            it["added_by"] = str(uid)
            it["priority"] = int(w)

        if extras:
            await loop.run_in_executor(None, pm.add_many, extras, str(uid))
            self.emit_playlist_update(gid)

    def emit_playlist_update(self, guild_id, payload=None):
        gid = self._gid(guild_id)
        if not self.emit_fn:
            return

        # payload complet par défaut
        if payload is None:
            payload = self._overlay_payload(gid)

        payload["guild_id"] = gid

        try:
            # nouvelle signature (avec kwargs)
            self.emit_fn("playlist_update", payload, guild_id=gid)
        except TypeError:
            # compat ancienne signature
            self.emit_fn("playlist_update", payload)

        try:
            print(
                f"[EMIT] playlist_update gid={gid} "
                f"paused={payload.get('is_paused')} "
                f"elapsed={(payload.get('progress') or {}).get('elapsed')} "
                f"title={(payload.get('current') or {}).get('title')} "
                f"only_elapsed={payload.get('only_elapsed', False)}"
            )
        except Exception:
            pass

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

    # ---------- Verrouillage par guilde ----------

    def _guild_lock(self, gid: int):
        lock = self._locks.get(gid)
        if not lock:
            lock = asyncio.Lock()
            self._locks[gid] = lock
        return lock

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
                # === JOIN SFX ===
                await self._play_join_sfx(interaction.guild)
            else:
                return await interaction.followup.send("❌ *Tu n'es même pas en vocal, vermine…*")

        # URL directe
        if query_or_url.startswith(("http://", "https://")):
            cleaned = _clean_url(query_or_url)
            chosen_provider = _infer_provider_from_url(cleaned) or (prov if prov != "auto" else None)

            # 🔁 Si l’URL est une playlist/mix supportée → on déplie (10)
            if is_bundle_url(cleaned):
                try:
                    bundle = expand_bundle(
                        cleaned,
                        limit=10,
                        cookies_file=self.youtube_cookies_file,
                        cookies_from_browser=self.cookies_from_browser,
                    )
                except Exception as e:
                    _greg_print(f"[bundle] expand error: {e}")
                    bundle = []

                if bundle:
                    first = {**bundle[0], "mode": play_mode}
                    await self._enqueue_bundle_after_first(interaction, first, bundle)
                    return
                else:
                    # Feedback explicite si la playlist/mix est vide inaccessible
                    try:
                        await interaction.followup.send("Playlist/Mix introuvable")
                    except Exception:
                        pass
            # sinon: ajout simple
            await self.add_to_queue(
                interaction,
                {"title": cleaned, "url": cleaned, "provider": chosen_provider, "mode": play_mode},
            )
            return

        # Recherche selon provider (auto -> YT d'abord)
        chosen = prov
        if chosen == "auto":
            chosen = "youtube"

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
                other = "soundcloud" if chosen == "youtube" else "youtube"
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
            self.search_results.pop(interaction.user.id, None)  # purge
            sel_url = _clean_url(selected.get("webpage_url", selected.get("url")))
            await self.add_to_queue(interaction, {
                "title": selected.get("title", "Titre inconnu"),
                "url": sel_url,
                "artist": selected.get("artist") or selected.get("uploader"),
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

    @app_commands.describe(mode="on/off (vide pour basculer)")
    @app_commands.command(
        name="musicmode",
        description="Active/désactive le rendu 'musique' (stéréo + basses + normalisation)."
    )
    async def slash_musicmode(self, interaction: discord.Interaction, mode: str | None = None):
        gid = self._gid(interaction.guild.id)
        cur = self._get_audio_mode(gid)

        mode = (mode or "").strip().lower()
        if mode not in ("", "on", "off"):
            return await self._i_send(interaction, "⚠️ Utilise: `/musicmode` (toggle) ou `/musicmode on|off`")

        new_mode = ("off" if cur != "off" else "music") if mode == "" else ("music" if mode == "on" else "off")
        self.audio_mode[gid] = new_mode

        await self._i_send(interaction, f"🎚️ Mode musique: **{'ON' if new_mode == 'music' else 'OFF'}**")

        g = interaction.guild
        vc = g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            # au lieu de: vc.stop()
            await self.restart_current_for_web(g.id)

    # =====================================================================
    #                         Actions internes factorisées
    # =====================================================================

    # --- helpers extracteur (compat sync/async et kwargs souples) ---
    def _extractor_kwargs(self, extractor_module, method_name: str, **maybe):
        fn = getattr(extractor_module, method_name, None)
        if not fn:
            return {}
        try:
            sig = inspect.signature(fn)
            return {k: v for k, v in (maybe or {}).items() if k in sig.parameters}
        except (TypeError, ValueError):
            return {}

    async def _call_extractor(self, extractor_module, method_name: str, *args, **kwargs):
        fn = getattr(extractor_module, method_name)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    def _unpack_download_result(self, res, fallback_title: str):
        if isinstance(res, tuple):
            if len(res) >= 3:
                return res[0], res[1], res[2]
            if len(res) == 2:
                return res[0], res[1], None
            return res[0], fallback_title, None
        return res, fallback_title, None

    def _kill_stream_proc(self, gid: int):
        src = self.current_source.pop(gid, None)
        if not src:
            return
        try:
            proc = getattr(src, "_ytdlp_proc", None)
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            getattr(src, "cleanup", lambda: None)()
        except Exception:
            pass

    async def add_to_queue(self, interaction_like, item):
        gid = self._gid(interaction_like.guild.id)

        try:
            if interaction_like and getattr(interaction_like, "user", None):
                item["added_by"] = str(interaction_like.user.id)
        except Exception:
            pass
        item = self._normalize_like_api(item)

        w = get_member_weight(self.bot, gid, int(item.get("added_by") or 0))
        item["priority"] = int(w)

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        if not can_bypass_quota(self.bot, gid, int(item.get("added_by") or 0)):
            if self._count_user_in_queue(queue, int(item.get("added_by") or 0)) >= PER_USER_CAP:
                return await interaction_like.followup.send(f"⛔ *Quota atteint ({PER_USER_CAP} pistes).*")

        await loop.run_in_executor(None, pm.add, item)
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

        if not self.is_playing.get(gid, False):
            _greg_print(f"[DEBUG add_to_queue] Rien ne joue encore, lancement play_next…")
            await self.play_next(interaction_like)

    async def play_next(self, interaction_like):
        """
        Lit la piste suivante :
        1) tente STREAM direct (FFmpeg URL directe)
        2) si échec → fallback STREAM_PIPE (yt-dlp → FFmpeg via pipe)
        - Sérialisation par guilde pour éviter les doublons
        - Repeat ALL géré
        """
        gid = self._gid(interaction_like.guild.id)
        pm = self.get_pm(gid)

        # -------- Verrou par guilde --------
        lock = self._guild_lock(gid)

        async with lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, pm.reload)

            # si déjà en lecture → ne pas relancer
            try:
                vc = interaction_like.guild.voice_client
                if vc and (vc.is_playing() or vc.is_paused()):
                    _greg_print(f"[DEBUG play_next] Ignoré: déjà en cours sur guild={gid}")
                    return
            except Exception:
                pass

            vc = interaction_like.guild.voice_client
            if not vc:
                try:
                    await interaction_like.followup.send("❌ *Pas de connexion vocale active.*")
                except Exception:
                    pass
                return

            # Pop suivant
            item = await loop.run_in_executor(None, pm.pop_next)
            if not item:
                self.is_playing[gid] = False
                _greg_print(f"[DEBUG play_next] Queue VIDE → arrêt")
                try:
                    await interaction_like.followup.send("📍 *Plus rien à jouer. Enfin une pause…*")
                except Exception:
                    pass
                # Nettoyage état
                for d in (self.current_song, self.play_start, self.paused_since,
                          self.paused_total, self.current_meta, getattr(self, "now_playing", {})):
                    try:
                        d.pop(gid, None)
                    except Exception:
                        pass
                self.emit_playlist_update(gid)
                return

            _greg_print(f"[DEBUG play_next] ITEM sélectionné: {item}")

            # Repeat all → remettre la piste en fin
            if self.repeat_all.get(gid):
                await loop.run_in_executor(None, pm.add, item)
                _greg_print("[DEBUG play_next] Repeat ALL actif → remis en fin de file")

            self.is_playing[gid] = True

            url = item.get("url")
            # État courant + méta min
            self.current_song[gid] = {
                "title": item.get("title", url),
                "url": url,
                "artist": item.get("artist"),
                "thumb": item.get("thumb"),
                "duration": item.get("duration"),
                "added_by": item.get("added_by"),
                "priority": item.get("priority"),
            }
            dur_int = int(item["duration"]) if isinstance(item.get("duration"), (int, float)) else None
            self.current_meta[gid] = {"duration": dur_int, "thumbnail": item.get("thumb")}
            self.now_playing[gid] = {
                "title": self.current_song[gid]["title"],
                "url": url,
                "artist": item.get("artist"),
                "thumb": item.get("thumb"),
                "duration": dur_int,
                "added_by": item.get("added_by"),
                "priority": item.get("priority"),
            }
            self.emit_playlist_update(gid)

            # Choix extracteur
            extractor = get_extractor(url)
            if extractor is None:
                try:
                    await interaction_like.followup.send("❌ *Aucun extracteur ne veut de ta soupe…*")
                except Exception:
                    pass
                # enchaîne la suivante
                asyncio.create_task(self.play_next(interaction_like))
                return

            # kwargs communs
            kwp = self._extractor_kwargs(
                extractor, "stream",
                cookies_file=self.youtube_cookies_file,
                cookies_from_browser=self.cookies_from_browser,
                ratelimit_bps=self.yt_ratelimit,
                afilter=self._afilter_for(gid),
            )

            # 1) STREAM direct
            try:
                srcp, real_title = await self._call_extractor(
                    extractor, "stream", url, self.ffmpeg_path, **kwp
                )
                if real_title and isinstance(real_title, str):
                    self.current_song[gid]["title"] = real_title
                    self.now_playing[gid]["title"] = real_title

                vc2 = interaction_like.guild.voice_client
                if vc2 and (vc2.is_playing() or vc2.is_paused()):
                    vc2.stop()

                self.current_source[gid] = srcp

                def _after_direct(e: Exception | None):
                    try:
                        self._kill_stream_proc(gid)
                    finally:
                        try:
                            self.current_source.pop(gid, None)
                        except Exception:
                            pass
                        asyncio.run_coroutine_threadsafe(self.play_next(interaction_like), self.bot.loop)

                vc.play(srcp, after=_after_direct)

                self._cancel_ticker(gid)
                self.play_start[gid] = time.monotonic()
                self.paused_total[gid] = 0.0
                self.paused_since.pop(gid, None)
                self._ensure_ticker(gid)

                try:
                    await interaction_like.followup.send(
                        f"▶️ *Streaming (direct)* : **{self.current_song[gid]['title']}**")
                except Exception:
                    pass
                self.emit_playlist_update(gid)
                return

            except Exception as ex_direct:
                _greg_print(f"[DEBUG stream direct KO] {ex_direct}")

            # 2) Fallback STREAM_PIPE
            try:
                # réutilise les mêmes kwargs mais pour stream_pipe (mêmes noms)
                kwp_pipe = self._extractor_kwargs(
                    extractor, "stream_pipe",
                    cookies_file=self.youtube_cookies_file,
                    cookies_from_browser=self.cookies_from_browser,
                    ratelimit_bps=self.yt_ratelimit,
                    afilter=self._afilter_for(gid),
                )

                srcp, real_title = await self._call_extractor(
                    extractor, "stream_pipe", url, self.ffmpeg_path, **kwp_pipe
                )

                if real_title and isinstance(real_title, str):
                    self.current_song[gid]["title"] = real_title
                    self.now_playing[gid]["title"] = real_title

                vc2 = interaction_like.guild.voice_client
                if vc2 and (vc2.is_playing() or vc2.is_paused()):
                    vc2.stop()

                self.current_source[gid] = srcp

                def _after_pipe(e: Exception | None):
                    try:
                        self._kill_stream_proc(gid)
                    finally:
                        try:
                            self.current_source.pop(gid, None)
                        except Exception:
                            pass
                        asyncio.run_coroutine_threadsafe(self.play_next(interaction_like), self.bot.loop)

                vc.play(srcp, after=_after_pipe)

                self._cancel_ticker(gid)
                self.play_start[gid] = time.monotonic()
                self.paused_total[gid] = 0.0
                self.paused_since.pop(gid, None)
                self._ensure_ticker(gid)

                try:
                    await interaction_like.followup.send(
                        f"▶️ *Streaming (pipe)* : **{self.current_song[gid]['title']}**")
                except Exception:
                    pass
                self.emit_playlist_update(gid)
                return

            except Exception as ex_pipe:
                _greg_print(f"[DEBUG stream_pipe KO] {ex_pipe}")
                try:
                    await interaction_like.followup.send(f"⚠️ *Stream KO (direct+pipe).* `{ex_pipe}`")
                except Exception:
                    pass
                asyncio.create_task(self.play_next(interaction_like))
                return

    async def _do_skip(self, guild: discord.Guild, send_fn):
        gid = self._gid(guild.id)
        vc = guild.voice_client

        await self._safe_send(send_fn, "⏭ *Et que ça saute !*")

        if vc and (vc.is_playing() or vc.is_paused()):
            self._kill_stream_proc(gid)
            vc.stop()  # after -> play_next
        else:
            # kill éventuel stream zombie
            self._kill_stream_proc(gid)

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
        # assassine tout process yt-dlp restant
        self._kill_stream_proc(gid)

        self.current_song.pop(gid, None)
        self.is_playing[gid] = False
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
            self.emit_playlist_update(gid)  # pousse l'état tout de suite
            await self._safe_send(send_fn, "⏸ *Enfin une pause…*")
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
        import asyncio, time
        t0 = time.monotonic()
        gid = self._gid(guild_id)

        def _sum_item(it):
            try:
                return f"title={it.get('title')!r}, artist={it.get('artist')!r}, dur={it.get('duration')}, url={it.get('url')!r}, prio={it.get('priority')}, by={it.get('added_by')}"
            except Exception:
                return repr(it)

        _greg_print("=" * 72)
        _greg_print(f"[play_for_user] START guild={gid}, user={user_id}")
        _greg_print(f"[play_for_user] RAW item: {item}")

        guild = self.bot.get_guild(gid)
        if not guild:
            _greg_print("[play_for_user] ❌ Serveur introuvable.")
            return

        member = guild.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            _greg_print("[play_for_user] ❌ Utilisateur pas en vocal.")
            return {"ok": False, "error_code": "USER_NOT_IN_VOICE", "message": "Tu dois être en vocal."}
        _greg_print(f"[play_for_user] ✔️ User voice channel: {member.voice.channel.name}")

        vc = guild.voice_client
        if not vc or not vc.is_connected():
            try:
                _greg_print(f"[play_for_user] 🔌 Connexion au vocal {member.voice.channel.name}…")
                await member.voice.channel.connect()
                _greg_print("[play_for_user] 🔌 Connecté.")
                # === JOIN SFX ===
                await self._play_join_sfx(guild)
            except Exception as e:
                _greg_print(f"[play_for_user] ❌ Connexion vocal échouée: {e}")
                return {"ok": False, "error_code": "VOICE_CONNECT_FAILED",
                        "message": "Impossible de rejoindre le vocal."}

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()

        # enrichir + normaliser + priorité/quotas (pour l'ITEM COURANT)
        item = dict(item or {})
        item["added_by"] = str(user_id)
        _greg_print(f"[play_for_user] ↪ avant normalize: {_sum_item(item)}")
        item = self._normalize_like_api(item)
        _greg_print(f"[play_for_user] ↪ après  normalize: {_sum_item(item)}")

        weight = int(get_member_weight(self.bot, gid, int(user_id)))
        item["priority"] = weight
        _greg_print(f"[play_for_user] priorité calculée (weight) = {weight}")

        # État playlist courant
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)
        _greg_print(f"[play_for_user] Etat queue AVANT ajout: n={len(queue)}")
        try:
            cnt_user = self._count_user_in_queue(queue, int(user_id))
        except Exception as e:
            cnt_user = -1
            _greg_print(f"[play_for_user] (warn) _count_user_in_queue KO: {e}")
        _greg_print(f"[play_for_user] Items de l'utilisateur dans la queue (avant): {cnt_user} (cap={PER_USER_CAP})")

        # Quota : on compte AVANT ajout (l'item courant prendra 1 slot)
        if not can_bypass_quota(self.bot, gid, int(user_id)):
            if cnt_user >= PER_USER_CAP:
                _greg_print(f"[play_for_user] ❌ Quota atteint ({PER_USER_CAP}) pour user={user_id}")
                return

        # === Détection playlist/mix et expansion (10 éléments) ===
        page_url = item.get("url") or ""
        is_bundle = is_bundle_url(page_url)
        _greg_print(f"[play_for_user] bundle? {is_bundle} — url={page_url!r}")

        bundle_entries = []
        if is_bundle:
            _greg_print("[play_for_user] 🧩 Expansion playlist/mix (expand_bundle)…")
            try:
                bundle_entries = expand_bundle(
                    page_url,
                    limit=10,
                    cookies_file=self.youtube_cookies_file,
                    cookies_from_browser=self.cookies_from_browser,
                ) or []
                _greg_print(f"[play_for_user] 🧩 expand_bundle → {len(bundle_entries)} entrées")
                if bundle_entries[:3]:
                    _greg_print("[play_for_user] 🧩 premiers éléments: " + " | ".join(
                        (be.get("title") or "?") for be in bundle_entries[:3]
                    ))
            except Exception as e:
                _greg_print(f"[play_for_user] 🧩 expand_bundle failed: {e}")
                bundle_entries = []

            if bundle_entries:
                head = bundle_entries[0]  # ★ la piste à jouer tout de suite
                _greg_print("[play_for_user] 🧩 head (1ère piste) = " + _sum_item(head))
                # on remplace l'URL/les méta de l'item courant par la 1ʳᵉ entrée
                item["title"] = head.get("title") or item.get("title")
                item["url"] = head.get("url") or item.get("url")
                item["artist"] = head.get("artist")
                item["thumb"] = head.get("thumb")
                item["duration"] = head.get("duration")
                _greg_print(f"[play_for_user] 🧩 item remplacé par head: {_sum_item(item)}")

        # 1) Ajout de l'item courant (avec insertion selon priorité)
        _greg_print(f"[play_for_user] ➕ Ajout de l'item courant…")
        _greg_print(f"[play_for_user]    item final: {_sum_item(item)}")
        await loop.run_in_executor(None, pm.add, item)

        new_queue = await loop.run_in_executor(None, pm.get_queue)
        _greg_print(f"[play_for_user] Etat queue APRÈS ajout: n={len(new_queue)}")
        try:
            cnt_user_after = self._count_user_in_queue(new_queue, int(user_id))
        except Exception as e:
            cnt_user_after = -1
            _greg_print(f"[play_for_user] (warn) _count_user_in_queue après ajout KO: {e}")
        _greg_print(f"[play_for_user] Items de l'utilisateur (après) : {cnt_user_after}/{PER_USER_CAP}")

        new_idx = len(new_queue) - 1
        target_idx = self._compute_insert_index(new_queue, weight)
        _greg_print(
            f"[play_for_user] 🎯 insert rebalancing: new_idx={new_idx}, target_idx={target_idx}, n={len(new_queue)}")
        if 0 <= target_idx < len(new_queue) and target_idx != new_idx:
            ok = await loop.run_in_executor(None, pm.move, new_idx, target_idx)
            _greg_print(f"[play_for_user]   move({new_idx}->{target_idx}) → {ok}")
            if not ok:
                _greg_print(f"[play_for_user] ⚠️ move invalide: src={new_idx}, dst={target_idx}, n={len(new_queue)}")

        # 2) Si c'est une playlist/mix → enfile les 9 suivantes (respect du quota)
        extras = []
        if is_bundle:
            # on réutilise le résultat déjà calculé
            extras = bundle_entries[1:10]
            _greg_print(f"[play_for_user] 🧩 extras init (après head): {len(extras)}")

            if extras:
                for it in extras:
                    it["added_by"] = str(user_id)
                    it["priority"] = weight

                remaining = PER_USER_CAP
                if not can_bypass_quota(self.bot, gid, int(user_id)):
                    remaining = max(0, PER_USER_CAP - self._count_user_in_queue(new_queue, int(user_id)))
                _greg_print(f"[play_for_user] 🧮 slots restants (quota) = {remaining}")

                extras = extras[:remaining] if remaining > 0 else []
                _greg_print(f"[play_for_user] 🧩 extras après quota-cut: {len(extras)}")

                if extras:
                    try:
                        await loop.run_in_executor(None, pm.add_many, extras, str(user_id))
                        _greg_print(f"[play_for_user] 🧩 +{len(extras)} piste(s) ajoutée(s) depuis la playlist/mix.")
                        # petit aperçu
                        _greg_print("[play_for_user]    extras titres: " + " | ".join(
                            (e.get("title") or "?") for e in extras[:5]
                        ))
                    except Exception as e:
                        _greg_print(f"[play_for_user] ❌ add_many(extras) failed: {e}")

        # 3) Démarrer si rien ne joue
        class FakeInteraction:
            def __init__(self, g): self.guild = g; self.followup = self
            async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")

        playing_state = self.is_playing.get(gid, False)
        _greg_print(f"[play_for_user] ▶️ is_playing[{gid}]={playing_state}")
        if not playing_state:
            _greg_print("[play_for_user] ▶️ Lancement play_next() (rien en cours).")
            await self.play_next(FakeInteraction(guild))
        else:
            _greg_print("[play_for_user] ▶️ Rien à lancer (déjà en cours).")

        self.emit_playlist_update(gid)

        dt = time.monotonic() - t0
        _greg_print(f"[play_for_user] DONE in {dt * 1000:.1f} ms")
        _greg_print("=" * 72)

    async def play_at_for_web(self, guild_id: int | str, requester_id: int | str, index: int):
        gid = int(guild_id)
        rid = int(requester_id)
        guild = self.bot.get_guild(gid)

        # Récup file & borne
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        queue = await loop.run_in_executor(None, pm.get_queue)
        if not (0 <= index < len(queue)):
            raise IndexError("index hors bornes")

        # Poids du propriétaire de l'item + droit du demandeur
        item = queue[index] or {}
        owner_id = int(item.get("added_by") or 0)
        owner_weight = get_member_weight(self.bot, gid, owner_id)

        # Autorisé si admin/manage_guild OU si requester.weight > owner_weight
        if not can_user_bump_over(self.bot, gid, rid, owner_weight):
            raise PermissionError("Insufficient priority for this action.")

        # Déplacement en tête
        ok = await loop.run_in_executor(None, pm.move, index, 0)
        if not ok:
            raise RuntimeError("Déplacement impossible.")

        # Lancer la lecture (ou passer à la suivante si déjà en cours)
        vc = guild.voice_client if guild else None
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # after -> play_next()
        else:
            class FakeInteraction:
                def __init__(self, g): self.guild = g; self.followup = self
                async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")
            await self.play_next(FakeInteraction(guild))

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

    async def stop_for_web(self, guild_id: int | str, requester_id: int | str) -> bool:
        gid = int(guild_id)
        rid = int(requester_id)

        # ⚖️ priorité globale : on regarde le poids max (queue + current)
        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        q = await loop.run_in_executor(None, pm.get_queue)

        owners = set()
        try:
            owners.add(self._get_current_owner_id(gid))
        except Exception:
            pass
        for it in (q or []):
            try:
                owners.add(int(it.get("added_by") or 0))
            except Exception:
                pass
        owners.discard(0)

        max_weight = 0
        for oid in owners:
            try:
                w = get_member_weight(self.bot, gid, int(oid))
                if w > max_weight:
                    max_weight = w
            except Exception:
                pass

        if max_weight > 0 and not can_user_bump_over(self.bot, gid, rid, max_weight):
            raise PermissionError("Insufficient priority to stop the player.")

        # ⏹ arrêt propre
        await loop.run_in_executor(None, pm.stop)

        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

        self._kill_stream_proc(gid)
        self._cancel_ticker(gid)
        self.is_playing[gid] = False
        self.current_song.pop(gid, None)
        self.now_playing.pop(gid, None)
        self.play_start.pop(gid, None)
        self.paused_since.pop(gid, None)
        self.paused_total.pop(gid, None)
        self.current_meta.pop(gid, None)

        self.emit_playlist_update(gid)
        return True

    async def skip_for_web(self, guild_id: int | str, requester_id: int | str) -> bool:
        gid = int(guild_id)
        rid = int(requester_id)

        # ⚖️ contrôle de priorité sur le morceau courant
        owner_id = self._get_current_owner_id(gid)
        if owner_id and owner_id != rid:
            owner_weight = get_member_weight(self.bot, gid, owner_id)
            if not can_user_bump_over(self.bot, gid, rid, owner_weight):
                raise PermissionError("Insufficient priority to skip the current item.")

        g = self.bot.get_guild(gid)
        vc = g and g.voice_client

        if vc and (vc.is_playing() or vc.is_paused()):
            self._kill_stream_proc(gid)
            vc.stop()  # after -> play_next
        else:
            # Si rien ne joue, force la suivante
            self._kill_stream_proc(gid)

            class FakeInteraction:
                def __init__(self, gg):
                    self.guild = gg
                    self.followup = self

                async def send(self, msg):
                    _greg_print(f"[WEB->Discord] {msg}")

            await self.play_next(FakeInteraction(g))

        self.emit_playlist_update(gid)
        return True

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
            vc.stop()
        else:
            class FakeInteraction:
                def __init__(self, g): self.guild = g; self.followup = self
                async def send(self, msg): _greg_print(f"[WEB->Discord] {msg}")
            await self.play_next(FakeInteraction(guild))

        self.emit_playlist_update(gid)

    async def repeat_for_web(self, guild_id: int | str, mode: Optional[str] = None) -> bool:
        gid = int(guild_id)
        cur = bool(self.repeat_all.get(gid, False))
        if mode is None or mode == "" or mode == "toggle":
            nxt = not cur
        else:
            nxt = (mode in ("on", "true", "1", "all"))
        self.repeat_all[gid] = bool(nxt)
        self.emit_playlist_update(gid)
        return bool(nxt)

    async def remove_at_for_web(self, guild_id: int | str, requester_id: int | str, index: int) -> bool:
        """
        Supprime l'élément à l'index si l'appelant est :
        - le propriétaire de l'item, OU
        - plus prioritaire que le propriétaire (can_user_bump_over == True).
        """
        gid = int(guild_id)
        rid = int(requester_id)

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        queue = await loop.run_in_executor(None, pm.get_queue)

        if not (0 <= index < len(queue)):
            raise IndexError("index hors bornes")

        item = queue[index] or {}
        owner_id = int(item.get("added_by") or 0)

        # propriétaire → OK direct
        if rid != owner_id:
            owner_weight = get_member_weight(self.bot, gid, owner_id)
            if not can_user_bump_over(self.bot, gid, rid, owner_weight):
                raise PermissionError("Insufficient priority to remove this item.")

        ok = await loop.run_in_executor(None, pm.remove_at, index)
        if ok:
            self.emit_playlist_update(gid)
        return bool(ok)

    async def move_for_web(self, guild_id: int | str, requester_id: int | str, src: int, dst: int) -> bool:
        """
        Déplace l'item src → dst avec règles de priorité :
        - On peut toujours déplacer ses propres items.
        - Pour déplacer l'item de quelqu’un d’autre : il faut un poids strictement supérieur
          à celui du propriétaire de l’item à déplacer.
        - Si on déplace vers le HAUT (dst < src), on ne peut PAS dépasser un item appartenant
          à un propriétaire dont le poids est >= au nôtre (sauf si c’est aussi nos propres items).
        - Vers le BAS (dst > src) : libre (on n’écrase le privilège de personne).
        """
        gid = int(guild_id)
        rid = int(requester_id)

        pm = self.get_pm(gid)
        loop = asyncio.get_running_loop()
        queue = await loop.run_in_executor(None, pm.get_queue)

        n = len(queue)
        if not (0 <= src < n and 0 <= dst < n):
            raise IndexError("index hors bornes")
        if src == dst:
            return True

        item = queue[src] or {}
        owner_id = int(item.get("added_by") or 0)

        requester_weight = get_member_weight(self.bot, gid, rid)
        owner_weight     = get_member_weight(self.bot, gid, owner_id)

        # Si on déplace l’item de quelqu’un d’autre → il faut être plus lourd
        if rid != owner_id and not can_user_bump_over(self.bot, gid, rid, owner_weight):
            raise PermissionError("Insufficient priority to move this item.")

        # Si on monte (dst < src), on ne doit pas dépasser des items de poids >= au nôtre
        if dst < src:
            for i in range(dst, src):
                it = queue[i] or {}
                it_owner_id = int(it.get("added_by") or 0)
                if it_owner_id == rid:
                    # on a le droit de dépasser nos propres items
                    continue
                it_owner_weight = get_member_weight(self.bot, gid, it_owner_id)
                if it_owner_weight >= requester_weight:
                    raise PermissionError("Insufficient priority to pass higher/equal priority items.")

        ok = await loop.run_in_executor(None, pm.move, src, dst)
        if ok:
            self.emit_playlist_update(gid)
        return bool(ok)


async def setup(bot, emit_fn=None):
    await bot.add_cog(Music(bot, emit_fn))
    _greg_print("✅ Cog 'Music' chargé — stream prioritaire (YT→SC), fallback pipe, extracteur auto par URL.")
