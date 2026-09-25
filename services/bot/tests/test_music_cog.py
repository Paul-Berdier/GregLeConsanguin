"""Cog Music — /play (défer + play_for_user, jamais de recherche bloquante) et /playlist (≤ 2000 car.)."""
from __future__ import annotations

import types

import pytest

import greg_shared.extractors.youtube as yt
from bot.cogs import music as music_mod

pytestmark = pytest.mark.asyncio


class FakeResponse:
    def __init__(self):
        self.deferred = False
        self.sent = []

    async def defer(self, **kw):
        self.deferred = True

    def is_done(self):
        return self.deferred or bool(self.sent)

    async def send_message(self, content=None, **kw):
        self.sent.append(content)


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kw):
        self.sent.append(content)


def make_inter(gid=1):
    return types.SimpleNamespace(
        guild_id=gid,
        user=types.SimpleNamespace(id=7, mention="<@7>"),
        response=FakeResponse(),
        followup=FakeFollowup(),
    )


class FakeSvc:
    def __init__(self, result=None, state=None):
        self.result = result or {"ok": True, "added": 1, "requested": 1, "truncated": None,
                                 "playlist": False, "title": "Titre"}
        self.calls = []
        self.state = state or {"queue": [], "current": None}
        self.now_playing = {}

    async def play_for_user(self, gid, uid, item):
        self.calls.append((gid, uid, item))
        return self.result

    def get_state(self, gid):
        return self.state


def make_cog(svc):
    bot = types.SimpleNamespace(player_service=svc)
    return music_mod.Music(bot, service=svc)


@pytest.fixture(autouse=True)
def _no_search(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("recherche YouTube synchrone appelée sur la boucle")

    monkeypatch.setattr(yt, "search", boom)


async def _play(cog, inter, q):
    await music_mod.Music.play.callback(cog, inter, q)


async def test_play_defers_and_delegates_free_text_to_play_for_user():
    svc = FakeSvc()
    cog = make_cog(svc)
    inter = make_inter()
    await _play(cog, inter, "daft punk around the world")
    assert inter.response.deferred is True
    assert len(svc.calls) == 1
    gid, uid, item = svc.calls[0]
    assert (gid, uid) == (1, 7)
    assert item["url"] == "daft punk around the world"
    assert len(inter.followup.sent) == 1


async def test_play_normalizes_schemeless_links():
    svc = FakeSvc()
    cog = make_cog(svc)
    await _play(cog, make_inter(), "  www.youtube.com/playlist?list=PLabc ")
    assert svc.calls[0][2]["url"] == "https://www.youtube.com/playlist?list=PLabc"


async def test_play_reports_playlist_counts_and_truncation():
    svc = FakeSvc({"ok": True, "added": 12, "requested": 26, "truncated": "limit",
                   "playlist": True, "title": "Titre 0"})
    inter = make_inter()
    await _play(make_cog(svc), inter, "https://www.youtube.com/playlist?list=PLabc")
    msg = inter.followup.sent[0]
    assert "12" in msg


async def test_play_error_uses_result_message():
    svc = FakeSvc({"ok": False, "error": "PLAYLIST_UNAVAILABLE", "message": "Playlist privée ou supprimée."})
    inter = make_inter()
    await _play(make_cog(svc), inter, "https://www.youtube.com/playlist?list=PLabc")
    assert "Playlist privée ou supprimée." in inter.followup.sent[0]


async def test_play_quota_error_has_real_counts():
    svc = FakeSvc({"ok": False, "error": "QUOTA_EXCEEDED", "message": "Quota atteint (10/10).",
                   "count": 10, "cap": 10})
    inter = make_inter()
    await _play(make_cog(svc), inter, "https://youtu.be/dQw4w9WgXcQ")
    msg = inter.followup.sent[0]
    assert "?" not in msg and "10" in msg


async def test_play_spotify_error_uses_message():
    svc = FakeSvc({"ok": False, "error": "SPOTIFY_UNSUPPORTED", "message": "Les liens Spotify ne sont pas supportés."})
    inter = make_inter()
    await _play(make_cog(svc), inter, "https://open.spotify.com/track/abc")
    assert "Spotify" in inter.followup.sent[0]


async def test_playlist_message_stays_under_discord_limit():
    long_title = "Un titre vraiment très très long " * 4
    q = [{"title": f"{long_title} #{i}",
          "url": f"https://www.youtube.com/watch?v=vid{i:08d}&list=PL{'x' * 32}"} for i in range(40)]
    svc = FakeSvc(state={"queue": q, "current": {"title": long_title, "url": q[0]["url"]}})
    inter = make_inter()
    await music_mod.Music.playlist.callback(make_cog(svc), inter)
    msg = inter.followup.sent[0]
    assert len(msg) <= 2000
    assert "de plus" in msg


async def test_play_search_timeout_is_not_reported_as_song_not_found():
    """Recherche lente/échouée (transient) : on affiche le message du service
    (« réessaie »), pas « ça existe pas ton truc » qui décourage de réessayer."""
    from greg_shared.constants import GREG_RESPONSES

    msg_txt = "La recherche YouTube met trop de temps, réessaie dans un instant."
    svc = FakeSvc({"ok": False, "error": "NO_RESULTS", "message": msg_txt, "transient": True})
    inter = make_inter()
    await _play(make_cog(svc), inter, "daft punk around the world")
    sent = inter.followup.sent[0]
    assert msg_txt in sent
    not_found = [t.format(user="<@7>") for t in GREG_RESPONSES["play_not_found"]]
    assert sent not in not_found


async def test_play_real_no_results_keeps_greg_tone():
    from greg_shared.constants import GREG_RESPONSES

    svc = FakeSvc({"ok": False, "error": "NO_RESULTS", "message": "Aucun résultat pour « zzz »."})
    inter = make_inter()
    await _play(make_cog(svc), inter, "zzz")
    assert inter.followup.sent[0] in [t.format(user="<@7>") for t in GREG_RESPONSES["play_not_found"]]


async def test_play_warns_when_the_playlist_was_ignored():
    note = "Playlist privée ou inaccessible : seule la vidéo demandée a été ajoutée."
    svc = FakeSvc({"ok": True, "added": 1, "requested": 1, "truncated": None, "playlist": False,
                   "title": "Rick", "playlist_error": "PLAYLIST_UNAVAILABLE", "message": note})
    inter = make_inter()
    await _play(make_cog(svc), inter, "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLprivate")
    assert note in inter.followup.sent[0]
