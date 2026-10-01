"""Synchro son/vidéo côté bot (spec §4.2) : source comptée, pré-lecture, log [SYNC], bloc clock, ticker."""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from bot.services.audio_clock import CountingSource
from core_fakes import harness, yt_entry  # noqa: F401  (fixture importée)

pytestmark = pytest.mark.asyncio

A = yt_entry(1, title="A")
B = yt_entry(2, title="B")


def _plays(vc, url):
    return sum(1 for s in vc.play_calls if s.url == url)


async def _playing(h, vc, url, n=1):
    await h.wait_for(lambda: _plays(vc, url) >= n, timeout=3, msg=f"{url} jamais joué")
    return [s for s in vc.play_calls if s.url == url][n - 1]


# ─────────────────────────── Pré-lecture (B2) ───────────────────────────


async def test_music_source_is_counted_and_primed_before_vc_play(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"read_delay": 0.2}  # 1er octet lent (mode pipe, yt-dlp qui démarre)
    h.seed_queue([A])
    t0 = time.monotonic()
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    assert isinstance(src, CountingSource)
    assert src.url == A["url"] and src.mode == "direct"
    assert h.ext.sources[0].reads == 1, "une trame lue d'avance, avant vc.play"
    assert src.frames == 0, "pas encore envoyée"
    assert h.svc.play_start[h.gid] - t0 >= 0.2, "play_start posé APRÈS la pré-lecture"


async def test_stream_without_audio_never_reaches_vc_play(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"no_audio": True}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await _playing(h, vc, B["url"])
    assert _plays(vc, A["url"]) == 0
    a_calls = [c for c in h.ext.calls if c[1] == A["url"] and c[0] == "stream"]
    assert len(a_calls) == h.ps._MAX_FAILURES_PER_TRACK, "même politique d'abandon qu'un extracteur KO"
    assert all(s.cleaned for s in h.ext.sources if s.url == A["url"])
    assert A["url"] not in h.urls()


async def test_skip_interrupts_a_preroll_that_never_ends(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"read_delay": 30}  # ffmpeg muet (réseau bloqué) : read() ne rend rien
    h.seed_queue([A, B])
    task = asyncio.create_task(h.svc.play_next(h.guild))
    await h.wait_for(lambda: h.ext.sources and h.ext.sources[0].url == A["url"], msg="A pas extrait")
    await h.svc.skip(h.gid)
    await h.wait_for(task.done, msg="la pré-lecture garde le verrou de lecture malgré le skip")
    await _playing(h, vc, B["url"])
    assert _plays(vc, A["url"]) == 0
    await h.wait_for(lambda: h.ext.sources[0].cleaned, msg="ffmpeg de A jamais tué")


async def test_silent_ffmpeg_is_a_failed_start_after_the_preroll_budget(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.ps, "_PREROLL_MAX_S", 0.2, raising=False)
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"read_delay": 30}  # ni trame ni fin de flux (b'')
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await _playing(h, vc, B["url"])
    assert _plays(vc, A["url"]) == 0
    a_srcs = [s for s in h.ext.sources if s.url == A["url"]]
    assert len(a_srcs) == h.ps._MAX_FAILURES_PER_TRACK, "même politique d'abandon qu'un extracteur KO"
    await h.wait_for(lambda: all(s.cleaned for s in a_srcs), msg="ffmpeg muet jamais tué")


async def test_first_frame_logs_sync_and_emits(harness, caplog):
    caplog.set_level(logging.INFO, logger="greg.player")
    h = harness
    vc = h.connect_bot()
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    before = len(h.bot.emits)
    src.read()  # le thread audio de discord.py envoie la 1re trame
    await h.wait_for(lambda: len(h.bot.emits) > before, msg="pas d'état à la 1re trame")
    sync = [r.getMessage() for r in caplog.records if "[SYNC]" in r.getMessage()]
    assert len(sync) == 1 and "mode=direct" in sync[0], sync


# ─────────────────────────── Bloc clock de get_state (B3) ───────────────────────────


def _clock(h):
    st = h.svc.get_state(h.gid)
    return st, st["clock"]


async def test_clock_status_follows_the_audio(harness):
    """loading → playing → paused → playing → stalled → playing (spec §7)."""
    h = harness
    vc = h.connect_bot()
    st, c = _clock(h)
    assert c["status"] == "idle" and c["play_id"] is None and c["position_ms"] is None
    h.ext.behaviour[A["url"]] = {"delay": 0.3}
    h.seed_queue([A])
    task = asyncio.create_task(h.svc.play_next(h.guild))
    await h.wait_for(lambda: h.ext.calls, msg="extraction jamais lancée")
    st, c = _clock(h)
    assert st["current"]["url"] == A["url"]
    assert (c["status"], c["position_ms"], st["position"], st["progress"]["elapsed"]) == ("loading", None, 0, 0)
    await task
    src = await _playing(h, vc, A["url"])
    st, c = _clock(h)
    assert c["status"] == "loading", "vc.play fait, aucune trame envoyée"
    assert isinstance(c["play_id"], str) and len(c["play_id"]) == 8
    int(c["play_id"], 16)
    for _ in range(60):
        src.read()  # 60 trames : 1,2 s
    st, c = _clock(h)
    assert (c["status"], c["position_ms"], st["position"], st["progress"]["elapsed"]) == ("playing", 1200.0, 1, 1)
    assert abs(c["sampled_at_ms"] - time.time() * 1000) < 1000
    assert await h.svc.pause(h.gid)
    await asyncio.sleep(0.3)  # pause plus longue que le seuil de blocage
    st, c = _clock(h)
    assert (c["status"], c["position_ms"]) == ("paused", 1200.0)
    assert await h.svc.resume(h.gid)
    assert _clock(h)[1]["status"] == "playing", "la pause n'est pas un blocage"
    src.last_read_at -= 1.0  # plus rien lu depuis 1 s : flux bloqué
    assert _clock(h)[1]["status"] == "stalled"
    src.read()
    st, c = _clock(h)
    assert (c["status"], c["position_ms"]) == ("playing", 1220.0)


async def test_play_id_changes_on_restart(harness):
    h = harness
    vc = h.connect_bot()
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    first = await _playing(h, vc, A["url"])
    first.read()
    pid = _clock(h)[1]["play_id"]
    assert await h.svc.restart(h.gid)
    again = await _playing(h, vc, A["url"], n=2)
    again.read()
    c = _clock(h)[1]
    assert c["status"] == "playing" and c["play_id"] != pid
    assert c["position_ms"] == 20.0, "repart de zéro"


async def test_loading_window_does_not_inherit_the_previous_position(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[B["url"]] = {"delay": 0.5}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    for _ in range(150):
        src.read()  # 3 s de A
    assert h.svc.get_state(h.gid)["position"] == 3
    emits = len(h.bot.emits)
    await h.svc.skip(h.gid)
    await h.wait_for(lambda: (h.svc.now_playing.get(h.gid) or {}).get("url") == B["url"], msg="B jamais choisi")
    st, c = _clock(h)
    assert st["current"]["url"] == B["url"]
    assert (c["status"], c["play_id"], c["position_ms"], st["position"]) == ("loading", None, None, 0)
    assert len(h.bot.emits) > emits, "l'état « loading » part tout de suite"
