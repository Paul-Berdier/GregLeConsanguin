"""PlayerService — lecture, échecs, contrôles, permissions, file d'attente."""
from __future__ import annotations

import asyncio
import os
import time

import pytest

from core_fakes import BOT_CHANNEL, FakeVC, harness, yt_entry  # noqa: F401  (fixture importée)

pytestmark = pytest.mark.asyncio

A = yt_entry(1, title="A")
B = yt_entry(2, title="B")
C = yt_entry(3, title="C")


def _plays(vc, url):
    return sum(1 for s in vc.play_calls if s.url == url)


def _count(h, url):
    return sum(1 for u in h.urls() if u == url)


# ─────────────────────────── Voix absente ───────────────────────────


async def test_play_next_without_voice_client_keeps_the_queue(harness):
    h = harness
    h.seed_queue([A, B, C])
    await h.svc.play_next(h.guild)  # Greg n'est pas en vocal
    await h.settle(0.1)
    assert h.urls() == [A["url"], B["url"], C["url"]]
    assert h.ext.calls == []


async def test_vc_play_failure_is_not_a_track_failure(harness):
    import discord

    h = harness
    vc = h.connect_bot()
    vc.play_exc = discord.ClientException("Not connected to voice.")
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.settle(0.1)
    assert h.urls()[0] == A["url"], "le morceau doit rester en tête de file"
    assert h.svc._track_failures == {}
    assert all(s.cleaned for s in h.ext.sources)


# ─────────────────────────── Plafond d'échecs ───────────────────────────


async def test_track_dying_at_start_is_abandoned_after_max_failures(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"die_after": 0.01}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=4, msg="B jamais joué (boucle infinie ?)")
    assert _plays(vc, A["url"]) == h.ps._MAX_FAILURES_PER_TRACK
    assert A["url"] not in h.urls()


async def test_track_cut_mid_stream_is_capped(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.ps, "_MIN_PLAYBACK_BEFORE_RECONNECT", 0.05)
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"die_after": 0.15}  # a démarré puis coupé (durée annoncée 180 s)
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=5, msg="coupure en boucle")
    assert 2 <= _plays(vc, A["url"]) <= 5


async def test_short_track_ending_normally_is_not_retried(harness):
    h = harness
    vc = h.connect_bot()
    short = yt_entry(9, title="Jingle", duration=3)
    h.ext.behaviour[short["url"]] = {"die_after": 0.05}
    h.seed_queue([short, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=3)
    assert _plays(vc, short["url"]) == 1


async def test_extractor_failures_are_capped_then_next_track(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"fail": True}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=4)
    a_calls = [c for c in h.ext.calls if c[1] == A["url"]]
    assert len(a_calls) == 2 * h.ps._MAX_FAILURES_PER_TRACK  # stream + stream_pipe par tentative
    assert A["url"] not in h.urls()


async def test_stream_pipe_not_retried_when_stream_already_tried_the_pipe(harness):
    """youtube.stream() bascule déjà sur stream_pipe en interne ; s'il échoue aussi,
    l'erreur porte pipe_tried=True → le player ne relance PAS une 2e extraction pipe."""
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"pipe_tried": True}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=4)
    a_calls = [c for c in h.ext.calls if c[1] == A["url"]]
    assert a_calls == [("stream", A["url"])] * h.ps._MAX_FAILURES_PER_TRACK, a_calls
    assert A["url"] not in h.urls()


async def test_duplicate_play_next_does_not_bypass_the_retry_backoff(harness, monkeypatch):
    """Web : play_for_user lance la lecture, puis voice/join (action 'join') rappelle
    ensure_playing → 2e play_next. Un échec transitoire doit quand même attendre le backoff."""
    import time

    h = harness
    monkeypatch.setattr(h.ps, "_RECONNECT_WAIT", 0.6)
    monkeypatch.setattr(h.ps, "_BACKOFF_MAX", 0.6)
    h.connect_bot()
    h.ext.behaviour[A["url"]] = {"fail": True, "delay": 0.1}
    stamps = []
    orig = h.ext._make

    async def stamped(method, url):
        stamps.append((time.monotonic(), method))
        return await orig(method, url)

    monkeypatch.setattr(h.ext, "_make", stamped)
    h.seed_queue([A, B])
    h.svc.ensure_playing(h.guild)
    h.svc.ensure_playing(h.guild)  # 2e appel (action 'join' juste après l'ajout)
    await h.wait_for(lambda: sum(1 for _, m in stamps if m == "stream") >= 2, timeout=3)
    attempts = [t for t, m in stamps if m == "stream"]
    assert attempts[1] - attempts[0] >= 0.6, f"2e tentative {attempts[1] - attempts[0]:.2f}s après la 1re"


async def test_unavailable_track_is_skipped_immediately(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"unavailable": True}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=2)
    assert [c for c in h.ext.calls if c[1] == A["url"]] == [("stream", A["url"])]  # ni pipe ni retry
    assert A["url"] not in h.urls()


async def test_skip_during_backoff_drops_the_failing_track(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.ps, "_RECONNECT_WAIT", 2.0)
    monkeypatch.setattr(h.ps, "_BACKOFF_MAX", 2.0)
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"fail": True}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.settle(0.1)
    assert h.urls()[0] == A["url"]  # remis en tête, retry en attente
    await h.svc.skip(h.gid)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=1.5)
    assert A["url"] not in h.urls()


# ─────────────────────────── Stop / skip pendant un chargement ───────────────────────────


async def test_stop_during_load_leaves_no_phantom_item(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"delay": 0.4}
    h.seed_queue([A, B])
    task = asyncio.create_task(h.svc.play_next(h.guild))
    await asyncio.sleep(0.1)
    await h.svc.stop(h.gid)
    await task
    await h.settle(0.2)
    assert h.queue() == []
    assert vc.play_calls == []
    assert all(s.cleaned for s in h.ext.sources)
    assert h.svc.current_song.get(h.gid) is None


async def test_stop_while_play_next_waits_for_the_queue_lock_plays_nothing(harness, monkeypatch):
    """stop() arrivé pendant que play_next attend le verrou de file : rien ne doit être joué."""
    import time

    h = harness
    vc = h.connect_bot()
    h.guild.add_member(10)
    for it in (A, B, C):  # extraction réaliste (thread) : rend la main à la boucle
        h.ext.behaviour[it["url"]] = {"delay": 0.1}
    h.seed_queue([A, B])
    pm = h.svc._get_pm(h.gid)
    real_insert_by = pm.insert_by

    def slow_insert_by(*a, **kw):
        time.sleep(0.2)  # écriture disque lente (pool), verrou de file tenu
        return real_insert_by(*a, **kw)

    monkeypatch.setattr(pm, "insert_by", slow_insert_by)
    t_enq = asyncio.create_task(h.svc.enqueue(h.gid, 10, C))
    await asyncio.sleep(0.05)
    t_next = asyncio.create_task(h.svc.play_next(h.guild))
    await asyncio.sleep(0.05)
    await h.svc.stop(h.gid)
    await t_enq
    await t_next
    await h.settle(0.3)
    assert vc.play_calls == [], [s.url for s in vc.play_calls]
    assert h.queue() == []
    assert h.svc.current_song.get(h.gid) is None


async def test_stale_pipe_source_is_cleaned_off_the_event_loop(harness):
    """Source pipe jamais jouée (stop pendant le chargement) : son cleanup() peut bloquer
    ~1 s (join du thread d'écriture) → jamais sur la boucle asyncio."""
    from core_fakes import loop_max_gap

    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"delay": 0.2, "cleanup_delay": 0.6}
    h.seed_queue([A, B])

    async def scenario():
        task = asyncio.create_task(h.svc.play_next(h.guild))
        await asyncio.sleep(0.05)
        await h.svc.stop(h.gid)
        await task
        await h.settle(0.8)

    _, gap = await loop_max_gap(scenario())
    assert gap < 0.3, f"boucle asyncio bloquée {gap:.2f}s par le cleanup de la source"
    assert vc.play_calls == []
    assert all(s.cleaned for s in h.ext.sources)


async def test_skip_during_load_moves_to_next_track(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"delay": 0.4}
    h.seed_queue([A, B])
    task = asyncio.create_task(h.svc.play_next(h.guild))
    await asyncio.sleep(0.1)
    await h.svc.skip(h.gid)
    await task
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=2)
    assert _plays(vc, A["url"]) == 0


# ─────────────────────────── repeat_all ───────────────────────────


async def test_repeat_all_retries_do_not_duplicate(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.ps, "_MIN_PLAYBACK_BEFORE_RECONNECT", 0.05)
    vc = h.connect_bot()
    await h.svc.toggle_repeat(h.gid, "on")
    h.ext.behaviour[A["url"]] = {"die_after": 0.15}  # coupé à chaque fois
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=5)
    assert _count(h, A["url"]) == 0, h.urls()  # abandonné : retiré de la boucle
    assert _count(h, B["url"]) == 1, h.urls()


async def test_restart_in_repeat_mode_does_not_duplicate(harness):
    h = harness
    vc = h.connect_bot()
    await h.svc.toggle_repeat(h.gid, "on")
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, A["url"]) == 1)
    assert _count(h, A["url"]) == 1  # copie repeat en fin de file
    assert await h.svc.restart(h.gid) is True
    await h.wait_for(lambda: _plays(vc, A["url"]) == 2)
    await h.settle(0.05)
    assert _count(h, A["url"]) == 1, h.urls()


# ─────────────────────────── play_at ───────────────────────────


async def test_play_at_requires_playback_control(harness):
    h = harness
    vc = h.connect_bot()
    h.guild.add_member(1, admin=True, channel_id=BOT_CHANNEL)
    h.guild.add_member(2, channel_id=BOT_CHANNEL)  # simple membre (poids 10)
    await h.svc.enqueue(h.gid, 1, A)  # morceau de l'admin (poids 100)
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, A["url"]) == 1)
    await h.svc.enqueue(h.gid, 2, B)
    await h.svc.enqueue(h.gid, 2, C)

    before = h.urls()
    with pytest.raises(PermissionError):
        await h.svc.play_at(h.gid, 2, 1)
    assert h.urls() == before
    assert vc.is_playing()


async def test_play_at_cannot_promote_normal_item_ahead_of_priority_items(harness):
    h = harness
    h.connect_bot()
    h.guild.add_member(1, roles=("DJ",), channel_id=BOT_CHANNEL)
    h.guild.add_member(2, channel_id=BOT_CHANNEL)
    await h.svc.enqueue(h.gid, 1, A)  # DJ (80) → zone prioritaire
    await h.svc.enqueue(h.gid, 2, B)  # normal
    before = h.urls()
    assert before == [A["url"], B["url"]]
    with pytest.raises(PermissionError):
        await h.svc.play_at(h.gid, 2, 1)
    assert h.urls() == before


async def test_play_at_allowed_for_own_item_when_idle(harness):
    h = harness
    vc = h.connect_bot()
    h.guild.add_member(2, channel_id=BOT_CHANNEL)
    await h.svc.enqueue(h.gid, 2, A)
    await h.svc.enqueue(h.gid, 2, B)
    assert await h.svc.play_at(h.gid, 2, 1) is True
    await h.wait_for(lambda: _plays(vc, B["url"]) == 1)


async def test_play_at_racing_play_next_plays_the_chosen_track(harness, monkeypatch):
    """play_next démarré pendant que play_at déplace X en tête (verrou de file tenu) :
    X doit être joué, pas jeté comme « périmé » (et A, B restent en file)."""
    import time

    h = harness
    vc = h.connect_bot()
    h.guild.add_member(7, channel_id=BOT_CHANNEL)
    a, b, x = (dict(it, added_by="7") for it in (A, B, C))
    h.seed_queue([a, b, x])
    pm = h.svc._get_pm(h.gid)
    real_move = pm.move

    def slow_move(*args, **kw):
        time.sleep(0.2)  # écriture disque lente (pool)
        return real_move(*args, **kw)

    monkeypatch.setattr(pm, "move", slow_move)
    t_at = asyncio.create_task(h.svc.play_at(h.gid, 7, 2))
    await asyncio.sleep(0.05)
    t_next = asyncio.create_task(h.svc.play_next(h.guild))  # fin d'intro, retry, fin de piste…
    assert await t_at is True
    await t_next
    await h.wait_for(lambda: vc.is_playing(), msg="rien ne joue")
    await h.settle(0.1)
    assert h.svc.current_song[h.gid]["url"] == x["url"], h.urls()
    assert h.urls() == [a["url"], b["url"]]


# ─────────────────────────── enqueue ───────────────────────────


async def test_concurrent_enqueues_keep_priority_order(harness):
    h = harness
    h.guild.add_member(10)            # normal
    h.guild.add_member(20, roles=("VIP",))  # prioritaire (60 > 50)
    h.seed_queue([dict(yt_entry(50 + i), added_by="99", priority=10) for i in range(3)])
    items = [yt_entry(60 + i) for i in range(6)]
    vip = yt_entry(77, title="VIP")
    coros = [h.svc.enqueue(h.gid, 10, it) for it in items[:3]]
    coros.append(h.svc.enqueue(h.gid, 20, vip))
    coros += [h.svc.enqueue(h.gid, 10, it) for it in items[3:]]
    results = await asyncio.gather(*coros)
    assert all(r["ok"] for r in results)
    q = h.queue()
    assert q[0]["url"] == vip["url"], [it["title"] for it in q]
    assert [it["url"] for it in q[1:4]] == [yt_entry(50 + i)["url"] for i in range(3)]
    assert [it["url"] for it in q[4:]] == [it["url"] for it in items]


async def test_enqueue_quota_error_shape(harness):
    h = harness
    h.guild.add_member(10)
    h.seed_queue([dict(yt_entry(i), added_by="10") for i in range(10)])
    res = await h.svc.enqueue(h.gid, 10, yt_entry(99))
    assert res["ok"] is False and res["error"] == "QUOTA_EXCEEDED"
    assert isinstance(res["message"], str) and "10/10" in res["message"]


async def test_enqueue_refuses_raw_bundle_url(harness):
    h = harness
    h.guild.add_member(10)
    res = await h.svc.enqueue(h.gid, 10, {"url": "https://www.youtube.com/playlist?list=PL123"})
    assert res["ok"] is False
    assert h.queue() == []


# ─────────────────────────── Guild inconnue ───────────────────────────


async def test_unknown_guild_never_creates_state(harness):
    h = harness
    unknown = 987654321
    st = h.svc.get_state(unknown)
    assert st["queue"] == [] and st["current"] is None
    assert h.svc.remove_at(unknown, 1, 0) is False
    assert h.svc.move(unknown, 1, 0, 1) is False
    assert await h.svc.play_at(unknown, 1, 0) is False
    hist = h.svc.get_history(unknown)
    assert hist["ok"] is True and hist["items"] == []
    await h.svc.skip(unknown)
    await h.svc.stop(unknown)
    assert unknown not in h.svc.pm_map and unknown not in h.svc.hm_map
    assert unknown not in h.svc._generation
    pdir = h.tmp_path / "playlists"
    assert not pdir.exists() or not any(p.name.endswith(f"{unknown}.json") for p in pdir.iterdir())


# ─────────────────────────── Connexion vocale ───────────────────────────


async def test_ensure_connected_waits_for_discord_reconnect(harness):
    h = harness
    ch = h.guild.channel(BOT_CHANNEL)
    vc = FakeVC(ch, h.guild, connected=False)
    h.guild.voice_client = vc

    async def reconnect_later():
        await asyncio.sleep(0.1)
        vc.connected = True

    reconnect = asyncio.create_task(reconnect_later())
    assert await h.svc.ensure_connected(h.guild, ch) is True
    await reconnect
    assert ch.connect_calls == []


async def test_ensure_connected_replaces_stale_voice_client(harness):
    h = harness
    ch = h.guild.channel(BOT_CHANNEL)
    stale = FakeVC(ch, h.guild, connected=False)
    h.guild.voice_client = stale
    assert await h.svc.ensure_connected(h.guild, ch) is True
    assert stale.disconnect_calls == 1
    assert len(ch.connect_calls) == 1
    assert h.guild.voice_client is not stale and h.guild.voice_client.is_connected()


async def test_busy_elsewhere_policy(harness):
    h = harness
    other = h.guild.channel(222)
    mine = h.guild.channel(BOT_CHANNEL)
    assert h.svc.busy_elsewhere(h.guild, other) is None  # pas connecté
    vc = h.connect_bot(BOT_CHANNEL)
    assert h.svc.busy_elsewhere(h.guild, other) is None  # connecté mais ne joue pas
    vc._playing = True
    assert h.svc.busy_elsewhere(h.guild, other) is None  # joue mais personne n'écoute
    h.guild.add_member(900, bot=True, channel_id=BOT_CHANNEL)
    assert h.svc.busy_elsewhere(h.guild, other) is None  # que des bots
    h.guild.add_member(901, channel_id=BOT_CHANNEL)
    assert h.svc.busy_elsewhere(h.guild, other) is mine
    assert h.svc.busy_elsewhere(h.guild, mine) is None  # même salon
    vc._paused = True
    assert h.svc.busy_elsewhere(h.guild, other) is mine  # en pause = occupé aussi


# ─────────────────────────── Cookies (C6) ───────────────────────────


async def test_cookies_file_is_resolved_on_each_use(harness, monkeypatch):
    h = harness
    paths = iter(["/tmp/a.txt", "/tmp/b.txt"])
    monkeypatch.setattr(type(h.ps.settings), "get_cookies_file", lambda self: next(paths))
    assert h.svc._cookies_file == "/tmp/a.txt"
    assert h.svc._cookies_file == "/tmp/b.txt"


async def test_duration_parser_keeps_hours(harness):
    h = harness
    assert h.svc._normalize_item({"url": "u", "duration": "1:02:03"})["duration"] == 3723


async def test_queue_users_cover_the_whole_queue(harness):
    """Une playlist (25 titres) + d'autres ajouts : les lignes au-delà de 25 gardent « par <nom> »."""
    h = harness
    h.guild.add_member(1)
    h.guild.add_member(2)
    h.seed_queue([dict(yt_entry(i), added_by="1") for i in range(25)]
                 + [dict(yt_entry(100 + i), added_by="2") for i in range(5)])
    users = h.svc.get_state(h.gid)["queue_users"]
    assert set(users) == {"1", "2"}
    assert users["2"]["display_name"] == "user2"


async def test_get_state_of_known_guild_does_not_write_files(harness):
    h = harness
    h.svc.get_state(h.gid)
    pdir = h.tmp_path / "playlists"
    assert not pdir.exists() or not any(os.scandir(pdir))


# ─────────────────────────── Contrôles pendant l'attente d'un retry ───────────────────────────


async def test_restart_during_retry_backoff_does_not_duplicate(harness, monkeypatch):
    # Piste morte au démarrage → remise en tête + retry en attente (current_song = A).
    # Un restart pendant l'attente ne doit pas la remettre une 2e fois en tête.
    h = harness
    monkeypatch.setattr(h.ps, "_RECONNECT_WAIT", 1.0)
    monkeypatch.setattr(h.ps, "_BACKOFF_MAX", 1.0)
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"die_after": 0.05}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: h.svc._retry_tasks.get(h.gid) is not None, timeout=2)
    assert h.urls()[0] == A["url"]
    h.ext.behaviour[A["url"]] = {"die_after": 30}  # coupure transitoire : le flux remarche
    assert await h.svc.restart(h.gid) is True
    await h.wait_for(lambda: _plays(vc, A["url"]) >= 2, timeout=2)
    await h.settle(1.3)
    assert _count(h, A["url"]) == 0, f"A dupliquée dans la file : {h.urls()}"
    assert _plays(vc, A["url"]) == 2, "A rejouée une fois de trop"


async def test_stop_racing_a_track_end_requeue_is_not_undone(harness, monkeypatch):
    # stop() vide la file pendant que _handle_track_end remet la piste coupée en tête :
    # la remise en tête et le retry ne doivent pas ressusciter la lecture après /stop.
    h = harness
    monkeypatch.setattr(h.ps, "_MIN_PLAYBACK_BEFORE_RECONNECT", 0.05)
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"die_after": 0.25}  # coupée en route (durée 180 s)
    h.seed_queue([A, B])
    pm = h.svc._get_pm(h.gid)
    real_stop = pm.stop

    def slow_stop():
        time.sleep(0.3)
        return real_stop()

    monkeypatch.setattr(pm, "stop", slow_stop)
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: _plays(vc, A["url"]) == 1)
    h.ext.behaviour[A["url"]] = {"die_after": 30}
    await asyncio.sleep(0.1)
    await h.svc.stop(h.gid)
    await h.settle(0.6)
    assert _plays(vc, A["url"]) == 1, "A rejouée après /stop"
    assert h.urls() == [], h.urls()


async def test_repeat_all_skip_during_backoff_keeps_track_in_the_loop(harness, monkeypatch):
    # En repeat_all, un skip normal laisse la piste dans la boucle : un skip pendant
    # l'attente d'un retry ne doit pas la retirer définitivement.
    h = harness
    monkeypatch.setattr(h.ps, "_RECONNECT_WAIT", 1.0)
    monkeypatch.setattr(h.ps, "_BACKOFF_MAX", 1.0)
    vc = h.connect_bot()
    await h.svc.toggle_repeat(h.gid, "on")
    h.ext.behaviour[A["url"]] = {"fail": True}  # échec transitoire (1/3)
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await h.wait_for(lambda: h.svc._retry_tasks.get(h.gid) is not None, timeout=2)
    await h.svc.skip(h.gid)
    await h.wait_for(lambda: _plays(vc, B["url"]) >= 1, timeout=2)
    await h.settle(0.1)
    assert _count(h, A["url"]) == 1, f"A retirée de la boucle repeat_all : {h.urls()}"
    # B joue (copie repeat en fin de file) ; A revient au tour suivant, comme après un skip normal.
    assert h.urls() == [A["url"], B["url"]], h.urls()

