"""PlayerService v2 — Service de lecture musicale.

Changements par rapport à v1 :
- Utilise greg_shared.priority (nouveau système avec PermissionResult)
- Émet via bot.emit_state_update() (Redis) au lieu de socketio direct
- find_insert_position() pour l'insertion triée en 2 zones
- check_quota() structuré

Fix v2.1 :
- Détection de coupure réseau Discord (1006 / WebSocket drop)
- Réinsertion automatique du morceau interrompu + délai de reconnexion
- _explicit_stops : distinction arrêt intentionnel vs coupure accidentelle

Fix v2.2 (playlists via liens + audit) :
- play_for_user répond vite : expansion/recherche dans un thread (jamais sur la
  boucle asyncio), 1re lecture lancée en tâche de fond, résultat détaillé
  (added/requested/truncated/playlist/title) ou erreur codée + message FR.
- Jamais d'URL de playlist brute dans la file ; liens Spotify refusés ;
  texte libre → recherche YouTube ; liens sans schéma normalisés.
- Quota calculé AVANT l'expansion ; limite PLAYLIST_EXPAND_LIMIT (défaut 25).
- Verrou de FILE par guild (distinct du verrou de LECTURE tenu pendant les
  extractions) : insertions triées atomiques, plus de mauvais item déplacé.
- Compteur d'échecs remis à zéro uniquement après une lecture saine ; coupures
  en cours de lecture plafonnées ; titres indisponibles sautés immédiatement.
- Génération par guild : stop/skip/play_at/restart pendant un chargement
  abandonnent proprement la source (plus de KeyError ni d'item fantôme).
- play_next ne dépile rien sans client vocal connecté.
- Politique de déplacement vocal (busy_elsewhere) + reconnexion vocale robuste ;
  connect_for_user la re-vérifie sous le verrou vocal après une reconnexion.
- Un retry (backoff) programmé n'est jamais court-circuité par un 2e play_next ;
  pas de 2e stream_pipe quand stream() a déjà tenté le pipe (pipe_tried).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

import discord

from greg_shared.config import settings
from greg_shared.extractors import (
    BundleError,
    TrackUnavailable,
    expand_bundle,
    get_extractor,
    is_bundle_url,
    is_spotify_url,
    is_url,
    normalize_link,
)
from greg_shared.extractors.soundcloud import is_short_link as sc_is_short_link
from greg_shared.extractors.youtube import search as yt_search

try:  # règle « lisible comme UN titre ? » de stream() (helper privé de l'extracteur)
    from greg_shared.extractors.youtube import _stream_target as yt_stream_target
except ImportError:  # pragma: no cover - renommé côté extracteur : pas de pré-contrôle
    yt_stream_target = None
from greg_shared.priority import (
    PermissionResult,
    build_user_info,
    can_bypass_quota,
    can_control_playback,
    can_edit_queue_item,
    check_quota,
    find_insert_position,
    get_member_weight,
    get_per_user_cap,
    is_owner,
    validate_move,
)

from bot.services.ffmpeg import detect_ffmpeg
from bot.services.playlist_manager import PlaylistManager
from bot.services.history_manager import HistoryManager

logger = logging.getLogger("greg.player")

AUDIO_EQ_PRESETS = {
    "off": None,
    "music": "highpass=f=32,volume=-6dB,bass=g=4:f=95:w=1.0,alimiter=limit=0.98:attack=5:release=50",
}

# Délai d'attente (secondes) avant de retenter la lecture après une coupure réseau.
# Doit être > au temps de reconnexion de discord.py (~2s).
_RECONNECT_WAIT = 3.5

# Si la chanson s'est arrêtée N secondes avant sa fin théorique, on considère
# que c'est une coupure réseau et non une fin naturelle.
_CUT_SHORT_MARGIN = 8

# Sous ce seuil (secondes lues), on considère que la chanson n'a JAMAIS
# vraiment démarré — donc ce n'est pas une coupure réseau, c'est un flux
# foireux (403, SABR, codec…). On ne re-enqueue pas, on incrémente un
# compteur d'échecs et on passe à la suite.
_MIN_PLAYBACK_BEFORE_RECONNECT = 5.0

# Nombre maximum de retries consécutifs sur une même URL avant abandon.
# Empêche la boucle infinie observée en cas de 403 permanent.
_MAX_FAILURES_PER_TRACK = 3

# Coupures EN COURS de lecture (après démarrage) tolérées pour une même URL :
# les vraies coupures Discord (1006) sont rares, un flux qui meurt toujours en
# route finit abandonné au lieu de boucler.
_MAX_CUTS_PER_TRACK = 3

# Délai d'attente exponentiel après échec (en secondes, plafonné).
_BACKOFF_BASE = 1.5
_BACKOFF_MAX = 8.0

# ── Budget de réponse de play_for_user (l'API attend 25 s) ──
_EXPAND_TIMEOUT = 20.0
_SEARCH_TIMEOUT = 15.0
_PLAY_FOR_USER_BUDGET = 22.0
# Budget minimal utile : en dessous (la commande a trop attendu son tour derrière
# une autre de la même guild), on répond tout de suite au lieu de répondre trop tard.
_MIN_PLAY_BUDGET = 2.0
_DEFAULT_PLAYLIST_EXPAND_LIMIT = 25

# ── Connexion vocale ──
# Attente max d'une reconnexion discord.py en cours (1006/4006) avant de forcer.
_VOICE_RECONNECT_WAIT = 4.0
_VOICE_CONNECT_TIMEOUT = 10.0
# discord.py réutilise le timeout de connect() pour TOUTES les reprises/reconnexions
# ultérieures (et l'attente du lecteur audio) : on lui rend son budget par défaut.
_VOICE_RESUME_TIMEOUT = 30.0

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_ERROR_MESSAGES = {
    "GUILD_NOT_FOUND": "Greg n'est pas (ou plus) sur ce serveur.",
    "USER_NOT_IN_VOICE": "Rejoins d'abord un salon vocal, après on cause.",
    "VOICE_CONNECT_FAILED": "Impossible de rejoindre ton salon vocal pour le moment.",
    "PLAYLIST_UNAVAILABLE": "Playlist privée, supprimée ou inaccessible pour Greg.",
    "PLAYLIST_EMPTY": "Cette playlist est vide (ou ne contient aucun titre lisible).",
    "UNSUPPORTED_SOURCE": "Ce lien n'est pas pris en charge : colle un lien YouTube ou SoundCloud.",
    "SPOTIFY_UNSUPPORTED": (
        "Les liens Spotify ne sont pas pris en charge : colle un lien YouTube ou SoundCloud, "
        "ou tape simplement le titre."
    ),
    "NO_RESULTS": "Aucun résultat trouvé pour ta recherche.",
    "EXPAND_TIMEOUT": "La playlist met trop de temps à charger, réessaie dans un instant.",
}

_BUSY_MESSAGE = "Greg est déjà occupé avec une autre demande sur ce serveur : réessaie dans un instant."
_UNPLAYABLE_LINK_MESSAGE = "Ce lien ne pointe vers aucun titre lisible : colle le lien d'une vidéo ou d'une playlist."
# Repli watch?v=ID&list=… → vidéo seule : on prévient que la playlist a été ignorée.
_PLAYLIST_IGNORED_MESSAGES = {
    "PLAYLIST_UNAVAILABLE": "Playlist privée ou inaccessible : seule la vidéo demandée a été ajoutée.",
    "EXPAND_TIMEOUT": "La playlist met trop de temps à charger : seule la vidéo demandée a été ajoutée.",
}


def _fail(code: str, message: Optional[str] = None, **extra) -> dict:
    """Réponse d'erreur du contrat C2 : {ok: False, error: CODE, message: texte FR}."""
    out = {"ok": False, "error": code, "message": message or _ERROR_MESSAGES.get(code, code)}
    out.update(extra)
    return out


def _quota_failure(reason: str) -> dict:
    parts = (reason or "").split(":")
    count, cap = None, None
    if len(parts) > 1 and "/" in parts[1]:
        try:
            count, cap = (int(x) for x in parts[1].split("/", 1))
        except ValueError:
            pass
    if cap is None:
        cap = get_per_user_cap()
        count = cap
    return _fail(
        "QUOTA_EXCEEDED",
        f"Quota atteint ({count}/{cap}) : attends que tes morceaux passent avant d'en rajouter.",
        count=count,
        cap=cap,
    )


def _playlist_expand_limit() -> int:
    try:
        return max(1, int(os.getenv("PLAYLIST_EXPAND_LIMIT", str(_DEFAULT_PLAYLIST_EXPAND_LIMIT))))
    except (TypeError, ValueError):
        return _DEFAULT_PLAYLIST_EXPAND_LIMIT


def _single_video_url(link: str) -> Optional[str]:
    """watch?v=ID&list=… → https://www.youtube.com/watch?v=ID (sans contexte de playlist)."""
    try:
        u = urlparse(link)
        host = (u.hostname or "").lower()
        if not host.endswith("youtube.com"):
            return None
        vid = (parse_qs(u.query).get("v") or [""])[0]
        if _YT_ID_RE.match(vid):
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass
    return None


def _cleanup_source(src) -> None:
    """Libère une source audio : ffmpeg ET, en mode pipe, le process yt-dlp attaché."""
    if src is None:
        return
    try:
        proc = getattr(src, "_ytdlp_proc", None)
        if proc is not None and proc.poll() is None:
            proc.kill()
    except Exception:
        pass
    try:
        if hasattr(src, "cleanup"):
            src.cleanup()
    except Exception:
        pass


def _cleanup_source_off_loop(src) -> None:
    """_cleanup_source dans le pool de threads, sans l'attendre.

    Depuis la boucle asyncio (chargement abandonné, voix indisponible) : en mode
    pipe, cleanup() d'une source jamais lue peut bloquer ~1 s (join du thread
    d'écriture de discord.py) et figerait tout le bot (gateway, Redis, autres guilds).
    """
    if src is None:
        return
    try:
        asyncio.get_running_loop().run_in_executor(None, _cleanup_source, src)
    except RuntimeError:
        _cleanup_source(src)


def _track_link_refusal(link: str) -> Optional[str]:
    """Raison (FR) pour laquelle stream() refuserait d'emblée ce lien comme titre, sinon None.

    Même règle que l'extracteur (youtube._stream_target, TrackUnavailable sans
    extraction) : refusé à l'ajout au lieu d'être ajouté (« Ajouté ✅ ») puis jeté
    en silence au moment de le jouer.
    """
    if yt_stream_target is None or not link or not is_url(link) or is_spotify_url(link):
        return None
    try:
        yt_stream_target(link)
    except TrackUnavailable as e:
        return str(e) or _UNPLAYABLE_LINK_MESSAGE
    except Exception:
        return None
    return None


class _VoiceUnavailable(RuntimeError):
    """vc.play() impossible (client vocal absent/déconnecté) : ce n'est PAS un échec du morceau."""


class PlayerService:
    """Service central de lecture musicale."""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.intro_playing: Dict[int, bool] = {}
        self.pm_map: Dict[int, PlaylistManager] = {}
        self.hm_map: Dict[int, HistoryManager] = {}
        self.ffmpeg_path = detect_ffmpeg()

        self.is_playing: Dict[int, bool] = {}
        self.current_song: Dict[int, dict] = {}
        self.current_meta: Dict[int, dict] = {}
        self.now_playing: Dict[int, dict] = {}
        self.repeat_all: Dict[int, bool] = {}
        self.audio_mode: Dict[int, str] = {}

        self.play_start: Dict[int, float] = {}
        self.paused_since: Dict[int, float] = {}
        self.paused_total: Dict[int, float] = {}
        self.current_source: Dict[int, Any] = {}
        self._progress_task: Dict[int, asyncio.Task] = {}
        # Verrou de LECTURE (play_next, tenu pendant les extractions longues)
        self._locks: Dict[int, asyncio.Lock] = {}
        # Verrou de FILE (mutations de la queue, toujours tenu très brièvement)
        self._queue_locks: Dict[int, asyncio.Lock] = {}
        # Verrou de CONNEXION vocale (évite deux connect() concurrents)
        self._voice_locks: Dict[int, asyncio.Lock] = {}

        # --- Fix reconnexion réseau ---
        # Ensemble des guild IDs pour lesquels l'arrêt a été déclenché
        # explicitement par une action utilisateur (skip, stop, play_at…).
        # Tout arrêt NON présent ici est considéré accidentel (coupure Discord).
        self._explicit_stops: Set[int] = set()

        # --- Fix boucle infinie 403 ---
        # Compteur d'échecs consécutifs par URL pour casser la boucle
        # quand un flux est systématiquement injouable (403/SABR permanent).
        # Clé : (guild_id, url) → nombre d'échecs. Remis à zéro UNIQUEMENT
        # après une lecture saine (pas au simple lancement de vc.play()).
        self._track_failures: Dict[tuple, int] = {}
        # Coupures en cours de lecture (branche « Reconnect »), même clé.
        self._track_cuts: Dict[tuple, int] = {}

        # Génération par guild : stop/skip/play_at/restart l'incrémentent ; un
        # play_next dont la génération a changé pendant un await abandonne.
        self._generation: Dict[int, int] = {}
        # Marqueur de la copie « repeat_all » ajoutée en fin de file par play_next
        # pour le morceau courant (permet de la retirer sans toucher aux vrais doublons).
        self._repeat_tags: Dict[int, str] = {}
        # Retry (backoff) en attente par guild : (tâche, url du morceau remis en tête).
        self._retry_tasks: Dict[int, Tuple[asyncio.Task, Optional[str]]] = {}
        # Références des tâches de fond (sinon le GC peut les collecter en vol).
        self._bg_tasks: Set[asyncio.Task] = set()

        self._ratelimit = settings.ytdlp_limit_bps

    # ─── Internal helpers ───

    @property
    def _cookies_file(self) -> Optional[str]:
        """Cookies YouTube résolus À CHAQUE USAGE (pas de snapshot à l'init) :
        un /yt_cookies_update est pris en compte sans redémarrer le bot."""
        try:
            return settings.get_cookies_file()
        except Exception:
            return None

    def _guild_lock(self, gid: int) -> asyncio.Lock:
        if gid not in self._locks:
            self._locks[gid] = asyncio.Lock()
        return self._locks[gid]

    def _queue_lock(self, gid: int) -> asyncio.Lock:
        if gid not in self._queue_locks:
            self._queue_locks[gid] = asyncio.Lock()
        return self._queue_locks[gid]

    def _voice_lock(self, gid: int) -> asyncio.Lock:
        if gid not in self._voice_locks:
            self._voice_locks[gid] = asyncio.Lock()
        return self._voice_locks[gid]

    def _spawn(self, coro) -> asyncio.Task:
        """Lance une tâche de fond en gardant une référence dessus."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _bump_generation(self, gid: int) -> None:
        self._generation[gid] = self._generation.get(gid, 0) + 1

    def _is_stale(self, gid: int, gen: int) -> bool:
        return self._generation.get(gid, 0) != gen

    def _get_pm(self, guild_id: int) -> PlaylistManager:
        gid = int(guild_id)
        if gid not in self.pm_map:
            self.pm_map[gid] = PlaylistManager(gid)
        return self.pm_map[gid]

    def _known_pm(self, gid: int) -> Optional[PlaylistManager]:
        """PlaylistManager seulement pour une guild où Greg est présent (ou déjà chargée) :
        une requête sur un guild_id arbitraire ne crée ni objet ni fichier."""
        if gid in self.pm_map:
            return self.pm_map[gid]
        if self.bot.get_guild(gid) is None:
            return None
        return self._get_pm(gid)

    def _get_hm(self, guild_id: int) -> HistoryManager:
        gid = int(guild_id)
        if gid not in self.hm_map:
            self.hm_map[gid] = HistoryManager(gid)
        return self.hm_map[gid]

    def get_history(self, guild_id: int, mode: str = "top", limit: int = 20) -> dict:
        """Retourne l'historique pour une guild."""
        gid = int(guild_id)
        if gid not in self.hm_map and self.bot.get_guild(gid) is None:
            return {"ok": True, "items": [], "mode": mode}
        hm = self._get_hm(gid)
        if mode == "recent":
            items = hm.get_recent(limit)
        else:
            items = hm.get_top(limit)
        return {"ok": True, "items": items, "mode": mode}

    def _afilter_for(self, gid: int) -> Optional[str]:
        return AUDIO_EQ_PRESETS.get(self.audio_mode.get(gid, "music"))

    def _clear_now_playing(self, gid: int):
        self.is_playing[gid] = False
        self._explicit_stops.discard(gid)
        for d in (self.current_song, self.play_start, self.paused_since,
                  self.paused_total, self.current_meta, self.now_playing):
            d.pop(gid, None)

    def _emit(self, gid: int, payload: dict = None):
        """Émet un state update via le bot (qui le publie sur Redis)."""
        try:
            self.bot.emit_state_update(gid, payload)
        except Exception as e:
            logger.error("emit failed: %s", e)

    def _extractor_kwargs(self, extractor, method_name: str, gid: int) -> dict:
        fn = getattr(extractor, method_name, None)
        if not fn:
            return {}
        try:
            sig = inspect.signature(fn)
            candidates = {
                "cookies_file": self._cookies_file,
                "ratelimit_bps": self._ratelimit,
                "afilter": self._afilter_for(gid),
            }
            return {k: v for k, v in candidates.items() if k in sig.parameters}
        except Exception:
            return {}

    def _current_owner_weight(self, gid: int) -> int:
        cur = self.now_playing.get(gid, {})
        w = int(cur.get("priority") or 0)
        if w > 0:
            return w
        owner = cur.get("added_by")
        try:
            return get_member_weight(self.bot, gid, int(owner))
        except Exception:
            return 0

    async def _ensure_can_control(self, gid: int, requester_id: int):
        """Vérifie qu'un user peut contrôler la lecture. Lève PermissionError sinon."""
        result = can_control_playback(self.bot, gid, requester_id, self._current_owner_weight(gid))
        if not result.allowed:
            raise PermissionError(result.reason)

    @staticmethod
    def _backoff(n: int) -> float:
        return min(_BACKOFF_MAX, _RECONNECT_WAIT * (_BACKOFF_BASE ** max(0, n - 1)))

    def _reset_track_counters(self, key: Optional[tuple]) -> None:
        if key:
            self._track_failures.pop(key, None)
            self._track_cuts.pop(key, None)

    @staticmethod
    def _is_permanent(err: BaseException) -> bool:
        return isinstance(err, TrackUnavailable) or getattr(err, "permanent", False) is True

    # ─── Stop intentionnel (helpers internes) ───

    def _mark_explicit_stop(self, gid: int):
        """
        À appeler AVANT tout vc.stop() déclenché volontairement
        (skip, stop, play_at, restart…).
        Permet à _after() de distinguer un arrêt voulu d'une coupure réseau.
        """
        self._explicit_stops.add(gid)

    # ─── Retry (backoff) ───

    def _cancel_retry(self, gid: int) -> Optional[str]:
        """Annule le retry en attente ; renvoie l'URL du morceau remis en tête (ou None)."""
        entry = self._retry_tasks.pop(gid, None)
        if not entry:
            return None
        task, url = entry
        if not task.done():
            task.cancel()
            return url
        return None

    def _schedule_retry(self, guild: discord.Guild, gid: int, url: Optional[str], wait_s: float) -> None:
        self._cancel_retry(gid)
        holder: Dict[str, asyncio.Task] = {}

        async def _retry():
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                return
            cur = self._retry_tasks.get(gid)
            if cur and cur[0] is holder.get("task"):
                self._retry_tasks.pop(gid, None)
            g = self.bot.get_guild(gid) or guild
            await self.play_next(g)

        task = self._spawn(_retry())
        holder["task"] = task
        self._retry_tasks[gid] = (task, url)

    # ─── File : opérations atomiques (verrou de file) ───

    async def _drop_repeat_copy_locked(self, gid: int) -> None:
        """Retire la copie repeat_all du morceau courant (appelant = détenteur du verrou de file)."""
        tag = self._repeat_tags.pop(gid, None)
        if not tag:
            return
        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.remove_last_where, lambda it: it.get("repeat_tag") == tag)

    async def _drop_repeat_copy(self, gid: int) -> None:
        async with self._queue_lock(gid):
            await self._drop_repeat_copy_locked(gid)

    async def _requeue_head(self, gid: int, item: Optional[dict]) -> None:
        """Remet un morceau en tête de file pour le rejouer, sans doublon repeat_all."""
        it = {k: v for k, v in dict(item or {}).items() if k != "repeat_tag"}
        if not it.get("url"):
            return
        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        async with self._queue_lock(gid):
            await self._drop_repeat_copy_locked(gid)
            await loop.run_in_executor(None, pm.insert_at, 0, it)

    async def _drop_head_if(self, gid: int, url: Optional[str], *, keep_in_loop: bool = False) -> None:
        """Retire la tête de file si c'est `url`.

        keep_in_loop (repeat_all) : le morceau retourne en fin de file, comme après
        un skip normal, au lieu de quitter la boucle.
        """
        if not url:
            return
        pm = self._get_pm(gid)
        async with self._queue_lock(gid):
            q = pm.peek_all()
            if q and q[0].get("url") == url:
                head = q[0]
                if pm.remove_at(0, expected=head) and keep_in_loop:
                    pm.add({k: v for k, v in dict(head).items() if k != "repeat_tag"})

    # ─── State ───

    def get_state(self, guild_id: int) -> dict:
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g.voice_client if g else None
        is_paused = bool(vc and vc.is_paused())

        start = self.play_start.get(gid)
        p_since = self.paused_since.get(gid)
        p_total = self.paused_total.get(gid, 0.0)

        elapsed = 0
        if start:
            base = p_since or time.monotonic()
            elapsed = max(0, int(base - start - p_total))

        meta = self.current_meta.get(gid, {})
        duration = meta.get("duration")
        thumb = meta.get("thumbnail")

        cur = self.now_playing.get(gid) or self.current_song.get(gid)
        if isinstance(cur, dict):
            if duration is None and isinstance(cur.get("duration"), (int, float)):
                duration = int(cur["duration"])
            thumb = thumb or cur.get("thumb") or cur.get("thumbnail")

        requested_by = None
        if isinstance(cur, dict) and cur.get("added_by"):
            try:
                requested_by = build_user_info(self.bot, gid, int(cur["added_by"]))
            except Exception:
                pass

        # Guild inconnue : état vide, sans créer de PlaylistManager ni de fichier.
        queue: List[dict] = []
        pm = self._known_pm(gid)
        if pm is not None:
            try:
                pm.reload()
            except Exception:
                pass
            queue = pm.to_dict().get("queue", [])

        # Toute la file (une playlist ajoute jusqu'à 25 titres d'un coup) : un
        # build_user_info par utilisateur distinct, pas par ligne.
        queue_users = {}
        seen = set()
        for it in queue:
            uid = (it or {}).get("requested_by") or (it or {}).get("added_by")
            if uid and str(uid) not in seen:
                seen.add(str(uid))
                try:
                    queue_users[str(uid)] = build_user_info(self.bot, gid, int(uid))
                except Exception:
                    pass

        return {
            "guild_id": gid,
            "queue": queue,
            "current": cur,
            "paused": is_paused,
            "is_paused": is_paused,
            "position": elapsed,
            "duration": int(duration) if duration else None,
            "progress": {"elapsed": elapsed, "duration": int(duration) if duration else None},
            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(gid, False)),
            "requested_by_user": requested_by,
            "queue_users": queue_users,
        }

    # ─── Enqueue ───

    def _normalize_item(self, it: dict) -> dict:
        """Normalise un item de queue."""
        url = (it.get("url") or "").strip() or None
        title = (it.get("title") or "").strip()
        artist = (it.get("artist") or "").strip() or None
        thumb = it.get("thumb") or it.get("thumbnail")
        provider = it.get("provider")

        duration = it.get("duration")
        if isinstance(duration, str):
            if duration.isdigit():
                duration = int(duration)
            elif ":" in duration:
                try:
                    parts = [int(x) for x in duration.split(":")]
                    duration = sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
                except Exception:
                    duration = None
            else:
                duration = None
        elif isinstance(duration, (int, float)):
            duration = int(duration)
        else:
            duration = None

        out = {
            "title": title or url or "Sans titre",
            "url": url,
            "artist": artist,
            "thumb": thumb,
            "duration": duration,
            "provider": provider,
        }
        for k in ("mode", "added_by", "priority", "ts"):
            if k in it:
                out[k] = it[k]
        return out

    async def enqueue(self, guild_id: int, user_id: int, item: dict) -> dict:
        gid = int(guild_id)
        if gid not in self.pm_map and self.bot.get_guild(gid) is None:
            return _fail("GUILD_NOT_FOUND")
        async with self._queue_lock(gid):
            res = await self._enqueue_locked(gid, user_id, item)
        if res.get("ok"):
            self._emit(gid)
        return res

    async def _enqueue_locked(self, gid: int, user_id: int, item: dict) -> dict:
        """Ajout d'un item (quota + position triée), l'appelant détient le verrou de file."""
        item = dict(item or {})
        item["added_by"] = str(user_id)
        if item.get("url"):
            item["url"] = normalize_link(str(item["url"]))
        item = self._normalize_item(item)

        url = item.get("url") or ""
        if not url or is_bundle_url(url):
            # Jamais d'URL de playlist brute dans la file : elle serait « lue »
            # comme un seul morceau (ré-extraite en boucle, seul le 1er titre joué).
            return _fail("UNSUPPORTED_SOURCE", "Lien de playlist non développé : impossible de l'ajouter tel quel.")
        refusal = _track_link_refusal(url)
        if refusal:
            return _fail("UNSUPPORTED_SOURCE", refusal)

        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        # Check quota
        quota = check_quota(queue, user_id, self.bot, gid)
        if not quota.allowed:
            return _quota_failure(quota.reason)

        # Attribuer le poids
        weight = get_member_weight(self.bot, gid, user_id)
        item["priority"] = weight

        # Insertion triée ATOMIQUE : la position est calculée sous le verrou du
        # PlaylistManager (plus de « mon item est le dernier » qui déplaçait
        # l'item d'un autre quand deux ajouts se croisaient).
        position = await loop.run_in_executor(
            None, pm.insert_by, item, lambda q: find_insert_position(q, weight),
        )
        return {"ok": True, "item": item, "position": position}

    # ─── Playback ───

    def busy_elsewhere(self, guild: discord.Guild, channel) -> Optional[discord.abc.GuildChannel]:
        """Salon où Greg joue (ou est en pause) pour quelqu'un, s'il est AUTRE que `channel`.

        Renvoie None si Greg n'est pas connecté, est déjà dans `channel`, ne joue
        pas, ou si personne (humain) ne l'écoute là-bas.
        """
        vc = getattr(guild, "voice_client", None)
        if not vc or not vc.is_connected():
            return None
        cur = getattr(vc, "channel", None)
        if cur is None:
            return None
        if channel is not None and int(cur.id) == int(getattr(channel, "id", 0) or 0):
            return None
        if not (vc.is_playing() or vc.is_paused()):
            return None
        humans = [m for m in (getattr(cur, "members", None) or []) if not getattr(m, "bot", False)]
        return cur if humans else None

    def busy_elsewhere_error(self, channel) -> dict:
        return _fail(
            "BOT_IN_OTHER_CHANNEL",
            f"Greg joue déjà dans <#{channel.id}>… Rejoins-le ou attends la fin du concert.",
        )

    def ensure_playing(self, guild: discord.Guild) -> None:
        """Lance play_next en tâche de fond si rien ne joue (jamais attendu : réponse rapide)."""
        gid = int(guild.id)
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return
        if vc.is_playing() or vc.is_paused():
            return
        entry = self._retry_tasks.get(gid)
        if entry and not entry[0].done():
            return  # un retry (backoff) relancera la lecture
        self._spawn(self.play_next(guild))

    async def ensure_connected(self, guild: discord.Guild, channel) -> bool:
        ok, _busy = await self._connect(guild, channel)
        return ok

    async def connect_for_user(self, guild: discord.Guild, channel) -> Optional[dict]:
        """Connexion vocale pour une demande utilisateur (play_for_user, action 'join').

        None si Greg est (ou vient d'arriver) dans `channel`, sinon l'erreur :
        BOT_IN_OTHER_CHANNEL (politique C7, re-vérifiée sous le verrou vocal APRÈS
        une éventuelle reconnexion Discord) ou VOICE_CONNECT_FAILED.
        """
        busy = self.busy_elsewhere(guild, channel)
        if busy is None:
            ok, busy = await self._connect(guild, channel, respect_busy=True)
            if busy is None:
                return None if ok else _fail("VOICE_CONNECT_FAILED")
        return self.busy_elsewhere_error(busy)

    async def _connect(self, guild: discord.Guild, channel, *, respect_busy: bool = False):
        """(connecté ?, salon occupé qui a bloqué le déplacement ou None)."""
        if not channel or not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return False, None
        gid = int(guild.id)
        async with self._voice_lock(gid):
            vc = guild.voice_client
            try:
                if vc and not vc.is_connected():
                    # discord.py est peut-être en train de se reconnecter (1006/4006).
                    vc = await self._await_voice_reconnect(guild)
                if vc and vc.is_connected():
                    if getattr(vc, "channel", None) and int(vc.channel.id) == int(channel.id):
                        return True, None
                    if respect_busy:
                        # Pendant la reconnexion, busy_elsewhere() ne voyait rien
                        # (is_connected() False) : on re-vérifie avant de déplacer Greg.
                        busy = self.busy_elsewhere(guild, channel)
                        if busy is not None:
                            return False, busy
                    await vc.move_to(channel)
                    return True, None
                if vc is not None:
                    # Client vocal fantôme : sans nettoyage, connect() lève
                    # « Already connected to a voice channel ».
                    await self._drop_stale_voice(vc)
                new_vc = await channel.connect(timeout=_VOICE_CONNECT_TIMEOUT)
                try:
                    # 10 s pour répondre à l'utilisateur, mais 30 s pour les reprises
                    # après coupure (1006 / migration de serveur vocal).
                    new_vc._connection.timeout = _VOICE_RESUME_TIMEOUT
                except Exception:
                    pass
                try:
                    await self._play_intro(guild, gid)
                except Exception:
                    pass
                return True, None
            except discord.ClientException as e:
                logger.warning("Connexion vocale impossible (ClientException): %s", e)
                return False, None
            except Exception as e:
                logger.warning("Connexion vocale impossible: %s", e)
                return False, None

    async def _await_voice_reconnect(self, guild: discord.Guild):
        loop = asyncio.get_running_loop()
        end = loop.time() + _VOICE_RECONNECT_WAIT
        while loop.time() < end:
            cur = guild.voice_client
            if cur is None or cur.is_connected():
                return cur
            await asyncio.sleep(0.1)
        return guild.voice_client

    async def _drop_stale_voice(self, vc) -> None:
        logger.warning("Client vocal non connecté après attente : nettoyage avant reconnexion.")
        try:
            await asyncio.wait_for(vc.disconnect(force=True), timeout=5)
        except Exception as e:
            logger.warning("Nettoyage du client vocal fantôme: %s", e)
            try:
                vc.cleanup()
            except Exception:
                pass

    async def _play_intro(self, guild: discord.Guild, gid: int):
        intro = os.path.join("assets", "sounds", "Ouais_cest_greg.mp3")
        if not os.path.exists(intro):
            return
        vc = guild.voice_client
        if not vc or not vc.is_connected() or vc.is_playing() or self.intro_playing.get(gid):
            return
        self.intro_playing[gid] = True

        def _after(_e):
            self.intro_playing[gid] = False
            try:
                asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)
            except Exception:
                pass

        try:
            src = discord.FFmpegPCMAudio(intro, executable=self.ffmpeg_path, before_options="-nostdin", options="-vn")
            vc.play(src, after=_after)
        except Exception as e:
            self.intro_playing[gid] = False
            logger.warning("Intro failed: %s", e)

    async def play_next(self, guild: discord.Guild):
        gid = int(guild.id)
        async with self._guild_lock(gid):
            loop = asyncio.get_running_loop()

            vc = guild.voice_client
            # Pas de voix → on ne touche PAS à la file (sinon chaque morceau serait
            # dépilé, extrait plusieurs fois puis jeté : file vidée pour rien).
            if not vc or not vc.is_connected():
                self._clear_now_playing(gid)
                self._emit(gid)
                return
            if vc.is_playing():
                return
            entry = self._retry_tasks.get(gid)
            if entry and not entry[0].done():
                # Un retry (backoff) est programmé : c'est lui qui relancera la lecture.
                # Sinon un 2e play_next (ensure_playing de l'action 'join', fin d'intro…)
                # redépilerait tout de suite le morceau en échec, sans attendre.
                # (La tâche de retry retire son entrée AVANT d'appeler play_next.)
                return
            if vc.is_paused():
                self._mark_explicit_stop(gid)
                vc.stop()

            pm = self._get_pm(gid)
            async with self._queue_lock(gid):
                await loop.run_in_executor(None, pm.reload)
                # Génération lue SOUS le verrou de file, juste avant de dépiler : un
                # play_at/restart qui a réordonné la file (puis incrémenté la génération)
                # avant ce dépilage est déjà pris en compte → son morceau n'est pas jeté.
                gen = self._generation.get(gid, 0)
                item = await loop.run_in_executor(None, pm.pop_next)
                if item and self.repeat_all.get(gid):
                    tag = f"{gid}:{time.monotonic_ns()}"
                    await loop.run_in_executor(None, pm.add, {**item, "repeat_tag": tag})
                    self._repeat_tags[gid] = tag
                else:
                    self._repeat_tags.pop(gid, None)

            if not item:
                self._clear_now_playing(gid)
                self._emit(gid)
                return

            if self._is_stale(gid, gen):
                # stop/skip pendant le dépilage : ce morceau est abandonné.
                self._spawn(self.play_next(guild))
                return

            url = item.get("url")
            self.current_song[gid] = dict(item)
            self.now_playing[gid] = dict(item)
            dur = int(item["duration"]) if isinstance(item.get("duration"), (int, float)) else None
            self.current_meta[gid] = {"duration": dur, "thumbnail": item.get("thumb")}

            extractor = get_extractor(url)
            if not extractor:
                self._clear_now_playing(gid)
                self._emit(gid)
                return

            failure_key = (gid, url) if url else None
            last_err: Optional[Exception] = None
            permanent = False
            srcp, title = None, None
            for method in ("stream", "stream_pipe"):
                if not hasattr(extractor, method):
                    continue
                try:
                    srcp, title = await self._call_extractor(
                        extractor, method, url, self.ffmpeg_path,
                        **self._extractor_kwargs(extractor, method, gid),
                    )
                    break
                except Exception as e:
                    last_err = e
                    if self._is_permanent(e):
                        # Indisponible (supprimée/privée/géo-bloquée…) : inutile
                        # d'essayer le pipe ou de réessayer.
                        permanent = True
                        logger.warning("[%s KO définitif] guild=%s url=%s: %s", method, gid, url, e)
                        break
                    logger.warning("[%s KO] guild=%s url=%s: %s", method, gid, url, e)
                    if self._is_stale(gid, gen):
                        break
                    if method == "stream" and getattr(e, "pipe_tried", False):
                        # youtube.stream() a déjà basculé sur stream_pipe en interne, qui
                        # a échoué aussi : pas de 2e extraction pipe complète (≈ 30 s de plus).
                        break

            if self._is_stale(gid, gen):
                # stop/skip/play_at/restart pendant le chargement : on jette la
                # source sans la jouer ni la réinsérer, et on laisse la suite se faire.
                _cleanup_source_off_loop(srcp)
                logger.info("[Chargement annulé] guild=%s url=%s", gid, url)
                self._spawn(self.play_next(guild))
                return

            if srcp is not None:
                if title and isinstance(title, str):
                    for d in (self.current_song, self.now_playing):
                        cs = d.get(gid)
                        if cs is not None:
                            cs["title"] = title
                try:
                    await self._play_source(guild, gid, srcp)
                except _VoiceUnavailable as e:
                    # La voix a disparu : pas un échec du morceau → il reste en tête.
                    logger.warning("[Voix indisponible] guild=%s url=%s: %s", gid, url, e)
                    _cleanup_source_off_loop(srcp)
                    await self._requeue_head(gid, item)
                    self._clear_now_playing(gid)
                    self._emit(gid)
                return

            cur_title = (self.current_song.get(gid, {}) or {}).get("title") or item.get("title", "?")

            if permanent:
                logger.warning("Track '%s' (guild %s) indisponible — ignoré (%s).", cur_title, gid, last_err)
                self._reset_track_counters(failure_key)
                await self._drop_repeat_copy(gid)
                self._clear_now_playing(gid)
                self._emit(gid)
                self._spawn(self.play_next(guild))
                return

            # ── Échec extracteur : tous les flux ont échoué avant lecture ───
            # On incrémente le même compteur que _after pour appliquer la
            # même politique d'abandon après N tentatives consécutives.
            fails = _MAX_FAILURES_PER_TRACK
            if failure_key:
                fails = self._track_failures.get(failure_key, 0) + 1
                self._track_failures[failure_key] = fails

            if fails >= _MAX_FAILURES_PER_TRACK:
                logger.error(
                    "Track '%s' (guild %s) impossible après %d tentatives — abandon (%s).",
                    cur_title, gid, fails, last_err,
                )
                self._reset_track_counters(failure_key)
                # En mode repeat_all, la copie ajoutée en fin de file est retirée
                # pour ne pas boucler sur un morceau injouable.
                await self._drop_repeat_copy(gid)
                self._clear_now_playing(gid)
                self._emit(gid)
                self._spawn(self.play_next(guild))
                return

            logger.warning(
                "Track '%s' (guild %s) échec extracteur %d/%d — backoff puis retry.",
                cur_title, gid, fails, _MAX_FAILURES_PER_TRACK,
            )
            # Réinsère en tête pour réessayer (la copie repeat_all éventuelle est
            # retirée : play_next en recréera une au prochain dépilage).
            await self._requeue_head(gid, item)
            self._clear_now_playing(gid)
            self._emit(gid)
            self._schedule_retry(guild, gid, url, self._backoff(fails))

    async def _call_extractor(self, extractor, method: str, *args, **kwargs):
        fn = getattr(extractor, method)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _play_source(self, guild: discord.Guild, gid: int, srcp):
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            raise _VoiceUnavailable("client vocal absent")
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        self.current_source[gid] = srcp
        # Génération au démarrage : un stop/skip/restart ultérieur la rend périmée.
        gen = self._generation.get(gid, 0)

        def _after(err):
            # ── Nettoyage de SA source (jamais celle du morceau suivant) ────
            ended = time.monotonic()
            if self.current_source.get(gid) is srcp:
                self.current_source.pop(gid, None)
            _cleanup_source(srcp)

            # ── Détection coupure réseau vs arrêt intentionnel ──────────────
            #
            # Un arrêt intentionnel (skip, stop, play_at, restart…) est marqué
            # via _mark_explicit_stop() AVANT que vc.stop() soit appelé.
            # Si le flag n'est pas là, la lecture s'est arrêtée toute seule :
            #   • soit fin naturelle de la chanson (elapsed ≈ duration)
            #   • soit coupure Discord 1006 (elapsed << duration mais lecture
            #     démarrée)
            #   • soit flux YouTube foireux (elapsed ≈ 0, jamais démarré)
            # La décision (et les écritures de file) se font sur la boucle
            # asyncio dans _handle_track_end.
            was_explicit = gid in self._explicit_stops
            self._explicit_stops.discard(gid)
            cur = self.current_song.get(gid)
            cur = dict(cur) if cur else None
            start = self.play_start.get(gid, ended)
            paused = self.paused_total.get(gid, 0.0)
            ps = self.paused_since.get(gid)
            if ps:
                paused += ended - ps
            elapsed = max(0.0, ended - start - paused)
            # Durée figée ICI (le morceau suivant peut réécrire current_meta avant
            # que la suite ne s'exécute sur la boucle).
            duration = (self.current_meta.get(gid) or {}).get("duration")
            if not duration and cur and isinstance(cur.get("duration"), (int, float)):
                duration = int(cur["duration"])
            if err:
                logger.warning("Lecture interrompue (guild %s): %s", gid, err)
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_track_end(guild, gid, cur, elapsed, duration, was_explicit, gen),
                    self.bot.loop,
                )
            except Exception as e:
                logger.error("Relance après fin de piste impossible (guild %s): %s", gid, e)

        # play_start AVANT vc.play : un _after immédiat ne doit pas lire l'ancien départ.
        self.play_start[gid] = time.monotonic()
        self.paused_total[gid] = 0.0
        self.paused_since.pop(gid, None)
        try:
            vc.play(srcp, after=_after)
        except Exception as e:
            if self.current_source.get(gid) is srcp:
                self.current_source.pop(gid, None)
            raise _VoiceUnavailable(str(e)) from e
        self.is_playing[gid] = True
        self._ensure_ticker(gid)
        self._emit(gid)

        try:
            cur = self.current_song.get(gid, {})
            added_by = cur.get("added_by") or cur.get("requested_by")
            self._get_hm(gid).record_play(cur, played_by=added_by)
        except Exception as e:
            logger.debug("history record failed: %s", e)

    async def _handle_track_end(self, guild: discord.Guild, gid: int, cur: Optional[dict],
                                elapsed: float, duration: Optional[int], was_explicit: bool,
                                gen: Optional[int] = None):
        """Suite d'une fin de piste (appelée sur la boucle depuis _after).

        gen : génération au démarrage de la piste (None = pas de contrôle).
        """
        cur_url = (cur or {}).get("url") if cur else None
        key = (gid, cur_url) if cur_url else None
        retry_n = 0
        drop = False

        if not was_explicit and cur:
            if duration and elapsed >= duration - _CUT_SHORT_MARGIN:
                # Fin naturelle (y compris les pistes très courtes) → lecture saine.
                self._reset_track_counters(key)
            elif elapsed < _MIN_PLAYBACK_BEFORE_RECONNECT:
                # Le flux est mort presque immédiatement → ce n'est PAS
                # une coupure réseau, c'est un flux injouable.
                fails = (self._track_failures.get(key, 0) + 1) if key else _MAX_FAILURES_PER_TRACK
                if key:
                    self._track_failures[key] = fails
                if fails >= _MAX_FAILURES_PER_TRACK:
                    logger.error(
                        "[Skip] Guild %s — '%s' injouable après %d tentatives, on abandonne.",
                        gid, cur.get("title", "?"), fails,
                    )
                    self._reset_track_counters(key)
                    drop = True
                else:
                    logger.warning(
                        "[Retry %d/%d] Guild %s — '%s' n'a pas démarré (%.1fs), nouvelle tentative.",
                        fails, _MAX_FAILURES_PER_TRACK, gid, cur.get("title", "?"), elapsed,
                    )
                    retry_n = fails
            elif duration:
                # Interrompue bien avant sa fin mais APRÈS avoir démarré : coupure
                # réseau Discord… ou flux qui meurt en route (plafonné).
                cuts = (self._track_cuts.get(key, 0) + 1) if key else _MAX_CUTS_PER_TRACK
                if key:
                    self._track_failures.pop(key, None)  # elle a bien démarré
                    self._track_cuts[key] = cuts
                if cuts >= _MAX_CUTS_PER_TRACK:
                    logger.error(
                        "[Reconnect] Guild %s — '%s' coupée %d fois, on abandonne.",
                        gid, cur.get("title", "?"), cuts,
                    )
                    self._reset_track_counters(key)
                    drop = True
                else:
                    logger.warning(
                        "[Reconnect] Guild %s — '%s' interrompue à %.0fs / %ds, réinsertion en tête de queue.",
                        gid, cur.get("title", "?"), elapsed, duration,
                    )
                    retry_n = cuts
            else:
                # Durée inconnue mais lue plus de quelques secondes → fin naturelle.
                self._reset_track_counters(key)
        else:
            # Arrêt explicite ou pas de current → on nettoie aussi.
            self._reset_track_counters(key)

        if retry_n:
            await self._requeue_head(gid, cur)
            if gen is not None and self._is_stale(gid, gen):
                # stop/skip/restart pendant la remise en tête : l'utilisateur a
                # repris la main → on annule la remise en tête, pas de retry.
                await self._drop_head_if(gid, cur_url)
                self._emit(gid)
                return
            self._emit(gid)
            wait_s = self._backoff(retry_n)
            logger.info("[Reconnect] Guild %s — attente %.1fs avant relecture.", gid, wait_s)
            self._schedule_retry(guild, gid, cur_url, wait_s)
            return

        if drop:
            # Abandon définitif : la copie repeat_all est retirée aussi.
            await self._drop_repeat_copy(gid)
            self._clear_now_playing(gid)
        await self.play_next(guild)

    # ─── Controls ───

    async def skip(self, guild_id: int, requester_id: int = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        g = self.bot.get_guild(gid)
        if g is None and gid not in self.pm_map:
            return False  # guild inconnue : aucun état créé (génération, file…)
        vc = g and g.voice_client
        self._bump_generation(gid)
        pending_url = self._cancel_retry(gid)
        if pending_url:
            # Un retry attendait : le morceau en échec avait été remis en tête → on le jette
            # (en repeat_all il reste dans la boucle, en fin de file, comme un skip normal).
            await self._drop_head_if(gid, pending_url, keep_in_loop=bool(self.repeat_all.get(gid)))
        if vc and (vc.is_playing() or vc.is_paused()):
            self._mark_explicit_stop(gid)
            vc.stop()
        elif g:
            self.ensure_playing(g)
        self._emit(gid)
        return True

    async def stop(self, guild_id: int, requester_id: int = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        pm = self._known_pm(gid)
        if pm is None:
            return False  # guild inconnue : aucun état créé (génération, file…)
        self._bump_generation(gid)
        self._cancel_retry(gid)
        loop = asyncio.get_running_loop()
        async with self._queue_lock(gid):
            await loop.run_in_executor(None, pm.stop)
            # 2e incrément APRÈS le vidage : un play_next qui attendait le verrou de
            # file a pu dépiler un morceau entre-temps (génération déjà relue) → abandonné.
            self._bump_generation(gid)
        self._repeat_tags.pop(gid, None)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self._mark_explicit_stop(gid)
            vc.stop()
        self._cancel_ticker(gid)
        self._clear_now_playing(gid)
        self._emit(gid)
        return True

    async def pause(self, guild_id: int, requester_id: int = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self.paused_since[gid] = time.monotonic()
            self._emit(gid)
            return True
        return False

    async def resume(self, guild_id: int, requester_id: int = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_paused():
            vc.resume()
            ps = self.paused_since.pop(gid, None)
            if ps:
                self.paused_total[gid] = self.paused_total.get(gid, 0.0) + (time.monotonic() - ps)
            self._emit(gid)
            return True
        return False

    def remove_at(self, guild_id: int, requester_id: int, index: int) -> bool:
        gid = int(guild_id)
        pm = self._known_pm(gid)
        if pm is None:
            return False
        q = pm.peek_all()
        if not (0 <= index < len(q)):
            return False
        perm = can_edit_queue_item(self.bot, gid, requester_id, q[index])
        if not perm.allowed:
            raise PermissionError(perm.reason)
        ok = pm.remove_at(index, expected=q[index])
        if ok:
            self._emit(gid)
        return ok

    def move(self, guild_id: int, requester_id: int, src: int, dst: int) -> bool:
        gid = int(guild_id)
        pm = self._known_pm(gid)
        if pm is None:
            return False
        q = pm.peek_all()
        if not (0 <= src < len(q) and 0 <= dst < len(q)):
            return False

        perm = can_edit_queue_item(self.bot, gid, requester_id, q[src])
        if not perm.allowed:
            raise PermissionError(perm.reason)

        move_perm = validate_move(q, src, dst, requester_id, self.bot, gid)
        if not move_perm.allowed:
            raise PermissionError(move_perm.reason)

        ok = pm.move(src, dst, expected=q[src])
        if ok:
            self._emit(gid)
        return ok

    async def play_at(self, guild_id: int, user_id: int, index: int) -> bool:
        """Joue le morceau à l'index donné dans la queue.

        C'est un skip déguisé : mêmes droits que skip (contrôle de la lecture en
        cours) + droits sur l'item + respect des zones de priorité.
        """
        gid = int(guild_id)
        pm = self._known_pm(gid)
        if pm is None:
            return False
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        loop = asyncio.get_running_loop()
        async with self._queue_lock(gid):
            q = pm.peek_all()
            if not (0 <= index < len(q)):
                return False
            item = q[index]
            perm = can_edit_queue_item(self.bot, gid, user_id, item)
            if not perm.allowed:
                raise PermissionError(perm.reason)
            if index > 0:
                move_perm = validate_move(q, index, 0, user_id, self.bot, gid)
                if not move_perm.allowed:
                    raise PermissionError(move_perm.reason)
            if (vc and (vc.is_playing() or vc.is_paused())) or self.now_playing.get(gid):
                await self._ensure_can_control(gid, user_id)
            if index > 0 and not await loop.run_in_executor(None, pm.move, index, 0, item):
                return False
        self._bump_generation(gid)
        self._cancel_retry(gid)
        if vc and (vc.is_playing() or vc.is_paused()):
            self._mark_explicit_stop(gid)
            vc.stop()
        elif g:
            self.ensure_playing(g)
        self._emit(gid)
        return True

    async def restart(self, guild_id: int, requester_id: int = None) -> bool:
        """Redémarre le morceau en cours depuis le début."""
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        cur = self.current_song.get(gid)
        if not cur:
            return False
        if self._known_pm(gid) is None:
            return False
        self._bump_generation(gid)
        pending_url = self._cancel_retry(gid)
        if pending_url:
            # Un retry attendait : le morceau est DÉJÀ en tête → on retire cette copie.
            await self._drop_head_if(gid, pending_url)
        # Remis en tête SANS doublon : la copie repeat_all est retirée d'abord.
        await self._requeue_head(gid, cur)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self._mark_explicit_stop(gid)
            vc.stop()
        elif g:
            self.ensure_playing(g)
        self._emit(gid)
        return True

    async def toggle_repeat(self, guild_id: int, mode: str = None) -> bool:
        gid = int(guild_id)
        cur = self.repeat_all.get(gid, False)
        if mode in (None, "", "toggle"):
            nxt = not cur
        else:
            nxt = mode in ("on", "true", "1", "all")
        self.repeat_all[gid] = nxt
        self._emit(gid)
        return nxt

    async def set_music_mode(self, guild_id: int, on_off: str = None) -> bool:
        gid = int(guild_id)
        cur = self.audio_mode.get(gid, "music")
        if on_off in ("on", "off"):
            new = "music" if on_off == "on" else "off"
        else:
            new = "off" if cur != "off" else "music"
        self.audio_mode[gid] = new
        return new == "music"

    # ─── Ajout utilisateur (web + /play) ───

    async def _remaining_quota(self, gid: int, user_id: int) -> Tuple[Optional[int], int, int]:
        """(places restantes, déjà en file, cap) pour l'utilisateur — restantes None = illimité."""
        cap = get_per_user_cap()
        if can_bypass_quota(self.bot, gid, user_id):
            return None, 0, cap
        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        async with self._queue_lock(gid):
            await loop.run_in_executor(None, pm.reload)
            queue = await loop.run_in_executor(None, pm.get_queue)
        count = sum(1 for it in queue if str(it.get("added_by")) == str(user_id))
        return max(0, cap - count), count, cap

    async def _search_track(self, text: str, timeout: float) -> dict:
        """Texte libre → 1er résultat YouTube (dans un thread, jamais sur la boucle)."""
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(yt_search, text, limit=1, cookies_file=self._cookies_file),
                timeout=timeout,
            )
        # transient=True : délai/erreur (bot-check, réseau…), PAS une vraie absence de
        # résultat → /play affiche le message (« réessaie ») et non « ça existe pas ».
        except asyncio.TimeoutError:
            logger.warning("Recherche YouTube trop lente pour %r", text)
            return _fail("NO_RESULTS", "La recherche YouTube met trop de temps, réessaie dans un instant.",
                         transient=True)
        except Exception as e:
            logger.warning("Recherche YouTube échouée pour %r: %s", text, e)
            return _fail("NO_RESULTS", "La recherche YouTube a échoué, réessaie dans un instant.",
                         transient=True)
        top = next((r for r in (results or []) if isinstance(r, dict) and (r.get("url") or r.get("webpage_url"))), None)
        if not top:
            return _fail("NO_RESULTS", f"Aucun résultat pour « {text[:80]} ».")
        return {"ok": True, "entry": top}

    async def _expand(self, link: str, limit: int, timeout: float):
        """Expansion d'une playlist (thread + timeout). Renvoie (entries, None) ou (None, erreur)."""
        try:
            entries = await asyncio.wait_for(
                asyncio.to_thread(expand_bundle, link, limit=limit, cookies_file=self._cookies_file),
                timeout=timeout,
            )
            return list(entries or []), None
        except BundleError as e:
            code = getattr(e, "code", None) or "PLAYLIST_UNAVAILABLE"
            msg = getattr(e, "message", None) or str(e) or None
            logger.warning("Expansion playlist %s → %s: %s", link, code, msg)
            return None, _fail(code, msg)
        except asyncio.TimeoutError:
            logger.warning("Expansion playlist %s: délai de %.0fs dépassé", link, timeout)
            return None, _fail("EXPAND_TIMEOUT")
        except Exception:
            logger.exception("Expansion playlist %s: erreur inattendue", link)
            return None, _fail("PLAYLIST_UNAVAILABLE")

    @staticmethod
    def _entry_to_item(e: dict) -> dict:
        return {
            "title": e.get("title"),
            "url": e.get("url") or e.get("webpage_url"),
            "artist": e.get("artist") or e.get("uploader"),
            "thumb": e.get("thumb") or e.get("thumbnail"),
            "duration": e.get("duration"),
            "provider": e.get("provider") or "youtube",
        }

    @staticmethod
    def _playlist_size(raw_entries) -> int:
        """Taille réelle de la playlist si l'extracteur la fournit (playlist_count), sinon 0."""
        size = 0
        for e in raw_entries or []:
            if isinstance(e, dict):
                try:
                    size = max(size, int(e.get("playlist_count") or 0))
                except (TypeError, ValueError):
                    pass
        return size

    async def play_for_user(self, guild_id: int, user_id: int, item: dict,
                            budget: Optional[float] = None) -> dict:
        """Ajoute un lien / une playlist / une recherche pour un utilisateur et lance la lecture.

        Répond vite (bien sous les 20 s) : expansion et recherche dans un thread
        avec timeout, 1re lecture lancée en tâche de fond (jamais attendue).
        `budget` (s) : temps de réponse restant quand la commande a attendu son tour
        (pont Redis : timeout de l'API − attente) ; défaut _PLAY_FOR_USER_BUDGET.
        Succès : {ok, added, requested, truncated, playlist, title}
                 (+ playlist_error / message si la playlist d'un lien watch?v=…&list=…
                 était illisible et que seule la vidéo a été ajoutée).
                 requested = taille de la playlist si l'extracteur la connaît, sinon le
                 nombre de titres vus : une BORNE BASSE quand truncated est posé.
        Échec  : {ok: False, error: CODE, message: texte FR}.
        """
        try:
            gid = int(guild_id)
        except (TypeError, ValueError):
            return _fail("GUILD_NOT_FOUND")
        g = self.bot.get_guild(gid)
        if not g:
            return _fail("GUILD_NOT_FOUND")
        member = g.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            return _fail("USER_NOT_IN_VOICE")
        channel = member.voice.channel

        item = dict(item or {})
        raw = str(item.get("url") or item.get("query") or "").strip()
        if not raw:
            return _fail("NO_RESULTS", "Rien à jouer : donne un lien ou un titre.")
        link = normalize_link(raw)
        if is_spotify_url(link):
            return _fail("SPOTIFY_UNSUPPORTED")
        refusal = None if is_bundle_url(link) else _track_link_refusal(link)
        if refusal:
            # stream() le jetterait en silence : refusé AVANT toute connexion vocale.
            return _fail("UNSUPPORTED_SOURCE", refusal)

        busy = self.busy_elsewhere(g, channel)
        if busy is not None:
            return self.busy_elsewhere_error(busy)

        loop = asyncio.get_running_loop()
        total = _PLAY_FOR_USER_BUDGET if budget is None else min(_PLAY_FOR_USER_BUDGET, float(budget))
        if total < _MIN_PLAY_BUDGET:
            # L'attente derrière une autre commande a mangé le budget : répondre
            # maintenant plutôt qu'après l'abandon de l'API (ajout fantôme en retard).
            return _fail("EXPAND_TIMEOUT", _BUSY_MESSAGE)
        deadline = loop.time() + total

        # Quota AVANT tout travail coûteux (connexion, expansion).
        remaining, count, cap = await self._remaining_quota(gid, user_id)
        if remaining == 0:
            return _quota_failure(f"quota_exceeded:{count}/{cap}")

        err = await self.connect_for_user(g, channel)
        if err is not None:
            return err

        def _time_left(cap_s: float) -> float:
            # Reste du budget global, jamais plus que cap_s ni moins d'1 s (sauf cap_s < 1).
            return min(cap_s, max(1.0, deadline - loop.time()))

        # Métadonnées fournies par l'appelant (l'API met souvent title = texte collé :
        # un titre qui n'est qu'un lien est ignoré, le vrai titre viendra de l'extraction).
        user_meta = {**self._entry_to_item(item), "provider": item.get("provider")}
        if user_meta.get("title") and (str(user_meta["title"]).strip() == raw or is_url(str(user_meta["title"]))):
            user_meta["title"] = None

        truncated: Optional[str] = None
        playlist = False
        playlist_error: Optional[str] = None
        if not is_url(link):
            found = await self._search_track(raw, _time_left(_SEARCH_TIMEOUT))
            if not found.get("ok"):
                return found
            entries = [self._entry_to_item(found["entry"])]
            requested = 1
        elif is_bundle_url(link) or sc_is_short_link(link):
            # on.soundcloud.com : titre OU set, seul expand_bundle le sait (après redirection).
            expand_limit = _playlist_expand_limit()
            limit = expand_limit if remaining is None else min(expand_limit, remaining)
            # +1 pour savoir si la playlist a été tronquée (quota ou limite).
            raw_entries, err = await self._expand(link, limit + 1, _time_left(_EXPAND_TIMEOUT))
            if err is not None:
                single = _single_video_url(link)
                if single is None or err["error"] not in ("PLAYLIST_UNAVAILABLE", "EXPAND_TIMEOUT"):
                    return err
                # watch?v=ID&list=… : la playlist est illisible mais la vidéo demandée
                # est explicite → on ajoute au moins celle-là (jamais le lien brut).
                logger.info("Playlist illisible (%s) → repli sur la vidéo seule %s", err["error"], single)
                entries = [{**user_meta, "url": single}]
                requested = 1
                playlist_error = err["error"]
            else:
                entries = [self._entry_to_item(e) for e in raw_entries if isinstance(e, dict)]
                entries = [e for e in entries if e.get("url")]
                if not entries:
                    return _fail("PLAYLIST_EMPTY")
                # Taille réelle si connue ; sinon titres vus (sonde +1 comprise) = borne basse.
                requested = max(len(entries), self._playlist_size(raw_entries))
                if len(entries) > limit:
                    truncated = "quota" if (remaining is not None and remaining < expand_limit) else "limit"
                    entries = entries[:limit]
                # Lien court SoundCloud résolu en un seul titre : ce n'est pas une playlist.
                playlist = is_bundle_url(link) or len(entries) > 1
        else:
            entries = [{**user_meta, "url": link}]
            requested = 1

        added = 0
        first_title: Optional[str] = None
        first_error: Optional[dict] = None
        async with self._queue_lock(gid):
            for e in entries:
                res = await self._enqueue_locked(gid, user_id, e)
                if res.get("ok"):
                    added += 1
                    it = res.get("item") or {}
                    if added == 1 and it.get("title") and it.get("title") != it.get("url"):
                        first_title = it["title"]
                    continue
                if first_error is None:
                    first_error = res
                if res.get("error") == "QUOTA_EXCEEDED":
                    truncated = "quota"
                    break
                logger.warning("Entrée ignorée (%s): %s", res.get("error"), e.get("url"))

        if added == 0:
            return first_error or _fail("PLAYLIST_EMPTY" if playlist else "NO_RESULTS")

        self._emit(gid)
        self.ensure_playing(g)
        out = {
            "ok": True,
            "added": added,
            "requested": requested,
            "truncated": truncated,
            "playlist": playlist,
            "title": first_title,
        }
        if playlist_error:
            # Champs additionnels : l'utilisateur qui a collé une playlist doit savoir
            # pourquoi un seul titre a été ajouté.
            out["playlist_error"] = playlist_error
            out["message"] = (_PLAYLIST_IGNORED_MESSAGES.get(playlist_error)
                              or _PLAYLIST_IGNORED_MESSAGES["PLAYLIST_UNAVAILABLE"])
        return out

    # ─── Progress ticker ───

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

        async def _run():
            try:
                while True:
                    g = self.bot.get_guild(gid)
                    vc = g.voice_client if g else None
                    if not vc or (not vc.is_playing() and not vc.is_paused()):
                        break

                    start = self.play_start.get(gid)
                    p_since = self.paused_since.get(gid)
                    p_total = self.paused_total.get(gid, 0.0)
                    elapsed = max(0, int((p_since or time.monotonic()) - start - p_total)) if start else 0

                    meta = self.current_meta.get(gid, {})
                    dur = meta.get("duration")
                    if dur is None:
                        cs = self.current_song.get(gid, {})
                        dur = int(cs["duration"]) if isinstance(cs.get("duration"), (int, float)) else None

                    try:
                        await self.bot.redis_bridge.publish_progress(
                            gid, elapsed, dur, bool(vc.is_paused()),
                        )
                    except Exception:
                        pass

                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass
            finally:
                self._progress_task.pop(gid, None)

        self._progress_task[gid] = asyncio.create_task(_run())
