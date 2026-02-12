from __future__ import annotations

import os
import time
import asyncio
import logging
from typing import Any, Optional, Dict, List

import discord

from utils.playlist_manager import PlaylistManager
from utils.priority_rules import (
    get_member_weight, can_user_bump_over, can_bypass_quota,
    first_non_priority_index, can_user_edit_item, build_user_out
)

from utils.ffmpeg import detect_ffmpeg
from api.services.oembed import oembed

from extractors import get_extractor, is_bundle_url, expand_bundle

log = logging.getLogger(__name__)

AUDIO_EQ_PRESETS = {
    "off":   None,
    "music": "highpass=f=32,volume=-6dB,bass=g=4:f=95:w=1.0,alimiter=limit=0.98:attack=5:release=50",
}


class PlayerService:
    def __init__(self, bot: discord.Client, emit_fn=None):
        self.bot = bot
        self.emit_fn = emit_fn
        self.intro_playing: Dict[int, bool] = {}

        # ✅ Keys = int guild_id partout (pas de mix str/int)
        self.pm_map: Dict[int, PlaylistManager] = {}
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

        self.youtube_cookies_file = (
            os.getenv("YTDLP_COOKIES_FILE")
            or (os.getenv("YOUTUBE_COOKIES_PATH") if os.getenv("YOUTUBE_COOKIES_PATH") else None)
            or ("youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None)
        )
        try:
            self.yt_ratelimit = int(os.getenv("YTDLP_LIMIT_BPS", "2500000"))
        except Exception:
            self.yt_ratelimit = 2_500_000

    def set_emit_fn(self, emit_fn):
        self.emit_fn = emit_fn

    def _guild_lock(self, gid: int) -> asyncio.Lock:
        lock = self._locks.get(gid)
        if not lock:
            lock = asyncio.Lock()
            self._locks[gid] = lock
        return lock

    def _get_pm(self, guild_id: int) -> PlaylistManager:
        gid = int(guild_id)
        pm = self.pm_map.get(gid)
        if pm is None:
            pm = PlaylistManager(gid)
            self.pm_map[gid] = pm
            log.info("PlaylistManager créée pour guild %s", gid)
        return pm

    def _afilter_for(self, gid: int) -> Optional[str]:
        mode = self.audio_mode.get(gid, "music")
        return AUDIO_EQ_PRESETS.get(mode)

    # ---------- overlay payload ----------
    def _overlay_payload(self, gid: int) -> dict:
        g = self.bot.get_guild(int(gid))
        vc = g.voice_client if g else None
        is_paused_vc = bool(vc and vc.is_paused())

        start = self.play_start.get(gid)
        paused_since = self.paused_since.get(gid)
        paused_total = self.paused_total.get(gid, 0.0)

        elapsed = 0
        if start:
            base = paused_since or time.monotonic()
            elapsed = max(0, int(base - start - paused_total))

        meta = self.current_meta.get(gid, {}) or {}
        duration = meta.get("duration")
        thumb = meta.get("thumbnail")

        cur = (self.now_playing.get(gid) or self.current_song.get(gid))
        if isinstance(cur, dict):
            if duration is None and isinstance(cur.get("duration"), (int, float)):
                duration = int(cur["duration"])
            thumb = thumb or cur.get("thumb") or cur.get("thumbnail")

        requested_by_user = None
        if isinstance(cur, dict) and cur.get("added_by"):
            try:
                requested_by_user = build_user_out(self.bot, gid, int(cur["added_by"]))
            except Exception:
                requested_by_user = None

        # queue + users
        pm = self._get_pm(gid)
        try:
            pm.reload()
        except Exception:
            pass

        queue = pm.to_dict().get("queue", []) or []
        uniq_ids: List[str] = []
        for it in queue:
            uid = (it or {}).get("requested_by") or (it or {}).get("added_by")
            if uid and str(uid) not in uniq_ids:
                uniq_ids.append(str(uid))
            if len(uniq_ids) >= 25:
                break

        queue_users: Dict[str, Dict[str, Any]] = {}
        for s in uniq_ids:
            try:
                queue_users[str(s)] = build_user_out(self.bot, gid, int(s))
            except Exception:
                pass

        # ✅ normalise toujours duration/position au root
        pos = int(elapsed) if elapsed is not None else 0
        dur = int(duration) if duration is not None else None

        return {
            "queue": queue,
            "current": cur,
            # ✅ standard "paused"
            "paused": bool(is_paused_vc),
            "is_paused": bool(is_paused_vc),  # compat

            # ✅ standard "position/duration" (plats)
            "position": pos,
            "duration": dur,

            # ✅ compat ancien format
            "progress": {"elapsed": pos, "duration": dur},

            "thumbnail": thumb,
            "repeat_all": bool(self.repeat_all.get(gid, False)),
            "requested_by_user": requested_by_user,
            "queue_users": queue_users,
        }


    # ✅ API unique pour REST + WS
    def get_state(self, guild_id: int) -> dict:
        gid = int(guild_id)
        payload = self._overlay_payload(gid)
        payload["guild_id"] = gid
        return payload

    def _emit_playlist_update(self, gid: int, payload=None):
        if not self.emit_fn:
            return
        if payload is None:
            payload = self.get_state(gid)
        else:
            payload = dict(payload)
            payload["guild_id"] = gid
        try:
            self.emit_fn("playlist_update", payload, guild_id=str(gid))
        except TypeError:
            self.emit_fn("playlist_update", payload)

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

                    pos = int(elapsed) if elapsed is not None else 0
                    dur = int(duration) if duration is not None else None

                    payload = {
                        "only_elapsed": True,
                        "paused": bool(vc and vc.is_paused()),
                        "is_paused": bool(vc and vc.is_paused()),

                        # ✅ champs plats
                        "position": pos,
                        "duration": dur,

                        # ✅ compat
                        "progress": {"elapsed": pos, "duration": dur},
                    }


                    self._emit_playlist_update(gid, payload)
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass
            finally:
                self._progress_task.pop(gid, None)

        self._progress_task[gid] = asyncio.create_task(_runner())

    def _current_owner_weight(self, guild_id: int) -> int:
        gid = int(guild_id)
        cur = self.now_playing.get(gid) or {}
        w = int(cur.get("priority") or 0)
        if w > 0:
            return w
        owner = cur.get("added_by") or cur.get("owner_id")
        try:
            return get_member_weight(self.bot, gid, int(owner))
        except Exception:
            return 0

    async def _ensure_can_control(self, guild_id: int, requester_id: int) -> None:
        gid = int(guild_id)
        if can_bypass_quota(self.bot, gid, int(requester_id)):
            return
        owner_w = self._current_owner_weight(gid)
        if not can_user_bump_over(self.bot, gid, int(requester_id), owner_w):
            raise PermissionError("PRIORITY_FORBIDDEN")

    async def _play_intro_and_then_next(self, guild: discord.Guild, gid: int) -> None:
        """
        Joue un petit son d'intro, puis enchaîne sur play_next si rien ne joue déjà.
        """
        intro_path = os.path.join("assets", "sounds", "Ouais_cest_greg.mp3")
        if not os.path.exists(intro_path):
            return

        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return

        # Si déjà en lecture (musique), ne pas interrompre
        if vc.is_playing() or vc.is_paused():
            return

        # Évite de lancer 2 intros en parallèle
        if self.intro_playing.get(gid):
            return

        self.intro_playing[gid] = True

        def _after(_e: Exception | None):
            self.intro_playing[gid] = False
            # Dès que l'intro finit, si rien ne joue, on enchaîne sur la musique
            try:
                asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)
            except Exception:
                pass

        try:
            # Utilise ton ffmpeg détecté
            source = discord.FFmpegPCMAudio(
                intro_path,
                executable=self.ffmpeg_path,
                before_options="-nostdin",
                options="-vn"
            )
            vc.play(source, after=_after)
        except Exception as e:
            self.intro_playing[gid] = False
            log.warning("Intro sound failed: %s", e)

    # ---------- normalisation ----------
    def _normalize_item(self, it: dict) -> dict:
        url = (it.get("url") or "").strip() or None
        title = (it.get("title") or "").strip()
        artist = (it.get("artist") or "").strip() or None
        thumb = (it.get("thumb") or it.get("thumbnail") or None)
        provider = it.get("provider")

        if url and (not title or not artist or not thumb):
            oe = oembed(url) or {}
            title = title or oe.get("title") or url
            artist = artist or oe.get("author_name")
            thumb = thumb or oe.get("thumbnail_url")

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
            "provider": provider,
        }
        for k in ("mode", "added_by", "priority", "ts"):
            if k in it:
                out[k] = it[k]
        return out

    # ---------- opérations publiques ----------
    async def ensure_connected(self, guild: discord.Guild, channel: Optional[discord.abc.GuildChannel]) -> bool:
        if not channel or not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return False

        vc = guild.voice_client
        try:
            # Déjà connecté → move si besoin
            if vc and vc.is_connected():
                if getattr(vc, "channel", None) and int(vc.channel.id) == int(channel.id):
                    return True
                await vc.move_to(channel)
                return True

            # Pas connecté → connect
            await channel.connect()

            # ✅ Intro uniquement à la connexion
            try:
                await self._play_intro_and_then_next(guild, int(guild.id))
            except Exception:
                pass

            return True

        except Exception as e:
            log.warning("Connexion/Move vocal impossible: %s", e)
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
            try:
                from settings import PER_USER_CAP
            except Exception:
                PER_USER_CAP = 999999
            user_count = sum(1 for it in queue if str(it.get("added_by")) == str(user_id))
            if user_count >= PER_USER_CAP:
                return {"ok": False, "error": f"Quota atteint ({PER_USER_CAP})."}

        weight = int(get_member_weight(self.bot, gid, int(user_id)))
        item["priority"] = weight

        await loop.run_in_executor(None, pm.add, item)

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
            if vc and vc.is_playing():
                return
            if vc and vc.is_paused():
                vc.stop()

            item = await loop.run_in_executor(None, pm.pop_next)
            if not item:
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
                "provider": item.get("provider"),
            }
            dur_int = int(item["duration"]) if isinstance(item.get("duration"), (int, float)) else None
            self.current_meta[gid] = {"duration": dur_int, "thumbnail": item.get("thumb")}
            self.now_playing[gid] = dict(self.current_song[gid])

            extractor = get_extractor(url)
            if extractor is None:
                self.is_playing[gid] = False
                self._emit_playlist_update(gid)
                return

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

            # try direct then pipe
            try:
                srcp, real_title = await self._call_extractor(extractor, "stream", url, self.ffmpeg_path, **_kw("stream"))
                if real_title and isinstance(real_title, str):
                    self.current_song[gid]["title"] = real_title
                    self.now_playing[gid]["title"] = real_title
                await self._play_source(guild, gid, srcp)
                return
            except Exception as ex_direct:
                log.debug("[stream direct KO] %s", ex_direct)

            srcp, real_title = await self._call_extractor(extractor, "stream_pipe", url, self.ffmpeg_path, **_kw("stream_pipe"))
            if real_title and isinstance(real_title, str):
                self.current_song[gid]["title"] = real_title
                self.now_playing[gid]["title"] = real_title
            await self._play_source(guild, gid, srcp)

    async def _call_extractor(self, extractor_module, method_name: str, *args, **kwargs):
        """
        ✅ IMPORTANT: pas de asyncio.run().
        Ton extractor YouTube est déjà async + fait ses heavy calls via to_thread/executor.
        """
        fn = getattr(extractor_module, method_name, None)
        if not fn:
            raise AttributeError(f"{extractor_module} has no method {method_name}")

        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _play_source(self, guild: discord.Guild, gid: int, srcp):
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        self.current_source[gid] = srcp

        def _after(_e: Exception | None):
            try:
                src = self.current_source.pop(gid, None)
                if src and hasattr(src, "cleanup"):
                    try:
                        src.cleanup()
                    except Exception:
                        pass
                proc = getattr(src, "_ytdlp_proc", None)
                if proc:
                    try:
                        proc.kill()
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
        self._emit_playlist_update(gid)

    # === commandes protégées par la priorité =====================

    async def stop(self, guild_id: int, requester_id: int | None = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, int(requester_id))

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

    async def skip(self, guild_id: int, requester_id: int | None = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, int(requester_id))

        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        else:
            if g:
                await self.play_next(g)
        self._emit_playlist_update(gid)
        return True

    async def pause(self, guild_id: int, requester_id: int | None = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, int(requester_id))

        g = self.bot.get_guild(gid)
        vc = g and g.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self.paused_since[gid] = time.monotonic()
            self._emit_playlist_update(gid)
            return True
        return False

    async def resume(self, guild_id: int, requester_id: int | None = None) -> bool:
        gid = int(guild_id)
        if requester_id is not None:
            await self._ensure_can_control(gid, int(requester_id))

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

    # === édition de queue protégée par la priorité ================

    def remove_at(self, guild_id: int, requester_id: int, index: int) -> bool:
        gid = int(guild_id)
        pm = self._get_pm(gid)
        q = pm.peek_all()
        if not (0 <= index < len(q)):
            return False
        it = q[index]
        if not can_user_edit_item(self.bot, gid, int(requester_id), it):
            raise PermissionError("PRIORITY_FORBIDDEN")
        ok = pm.remove_at(index)
        if ok:
            self._emit_playlist_update(gid)
        return ok

    def move(self, guild_id: int, requester_id: int, src: int, dst: int) -> bool:
        gid = int(guild_id)
        pm = self._get_pm(gid)
        q = pm.peek_all()
        if not (0 <= src < len(q) and 0 <= dst < len(q)):
            return False

        barrier = first_non_priority_index(q)
        src_prio, dst_prio = src < barrier, dst < barrier

        if src_prio != dst_prio and not can_bypass_quota(self.bot, gid, int(requester_id)):
            raise PermissionError("PRIORITY_FORBIDDEN")

        it = q[src]
        if not can_user_edit_item(self.bot, gid, int(requester_id), it):
            raise PermissionError("PRIORITY_FORBIDDEN")

        ok = pm.move(src, dst)
        if ok:
            self._emit_playlist_update(gid)
        return ok

    # === réglages ================================================

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

    # === entrée principale (commande / web) ======================

    async def play_for_user(self, guild_id: int, user_id: int, item: dict):
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        if not g:
            return {"ok": False, "error": "GUILD_NOT_FOUND"}

        member = g.get_member(int(user_id))
        if not member or not member.voice or not member.voice.channel:
            return {"ok": False, "error": "USER_NOT_IN_VOICE"}

        if not await self.ensure_connected(g, member.voice.channel):
            return {"ok": False, "error": "VOICE_CONNECT_FAILED"}

        url = (item or {}).get("url") or ""
        bundle_entries: List[dict] = []
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
                    "provider": head.get("provider") or "youtube",
                }}

        res = await self.enqueue(gid, int(user_id), item)
        if not res.get("ok"):
            return res

        if bundle_entries and len(bundle_entries) > 1:
            tail = bundle_entries[1:10]
            for e in tail:
                try:
                    _ = await self.enqueue(gid, int(user_id), {
                        "title": e.get("title"),
                        "url": e.get("url"),
                        "artist": e.get("artist"),
                        "thumb": e.get("thumb"),
                        "duration": e.get("duration"),
                        "provider": e.get("provider") or "youtube",
                    })
                except Exception:
                    pass
            self._emit_playlist_update(gid)

        if not self.is_playing.get(gid, False):
            await self.play_next(g)
        return {"ok": True}
