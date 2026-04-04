"""PlayerService v2 — Service de lecture musicale.

Changements par rapport à v1 :
- Utilise greg_shared.priority (nouveau système avec PermissionResult)
- Émet via bot.emit_state_update() (Redis) au lieu de socketio direct
- find_insert_position() pour l'insertion triée en 2 zones
- check_quota() structuré
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from typing import Any, Dict, List, Optional

import discord

from greg_shared.config import settings
from greg_shared.extractors import expand_bundle, get_extractor, is_bundle_url
from greg_shared.priority import (
    PermissionResult,
    build_user_info,
    can_control_playback,
    can_edit_queue_item,
    check_quota,
    find_insert_position,
    get_member_weight,
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
        self._locks: Dict[int, asyncio.Lock] = {}

        self._cookies_file = settings.get_cookies_file()
        self._ratelimit = settings.ytdlp_limit_bps

    # ─── Internal helpers ───

    def _guild_lock(self, gid: int) -> asyncio.Lock:
        if gid not in self._locks:
            self._locks[gid] = asyncio.Lock()
        return self._locks[gid]

    def _get_pm(self, guild_id: int) -> PlaylistManager:
        gid = int(guild_id)
        if gid not in self.pm_map:
            self.pm_map[gid] = PlaylistManager(gid)
        return self.pm_map[gid]

    def _get_hm(self, guild_id: int) -> HistoryManager:
        gid = int(guild_id)
        if gid not in self.hm_map:
            self.hm_map[gid] = HistoryManager(gid)
        return self.hm_map[gid]

    def get_history(self, guild_id: int, mode: str = "top", limit: int = 20) -> dict:
        """Retourne l'historique pour une guild."""
        hm = self._get_hm(guild_id)
        if mode == "recent":
            items = hm.get_recent(limit)
        else:
            items = hm.get_top(limit)
        return {"ok": True, "items": items, "mode": mode}

    def _afilter_for(self, gid: int) -> Optional[str]:
        return AUDIO_EQ_PRESETS.get(self.audio_mode.get(gid, "music"))

    def _clear_now_playing(self, gid: int):
        self.is_playing[gid] = False
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

        pm = self._get_pm(gid)
        try:
            pm.reload()
        except Exception:
            pass

        queue = pm.to_dict().get("queue", [])
        queue_users = {}
        seen = set()
        for it in queue[:25]:
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
        from greg_shared.extractors import get_extractor
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
                    duration = parts[-1] + (parts[-2] * 60 if len(parts) >= 2 else 0)
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
        item = dict(item or {})
        item["added_by"] = str(user_id)
        item = self._normalize_item(item)

        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.reload)
        queue = await loop.run_in_executor(None, pm.get_queue)

        # Check quota
        quota = check_quota(queue, user_id, self.bot, gid)
        if not quota.allowed:
            parts = quota.reason.split(":")
            return {"ok": False, "error": f"Quota atteint ({parts[1] if len(parts) > 1 else ''})."}

        # Attribuer le poids
        weight = get_member_weight(self.bot, gid, user_id)
        item["priority"] = weight

        # Ajouter à la queue
        await loop.run_in_executor(None, pm.add, item)

        # Trouver la bonne position et déplacer si nécessaire
        new_queue = await loop.run_in_executor(None, pm.get_queue)
        current_idx = len(new_queue) - 1
        target_idx = find_insert_position(new_queue[:-1], weight)  # Chercher dans la queue SANS le nouvel item

        if 0 <= target_idx < len(new_queue) and target_idx != current_idx:
            await loop.run_in_executor(None, pm.move, current_idx, target_idx)

        self._emit(gid)
        return {"ok": True, "item": item, "position": target_idx}

    # ─── Playback ───

    async def ensure_connected(self, guild: discord.Guild, channel) -> bool:
        if not channel or not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return False
        vc = guild.voice_client
        try:
            if vc and vc.is_connected():
                if getattr(vc, "channel", None) and int(vc.channel.id) == int(channel.id):
                    return True
                await vc.move_to(channel)
                return True
            await channel.connect()
            # Jouer l'intro si elle existe
            try:
                await self._play_intro(guild, int(guild.id))
            except Exception:
                pass
            return True
        except Exception as e:
            logger.warning("Connexion vocale impossible: %s", e)
            return False

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
            pm = self._get_pm(gid)
            await loop.run_in_executor(None, pm.reload)

            vc = guild.voice_client
            if vc and vc.is_playing():
                return
            if vc and vc.is_paused():
                vc.stop()

            item = await loop.run_in_executor(None, pm.pop_next)
            if not item:
                self._clear_now_playing(gid)
                self._emit(gid)
                return

            if self.repeat_all.get(gid):
                await loop.run_in_executor(None, pm.add, item)

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

            # Essai stream direct puis pipe
            for method in ("stream", "stream_pipe"):
                if not hasattr(extractor, method):
                    continue
                try:
                    srcp, title = await self._call_extractor(
                        extractor, method, url, self.ffmpeg_path,
                        **self._extractor_kwargs(extractor, method, gid),
                    )
                    if title and isinstance(title, str):
                        self.current_song[gid]["title"] = title
                        self.now_playing[gid]["title"] = title
                    await self._play_source(guild, gid, srcp)
                    return
                except Exception as e:
                    logger.warning("[%s KO] guild=%s url=%s: %s", method, gid, url, e)

            # Aucun method n'a marché
            logger.error("Tous les extractors ont échoué pour %s", url)
            self._clear_now_playing(gid)
            self._emit(gid)
            asyncio.create_task(self.play_next(guild))

    async def _call_extractor(self, extractor, method: str, *args, **kwargs):
        fn = getattr(extractor, method)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _play_source(self, guild: discord.Guild, gid: int, srcp):
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        self.current_source[gid] = srcp

        def _after(_e):
            try:
                src = self.current_source.pop(gid, None)
                if src and hasattr(src, "cleanup"):
                    try:
                        src.cleanup()
                    except Exception:
                        pass
            finally:
                asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)

        vc.play(srcp, after=_after)
        self.play_start[gid] = time.monotonic()
        self.paused_total[gid] = 0.0
        self.paused_since.pop(gid, None)
        self.is_playing[gid] = True
        self._ensure_ticker(gid)
        self._emit(gid)

        # Record in history
        try:
            cur = self.current_song.get(gid, {})
            added_by = cur.get("added_by") or cur.get("requested_by")
            self._get_hm(gid).record_play(cur, played_by=added_by)
        except Exception as e:
            logger.debug("history record failed: %s", e)

    # ─── Controls ───

    async def skip(self, guild_id: int, requester_id: int = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        elif g:
            await self.play_next(g)
        self._emit(gid)
        return True

    async def stop(self, guild_id: int, requester_id: int = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, requester_id)
        pm = self._get_pm(gid)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pm.stop)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
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
        pm = self._get_pm(gid)
        q = pm.peek_all()
        if not (0 <= index < len(q)):
            return False
        perm = can_edit_queue_item(self.bot, gid, requester_id, q[index])
        if not perm.allowed:
            raise PermissionError(perm.reason)
        ok = pm.remove_at(index)
        if ok:
            self._emit(gid)
        return ok

    def move(self, guild_id: int, requester_id: int, src: int, dst: int) -> bool:
        gid = int(guild_id)
        pm = self._get_pm(gid)
        q = pm.peek_all()
        if not (0 <= src < len(q) and 0 <= dst < len(q)):
            return False

        # Check permission sur l'item
        perm = can_edit_queue_item(self.bot, gid, requester_id, q[src])
        if not perm.allowed:
            raise PermissionError(perm.reason)

        # Valider le move (zone prio/normal)
        move_perm = validate_move(q, src, dst, requester_id, self.bot, gid)
        if not move_perm.allowed:
            raise PermissionError(move_perm.reason)

        ok = pm.move(src, dst)
        if ok:
            self._emit(gid)
        return ok

    async def play_at(self, guild_id: int, user_id: int, index: int) -> bool:
        """Joue le morceau à l'index donné dans la queue."""
        gid = int(guild_id)
        pm = self._get_pm(gid)
        q = pm.peek_all()
        if not (0 <= index < len(q)):
            return False
        item = q[index]
        # Retire l'item de sa position actuelle
        pm.remove_at(index)
        # L'insère en tête
        pm.insert_at(0, item)
        # Skip le morceau en cours pour lancer le prochain (qui est notre item)
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # triggers _after which calls play_next
        elif g:
            await self.play_next(g)
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
        # Réinsère le morceau en tête de queue
        pm = self._get_pm(gid)
        pm.insert_at(0, dict(cur))
        # Skip pour relancer
        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        elif g:
            await self.play_next(g)

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

    async def play_for_user(self, guild_id: int, user_id: int, item: dict) -> dict:
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        if not g:
            return {"ok": False, "error": "GUILD_NOT_FOUND"}
        member = g.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            return {"ok": False, "error": "USER_NOT_IN_VOICE"}
        if not await self.ensure_connected(g, member.voice.channel):
            return {"ok": False, "error": "VOICE_CONNECT_FAILED"}

        url = (item or {}).get("url", "")
        bundle_entries = []
        if is_bundle_url(url):
            try:
                bundle_entries = expand_bundle(url, limit=10, cookies_file=self._cookies_file) or []
            except Exception:
                pass

        if bundle_entries:
            head = bundle_entries[0]
            item = {**item, "title": head.get("title") or item.get("title"),
                    "url": head.get("url") or item.get("url"),
                    "artist": head.get("artist"), "thumb": head.get("thumb"),
                    "duration": head.get("duration"), "provider": head.get("provider") or "youtube"}

        res = await self.enqueue(gid, user_id, item)
        if not res.get("ok"):
            return res

        if bundle_entries and len(bundle_entries) > 1:
            for e in bundle_entries[1:10]:
                try:
                    await self.enqueue(gid, user_id, {
                        "title": e.get("title"), "url": e.get("url"),
                        "artist": e.get("artist"), "thumb": e.get("thumb"),
                        "duration": e.get("duration"), "provider": e.get("provider") or "youtube",
                    })
                except Exception:
                    pass

        if not self.is_playing.get(gid, False):
            await self.play_next(g)
        return {"ok": True}

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
