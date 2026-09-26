# SoundCloud : sets détectés/expansés (permaliens canoniques), HTTP hors boucle,
# URL de set refusée par stream(), extraits Go+ refusés.

from __future__ import annotations

import asyncio
import threading

import discord
import greg_shared.extractors as ext
import pytest
from greg_shared.extractors import TrackUnavailable, soundcloud

SET_URL = "https://soundcloud.com/the-concept-band/sets/the-royal-concept-ep"


def _track(i, **extra):
    t = {
        "kind": "track",
        "id": 1000 + i,
        "title": f"Morceau {i}",
        "permalink_url": f"https://soundcloud.com/the-concept-band/morceau-{i}",
        "duration": 180000 + i * 1000,
        "artwork_url": f"https://i1.sndcdn.com/artworks-{i}-large.jpg",
        "user": {"username": "The Royal Concept"},
        "policy": "ALLOW",
        "streamable": True,
        "media": {"transcodings": [
            {"url": f"https://api-v2.soundcloud.com/media/{i}/progressive",
             "format": {"protocol": "progressive"}, "snipped": False},
        ]},
    }
    t.update(extra)
    return t


class _Resp:
    def __init__(self, status=200, data=None, url=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._data = data
        self.url = url

    def json(self):
        return self._data


class _Session:
    def __init__(self, routes, redirects=None):
        self.routes = routes
        self.redirects = dict(redirects or {})
        self.calls = []
        self.heads = []

    def head(self, url, allow_redirects=False, timeout=None):
        # on.soundcloud.com → 302 vers le permalien (suivi par requests)
        self.heads.append(url)
        assert allow_redirects, "la redirection du lien court doit être suivie"
        final = self.redirects.get(url, url)
        return _Resp(200 if final != url else 404, None, url=final)

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        for prefix, fn in self.routes:
            if url.startswith(prefix):
                return fn(url, params or {})
        raise AssertionError(f"URL inattendue: {url}")


@pytest.fixture
def sc_api(monkeypatch):
    state = {"session": None}

    def install(routes, cids=("cid-ok",), redirects=None):
        sess = _Session(routes, redirects)
        state["session"] = sess
        monkeypatch.setattr(soundcloud, "_requests_session", lambda: sess)
        monkeypatch.setattr(soundcloud, "_sc_client_ids", lambda: list(cids))
        return sess

    return install


@pytest.mark.parametrize("url,expected", [
    (SET_URL, True),
    ("soundcloud.com/the-concept-band/sets/the-royal-concept-ep", True),
    ("https://m.soundcloud.com/artist/sets/album-x", True),
    ("https://soundcloud.com/discover/sets/charts-top:all-music:fr", True),
    ("https://soundcloud.com/artist/track?in=artist/sets/foo", False),
    ("https://soundcloud.com/artist/track", False),
    ("https://soundcloud.com/artist", False),
    ("https://www.youtube.com/playlist?list=PLx", False),
])
def test_is_playlist_url(url, expected):
    assert soundcloud.is_playlist_url(url) is expected


def test_expand_bundle_returns_canonical_permalinks(sc_api):
    full = [_track(1), _track(2), _track(3)]
    stubs = [{"id": 1004, "kind": "track"}, {"id": 1005, "kind": "track"}, {"id": 1006, "kind": "track"}]
    playlist = {"kind": "playlist", "id": 42, "title": "EP", "tracks": full + stubs}

    def resolve(url, params):
        assert params["url"].startswith("https://soundcloud.com/")
        return _Resp(200, playlist)

    def tracks(url, params):
        ids = [int(x) for x in params["ids"].split(",")]
        return _Resp(200, [_track(i - 1000) for i in ids])

    sc_api([("https://api-v2.soundcloud.com/resolve", resolve),
            ("https://api-v2.soundcloud.com/tracks", tracks)])

    out = ext.expand_bundle(SET_URL, limit=5)
    assert [e["url"] for e in out] == [f"https://soundcloud.com/the-concept-band/morceau-{i}" for i in range(1, 6)]
    for e in out:
        assert e["provider"] == "soundcloud"
        assert e["webpage_url"] == e["url"]
        assert isinstance(e["duration"], int)
        assert set(e) >= {"title", "url", "webpage_url", "artist", "thumb", "duration", "provider"}
    assert out[0]["title"] == "Morceau 1"
    assert out[0]["artist"] == "The Royal Concept"


def test_expand_bundle_skips_blocked_and_preview_only_tracks(sc_api):
    playlist = {"kind": "playlist", "id": 42, "tracks": [
        _track(1, policy="BLOCK"),
        _track(2, policy="SNIP"),
        _track(3),
        _track(4, streamable=False),
        _track(5),
    ]}
    sc_api([("https://api-v2.soundcloud.com/resolve", lambda u, p: _Resp(200, playlist))])
    out = ext.expand_bundle(SET_URL, limit=10)
    assert [e["title"] for e in out] == ["Morceau 3", "Morceau 5"]


def test_expand_bundle_not_found_raises(sc_api):
    sc_api([("https://api-v2.soundcloud.com/resolve", lambda u, p: _Resp(404, {}))])
    with pytest.raises(ext.BundleError) as ei:
        ext.expand_bundle(SET_URL)
    assert ei.value.code == "PLAYLIST_UNAVAILABLE"


def test_expand_bundle_empty_raises(sc_api):
    sc_api([("https://api-v2.soundcloud.com/resolve",
             lambda u, p: _Resp(200, {"kind": "playlist", "id": 1, "tracks": []}))])
    with pytest.raises(ext.BundleError) as ei:
        ext.expand_bundle(SET_URL)
    assert ei.value.code == "PLAYLIST_EMPTY"


def test_expand_bundle_tries_next_client_id_on_401(sc_api):
    playlist = {"kind": "playlist", "id": 42, "tracks": [_track(1)]}

    def resolve(url, params):
        return _Resp(401, {}) if params["client_id"] == "bad" else _Resp(200, playlist)

    sc_api([("https://api-v2.soundcloud.com/resolve", resolve)], cids=("bad", "good"))
    out = ext.expand_bundle(SET_URL)
    assert len(out) == 1


def test_stream_rejects_set_urls_without_http(monkeypatch):
    monkeypatch.setattr(soundcloud, "_requests_session",
                        lambda: pytest.fail("aucun appel HTTP attendu"))
    with pytest.raises(TrackUnavailable) as ei:
        asyncio.run(soundcloud.stream(SET_URL, None))
    assert ei.value.permanent is True


def test_stream_runs_blocking_http_off_the_event_loop(monkeypatch, sc_api):
    threads = []
    sess = sc_api([
        ("https://api-v2.soundcloud.com/resolve", lambda u, p: _Resp(200, _track(1))),
        ("https://api-v2.soundcloud.com/media/", lambda u, p: _Resp(200, {"url": "https://cf-media.sndcdn.com/x.mp3"})),
    ])
    orig_get = sess.get

    def spy_get(url, params=None, timeout=None):
        threads.append(threading.current_thread() is threading.main_thread())
        return orig_get(url, params=params, timeout=timeout)

    sess.get = spy_get

    class _FakeAudio:
        def __init__(self, source, **kw):
            self.source = source

    monkeypatch.setattr(discord, "FFmpegPCMAudio", _FakeAudio)
    src, title = asyncio.run(soundcloud.stream("https://soundcloud.com/the-concept-band/morceau-1", None))
    assert title == "Morceau 1"
    assert src.source == "https://cf-media.sndcdn.com/x.mp3"
    assert threads and not any(threads), "les requêtes HTTP ne doivent pas tourner sur la boucle asyncio"


def test_pick_transcodings_ignores_previews():
    tr = {"media": {"transcodings": [
        {"url": "https://api/preview/1", "format": {"protocol": "progressive"}, "snipped": True},
        {"url": "https://api/x/hls", "format": {"protocol": "hls"}, "snipped": False},
    ]}}
    prog, hls = soundcloud._pick_transcodings(tr)
    assert prog is None
    assert hls["url"] == "https://api/x/hls"


def test_go_plus_preview_only_is_track_unavailable(monkeypatch, sc_api):
    snip = _track(1, policy="SNIP", media={"transcodings": [
        {"url": "https://api-v2.soundcloud.com/media/1/preview/progressive",
         "format": {"protocol": "progressive"}, "snipped": True}]})
    sc_api([("https://api-v2.soundcloud.com/resolve", lambda u, p: _Resp(200, snip))])
    with pytest.raises(TrackUnavailable):
        asyncio.run(soundcloud.stream("https://soundcloud.com/the-concept-band/morceau-1", None))


def test_drm_only_track_is_track_unavailable(monkeypatch):
    from yt_dlp.utils import DownloadError

    seen_opts = []

    class _DrmYDL:
        def __init__(self, opts=None):
            seen_opts.append(dict(opts or {}))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            raise DownloadError("ERROR: [soundcloud] 75206121: This video is DRM protected")

    monkeypatch.setattr(soundcloud, "_sc_client_ids", list)
    monkeypatch.setattr(soundcloud, "YoutubeDL", _DrmYDL)
    with pytest.raises(TrackUnavailable):
        asyncio.run(soundcloud.stream("https://soundcloud.com/the-concept-band/world-on-fire-1", None))
    # repli yt-dlp : jamais la résolution complète d'un set (lien court…)
    assert seen_opts[0]["noplaylist"] is True
    assert seen_opts[0]["playlist_items"] == "1"


# ── Liens courts on.soundcloud.com (partage depuis l'appli mobile) ──

SHORT = "https://on.soundcloud.com/AbCdEf123"
SHORT_REDIRECT = SET_URL + "?si=0123456789abcdef&utm_source=clipboard&utm_medium=text"


@pytest.mark.parametrize("url,expected", [
    (SHORT, True),
    ("on.soundcloud.com/AbCdEf123", True),
    (SET_URL, False),
    ("https://soundcloud.com/artist/track", False),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
])
def test_is_short_link(url, expected):
    assert soundcloud.is_short_link(url) is expected


def test_resolve_short_link_follows_redirect_to_canonical_permalink(sc_api):
    sc_api([], redirects={SHORT: SHORT_REDIRECT})
    assert soundcloud.resolve_short_link(SHORT) == SET_URL
    # Pas un lien court : inchangé, sans réseau
    assert soundcloud.resolve_short_link(SET_URL) == SET_URL


def test_resolve_short_link_failure_keeps_original(sc_api):
    sc_api([], redirects={})  # 404, pas de redirection
    assert soundcloud.resolve_short_link(SHORT) == SHORT


def test_short_link_to_a_set_is_expanded(sc_api):
    playlist = {"kind": "playlist", "id": 42, "tracks": [_track(1), _track(2)]}

    def resolve(url, params):
        assert params["url"] == SET_URL
        return _Resp(200, playlist)

    sc_api([("https://api-v2.soundcloud.com/resolve", resolve)], redirects={SHORT: SHORT_REDIRECT})
    out = ext.expand_bundle(SHORT, limit=5)
    assert [e["title"] for e in out] == ["Morceau 1", "Morceau 2"]


def test_short_link_to_a_track_expands_to_that_track(sc_api):
    track_url = "https://soundcloud.com/the-concept-band/morceau-1"
    sc_api([("https://api-v2.soundcloud.com/resolve", lambda u, p: _Resp(200, _track(1)))],
           redirects={SHORT: track_url + "?si=abc"})
    out = ext.expand_bundle(SHORT, limit=5)
    assert [e["url"] for e in out] == [track_url]


def test_is_bundle_url_stays_offline_for_short_links(monkeypatch):
    # Contrat C1 : is_bundle_url = /sets/ pour SoundCloud, sans aucun appel réseau
    monkeypatch.setattr(soundcloud, "_requests_session", lambda: pytest.fail("aucun appel HTTP attendu"))
    assert ext.is_bundle_url(SHORT) is False


def test_stream_short_link_to_a_set_is_track_unavailable(sc_api, monkeypatch):
    sc_api([("https://api-v2.soundcloud.com/resolve",
             lambda u, p: pytest.fail("un set ne doit jamais être résolu comme un titre"))],
           redirects={SHORT: SHORT_REDIRECT})
    monkeypatch.setattr(soundcloud, "YoutubeDL", lambda *a, **k: pytest.fail("pas de repli yt-dlp"))
    with pytest.raises(TrackUnavailable) as ei:
        asyncio.run(soundcloud.stream(SHORT, None))
    assert ei.value.permanent is True
    assert "sets" in str(ei.value)


def test_stream_short_link_to_a_track_plays_it(sc_api, monkeypatch):
    track_url = "https://soundcloud.com/the-concept-band/morceau-1"
    resolved = []

    def resolve(url, params):
        resolved.append(params["url"])
        return _Resp(200, _track(1))

    sc_api([
        ("https://api-v2.soundcloud.com/resolve", resolve),
        ("https://api-v2.soundcloud.com/media/", lambda u, p: _Resp(200, {"url": "https://cf-media.sndcdn.com/x.mp3"})),
    ], redirects={SHORT: track_url + "?si=abc"})

    class _FakeAudio:
        def __init__(self, source, **kw):
            self.source = source

    monkeypatch.setattr(discord, "FFmpegPCMAudio", _FakeAudio)
    _src, title = asyncio.run(soundcloud.stream(SHORT, None))
    assert title == "Morceau 1"
    assert resolved == [track_url]


def test_ytdlp_fallback_resolving_a_set_is_track_unavailable(sc_api, monkeypatch):
    # Lien court non résolu + aucun client_id : le repli yt-dlp suit la redirection
    # jusqu'au set → refus explicite plutôt que son 1er morceau en silence
    sc_api([], cids=(), redirects={})

    class _SetYDL:
        def __init__(self, opts=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "playlist", "extractor_key": "SoundcloudSet", "webpage_url": SET_URL,
                    "entries": [{"url": "https://cf-media.sndcdn.com/x.mp3", "title": "Morceau 1"}]}

    monkeypatch.setattr(soundcloud, "YoutubeDL", _SetYDL)
    with pytest.raises(TrackUnavailable):
        asyncio.run(soundcloud.stream(SHORT, None))


def test_ytdlp_fallback_search_still_plays_first_result(sc_api, monkeypatch):
    sc_api([], cids=())

    class _SearchYDL:
        def __init__(self, opts=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "playlist", "webpage_url": "scsearch3:gimme twice",
                    "entries": [{"url": "https://cf-media.sndcdn.com/x.mp3", "title": "Gimme Twice"}]}

    class _FakeAudio:
        def __init__(self, source, **kw):
            self.source = source

    monkeypatch.setattr(soundcloud, "YoutubeDL", _SearchYDL)
    monkeypatch.setattr(discord, "FFmpegPCMAudio", _FakeAudio)
    _src, title = asyncio.run(soundcloud.stream("gimme twice", None))
    assert title == "Gimme Twice"


def test_stream_resolve_kind_playlist_is_track_unavailable(sc_api, monkeypatch):
    # Filet de sécurité : un set résolu comme « titre » ne joue plus son 1er morceau en silence
    sc_api([("https://api-v2.soundcloud.com/resolve",
             lambda u, p: _Resp(200, {"kind": "playlist", "id": 42, "tracks": [_track(1)]}))])
    monkeypatch.setattr(soundcloud, "YoutubeDL", lambda *a, **k: pytest.fail("pas de repli yt-dlp"))
    with pytest.raises(TrackUnavailable):
        asyncio.run(soundcloud.stream("https://soundcloud.com/the-concept-band/morceau-x", None))
