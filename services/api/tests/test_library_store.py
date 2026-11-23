"""library_store — chansonnier du Roi dans Redis (spec 2026-11-23 §3) : identité des titres, nettoyage,
relecture tolérante, lecture-écriture atomique (WATCH / MULTI / EXEC), Redis coupé.

FakeRedis implémente EXACTEMENT les commandes utilisées par le module (GET, SET, WATCH, UNWATCH, MULTI /
EXEC via pipeline) ; il est aussi importé par test_library_routes.py.
"""
from __future__ import annotations

import json
import types

import api.services.library_store as store
import pytest
import redis
from api.services.library_store import LibraryError

UID = 777
KEY = f"greg:library:{UID}"
VID = "dQw4w9WgXcQ"


# ─────────────────────────── Faux Redis ───────────────────────────

class FakeRedis:
    """Redis en mémoire, limité aux commandes du chansonnier.

    - `fail` : exception levée par toute commande (Redis coupé).
    - `interleave` : écritures « d'un autre onglet » jouées juste avant les prochains EXEC (une par EXEC),
      pour provoquer un WatchError comme le ferait Redis.
    - `log` : commandes reçues, dans l'ordre.
    """

    def __init__(self):
        self.kv: dict[str, str] = {}
        self.version: dict[str, int] = {}
        self.fail: BaseException | None = None
        self.interleave: list = []
        self.log: list[tuple] = []

    def _cmd(self, *args):
        self.log.append(args)
        if self.fail is not None:
            raise self.fail

    def write(self, key: str, value: str):
        """Écriture hors transaction (un autre client) : change la version vue par WATCH."""
        assert isinstance(value, str), "decode_responses=True : Redis stocke du texte"
        self.kv[key] = value
        self.version[key] = self.version.get(key, 0) + 1

    def get(self, key):
        self._cmd("GET", key)
        return self.kv.get(key)

    def set(self, key, value):
        self._cmd("SET", key)
        self.write(key, value)

    def pipeline(self, transaction=True):
        assert transaction, "le chansonnier écrit toujours en transaction"
        return FakePipeline(self)

    def close(self):
        pass

    def commands(self) -> list[str]:
        return [c[0] for c in self.log]


class FakePipeline:
    def __init__(self, r: FakeRedis):
        self.r = r
        self.watched: dict[str, int] | None = None
        self.queued: list | None = None  # None : mode immédiat ; liste après MULTI

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.reset()
        return False

    def watch(self, *keys):
        self.r._cmd("WATCH", *keys)
        self.watched = {k: self.r.version.get(k, 0) for k in keys}

    def unwatch(self):
        self.r._cmd("UNWATCH")
        self.watched = None

    def get(self, key):
        assert self.queued is None, "GET après MULTI : la valeur ne serait connue qu'à EXEC"
        return self.r.get(key)

    def multi(self):
        assert self.queued is None and self.watched is not None, "MULTI sans WATCH"
        self.r._cmd("MULTI")
        self.queued = []

    def set(self, key, value):
        assert self.queued is not None, "SET hors MULTI : écriture non atomique"
        self.queued.append((key, value))
        return self

    def execute(self):
        try:
            self.r._cmd("EXEC")
            if self.r.interleave:
                self.r.interleave.pop(0)()
            if any(self.r.version.get(k, 0) != v for k, v in (self.watched or {}).items()):
                raise redis.WatchError("Watched variable changed.")
            for k, v in self.queued or []:
                self.r.write(k, v)
            return [True] * len(self.queued or [])
        finally:
            self.reset()

    def reset(self):
        self.watched = None
        self.queued = None


@pytest.fixture()
def fake_store(monkeypatch):
    """FakeRedis branché à la place du client du chansonnier."""
    fr = FakeRedis()
    monkeypatch.setattr(store, "_get_redis", lambda: fr)
    return fr


def yt(i: int = 0, **kw) -> dict:
    """Track tel que le site l'envoie (vidéo YouTube n° i)."""
    t = {"url": f"https://www.youtube.com/watch?v=vid{i:08d}", "title": f"Titre {i}", "artist": "Artiste",
         "duration": 180, "thumb": f"https://i.ytimg.com/vi/vid{i:08d}/hqdefault.jpg", "provider": "youtube"}
    t.update(kw)
    return t


def stored(uid: int = UID, fr: FakeRedis | None = None) -> dict:
    return json.loads(fr.kv[f"greg:library:{uid}"])


def doc(likes=(), playlists=()) -> str:
    """Valeur Redis valide (v1) à partir de tracks déjà nettoyés."""
    return json.dumps({"v": 1, "likes": list(likes), "playlists": list(playlists)})


# ─────────────────────────── track_key ───────────────────────────

@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&list=PLabc&index=3",
    f"https://www.youtube.com/watch?feature=share&v={VID}",
    f"http://m.youtube.com/watch?v={VID}",
    f"https://music.youtube.com/watch?v={VID}&si=xyz",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=AbCdEf&t=42",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}?start=10",
    f"https://www.youtube-nocookie.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}",
    f"https://www.youtube.com/v/{VID}",
    f"https://WWW.YOUTUBE.COM/watch?v={VID}",
    f"  https://www.youtube.com/watch?v={VID}  ",
    f"www.youtube.com/watch?v={VID}",
])
def test_track_key_youtube_forms_share_the_video_id(url):
    assert store.track_key(url) == f"yt:{VID}"


@pytest.mark.parametrize("url,key", [
    ("https://soundcloud.com/artiste/titre", "url:https://soundcloud.com/artiste/titre"),
    ("https://soundcloud.com/artiste/titre/", "url:https://soundcloud.com/artiste/titre"),
    ("  https://soundcloud.com/artiste/titre//  ", "url:https://soundcloud.com/artiste/titre"),
    ("https://example.com/a b", "url:https://example.com/ab"),
    # Pas une vidéo : la liste, le lecteur de playlist, un autre site qui imite ?v=
    ("https://www.youtube.com/playlist?list=PLabc", "url:https://www.youtube.com/playlist?list=PLabc"),
    ("https://www.youtube.com/embed/videoseries?list=PLabc",
     "url:https://www.youtube.com/embed/videoseries?list=PLabc"),
    (f"https://example.com/watch?v={VID}", f"url:https://example.com/watch?v={VID}"),
    (f"https://notyoutube.com/watch?v={VID}", f"url:https://notyoutube.com/watch?v={VID}"),
    ("https://www.youtube.com/watch?v=short", "url:https://www.youtube.com/watch?v=short"),
])
def test_track_key_other_links_compare_by_url(url, key):
    assert store.track_key(url) == key


# ─────────────────────────── clean_track ───────────────────────────

def test_clean_track_keeps_the_stored_shape():
    t = store.clean_track(yt(1), 1700000000)
    assert t == {
        "url": "https://www.youtube.com/watch?v=vid00000001", "title": "Titre 1", "artist": "Artiste",
        "duration": 180, "thumb": "https://i.ytimg.com/vi/vid00000001/hqdefault.jpg", "provider": "youtube",
        "added_at": 1700000000,
    }


def test_clean_track_defaults_and_cleaning():
    t = store.clean_track({"url": "  https://soundcloud.com/a/b  ", "title": "  ",
                           "artist": " Le\n\tBarde\x00 ", "thumbnail": "https://img/x.jpg",
                           "duration": 212.9, "added_at": 5, "extra": "ignoré"})
    assert t["url"] == "https://soundcloud.com/a/b"
    assert t["title"] == "https://soundcloud.com/a/b"  # titre vide → l'url
    assert t["artist"] == "Le Barde"                    # blancs réduits, contrôles retirés
    assert t["thumb"] == "https://img/x.jpg"             # alias thumbnail
    assert t["duration"] == 212
    assert t["provider"] == "soundcloud"                 # déduit de l'hôte
    assert t["added_at"] == 0                            # posé par le serveur, jamais lu du corps
    assert set(t) == {"url", "title", "artist", "duration", "thumb", "provider", "added_at"}


def test_clean_track_cuts_long_texts():
    long_url = "https://example.com/" + "a" * 400
    t = store.clean_track({"url": long_url, "title": "T" * 250, "artist": "A" * 150})
    assert t["title"] == "T" * 200 and t["artist"] == "A" * 120
    assert store.clean_track({"url": long_url})["title"] == long_url[:200]


@pytest.mark.parametrize("duration,expected", [(None, None), (0, 0), (86400, 86400), (86401, None),
                                               (-5, None), (59.99, 59)])
def test_clean_track_duration_range(duration, expected):
    assert store.clean_track(yt(duration=duration))["duration"] == expected


@pytest.mark.parametrize("thumb", ["javascript:alert(1)", "/relatif.jpg", "data:image/png;base64,AAAA",
                                   "https://img/" + "x" * 500, "https://img/a b.jpg", ""])
def test_clean_track_drops_a_thumb_that_is_not_a_short_http_link(thumb):
    assert store.clean_track(yt(thumb=thumb))["thumb"] is None


@pytest.mark.parametrize("provider,url,expected", [
    ("youtube", "https://www.youtube.com/watch?v=x", "youtube"),
    ("SoundCloud", "https://soundcloud.com/a/b", "soundcloud"),
    (None, "https://youtu.be/dQw4w9WgXcQ", "youtube"),
    ("spotify", "https://on.soundcloud.com/abc", "soundcloud"),
    (None, "https://example.com/son.mp3", None),
])
def test_clean_track_provider(provider, url, expected):
    assert store.clean_track({"url": url, "provider": provider})["provider"] == expected


@pytest.mark.parametrize("raw", [
    None, "https://youtu.be/x", ["https://youtu.be/x"],
    {}, {"url": None}, {"url": 42}, {"url": ""}, {"url": "   "},
    {"url": "javascript:alert(1)"}, {"url": "ftp://example.com/a"}, {"url": "//example.com/a"},
    {"url": "www.youtube.com/watch?v=dQw4w9WgXcQ"},  # sans schéma : le site envoie des liens complets
    {"url": "https://"}, {"url": "https://example.com/a b"}, {"url": "https://example.com/\x00"},
    {"url": "https://example.com/" + "a" * 481},
    {"url": "https://x.y/a", "title": 12}, {"url": "https://x.y/a", "artist": ["a"]},
    {"url": "https://x.y/a", "thumb": {"u": 1}}, {"url": "https://x.y/a", "provider": 1},
    {"url": "https://x.y/a", "duration": "3:20"}, {"url": "https://x.y/a", "duration": True},
    {"url": "https://x.y/a", "duration": float("nan")}, {"url": "https://x.y/a", "duration": float("inf")},
])
def test_clean_track_refuses_invalid_input(raw):
    with pytest.raises(LibraryError) as ei:
        store.clean_track(raw)
    assert ei.value.code == "INVALID_TRACK" and ei.value.status == 400 and ei.value.message


def test_clean_track_url_length_limit_is_500():
    ok = "https://example.com/" + "a" * 480
    assert len(ok) == 500 and store.clean_track({"url": ok})["url"] == ok


def test_clean_tracks_reports_the_bad_index_and_bounds_the_list():
    with pytest.raises(LibraryError) as ei:
        store.clean_tracks([yt(0), {"url": "nope"}, yt(2)])
    assert ei.value.code == "INVALID_TRACK" and ei.value.extra == {"index": 1}
    with pytest.raises(LibraryError) as ei:
        store.clean_tracks({"url": "https://x.y"})
    assert ei.value.code == "INVALID_REQUEST"
    with pytest.raises(LibraryError) as ei:
        store.clean_tracks([yt(i) for i in range(4)], max_items=3)
    assert ei.value.code == "INVALID_REQUEST" and "3" in ei.value.message


# ─────────────────────────── noms, ids, positions ───────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Soirée", "Soirée"),
    ("  Les   grands\n\tairs  ", "Les grands airs"),
    ("Bal\x00 du\x07 Roi\x7f", "Bal du Roi"),
    ("x" * 60, "x" * 60),
    ("👑 Couronnement", "👑 Couronnement"),
])
def test_clean_name(raw, expected):
    assert store.clean_name(raw) == expected


@pytest.mark.parametrize("raw", [None, 12, ["a"], "", "   ", "\x00\x01", "x" * 61, "  " + "y" * 61 + "  "])
def test_clean_name_refuses(raw):
    with pytest.raises(LibraryError) as ei:
        store.clean_name(raw)
    assert ei.value.code == "INVALID_NAME" and ei.value.status == 400


@pytest.mark.parametrize("raw", [None, 3, "", "a/b", "a:b", "../etc", "x" * 65, "é"])
def test_clean_playlist_id_refuses(raw):
    with pytest.raises(LibraryError) as ei:
        store.clean_playlist_id(raw)
    assert ei.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize("raw", [None, -1, True, False, "1", 1.0, [1]])
def test_clean_index_refuses(raw):
    with pytest.raises(LibraryError) as ei:
        store.clean_index(raw)
    assert ei.value.code == "INVALID_REQUEST"


def test_clean_label():
    assert store.clean_label(None) is None
    assert store.clean_label("   ") is None
    assert store.clean_label("  Coups\nde cœur ") == "Coups de cœur"
    assert store.clean_label("L" * 300) == "L" * 200
    with pytest.raises(LibraryError):
        store.clean_label(3)


# ─────────────────────────── relecture ───────────────────────────

def test_parse_missing_value_is_an_empty_library():
    assert store.parse_library(None) == ({"likes": [], "playlists": []}, False)


@pytest.mark.parametrize("raw", ["pas du json", "[1, 2]", '"texte"', json.dumps({"v": 2, "likes": []}),
                                 json.dumps({"likes": []}), json.dumps({"v": "1"})])
def test_parse_unreadable_or_foreign_value_is_empty_and_lossy(raw):
    assert store.parse_library(raw) == ({"likes": [], "playlists": []}, True)


def test_parse_keeps_valid_entries_and_flags_the_rest():
    good = store.clean_track(yt(1), 10)
    raw = json.dumps({"v": 1, "likes": [good, {"url": "javascript:x"}, good],
                      "playlists": [{"id": "abc", "name": "Bal", "tracks": [good, 3],
                                     "created_at": 1, "updated_at": 2},
                                    {"id": "abc", "name": "doublon", "tracks": []},
                                    {"id": "../x", "name": "id invalide", "tracks": []}]})
    state, lossy = store.parse_library(raw)
    assert lossy is True
    assert state["likes"] == [good]
    assert state["playlists"] == [{"id": "abc", "name": "Bal", "tracks": [good], "created_at": 1, "updated_at": 2}]


def test_parse_clean_value_round_trips():
    good = store.clean_track(yt(1), 10)
    pl = {"id": "AbC_-123xyz", "name": "Bal", "tracks": [good], "created_at": 1, "updated_at": 2}
    state, lossy = store.parse_library(doc([good], [pl]))
    assert lossy is False and state == {"likes": [good], "playlists": [pl]}


# ─────────────────────────── lecture / écriture ───────────────────────────

def test_read_library_shape(fake_store):
    assert store.read_library(UID) == {"likes": [], "playlists": [],
                                       "limits": {"likes": 500, "playlists": 50, "tracks": 200, "name": 60}}
    assert fake_store.commands() == ["GET"]
    assert fake_store.log[0] == ("GET", KEY)


def test_mutate_writes_versioned_json_under_the_user_key(fake_store):
    library, extra = store.mutate(UID, store.op_add_like(store.clean_track(yt(1), 42)))
    assert extra == {}
    assert library["likes"][0]["url"] == yt(1)["url"]
    saved = stored(fr=fake_store)
    assert saved["v"] == 1 and saved["playlists"] == [] and saved["likes"][0]["added_at"] == 42
    assert fake_store.commands() == ["WATCH", "GET", "MULTI", "EXEC"]


def test_mutate_without_change_writes_nothing(fake_store):
    fake_store.write(KEY, doc())
    store.mutate(UID, store.op_remove_like(yt(1)["url"]))
    assert fake_store.commands() == ["WATCH", "GET", "UNWATCH"]


def test_mutate_retries_after_a_concurrent_write_and_keeps_both_changes(fake_store):
    other = store.clean_track(yt(9), 1)
    # Un autre onglet ajoute un coup de cœur entre notre lecture et notre EXEC.
    fake_store.interleave.append(lambda: fake_store.write(KEY, doc([other])))
    library, _ = store.mutate(UID, store.op_add_like(store.clean_track(yt(1), 2)))
    assert [t["url"] for t in library["likes"]] == [yt(1)["url"], yt(9)["url"]]
    assert [t["url"] for t in stored(fr=fake_store)["likes"]] == [yt(1)["url"], yt(9)["url"]]
    assert fake_store.commands().count("EXEC") == 2


def test_mutate_gives_up_after_five_conflicts(fake_store):
    for i in range(store.MAX_TRIES):
        fake_store.interleave.append(lambda i=i: fake_store.write(KEY, doc([store.clean_track(yt(100 + i))])))
    with pytest.raises(LibraryError) as ei:
        store.mutate(UID, store.op_add_like(store.clean_track(yt(1))))
    assert ei.value.code == "STORAGE_UNAVAILABLE" and ei.value.status == 503
    assert ei.value.message == store.MSG_STORAGE_BUSY
    assert fake_store.commands().count("EXEC") == store.MAX_TRIES == 5
    assert yt(1)["url"] not in fake_store.kv[KEY]


def test_operation_error_writes_nothing(fake_store):
    with pytest.raises(LibraryError) as ei:
        store.mutate(UID, store.op_delete_playlist("inconnu"))
    assert ei.value.code == "PLAYLIST_NOT_FOUND" and ei.value.status == 404
    assert "EXEC" not in fake_store.commands() and KEY not in fake_store.kv


@pytest.mark.parametrize("exc", [redis.ConnectionError("Connection refused"), redis.TimeoutError("lent"),
                                 redis.ResponseError("OOM"), OSError("réseau")])
def test_redis_failure_is_storage_unavailable(fake_store, exc):
    fake_store.fail = exc
    for call in (lambda: store.read_library(UID),
                 lambda: store.mutate(UID, store.op_add_like(store.clean_track(yt(1))))):
        with pytest.raises(LibraryError) as ei:
            call()
        assert ei.value.code == "STORAGE_UNAVAILABLE" and ei.value.status == 503
        assert ei.value.message == store.MSG_STORAGE_UNAVAILABLE
        assert str(exc) not in ei.value.message


def test_unbuildable_client_is_storage_unavailable(monkeypatch):
    def boom():
        raise ValueError("Redis URL must specify one of the following schemes")

    monkeypatch.setattr(store, "_get_redis", boom)
    with pytest.raises(LibraryError) as ei:
        store.read_library(UID)
    assert ei.value.code == "STORAGE_UNAVAILABLE"


def test_corrupt_value_is_read_as_empty_and_backed_up_before_the_first_write(fake_store, monkeypatch):
    monkeypatch.setattr(store, "time", types.SimpleNamespace(time=lambda: 1234.5))
    fake_store.write(KEY, "{ceci n'est pas du json")
    assert store.read_library(UID)["likes"] == []
    assert fake_store.kv[KEY] == "{ceci n'est pas du json"  # une lecture n'écrit jamais

    store.mutate(UID, store.op_add_like(store.clean_track(yt(1))))
    assert fake_store.kv[f"{KEY}:corrupt:1234"] == "{ceci n'est pas du json"
    assert [t["url"] for t in stored(fr=fake_store)["likes"]] == [yt(1)["url"]]


def test_partially_invalid_value_is_backed_up_too(fake_store, monkeypatch):
    monkeypatch.setattr(store, "time", types.SimpleNamespace(time=lambda: 99))
    good = store.clean_track(yt(1), 1)
    raw = json.dumps({"v": 1, "likes": [good, {"url": "javascript:x"}], "playlists": []})
    fake_store.write(KEY, raw)
    store.mutate(UID, store.op_add_like(store.clean_track(yt(2))))
    assert fake_store.kv[f"{KEY}:corrupt:99"] == raw
    assert [t["url"] for t in stored(fr=fake_store)["likes"]] == [yt(2)["url"], yt(1)["url"]]


def test_clean_value_is_never_backed_up(fake_store):
    fake_store.write(KEY, doc([store.clean_track(yt(1), 1)]))
    store.mutate(UID, store.op_add_like(store.clean_track(yt(2))))
    assert [k for k in fake_store.kv if ":corrupt:" in k] == []


# ─────────────────────────── opérations ───────────────────────────

def _state(likes=(), playlists=()):
    return {"likes": list(likes), "playlists": list(playlists)}


def _pl(pid="pl1", n=0, start=0):
    return {"id": pid, "name": "Bal", "tracks": [store.clean_track(yt(start + i), 1) for i in range(n)],
            "created_at": 1, "updated_at": 1}


def test_op_add_like_newest_first_and_idempotent_by_identity():
    st = _state()
    assert store.op_add_like(store.clean_track(yt(1)))(st) == (True, {})
    assert store.op_add_like(store.clean_track(yt(2)))(st) == (True, {})
    again = store.clean_track({"url": "https://youtu.be/vid00000001?si=x"})
    assert store.op_add_like(again)(st) == (False, {})
    assert [t["url"] for t in st["likes"]] == [yt(2)["url"], yt(1)["url"]]


def test_op_add_like_limit():
    st = _state([store.clean_track(yt(i)) for i in range(store.LIMIT_LIKES)])
    with pytest.raises(LibraryError) as ei:
        store.op_add_like(store.clean_track(yt(9999)))(st)
    assert ei.value.code == "LIMIT_REACHED" and ei.value.status == 409 and ei.value.extra == {"limit": "likes"}
    # Déjà aimé : idempotent même à la limite.
    assert store.op_add_like(store.clean_track(yt(0)))(st) == (False, {})


def test_op_create_playlist_dedupes_caps_and_avoids_id_collisions():
    st = _state(playlists=[_pl("taken")])
    ids = iter(["taken", "fresh"])
    tracks = [store.clean_track(yt(i)) for i in range(250)] + [store.clean_track(yt(0))]
    changed, extra = store.op_create_playlist("Bal", [tracks[0], tracks[0]] + tracks, 50, lambda: next(ids))(st)
    assert changed and extra == {"playlist_id": "fresh"}
    pl = st["playlists"][-1]
    assert pl["id"] == "fresh" and pl["name"] == "Bal" and pl["created_at"] == pl["updated_at"] == 50
    assert len(pl["tracks"]) == store.LIMIT_TRACKS
    assert len({store.track_key(t["url"]) for t in pl["tracks"]}) == store.LIMIT_TRACKS


def test_op_create_playlist_default_id_is_token_urlsafe_8():
    st = _state()
    _, extra = store.op_create_playlist("Bal", [], 1)(st)
    assert store._PLAYLIST_ID_RE.match(extra["playlist_id"]) and len(extra["playlist_id"]) == 11


def test_op_create_playlist_limit():
    st = _state(playlists=[_pl(f"p{i}") for i in range(store.LIMIT_PLAYLISTS)])
    with pytest.raises(LibraryError) as ei:
        store.op_create_playlist("Bal", [], 1)(st)
    assert ei.value.code == "LIMIT_REACHED" and ei.value.extra == {"limit": "playlists"}


def test_op_add_tracks_counts_duplicates_and_overflow_as_skipped():
    st = _state(playlists=[_pl("p", n=store.LIMIT_TRACKS - 3)])
    new = [store.clean_track(yt(0)), store.clean_track(yt(500)), store.clean_track(yt(500)),
           store.clean_track(yt(501)), store.clean_track(yt(502)), store.clean_track(yt(503))]
    changed, extra = store.op_add_tracks("p", new, 77)(st)
    assert changed and extra == {"added": 3, "skipped": 3}
    pl = st["playlists"][0]
    assert len(pl["tracks"]) == store.LIMIT_TRACKS and pl["updated_at"] == 77
    assert [t["url"] for t in pl["tracks"][-3:]] == [yt(500)["url"], yt(501)["url"], yt(502)["url"]]
    # Pleine : rien ajouté, tout compté, aucune écriture.
    assert store.op_add_tracks("p", [store.clean_track(yt(900))], 78)(st) == (False, {"added": 0, "skipped": 1})


def test_op_move_track():
    st = _state(playlists=[_pl("p", n=4)])
    assert store.op_move_track("p", 0, 3, 9)(st) == (True, {})
    assert [t["title"] for t in st["playlists"][0]["tracks"]] == ["Titre 1", "Titre 2", "Titre 3", "Titre 0"]
    assert store.op_move_track("p", 2, 2, 9)(st) == (False, {})
    for src, dst in ((4, 0), (0, 4)):
        with pytest.raises(LibraryError) as ei:
            store.op_move_track("p", src, dst, 9)(st)
        assert ei.value.code == "INVALID_REQUEST"


def test_op_remove_track_by_identity():
    st = _state(playlists=[_pl("p", n=3)])
    assert store.op_remove_track("p", "https://youtu.be/vid00000001", 5)(st) == (True, {})
    assert [t["title"] for t in st["playlists"][0]["tracks"]] == ["Titre 0", "Titre 2"]
    assert store.op_remove_track("p", "https://youtu.be/vid00000001", 6)(st) == (False, {})
    assert st["playlists"][0]["updated_at"] == 5
