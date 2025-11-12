# api/services/player_service.py
from __future__ import annotations

import os
import time
import asyncio
import logging
from typing import Any, Optional, Dict, List

import discord

from utils.playlist_manager import PlaylistManager
from utils.priority_rules import (
    get_member_weight, PER_USER_CAP, can_bypass_quota, can_user_bump_over
)
from utils.ffmpeg import detect_ffmpeg
from api.services.oembed import oembed

# tes extracteurs existants (YT only si besoin)
from extractors import get_extractor, get_search_module, is_bundle_url, expand_bundle

log = logging.getLogger(__name__)

AUDIO_EQ_PRESETS = {
    "off":   None,
    "music": "highpass=f=32,volume=-6dB,bass=g=4:f=95:w=1.0,alimiter=limit=0.98:attack=5:release=50",
}

class PlayerService:
    """
    Service unique pour gérer la musique:
      - queue/PM par guild
      - stream (direct → fallback pipe)
      - ticker (progress elapsed) → overlay emit
      - règles de priorité/quota
    Pensé pour être appelé par **commands/** ET **API REST**.
    """

    def __init__(self, bot: discord.Client, emit_fn=None):
        self.bot = bot
        self.emit_fn = emit_fn

        self.pm_map: Dict[str, PlaylistManager] = {}
        self.ffmpeg_path = detect_ffmpeg()

        # états par guilde
        self.is_playing: Dict[int, bool] = {}
        self.current_song: Dict[int, dict] = {}
        self.current_meta: Dict[int, dict] = {}
        self.now_playing: Dict[int, dict] = {}
        self.repeat_all: Dict[int, bool] = {}
        self.audio_mode: Dict[int, str] = {}  # "music"|"off"

        self.play_start: Dict[int, float] = {}
        self.paused_since: Dict[int, float] = {}
        self.paused_total: Dict[int, float] = {}
        self.current_source: Dict[int, Any] = {}
        self._progress_task: Dict[int, asyncio.Task] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

        # YouTube cookies & ratelimit
        self.youtube_cookies_file = (
            os.getenv("YTDLP_COOKIES_FILE")
            or ("youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None)
        )
        try:
            self.yt_ratelimit = int(os.getenv("YTDLP_LIMIT_BPS", "2500000"))
        except Exception:
            self.yt_ratelimit = 2_500_000

    # --------- wiring ---------
    def set_emit_fn(self, emit_fn):
        self.emit_fn = emit_fn

    # --------- utils de base ---------
    @staticmethod
    def _gid(v) -> int:
        return int(v)

    def _guild_lock(self, gid: int) -> asyncio.Lock:
        lock = self._locks.get(gid)
        if not lock:
            lock = asyncio.Lock()
            self._locks[gid] = lock
        return lock

    def _get_pm(self, guild_id: int) -> PlaylistManager:
        gid = str(int(guild_id))
        pm = self.pm_map.get(gid)
        if pm is None:
            pm = PlaylistManager(gid)
            self.pm_map[gid] = pm
            log.info("PlaylistManager créée pour guild %s", gid)
        return pm

    def _afilter_for(self, gid: int) -> Optional[str]:
        mode = self.audio_mode.get(gid, "music")
        return AUDIO_EQ_PRESETS.get(mode)

    def _emit_playlist_update(self, gid: int, payload=None):
        if not self.emit_fn:
            return
        if payload is None:
            payload = self._overlay_payload(gid)
        payload["guild_id"] = gid
        try:
            self.emit_fn("playlist_update", payload, guild_id=gid)
        except TypeError:
            # compat “vieux” emit sans room
            self.emit_fn("playlist_update", payload)

    # --------- normalisation / enrichissement ---------
    def _normalize_item(self, it: dict) -> dict:
        url = (it.get("url") or "").strip() or None
        title = (it.get("title") or "").strip()
        artist = (it.get("artist") or "").strip() or None
        thumb = (it.get("thumb") or it.get("thumbnail") or None)

        # Enrichissement léger via oEmbed si champs manquants
        if url and (not title or not artist or not thumb):
            oe = oembed(url) or {}
            title = title or oe.get("title") or url
            artist = artist or oe.get("author_name")
            thumb = thumb or oe.get("thumbnail_url")

        # durée: accepte int/str "M:SS" etc.
        duration = it.get("duration")
        if isinstance(duration, str) and duration.isdigit():
            duration = int(duration)
        elif isinstance(duration, str) and ":" in duration:
            try:
                parts = [int(x) for x in duration.split(":")]
                duration = parts[-1] + (parts[-2] * 60 if len(parts) >= 2 else 0) + (parts[-3] * 3600 if len(parts) >= 3 else 0)
            except Exception:
                duration = None
        elif isinstance(duration, (int, float)):
            duration = int(duration)
        else:
            duration = None

        out = {
            "title": title or (url or "Sans titre"),
            "url": url,
            "artist": artist,
            "thumb": thumb,
            "duration": duration,
        }
        # pass-through utiles
        for k in ("provider", "mode", "added_by", "priority"):
            if k in it:
                out[k] = it[k]
        return out

    # --------- overlay payload & ticker ---------
    def _overlay_payload(self, gid: int) -> dict:
        g = self.bot.get_guild(int(gid))
        vc = g.voice_client if g else None
        is_paused_vc = bool(vc and vc.is_paused())

        # elapsed
        start = self.play_start.get(gid)
        paused_since = self.paused_since.get(gid)
        paused_total = self.paused_total.get(gid, 0.0)
        elapsed = 0
        if start:
            base = paused_since or time.monotonic()
            elapsed = max(0, int(base - start - paused_total))

        # duration & thumb
        meta = self.current_meta.get(gid, {})
        duration = meta.get("duration")
        thumb = meta.get("thumbnail")

        cur = (self.now_playing.get(gid) or self.current_song.get(gid))
        if isinstance(cur, dict):
            if duration is None and isinstance(cur.get("duration"), (int, float)):
                duration = int(cur["duration"])
            thumb = thumb or cur.get("thumb") or cur.get("thumbnail")

        return {
            "queue": self._get_pm(gid).to_dict().get("queue", []),
            "current": cur,
            "is_paused": is_paused_vc,
            "progress": {"elapsed": elapsed, "duration": (int(duration) if duration is not None else None)},
            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(gid, False)),
        }

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

                    # envoie minimaliste: only_elapsed
                    start = self.play_start.get(gid)
                    paused_since = self.paused_since.get(gid)
                    paused_total = self.paused_total.get(gid, 0.0)
                    elapsed = 0
                    if start:
                        base = paused_since or time.monotonic()
                        elapsed = max(0, int(base - start - paused_total))

                    meta = self.current_meta.get(gid, {}) or {}
                    duration = meta.get("duration")
                    if duration is None and self.current_song.get(gid, {}).get("duration"):
                        duration = int(self.current_song[gid]["duration"])

                    payload = {
                        "guild_id": gid,
                        "only_elapsed": True,
                        "is_paused": bool(vc and vc.is_paused()),
                        "progress": {"elapsed": elapsed, "duration": duration},
                    }
                    self._emit_playlist_update(gid, payload)
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass
            finally:
                self._progress_task.pop(gid, None)

        self._progress_task[gid] = asyncio.create_task(_runner())

    # --------- opérations publiques (API + Commands) ---------
    async def ensure_connected(self, guild: discord.Guild, channel: Optional[discord.VoiceChannel]) -> bool:
        vc = guild.voice_client
        if vc and vc.is_connected():
            return True
        if not channel:
            return False
        try:
            await channel.connect()
            return True
        except Exception as e:
            log.warning("Connexion vocale impossible: %s", e)
            return False

    async def enqueue(self, guild_id: int, user_id: int, item: dict) -> dict:
        gid = int(guild_id)
        item = dict(item or {})
        item["added_by"] = str(user_id)
        item = self._normalize_item(item)

        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        if not can_bypass_quota(self.bot, gid, int(user_id)):
            user_count = sum(1 for it in queue if str(it.get("added_by")) == str(user_id))
            if user_count >= PER_USER_CAP:
                return {"ok": False, "error": f"Quota atteint ({PER_USER_CAP})."}

        weight = int(get_member_weight(self.bot, gid, int(user_id)))
        item["priority"] = weight

        await loop.run_in_executor(None, pm.add, item)

        # réinsertion par priorité
        new_queue = await loop.run_in_executor(None, pm.get_queue)
        new_idx = len(new_queue) - 1
        target_idx = 0
        for i, it in enumerate(new_queue):
            try:
                w = int(it.get("priority") or 0)
            except Exception:
                w = 0
            if weight > w:
                target_idx = i
                break
            target_idx = i + 1
        if 0 <= target_idx < len(new_queue) and target_idx != new_idx:
            await loop.run_in_executor(None, pm.move, new_idx, target_idx)

        self._emit_playlist_update(gid)
        return {"ok": True, "item": item, "moved_to": target_idx}

    async def play_next(self, guild: discord.Guild):
        gid = int(guild.id)
        lock = self._guild_lock(gid)
        async with lock:
            loop = asyncio.get_running_loop()
            pm = self._get_pm(gid)
            await loop.run_in_executor(None, pm.reload)

            vc = guild.voice_client
            if vc and (vc.is_playing() or vc.is_paused()):
                return  # déjà en cours

            item = await loop.run_in_executor(None, pm.pop_next)
            if not item:
                # fin de queue
                self.is_playing[gid] = False
                for d in (self.current_song, self.play_start, self.paused_since,
                          self.paused_total, self.current_meta, self.now_playing):
                    d.pop(gid, None)
                self._emit_playlist_update(gid)
                return

            if self.repeat_all.get(gid):
                await loop.run_in_executor(None, pm.add, item)

            item = self._normalize_item(item)
            url = item.get("url")
            self.current_song[gid] = {
                "title": item.get("title") or url,
                "url": url,
                "artist": item.get("artist"),
                "thumb": item.get("thumb"),
                "duration": item.get("duration"),
                "added_by": item.get("added_by"),
                "priority": item.get("priority"),
            }
            dur_int = int(item["duration"]) if isinstance(item.get("duration"), (int, float)) else None
            self.current_meta[gid] = {"duration": dur_int, "thumbnail": item.get("thumb")}
            self.now_playing[gid] = dict(self.current_song[gid])

            extractor = get_extractor(url)
            if extractor is None:
                self.is_playing[gid] = False
                self._emit_playlist_update(gid)
                return

            # kwargs compatibles avec ta signature
            def _kw(method):
                import inspect
                fn = getattr(extractor, method, None)
                if not fn:
                    return {}
                try:
                    sig = inspect.signature(fn)
                    cand = dict(
                        cookies_file=self.youtube_cookies_file,
                        cookies_from_browser=None,
                        ratelimit_bps=self.yt_ratelimit,
                        afilter=self._afilter_for(gid),
                    )
                    return {k: v for k, v in cand.items() if k in sig.parameters}
                except Exception:
                    return {}

            # 1) STREAM direct
            try:
                srcp, real_title = await self._call_extractor(extractor, "stream", url, self.ffmpeg_path, **_kw("stream"))
                if real_title and isinstance(real_title, str):
                    self.current_song[gid]["title"] = real_title
                    self.now_playing[gid]["title"] = real_title
                await self._play_source(guild, gid, srcp, fallback=False)
                return
            except Exception as ex_direct:
                log.debug("[stream direct KO] %s", ex_direct)

            # 2) PIPE fallback
            srcp, real_title = await self._call_extractor(extractor, "stream_pipe", url, self.ffmpeg_path, **_kw("stream_pipe"))
            if real_title and isinstance(real_title, str):
                self.current_song[gid]["title"] = real_title
                self.now_playing[gid]["title"] = real_title
            await self._play_source(guild, gid, srcp, fallback=True)

    async def _call_extractor(self, extractor_module, method_name: str, *args, **kwargs):
        fn = getattr(extractor_module, method_name)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def _play_source(self, guild: discord.Guild, gid: int, srcp, fallback: bool):
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        self.current_source[gid] = srcp

        def _after(_e: Exception | None):
            try:
                src = self.current_source.pop(gid, None)
                if src and hasattr(src, "cleanup"):
                    try: src.cleanup()
                    except Exception: pass
                proc = getattr(src, "_ytdlp_proc", None)
                if proc:
                    try: proc.kill()
                    except Exception: pass
            finally:
                asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)

        vc.play(srcp, after=_after)
        self.play_start[gid] = time.monotonic()
        self.paused_total[gid] = 0.0
        self.paused_since.pop(gid, None)
        self.is_playing[gid] = True
        self._ensure_ticker(gid)
        self._emit_playlist_update(gid)

    # === commandes basiques (API/Discord) ===
    async def stop(self, guild_id: int):
        gid = int(guild_id)
        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.stop)

        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

        self._cancel_ticker(gid)
        self.is_playing[gid] = False
        for d in (self.current_song, self.now_playing, self.play_start,
                  self.paused_since, self.paused_total, self.current_meta):
            d.pop(gid, None)
        self._emit_playlist_update(gid)
        return True

    async def skip(self, guild_id: int):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        else:
            await self.play_next(g)
        self._emit_playlist_update(gid)
        return True

    async def pause(self, guild_id: int):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self.paused_since[gid] = time.monotonic()
            self._emit_playlist_update(gid)
            return True
        return False

    async def resume(self, guild_id: int):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_paused():
            vc.resume()
            ps = self.paused_since.pop(gid, None)
            if ps:
                self.paused_total[gid] = self.paused_total.get(gid, 0.0) + (time.monotonic() - ps)
            self._emit_playlist_update(gid)
            return True
        return False

    async def toggle_repeat(self, guild_id: int, mode: Optional[str] = None) -> bool:
        gid = int(guild_id)
        cur = bool(self.repeat_all.get(gid, False))
        nxt = (not cur) if (mode in (None, "", "toggle")) else (mode in ("on", "true", "1", "all"))
        self.repeat_all[gid] = bool(nxt)
        self._emit_playlist_update(gid)
        return bool(nxt)

    async def set_music_mode(self, guild_id: int, on_off: Optional[str]) -> bool:
        gid = int(guild_id)
        cur = self.audio_mode.get(gid, "music")
        if on_off in ("on", "off"):
            new_mode = "music" if on_off == "on" else "off"
        else:
            new_mode = "off" if cur != "off" else "music"
        self.audio_mode[gid] = new_mode
        return new_mode == "music"

    # Helpers webhook/API
    async def play_for_user(self, guild_id: int, user_id: int, item: dict):
        """
        Version API: connecte, enfile et déclenche play si idle.
        """
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        if not g:
            return {"ok": False, "error": "GUILD_NOT_FOUND"}

        member = g.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            return {"ok": False, "error": "USER_NOT_IN_VOICE"}

        if not await self.ensure_connected(g, member.voice.channel):
            return {"ok": False, "error": "VOICE_CONNECT_FAILED"}

        # playlist/mix expansion si besoin
        url = (item or {}).get("url") or ""
        bundle_entries = []
        if is_bundle_url(url):
            try:
                bundle_entries = expand_bundle(
                    url, limit=10, cookies_file=self.youtube_cookies_file, cookies_from_browser=None
                ) or []
            except Exception:
                bundle_entries = []
            if bundle_entries:
                head = bundle_entries[0]
                item = {**item, **{
                    "title": head.get("title") or item.get("title"),
                    "url": head.get("url") or item.get("url"),
                    "artist": head.get("artist"),
                    "thumb": head.get("thumb"),
                    "duration": head.get("duration"),
                }}

        res = await self.enqueue(gid, int(user_id), item)
        if not res.get("ok"):
            return res

        if not self.is_playing.get(gid, False):
            await self.play_next(g)
        return {"ok": True}
