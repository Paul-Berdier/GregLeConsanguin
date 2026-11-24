"""PlayerService.play_for_user avec item["items"] — lot de titres connus (chansonnier du Roi, /queue/add_many,
spec 2026-11-23 §3) : plafond min(limite d'expansion, quota restant), requested = len(items), playlist = True,
mêmes contrôles avant (salon vocal, Greg ailleurs, budget, quota, connexion) et même boucle d'ajout."""
from __future__ import annotations

import core_fakes
import pytest
from core_fakes import BOT_CHANNEL, yt_entry

# Fixture du harnais PlayerService (faux Discord / extracteurs), rendue visible dans ce module.
harness = core_fakes.harness

pytestmark = pytest.mark.asyncio

USER = 501


def _items(n, start=0):
    return [yt_entry(i) for i in range(start, start + n)]


def _in_voice(h, uid=USER, channel_id=BOT_CHANNEL, **kw):
    return h.guild.add_member(uid, channel_id=channel_id, **kw)


def _batch(items, label=None):
    return {"items": items, "title": label}


async def test_batch_is_enqueued_in_order_without_search_nor_expansion(harness):
    h = harness
    _in_voice(h)
    vc = h.connect_bot()
    items = _items(3)
    res = await h.svc.play_for_user(h.gid, USER, _batch(items, "Bal du Roi"))

    assert res == {"ok": True, "added": 3, "requested": 3, "truncated": None,
                   "playlist": True, "title": "Bal du Roi"}
    assert h.ext.expand_calls == [] and h.ext.search_calls == []
    await h.wait_for(lambda: len(vc.play_calls) == 1, timeout=3)
    played_or_queued = [vc.play_calls[0].url] + h.urls()
    assert played_or_queued == [e["url"] for e in items]


async def test_batch_keeps_track_metadata_and_requester(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.svc.ensure_playing = lambda guild: None  # rien ne part en lecture : la file reste lisible
    sc = {"url": "https://soundcloud.com/artiste/titre", "title": "Le Barde", "artist": "Troubadour",
          "duration": 61, "thumb": "https://img/sc.jpg", "provider": "soundcloud"}
    res = await h.svc.play_for_user(h.gid, USER, _batch([yt_entry(1, duration=212), sc]))
    assert res["ok"] is True and res["added"] == 2
    q = h.queue()
    assert [it["url"] for it in q] == [yt_entry(1)["url"], sc["url"]]
    assert q[0]["title"] == "Titre 1" and q[0]["duration"] == 212 and q[0]["provider"] == "youtube"
    assert (q[1]["title"], q[1]["artist"], q[1]["duration"], q[1]["thumb"], q[1]["provider"]) == (
        "Le Barde", "Troubadour", 61, "https://img/sc.jpg", "soundcloud")
    assert all(str(it["added_by"]) == str(USER) for it in q)


async def test_without_label_the_title_is_the_first_added_track(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(2)))
    assert res["title"] == "Titre 0" and res["playlist"] is True


async def test_entries_without_url_are_dropped_but_counted_as_requested(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.svc.ensure_playing = lambda guild: None
    items = [yt_entry(0), {"title": "sans lien"}, "pas un objet", yt_entry(2), {"url": "   "}]
    res = await h.svc.play_for_user(h.gid, USER, _batch(items))
    assert res["ok"] is True and res["added"] == 2 and res["requested"] == 5
    assert res["truncated"] is None
    assert h.urls() == [yt_entry(0)["url"], yt_entry(2)["url"]]


async def test_batch_is_capped_by_the_expand_limit(harness, monkeypatch):
    h = harness
    monkeypatch.setenv("PLAYLIST_EXPAND_LIMIT", "5")
    _in_voice(h, admin=True)  # admin : pas de quota
    h.connect_bot()
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(8)))
    assert res["ok"] is True and res["added"] == 5 and res["requested"] == 8 and res["truncated"] == "limit"


async def test_batch_is_capped_by_the_remaining_quota(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.svc.ensure_playing = lambda guild: None
    h.seed_queue([dict(yt_entry(100 + i), added_by=str(USER)) for i in range(7)])  # reste 3 (cap 10)
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(5)))
    assert res["ok"] is True and res["added"] == 3 and res["requested"] == 5 and res["truncated"] == "quota"
    mine = [it for it in h.queue() if str(it.get("added_by")) == str(USER)]
    assert len(mine) == 10


async def test_exhausted_quota_fails_fast_without_connecting(harness):
    h = harness
    _in_voice(h)
    h.seed_queue([dict(yt_entry(100 + i), added_by=str(USER)) for i in range(10)])
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(3)))
    assert res["ok"] is False and res["error"] == "QUOTA_EXCEEDED" and res["message"]
    assert h.guild.voice_client is None and len(h.queue()) == 10


async def test_refused_entries_are_skipped_and_the_rest_added(harness, monkeypatch):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.svc.ensure_playing = lambda guild: None
    refused = "https://www.youtube.com/feed/trending"

    def fake_target(url):
        if url == refused:
            raise h.ps.TrackUnavailable("Lien YouTube sans vidéo.")
        return url

    monkeypatch.setattr(h.ps, "yt_stream_target", fake_target)
    items = [yt_entry(0), {"url": "https://www.youtube.com/playlist?list=PLx"}, {"url": refused},
             {"url": "https://open.spotify.com/track/abc"}, {"url": "daft punk"}, yt_entry(1)]
    res = await h.svc.play_for_user(h.gid, USER, _batch(items))
    assert res["ok"] is True and res["added"] == 2 and res["requested"] == 6
    assert h.urls() == [yt_entry(0)["url"], yt_entry(1)["url"]]
    assert h.ext.search_calls == [] and h.ext.expand_calls == []


async def test_batch_of_only_spotify_or_text_is_refused_before_voice(harness):
    h = harness
    _in_voice(h)
    res = await h.svc.play_for_user(h.gid, USER, _batch([{"url": "https://open.spotify.com/track/abc"},
                                                         {"url": "daft punk"}]))
    assert res["ok"] is False and res["error"] == "SPOTIFY_UNSUPPORTED" and res["message"]
    assert h.guild.voice_client is None and h.queue() == []

    res = await h.svc.play_for_user(h.gid, USER, _batch([{"title": "sans lien"}]))
    assert res["ok"] is False and res["error"] == "PLAYLIST_EMPTY"
    assert h.guild.voice_client is None


async def test_batch_where_every_entry_is_refused_at_enqueue_returns_the_first_error(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    res = await h.svc.play_for_user(h.gid, USER, _batch([{"url": "https://www.youtube.com/playlist?list=PLx"}]))
    assert res["ok"] is False and res["error"] == "UNSUPPORTED_SOURCE"
    assert h.queue() == []


async def test_batch_of_only_playlist_or_unplayable_links_is_refused_before_voice(harness, monkeypatch):
    # Comme un lien seul : rien de jouable → refus AVANT de faire venir Greg dans le salon.
    h = harness
    _in_voice(h)
    unplayable = "https://www.youtube.com/feed/trending"

    def fake_target(url):
        if url == unplayable:
            raise h.ps.TrackUnavailable("Lien YouTube sans vidéo.")
        return url

    monkeypatch.setattr(h.ps, "yt_stream_target", fake_target)
    res = await h.svc.play_for_user(h.gid, USER, _batch([{"url": "https://www.youtube.com/playlist?list=PLx"},
                                                         {"url": unplayable}]))
    assert res["ok"] is False and res["error"] == "UNSUPPORTED_SOURCE"
    assert res["message"] == h.ps._RAW_BUNDLE_MESSAGE  # le 1er refus, dans l'ordre du lot
    assert h.guild.voice_client is None and h.queue() == []

    res = await h.svc.play_for_user(h.gid, USER, _batch([{"url": unplayable}]))
    assert res == {**res, "ok": False, "error": "UNSUPPORTED_SOURCE", "message": "Lien YouTube sans vidéo."}
    assert h.guild.voice_client is None


async def test_user_not_in_voice(harness):
    h = harness
    h.guild.add_member(USER)
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(2)))
    assert res["ok"] is False and res["error"] == "USER_NOT_IN_VOICE"
    assert h.queue() == []


async def test_refuses_to_pull_greg_out_of_a_busy_channel(harness):
    h = harness
    vc = h.connect_bot(BOT_CHANNEL)
    h.guild.add_member(700, channel_id=BOT_CHANNEL)
    vc._playing = True
    _in_voice(h, channel_id=222)
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(2)))
    assert res["ok"] is False and res["error"] == "BOT_IN_OTHER_CHANNEL"
    assert vc.moves == [] and h.queue() == []


async def test_budget_eaten_by_the_command_queue_fails_fast(harness):
    h = harness
    _in_voice(h)
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(2)), budget=0.5)
    assert res["ok"] is False and res["error"] == "EXPAND_TIMEOUT"
    assert h.guild.voice_client is None and h.queue() == []


async def test_connects_to_the_requester_channel(harness):
    h = harness
    _in_voice(h)
    res = await h.svc.play_for_user(h.gid, USER, _batch(_items(1)))
    assert res["ok"] is True
    assert h.guild.voice_client is not None and h.guild.channel(BOT_CHANNEL).connect_calls


async def test_items_win_over_url(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.svc.ensure_playing = lambda guild: None
    res = await h.svc.play_for_user(h.gid, USER, {"items": _items(1), "url": "https://www.youtube.com/playlist?list=PLx"})
    assert res["ok"] is True and res["playlist"] is True
    assert h.ext.expand_calls == [] and h.urls() == [yt_entry(0)["url"]]


@pytest.mark.parametrize("items", [[], None, "pas une liste", {"url": "x"}])
async def test_empty_or_non_list_items_keep_the_single_item_behaviour(harness, items):
    h = harness
    _in_voice(h)
    h.connect_bot()
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    h.ext.behaviour[url] = {"delay": 0.5}
    res = await h.svc.play_for_user(h.gid, USER, {"items": items, "url": url, "title": "Rick"})
    assert res == {"ok": True, "added": 1, "requested": 1, "truncated": None, "playlist": False, "title": "Rick"}

    res = await h.svc.play_for_user(h.gid, USER, {"items": items})
    assert res["ok"] is False and res["error"] == "NO_RESULTS"


async def test_malformed_entry_fields_do_not_crash(harness):
    h = harness
    _in_voice(h)
    h.connect_bot()
    h.svc.ensure_playing = lambda guild: None
    res = await h.svc.play_for_user(h.gid, USER, _batch([
        {"url": yt_entry(0)["url"], "title": 12, "artist": ["x"], "duration": "3:05"},
        {"url": yt_entry(1)["url"], "title": yt_entry(1)["url"]},  # titre = le lien : ignoré
    ], label=42))
    assert res["ok"] is True and res["added"] == 2
    q = h.queue()
    assert q[0]["title"] == yt_entry(0)["url"] and q[0]["artist"] is None and q[0]["duration"] == 185
    assert q[1]["title"] == yt_entry(1)["url"]
    assert res["title"] is None  # libellé illisible et aucun vrai titre : rien d'inventé
