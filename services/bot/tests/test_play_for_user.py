"""PlayerService.play_for_user — contrat C2 (réponse rapide, playlists, quota, recherche texte…)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from core_fakes import (  # noqa: F401  (fixture importée)
    BOT_CHANNEL,
    FakeSource,
    harness,
    loop_max_gap,
    make_bundle_error,
    yt_entry,
)

pytestmark = pytest.mark.asyncio

USER = 501
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLabcdefghijklmnop"


def _entries(n, start=0):
    return [yt_entry(i) for i in range(start, start + n)]


def _in_voice(h, uid=USER, channel_id=BOT_CHANNEL, **kw):
    return h.guild.add_member(uid, channel_id=channel_id, **kw)


async def test_event_loop_never_blocked_while_expanding_bundle(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()

    def slow_expand(url, limit):
        time.sleep(1.5)  # expand_bundle est synchrone (yt-dlp) : doit tourner dans un thread
        return _entries(3)

    h.ext.expand_impl = slow_expand
    res, gap = await loop_max_gap(h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL}))

    assert gap < 0.5, f"boucle asyncio bloquée {gap:.2f}s pendant l'expansion"
    assert res["ok"] is True, res
    assert res["added"] == 3 and res["playlist"] is True
    assert h.ext.expand_threads and h.ext.expand_threads[0] != threading.main_thread().name


async def test_success_shape_and_first_playback_started_in_background(harness):
    h = harness
    _in_voice(h)
    vc = h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(4)
    # L'extraction du 1er morceau est lente : play_for_user ne doit PAS l'attendre.
    for i in range(4):
        h.ext.behaviour[yt_entry(i)["url"]] = {"delay": 1.0}

    t0 = time.perf_counter()
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    elapsed = time.perf_counter() - t0

    assert res == {
        "ok": True, "added": 4, "requested": 4, "truncated": None,
        "playlist": True, "title": "Titre 0",
    }
    assert elapsed < 0.5, f"play_for_user a attendu la lecture ({elapsed:.2f}s)"
    await h.wait_for(lambda: len(vc.play_calls) == 1, timeout=3)
    assert vc.play_calls[0].url == yt_entry(0)["url"]


async def test_bundle_error_is_reported_and_raw_playlist_url_never_enqueued(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()

    def boom(url, limit):
        raise make_bundle_error(h.ps, "PLAYLIST_UNAVAILABLE", "Playlist privée ou supprimée.")

    h.ext.expand_impl = boom
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL, "title": PLAYLIST_URL})

    assert res == {"ok": False, "error": "PLAYLIST_UNAVAILABLE", "message": "Playlist privée ou supprimée."}
    assert h.queue() == []


async def test_unexpected_expand_exception_maps_to_playlist_unavailable(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()

    def boom(url, limit):
        raise RuntimeError("ERROR: [youtube:tab] Sign in to confirm you're not a bot")

    h.ext.expand_impl = boom
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["ok"] is False and res["error"] == "PLAYLIST_UNAVAILABLE"
    assert res["message"]
    assert h.queue() == []


async def test_playlist_empty_error_passthrough(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()

    def empty(url, limit):
        raise make_bundle_error(h.ps, "PLAYLIST_EMPTY", "Playlist vide.")

    h.ext.expand_impl = empty
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["error"] == "PLAYLIST_EMPTY" and res["message"] == "Playlist vide."
    assert h.queue() == []


async def test_expand_timeout_returns_expand_timeout_and_enqueues_nothing(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.ps, "_EXPAND_TIMEOUT", 0.3)
    _in_voice(h)
    h.connect_bot()

    def hang(url, limit):
        time.sleep(1.0)
        return _entries(3)

    h.ext.expand_impl = hang
    t0 = time.perf_counter()
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert time.perf_counter() - t0 < 0.9
    assert res["ok"] is False and res["error"] == "EXPAND_TIMEOUT" and res["message"]
    assert h.queue() == []


async def test_entries_that_are_bundle_urls_are_never_enqueued(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    bad = yt_entry(1, url="https://www.youtube.com/watch?v=vid00000001&list=PLxyz")
    h.ext.expand_impl = lambda url, limit: [yt_entry(0), bad, yt_entry(2)]

    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["ok"] is True
    assert res["added"] == 2
    urls = h.urls()
    assert all("list=" not in u for u in urls), urls


async def test_watch_list_link_falls_back_to_single_video_when_playlist_unavailable(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()

    def boom(url, limit):
        raise make_bundle_error(h.ps, "PLAYLIST_UNAVAILABLE", "Playlist privée.")

    h.ext.expand_impl = boom
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLprivate123&index=3"
    res = await h.svc.play_for_user(h.gid, USER, {"url": url})
    assert res["ok"] is True and res["added"] == 1 and res["playlist"] is False
    assert h.urls() in ([], ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])  # [] si déjà dépilé
    assert all("list=" not in u for u in h.urls())
    # L'utilisateur qui a collé une playlist doit savoir qu'elle a été ignorée.
    assert res["playlist_error"] == "PLAYLIST_UNAVAILABLE"
    assert "playlist" in res["message"].lower()


async def test_regular_success_has_no_playlist_error(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(2)
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["ok"] is True and "playlist_error" not in res and "message" not in res


async def test_quota_remaining_is_computed_before_expansion(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    # 7 morceaux déjà en file pour USER → reste 3 (cap par défaut 10)
    h.seed_queue([dict(yt_entry(100 + i), added_by=str(USER)) for i in range(7)])
    h.ext.expand_impl = lambda url, limit: _entries(min(limit, 30))

    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})

    assert h.ext.expand_calls[0]["limit"] <= 4  # min(25, 3) (+1 pour détecter la troncature)
    assert res["ok"] is True
    assert res["added"] == 3
    assert res["truncated"] == "quota"
    mine = [it for it in h.queue() if str(it.get("added_by")) == str(USER)]
    assert len(mine) <= 10


async def test_quota_exhausted_fails_fast_without_expanding(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.seed_queue([dict(yt_entry(100 + i), added_by=str(USER)) for i in range(10)])
    h.ext.expand_impl = lambda url, limit: _entries(5)

    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["ok"] is False and res["error"] == "QUOTA_EXCEEDED" and res["message"]
    assert h.ext.expand_calls == []


async def test_playlist_expand_limit_env_truncates(harness, monkeypatch):
    h = harness
    monkeypatch.setenv("PLAYLIST_EXPAND_LIMIT", "5")
    _in_voice(h, admin=True)  # admin : pas de quota
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(min(limit, 40))

    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["ok"] is True and res["added"] == 5 and res["truncated"] == "limit"


async def test_requested_is_the_real_playlist_size_when_known(harness):
    """29 titres, quota 10 : requested = 29 (taille réelle fournie par l'extracteur),
    pas 11 (taille de la sonde limit + 1)."""
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: [dict(e, playlist_count=29) for e in _entries(min(limit, 29))]
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["ok"] is True and res["added"] == 10 and res["truncated"] == "quota"
    assert res["requested"] == 29


async def test_requested_is_a_lower_bound_when_size_unknown(harness):
    """Sans taille connue : requested ne dépasse jamais ce qui a été vu (sonde incluse)
    et reste ≥ added — c'est une borne basse quand truncated est posé."""
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(min(limit, 29))
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL})
    assert res["truncated"] == "quota" and res["added"] == 10
    assert res["added"] < res["requested"] <= 29


async def test_budget_eaten_by_the_command_queue_fails_fast(harness):
    """La commande a attendu derrière une autre (même guild) : s'il ne reste presque
    plus de budget avant que l'API abandonne, on répond tout de suite sans rien faire."""
    h = harness
    _in_voice(h)
    h.ext.expand_impl = lambda url, limit: _entries(3)
    t0 = time.perf_counter()
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL}, budget=0.5)
    assert time.perf_counter() - t0 < 0.3
    assert res["ok"] is False and res["error"] == "EXPAND_TIMEOUT" and res["message"]
    assert h.ext.expand_calls == [] and h.guild.voice_client is None and h.queue() == []


async def test_budget_caps_the_expansion_timeout(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.ps, "_MIN_PLAY_BUDGET", 0.2)
    _in_voice(h)
    h.connect_bot()

    def hang(url, limit):
        time.sleep(2.0)
        return _entries(3)

    h.ext.expand_impl = hang
    t0 = time.perf_counter()
    res = await h.svc.play_for_user(h.gid, USER, {"url": PLAYLIST_URL}, budget=0.5)
    assert time.perf_counter() - t0 < 1.5
    assert res["ok"] is False and res["error"] == "EXPAND_TIMEOUT"
    assert h.queue() == []


async def test_free_text_is_resolved_by_search_in_a_thread(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    q = "daft punk around the world"
    h.ext.search_results[q] = [{
        "title": "Daft Punk - Around The World", "url": "https://www.youtube.com/watch?v=K0HSD_i2DvA",
        "webpage_url": "https://www.youtube.com/watch?v=K0HSD_i2DvA", "duration": 240,
        "thumb": "http://img", "thumbnail": "http://img", "provider": "youtube", "uploader": "Daft Punk",
    }]

    res = await h.svc.play_for_user(h.gid, USER, {"url": q, "title": q})

    assert res["ok"] is True and res["added"] == 1 and res["playlist"] is False
    assert res["title"] == "Daft Punk - Around The World"
    assert h.ext.search_calls == [{"query": q, "limit": 1}]
    assert h.ext.search_threads[0] != threading.main_thread().name
    await asyncio.sleep(0.05)
    played_or_queued = [u for _, u in h.ext.calls] + h.urls()
    assert "https://www.youtube.com/watch?v=K0HSD_i2DvA" in played_or_queued
    assert q not in played_or_queued


async def test_free_text_without_results_returns_no_results(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    res = await h.svc.play_for_user(h.gid, USER, {"url": "zzzz introuvable"})
    assert res["ok"] is False and res["error"] == "NO_RESULTS" and res["message"]
    assert not res.get("transient")  # vraie absence de résultat
    assert h.queue() == []


async def test_search_timeout_or_failure_is_flagged_transient(harness, monkeypatch):
    h = harness
    _in_voice(h)
    h.connect_bot()
    monkeypatch.setattr(h.ps, "_SEARCH_TIMEOUT", 0.2)

    def slow_search(query, **kw):
        time.sleep(0.6)
        return []

    monkeypatch.setattr(h.ps, "yt_search", slow_search)
    res = await h.svc.play_for_user(h.gid, USER, {"url": "daft punk"})
    assert res["ok"] is False and res["error"] == "NO_RESULTS"
    assert res["transient"] is True and "trop de temps" in res["message"]

    def broken_search(query, **kw):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(h.ps, "yt_search", broken_search)
    res = await h.svc.play_for_user(h.gid, USER, {"url": "daft punk"})
    assert res["ok"] is False and res["error"] == "NO_RESULTS" and res["transient"] is True
    assert h.queue() == []


async def test_link_the_extractor_refuses_as_a_track_is_refused_at_add_time(harness, monkeypatch):
    """Ce que stream() refuserait d'emblée (TrackUnavailable sans extraction) est refusé
    à l'ajout — pas « Ajouté ✅ » puis jeté en silence à la lecture."""
    h = harness
    _in_voice(h)
    refused = "https://www.youtube.com/feed/trending"
    reason = "Lien YouTube sans vidéo : colle le lien d'une vidéo ou d'une playlist."

    def fake_target(url):
        if url == refused:
            raise h.ps.TrackUnavailable(reason)
        return url

    monkeypatch.setattr(h.ps, "yt_stream_target", fake_target)
    res = await h.svc.play_for_user(h.gid, USER, {"url": "www.youtube.com/feed/trending", "title": refused})
    assert res == {"ok": False, "error": "UNSUPPORTED_SOURCE", "message": reason}
    assert h.queue() == [] and h.ext.expand_calls == []
    assert h.guild.voice_client is None  # refusé avant toute connexion vocale
    res = await h.svc.enqueue(h.gid, USER, {"url": refused})
    assert res["ok"] is False and res["error"] == "UNSUPPORTED_SOURCE" and h.queue() == []


async def test_youtube_clip_link_is_not_refused(harness):
    """Règle RÉELLE de l'extracteur : un clip (sans id vidéo dans l'URL) reste un titre valide."""
    h = harness
    _in_voice(h)
    h.connect_bot()
    url = "https://www.youtube.com/clip/UgkxU2HSeGL_NvmDJ-nQJrlLwllwMDBdGZFs"
    h.ext.behaviour[url] = {"delay": 0.5}
    res = await h.svc.play_for_user(h.gid, USER, {"url": url})
    assert res["ok"] is True and res["added"] == 1


async def test_spotify_links_are_rejected_explicitly(harness):
    h = harness
    _in_voice(h)
    res = await h.svc.play_for_user(h.gid, USER, {"url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"})
    assert res["ok"] is False and res["error"] == "SPOTIFY_UNSUPPORTED" and res["message"]
    assert h.queue() == []
    assert h.guild.voice_client is None  # rien n'a été fait (pas de connexion vocale)


async def test_schemeless_playlist_link_is_normalized_and_expanded(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(2)
    res = await h.svc.play_for_user(h.gid, USER, {"url": "  www.youtube.com/playlist?list=PLabc  "})
    assert res["ok"] is True and res["playlist"] is True
    assert h.ext.expand_calls[0]["url"] == "https://www.youtube.com/playlist?list=PLabc"


SC_SHORT = "https://on.soundcloud.com/AbCdEf123"


async def test_soundcloud_short_link_to_a_set_is_expanded(harness):
    # on.soundcloud.com : titre OU set, inconnu hors ligne → c'est expand_bundle qui tranche.
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(3)
    res = await h.svc.play_for_user(h.gid, USER, {"url": SC_SHORT})
    assert res["ok"] is True and res["added"] == 3 and res["playlist"] is True
    assert h.ext.expand_calls and h.ext.expand_calls[0]["url"] == SC_SHORT
    assert SC_SHORT not in [it.get("url") for it in h.queue()], "lien court brut mis en file"


async def test_soundcloud_short_link_to_a_track_is_not_a_playlist(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.ext.expand_impl = lambda url, limit: _entries(1)
    res = await h.svc.play_for_user(h.gid, USER, {"url": SC_SHORT})
    assert res["ok"] is True and res["added"] == 1
    assert res["playlist"] is False, "un lien court vers UN titre annoncé comme playlist"
    assert [it.get("url") for it in h.queue()] == [yt_entry(0)["url"]]


async def test_guild_none_or_unknown(harness):
    h = harness
    assert (await h.svc.play_for_user(None, USER, {"url": "x"}))["error"] == "GUILD_NOT_FOUND"
    assert (await h.svc.play_for_user(123, USER, {"url": "x"}))["error"] == "GUILD_NOT_FOUND"


async def test_user_not_in_voice(harness):
    h = harness
    h.guild.add_member(USER)  # pas en vocal
    res = await h.svc.play_for_user(h.gid, USER, {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert res["ok"] is False and res["error"] == "USER_NOT_IN_VOICE" and res["message"]


async def test_refuses_to_pull_greg_out_of_a_busy_channel(harness):
    h = harness
    vc = h.connect_bot(BOT_CHANNEL)
    h.guild.add_member(700, channel_id=BOT_CHANNEL)  # un auditeur humain avec Greg
    vc._playing = True  # Greg joue
    _in_voice(h, channel_id=222)  # le demandeur est dans un AUTRE salon

    res = await h.svc.play_for_user(h.gid, USER, {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert res["ok"] is False and res["error"] == "BOT_IN_OTHER_CHANNEL"
    assert f"<#{BOT_CHANNEL}>" in res["message"]
    assert vc.moves == []
    assert h.queue() == []


async def test_busy_policy_rechecked_after_a_voice_reconnect(harness):
    """C7 : pendant une reconnexion Discord (is_connected False), busy_elsewhere ne voit
    rien ; ensure_connected ne doit pas pour autant déplacer Greg une fois reconnecté."""
    h = harness
    vc = h.connect_bot(BOT_CHANNEL)
    h.guild.add_member(700, channel_id=BOT_CHANNEL)  # auditeur dans le salon de Greg
    _in_voice(h, channel_id=222)                     # demandeur dans un autre salon
    vc.play(FakeSource("https://www.youtube.com/watch?v=vid00000001", 30.0), after=None)
    vc.connected = False  # micro-coupure : discord.py se reconnecte

    async def reconnect_soon():
        await asyncio.sleep(0.1)
        vc.connected = True

    reconnect = asyncio.create_task(reconnect_soon())
    res = await h.svc.play_for_user(h.gid, USER, {"url": yt_entry(9)["url"]})
    await reconnect
    assert res["ok"] is False and res["error"] == "BOT_IN_OTHER_CHANNEL", res
    assert f"<#{BOT_CHANNEL}>" in res["message"]
    assert vc.moves == [] and h.queue() == []


async def test_reconnect_that_fails_lets_the_requester_get_greg(harness):
    """Reconnexion ratée : Greg ne joue plus nulle part → le demandeur peut l'avoir."""
    h = harness
    vc = h.connect_bot(BOT_CHANNEL)
    h.guild.add_member(700, channel_id=BOT_CHANNEL)
    _in_voice(h, channel_id=222)
    vc.play(FakeSource("https://www.youtube.com/watch?v=vid00000001", 30.0), after=None)
    vc.connected = False  # ne se reconnectera jamais (client fantôme)
    res = await h.svc.play_for_user(h.gid, USER, {"url": yt_entry(9)["url"]})
    assert res["ok"] is True, res
    assert h.guild.voice_client is not vc and h.guild.voice_client.channel.id == 222


async def test_single_url_keeps_metadata_and_connects(harness):
    h = harness
    _in_voice(h)
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    h.ext.behaviour[url] = {"delay": 0.5}
    res = await h.svc.play_for_user(h.gid, USER, {"url": url, "title": "Rick", "duration": 212})
    assert res == {"ok": True, "added": 1, "requested": 1, "truncated": None, "playlist": False, "title": "Rick"}
    assert h.guild.voice_client is not None
    assert h.guild.channel(BOT_CHANNEL).connect_calls  # connexion faite
