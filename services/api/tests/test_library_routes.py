"""Routes /library/* — chansonnier du Roi (spec 2026-11-23 §3) : session obligatoire (SEC-C1), données de
chaque Roi isolées, plafonds, idempotence, doublons, bornes, conflits d'écriture, Redis coupé."""
from __future__ import annotations

import json

import api.services.library_store as store
import pytest
import redis
from test_library_store import FakeRedis, yt

BASE = "/api/v1"
UID = 777  # SESSION_USER_ID de conftest
KEY = f"greg:library:{UID}"

NOT_AUTHENTICATED_BODY = {
    "ok": False,
    "error": "NOT_AUTHENTICATED",
    "message": "Connecte-toi avec Discord pour contrôler Greg.",
}

# (méthode, chemin, corps valide) — toutes les routes du chansonnier.
LIBRARY_ROUTES = [
    ("get", "/library", None),
    ("post", "/library/likes/add", {"track": yt(1)}),
    ("post", "/library/likes/remove", {"url": yt(1)["url"]}),
    ("post", "/library/playlists/create", {"name": "Bal"}),
    ("post", "/library/playlists/rename", {"id": "abc", "name": "Bal"}),
    ("post", "/library/playlists/delete", {"id": "abc"}),
    ("post", "/library/playlists/add", {"id": "abc", "tracks": [yt(1)]}),
    ("post", "/library/playlists/remove", {"id": "abc", "url": yt(1)["url"]}),
    ("post", "/library/playlists/move", {"id": "abc", "src": 0, "dst": 1}),
    ("post", "/library/playlists/restore", {"playlist": {"id": "abc", "name": "Bal", "tracks": [yt(1)]}, "index": 0}),
]
_IDS = [f"{m} {p}" for m, p, _ in LIBRARY_ROUTES]
MUTATION_PATHS = [p for m, p, _ in LIBRARY_ROUTES if m == "post"]


@pytest.fixture()
def fr(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(store, "_get_redis", lambda: fake)
    return fake


def post(client, path, body, **kw):
    return client.post(f"{BASE}{path}", json=body, **kw)


def ok(r, status=200) -> dict:
    assert r.status_code == status, r.get_json()
    body = r.get_json()
    assert body["ok"] is True
    return body


def err(r, status, code) -> dict:
    assert r.status_code == status, r.get_json()
    body = r.get_json()
    assert body["ok"] is False and body["error"] == code
    assert isinstance(body["message"], str) and body["message"]
    return body


def create(client, name="Bal", tracks=None) -> str:
    body = {"name": name} if tracks is None else {"name": name, "tracks": tracks}
    return ok(post(client, "/library/playlists/create", body))["playlist_id"]


def seed(fake: FakeRedis, likes=(), playlists=(), uid=UID):
    fake.write(f"greg:library:{uid}", json.dumps({"v": 1, "likes": list(likes), "playlists": list(playlists)}))


# ── Session obligatoire (SEC-C1) ──

@pytest.mark.parametrize("method,path,body", LIBRARY_ROUTES, ids=_IDS)
def test_every_library_route_requires_a_session(client, fr, method, path, body):
    kw = {"headers": {"X-User-ID": "456"}}
    if body is not None:
        kw["json"] = {**body, "user_id": "456"}
    r = getattr(client, method)(f"{BASE}{path}", **kw)
    assert r.status_code == 401
    assert r.get_json() == NOT_AUTHENTICATED_BODY
    assert fr.log == []  # pas un seul accès à Redis


def test_body_and_header_user_id_are_ignored(logged_client, fr):
    victim = "111111111111111111"
    ok(post(logged_client, "/library/likes/add", {"track": yt(1), "user_id": victim},
            headers={"X-User-ID": victim}))
    assert list(fr.kv) == [KEY]
    r = logged_client.get(f"{BASE}/library?user_id={victim}", headers={"X-User-ID": victim})
    assert len(ok(r)["library"]["likes"]) == 1


def test_each_king_has_his_own_library(app, logged_client, login, fr):
    other = login(app.test_client(), 888)
    ok(post(logged_client, "/library/likes/add", {"track": yt(1)}))
    pid = create(logged_client, "À moi")

    lib = ok(other.get(f"{BASE}/library"))["library"]
    assert lib["likes"] == [] and lib["playlists"] == []
    # La playlist d'un autre Roi est introuvable, même avec son id.
    err(post(other, "/library/playlists/delete", {"id": pid}), 404, "PLAYLIST_NOT_FOUND")
    err(post(other, "/library/playlists/add", {"id": pid, "tracks": [yt(2)]}), 404, "PLAYLIST_NOT_FOUND")
    ok(post(other, "/library/likes/remove", {"url": yt(1)["url"]}))

    mine = ok(logged_client.get(f"{BASE}/library"))["library"]
    assert len(mine["likes"]) == 1 and [p["id"] for p in mine["playlists"]] == [pid]
    assert set(fr.kv) == {KEY}  # rien n'a été écrit pour 888


# ── GET /library ──

def test_get_empty_library(logged_client, fr):
    body = ok(logged_client.get(f"{BASE}/library"))
    assert body == {"ok": True, "library": {
        "likes": [], "playlists": [],
        "limits": {"likes": 500, "playlists": 50, "tracks": 200, "name": 60},
    }}


# ── Coups de cœur ──

def test_like_is_stored_with_the_seven_keys_and_returned_with_the_library(logged_client, fr):
    body = ok(post(logged_client, "/library/likes/add", {"track": yt(1, thumb=None, extra="x")}))
    assert set(body) == {"ok", "library"}
    like = body["library"]["likes"][0]
    assert set(like) == {"url", "title", "artist", "duration", "thumb", "provider", "added_at"}
    assert like["url"] == yt(1)["url"] and like["thumb"] is None and isinstance(like["added_at"], int)
    assert like["added_at"] > 1_600_000_000
    assert body["library"]["limits"]["likes"] == 500
    assert json.loads(fr.kv[KEY])["likes"] == [like]


def test_lone_surrogates_are_stored_cleaned_not_a_500(logged_client, fr):
    # Emoji coupé en deux par le site (« \ud83d » isolé) : json.loads l'accepte, Redis (UTF-8 strict) non.
    ok(post(logged_client, "/library/likes/add", {"track": yt(1, title="Rick \ud83d")}))
    assert json.loads(fr.kv[KEY])["likes"][0]["title"] == "Rick"
    pid = create(logged_client, "Bal \udc00du Roi")
    assert json.loads(fr.kv[KEY])["playlists"][0]["name"] == "Bal du Roi"
    ok(post(logged_client, "/library/playlists/rename", {"id": pid, "name": "\ud83d Fête"}))
    assert json.loads(fr.kv[KEY])["playlists"][0]["name"] == "Fête"


def test_likes_newest_first_and_idempotent_across_url_forms(logged_client, fr):
    ok(post(logged_client, "/library/likes/add", {"track": yt(1)}))
    ok(post(logged_client, "/library/likes/add", {"track": yt(2)}))
    writes = fr.commands().count("EXEC")
    body = ok(post(logged_client, "/library/likes/add",
                   {"track": {"url": "https://youtu.be/vid00000001?si=abc", "title": "autre titre"}}))
    assert [t["url"] for t in body["library"]["likes"]] == [yt(2)["url"], yt(1)["url"]]
    assert body["library"]["likes"][1]["title"] == "Titre 1"  # l'entrée existante ne bouge pas
    assert fr.commands().count("EXEC") == writes  # rien réécrit


def test_like_limit_is_409(logged_client, fr):
    seed(fr, likes=[store.clean_track(yt(i), 1) for i in range(500)])
    body = err(post(logged_client, "/library/likes/add", {"track": yt(9999)}), 409, "LIMIT_REACHED")
    assert body["limit"] == "likes"
    # Un titre déjà aimé reste accepté (idempotent) à la limite.
    ok(post(logged_client, "/library/likes/add", {"track": yt(3)}))


def test_library_over_the_byte_budget_is_409_size_and_can_still_shrink(logged_client, fr, monkeypatch):
    ok(post(logged_client, "/library/likes/add", {"track": yt(1)}))
    # Budget sous le chansonnier vide lui-même : tout ajout est refusé, retirer passe encore.
    monkeypatch.setattr(store, "MAX_LIBRARY_BYTES", 10)
    body = err(post(logged_client, "/library/likes/add", {"track": yt(2)}), 409, "LIMIT_REACHED")
    assert body["limit"] == "size" and body["message"] == store.MSG_LIMIT_SIZE
    err(post(logged_client, "/library/playlists/create", {"name": "Bal"}), 409, "LIMIT_REACHED")
    assert [t["url"] for t in json.loads(fr.kv[KEY])["likes"]] == [yt(1)["url"]]
    assert ok(post(logged_client, "/library/likes/remove", {"url": yt(1)["url"]}))["library"]["likes"] == []


def test_library_responses_are_utf8_not_escaped(logged_client, fr):
    # jsonify écrirait « 👑 » (12 octets) pour 👑 et « à » pour à : jusqu'à 3 fois le stocké.
    title = "Couronnement 👑 du Roi, à l’église"
    r = post(logged_client, "/library/likes/add", {"track": yt(1, title=title)})
    assert ok(r)["library"]["likes"][0]["title"] == title
    for resp in (r, logged_client.get(f"{BASE}/library")):
        assert resp.mimetype == "application/json"
        assert title.encode("utf-8") in resp.data and b"\\u" not in resp.data


def test_unlike_by_identity_and_idempotent(logged_client, fr):
    ok(post(logged_client, "/library/likes/add", {"track": yt(1)}))
    ok(post(logged_client, "/library/likes/add", {"track": yt(2)}))
    body = ok(post(logged_client, "/library/likes/remove", {"url": "https://www.youtube.com/shorts/vid00000001"}))
    assert [t["url"] for t in body["library"]["likes"]] == [yt(2)["url"]]
    body = ok(post(logged_client, "/library/likes/remove", {"url": yt(1)["url"]}))
    assert [t["url"] for t in body["library"]["likes"]] == [yt(2)["url"]]


@pytest.mark.parametrize("track", [None, "https://youtu.be/x", {"url": "javascript:alert(1)"},
                                   {"url": "https://x.y/" + "a" * 500}, {"url": "https://x.y", "title": 5}])
def test_invalid_like_is_400_before_any_redis_access(logged_client, fr, track):
    err(post(logged_client, "/library/likes/add", {"track": track}), 400, "INVALID_TRACK")
    assert fr.log == []


def test_duration_too_big_for_a_float_is_400_not_500(logged_client, fr):
    # 400 chiffres : un entier JSON valide, que math.isfinite ne sait pas convertir (OverflowError → 500).
    huge = yt(1, duration=10 ** 400)
    err(post(logged_client, "/library/likes/add", {"track": huge}), 400, "INVALID_TRACK")
    body = err(post(logged_client, "/library/playlists/create", {"name": "Bal", "tracks": [yt(0), huge]}),
               400, "INVALID_TRACK")
    assert body["index"] == 1
    err(post(logged_client, "/library/playlists/add", {"id": "abc", "tracks": [huge]}), 400, "INVALID_TRACK")
    assert fr.log == []


@pytest.mark.parametrize("url", [None, 3, "", "   ", "x" * 501])
def test_invalid_unlike_is_400(logged_client, fr, url):
    err(post(logged_client, "/library/likes/remove", {"url": url}), 400, "INVALID_REQUEST")
    assert fr.log == []


def _likes(body) -> list[str]:
    return [t["title"] for t in body["library"]["likes"]]


def test_like_index_puts_it_back_at_its_old_position(logged_client, fr):
    for i in (1, 2, 3):
        ok(post(logged_client, "/library/likes/add", {"track": yt(i)}))
    ok(post(logged_client, "/library/likes/remove", {"url": yt(2)["url"]}))
    # annulation du retrait : au rang qu'il avait (1), pas en tête
    body = ok(post(logged_client, "/library/likes/add", {"track": yt(2), "index": 1}))
    assert set(body) == {"ok", "library"}
    assert _likes(body) == ["Titre 3", "Titre 2", "Titre 1"]
    # borné : au-delà → à la fin, négatif → en tête ; absent ou null → en tête (inchangé)
    assert _likes(ok(post(logged_client, "/library/likes/add", {"track": yt(4), "index": 99})))[-1] == "Titre 4"
    assert _likes(ok(post(logged_client, "/library/likes/add", {"track": yt(5), "index": -3})))[0] == "Titre 5"
    assert _likes(ok(post(logged_client, "/library/likes/add", {"track": yt(6), "index": None})))[0] == "Titre 6"
    assert _likes(ok(post(logged_client, "/library/likes/add", {"track": yt(7)})))[0] == "Titre 7"
    # déjà aimé : ne bouge pas, rien d'écrit
    writes = fr.commands().count("EXEC")
    assert _likes(ok(post(logged_client, "/library/likes/add", {"track": yt(4), "index": 0})))[-1] == "Titre 4"
    assert fr.commands().count("EXEC") == writes


@pytest.mark.parametrize("index", ["1", True, 1.0, [1], {"i": 1}])
def test_like_index_not_an_integer_is_400_before_any_redis_access(logged_client, fr, index):
    err(post(logged_client, "/library/likes/add", {"track": yt(1), "index": index}), 400, "INVALID_REQUEST")
    assert fr.log == []


# ── Playlists ──

def test_create_playlist_with_tracks_deduped_and_capped(logged_client, fr):
    tracks = [yt(1), {"url": "https://youtu.be/vid00000001"}] + [yt(i) for i in range(2, 252)]
    body = ok(post(logged_client, "/library/playlists/create", {"name": "  Les grands\nairs ", "tracks": tracks}))
    pid = body["playlist_id"]
    assert isinstance(pid, str) and len(pid) == 11
    [pl] = body["library"]["playlists"]
    assert pl["id"] == pid and pl["name"] == "Les grands airs"
    assert len(pl["tracks"]) == 200
    assert pl["tracks"][0]["url"] == yt(1)["url"] and pl["tracks"][1]["url"] == yt(2)["url"]
    assert pl["created_at"] == pl["updated_at"] and isinstance(pl["created_at"], int)
    assert set(pl) == {"id", "name", "tracks", "created_at", "updated_at"}


def test_create_playlist_without_tracks_and_in_creation_order(logged_client, fr):
    a = create(logged_client, "A")
    b = create(logged_client, "B", tracks=[])
    lib = ok(logged_client.get(f"{BASE}/library"))["library"]
    assert [(p["id"], p["name"], p["tracks"]) for p in lib["playlists"]] == [(a, "A", []), (b, "B", [])]


@pytest.mark.parametrize("name", [None, "", "   ", "\x00", "x" * 61, 42, ["Bal"]])
def test_create_playlist_invalid_name_is_400(logged_client, fr, name):
    err(post(logged_client, "/library/playlists/create", {"name": name}), 400, "INVALID_NAME")
    assert fr.log == []


def test_create_playlist_invalid_tracks(logged_client, fr):
    err(post(logged_client, "/library/playlists/create", {"name": "Bal", "tracks": {"url": yt(1)["url"]}}),
        400, "INVALID_REQUEST")
    body = err(post(logged_client, "/library/playlists/create",
                    {"name": "Bal", "tracks": [yt(1), {"url": "ftp://x"}]}), 400, "INVALID_TRACK")
    assert body["index"] == 1
    err(post(logged_client, "/library/playlists/create",
             {"name": "Bal", "tracks": [yt(i) for i in range(501)]}), 400, "INVALID_REQUEST")
    assert fr.log == []


def test_playlist_limit_is_409(logged_client, fr):
    seed(fr, playlists=[{"id": f"p{i}", "name": f"P{i}", "tracks": [], "created_at": 1, "updated_at": 1}
                        for i in range(50)])
    body = err(post(logged_client, "/library/playlists/create", {"name": "Une de trop"}), 409, "LIMIT_REACHED")
    assert body["limit"] == "playlists"


def test_rename_playlist(logged_client, fr):
    pid = create(logged_client, "Ancien")
    body = ok(post(logged_client, "/library/playlists/rename", {"id": pid, "name": " Nouveau "}))
    [pl] = body["library"]["playlists"]
    assert pl["name"] == "Nouveau" and pl["updated_at"] >= pl["created_at"]
    err(post(logged_client, "/library/playlists/rename", {"id": "inconnu", "name": "x"}), 404, "PLAYLIST_NOT_FOUND")
    err(post(logged_client, "/library/playlists/rename", {"id": pid, "name": ""}), 400, "INVALID_NAME")
    err(post(logged_client, "/library/playlists/rename", {"id": "a/b", "name": "x"}), 400, "INVALID_REQUEST")


def test_delete_playlist(logged_client, fr):
    a = create(logged_client, "A")
    b = create(logged_client, "B")
    body = ok(post(logged_client, "/library/playlists/delete", {"id": a}))
    assert [p["id"] for p in body["library"]["playlists"]] == [b]
    err(post(logged_client, "/library/playlists/delete", {"id": a}), 404, "PLAYLIST_NOT_FOUND")
    err(post(logged_client, "/library/playlists/delete", {"id": None}), 400, "INVALID_REQUEST")


def test_add_tracks_reports_added_and_skipped(logged_client, fr):
    pid = create(logged_client, tracks=[yt(i) for i in range(197)])
    new = [yt(0), yt(500), {"url": "https://youtu.be/vid00000500"}, yt(501), yt(502), yt(503)]
    body = ok(post(logged_client, "/library/playlists/add", {"id": pid, "tracks": new}))
    assert body["added"] == 3 and body["skipped"] == 3
    [pl] = body["library"]["playlists"]
    assert len(pl["tracks"]) == 200 and pl["tracks"][-1]["url"] == yt(502)["url"]
    # Pleine : 200, rien ajouté, tout compté.
    body = ok(post(logged_client, "/library/playlists/add", {"id": pid, "tracks": [yt(900)]}))
    assert body["added"] == 0 and body["skipped"] == 1


def test_add_tracks_errors(logged_client, fr):
    pid = create(logged_client)
    err(post(logged_client, "/library/playlists/add", {"id": pid, "tracks": []}), 400, "INVALID_REQUEST")
    err(post(logged_client, "/library/playlists/add", {"id": pid}), 400, "INVALID_REQUEST")
    err(post(logged_client, "/library/playlists/add", {"id": pid, "tracks": [{"title": "sans lien"}]}),
        400, "INVALID_TRACK")
    err(post(logged_client, "/library/playlists/add", {"id": "inconnu", "tracks": [yt(1)]}),
        404, "PLAYLIST_NOT_FOUND")


def test_remove_track_from_playlist(logged_client, fr):
    pid = create(logged_client, tracks=[yt(0), yt(1), yt(2)])
    body = ok(post(logged_client, "/library/playlists/remove", {"id": pid, "url": "https://youtu.be/vid00000001"}))
    assert [t["title"] for t in body["library"]["playlists"][0]["tracks"]] == ["Titre 0", "Titre 2"]
    # Absent : rien à faire.
    ok(post(logged_client, "/library/playlists/remove", {"id": pid, "url": yt(1)["url"]}))
    err(post(logged_client, "/library/playlists/remove", {"id": "inconnu", "url": yt(1)["url"]}),
        404, "PLAYLIST_NOT_FOUND")
    err(post(logged_client, "/library/playlists/remove", {"id": pid}), 400, "INVALID_REQUEST")


def test_move_track_in_playlist(logged_client, fr):
    pid = create(logged_client, tracks=[yt(0), yt(1), yt(2), yt(3)])
    body = ok(post(logged_client, "/library/playlists/move", {"id": pid, "src": 3, "dst": 0}))
    assert [t["title"] for t in body["library"]["playlists"][0]["tracks"]] == [
        "Titre 3", "Titre 0", "Titre 1", "Titre 2"]
    writes = fr.commands().count("EXEC")
    ok(post(logged_client, "/library/playlists/move", {"id": pid, "src": 1, "dst": 1}))
    assert fr.commands().count("EXEC") == writes


@pytest.mark.parametrize("src,dst", [(4, 0), (0, 4), (-1, 0), (0, -1), ("1", 0), (True, 0), (1.0, 0), (None, 0)])
def test_move_out_of_bounds_or_not_an_index_is_400(logged_client, fr, src, dst):
    pid = create(logged_client, tracks=[yt(0), yt(1), yt(2), yt(3)])
    err(post(logged_client, "/library/playlists/move", {"id": pid, "src": src, "dst": dst}), 400, "INVALID_REQUEST")


def test_move_in_unknown_playlist_is_404(logged_client, fr):
    err(post(logged_client, "/library/playlists/move", {"id": "inconnu", "src": 0, "dst": 0}),
        404, "PLAYLIST_NOT_FOUND")


def _titles(body, i=0) -> list[str]:
    return [t["title"] for t in body["library"]["playlists"][i]["tracks"]]


def test_move_with_url_moves_when_the_track_at_src_is_that_one(logged_client, fr):
    pid = create(logged_client, tracks=[yt(0), yt(1), yt(2), yt(3)])
    # même vidéo sous une autre forme : même identité
    body = ok(post(logged_client, "/library/playlists/move",
                   {"id": pid, "src": 3, "dst": 0, "url": "https://youtu.be/vid00000003"}))
    assert _titles(body) == ["Titre 3", "Titre 0", "Titre 1", "Titre 2"]


def test_move_with_url_of_another_track_is_409_stale_and_moves_nothing(logged_client, fr):
    pid = create(logged_client, tracks=[yt(0), yt(1), yt(2), yt(3)])
    stored_before = fr.kv[KEY]
    writes = fr.commands().count("EXEC")
    # copie du site dépassée : elle croit trouver Titre 3 au rang 1 (réordonnée dans un autre onglet)
    body = err(post(logged_client, "/library/playlists/move", {"id": pid, "src": 1, "dst": 0, "url": yt(3)["url"]}),
               409, "STALE")
    assert body["message"] == store.MSG_STALE and "library" not in body
    # rang disparu (playlist raccourcie ailleurs) : la copie est dépassée aussi
    err(post(logged_client, "/library/playlists/move", {"id": pid, "src": 7, "dst": 0, "url": yt(3)["url"]}),
        409, "STALE")
    assert fr.kv[KEY] == stored_before and fr.commands().count("EXEC") == writes
    # bon titre, destination hors de la playlist : 400 comme sans url ; playlist inconnue : 404 d'abord
    err(post(logged_client, "/library/playlists/move", {"id": pid, "src": 3, "dst": 4, "url": yt(3)["url"]}),
        400, "INVALID_REQUEST")
    err(post(logged_client, "/library/playlists/move", {"id": "inconnu", "src": 0, "dst": 1, "url": yt(3)["url"]}),
        404, "PLAYLIST_NOT_FOUND")


@pytest.mark.parametrize("url", [3, "", "   ", "x" * 501, ["https://youtu.be/vid00000003"]])
def test_move_with_an_invalid_url_is_400_before_any_redis_access(logged_client, fr, url):
    err(post(logged_client, "/library/playlists/move", {"id": "abc", "src": 0, "dst": 1, "url": url}),
        400, "INVALID_REQUEST")
    assert fr.log == []


# ── Annulation d'une suppression : POST /library/playlists/restore ──

def _snapshot(client, pid) -> dict:
    lib = ok(client.get(f"{BASE}/library"))["library"]
    return next(p for p in lib["playlists"] if p["id"] == pid)


def _ids(body) -> list[str]:
    return [p["id"] for p in body["library"]["playlists"]]


def test_restore_puts_a_deleted_playlist_back_in_place_under_its_id(logged_client, fr):
    old = [store.clean_track(yt(i), 500 + i) for i in range(3)]
    seed(fr, playlists=[{"id": pid, "name": name, "tracks": old if pid == "bbb" else [],
                         "created_at": 1000, "updated_at": 2000}
                        for pid, name in (("aaa", "A"), ("bbb", "Les grands airs"), ("ccc", "C"))])
    snap = _snapshot(logged_client, "bbb")
    assert _ids(ok(post(logged_client, "/library/playlists/delete", {"id": "bbb"}))) == ["aaa", "ccc"]

    body = ok(post(logged_client, "/library/playlists/restore", {"playlist": snap, "index": 1}))
    assert set(body) == {"ok", "library"}
    assert _ids(body) == ["aaa", "bbb", "ccc"]
    # à l'identique : id, nom, titres et leurs dates, dates de la playlist
    assert body["library"]["playlists"][1] == snap
    assert json.loads(fr.kv[KEY])["playlists"][1] == snap


def test_restore_is_idempotent_when_the_id_is_already_there(logged_client, fr):
    pid = create(logged_client, "Bal", tracks=[yt(1)])
    snap = _snapshot(logged_client, pid)
    ok(post(logged_client, "/library/playlists/delete", {"id": pid}))
    ok(post(logged_client, "/library/playlists/restore", {"playlist": snap, "index": 0}))
    # restaurée ailleurs entre-temps, puis renommée : rejouer ne change rien, ni n'écrase
    ok(post(logged_client, "/library/playlists/rename", {"id": pid, "name": "Veillée"}))
    stored_before = fr.kv[KEY]
    writes = fr.commands().count("EXEC")
    body = ok(post(logged_client, "/library/playlists/restore", {"playlist": snap, "index": 0}))
    assert [(p["id"], p["name"]) for p in body["library"]["playlists"]] == [(pid, "Veillée")]
    assert fr.kv[KEY] == stored_before and fr.commands().count("EXEC") == writes


@pytest.mark.parametrize("index,ids", [
    (0, ["back", "aaa", "bbb"]), (2, ["aaa", "bbb", "back"]), (99, ["aaa", "bbb", "back"]),
    (-5, ["back", "aaa", "bbb"]), (None, ["aaa", "bbb", "back"]), ("absent", ["aaa", "bbb", "back"]),
])
def test_restore_index_is_clamped_and_defaults_to_the_end(logged_client, fr, index, ids):
    seed(fr, playlists=[{"id": p, "name": p, "tracks": [], "created_at": 1, "updated_at": 1} for p in ("aaa", "bbb")])
    body = {"playlist": {"id": "back", "name": "Revenue", "tracks": [yt(1)]}}
    if index != "absent":
        body["index"] = index
    assert _ids(ok(post(logged_client, "/library/playlists/restore", body))) == ids


def test_restore_cleans_like_a_creation(logged_client, fr):
    tracks = [yt(1), {"url": "https://youtu.be/vid00000001"}] + [yt(i) for i in range(2, 252)]
    body = ok(post(logged_client, "/library/playlists/restore", {
        "playlist": {"id": "back", "name": "  Les grands\nairs ", "tracks": tracks,
                     "created_at": 9_999_999_999, "updated_at": "hier"}, "index": 0}))
    [pl] = body["library"]["playlists"]
    assert pl["name"] == "Les grands airs" and len(pl["tracks"]) == 200
    assert pl["tracks"][0]["url"] == yt(1)["url"] and pl["tracks"][1]["url"] == yt(2)["url"]
    # dates impossibles (futur, texte) : maintenant
    assert pl["created_at"] == pl["updated_at"] and 1_600_000_000 < pl["created_at"] < 9_999_999_999
    assert set(pl) == {"id", "name", "tracks", "created_at", "updated_at"}


@pytest.mark.parametrize("body,status,code", [
    ({}, 400, "INVALID_REQUEST"),
    ({"playlist": None}, 400, "INVALID_REQUEST"),
    ({"playlist": "back"}, 400, "INVALID_REQUEST"),
    ({"playlist": {"name": "Bal"}}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "tmp:1", "name": "Bal"}}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "../etc", "name": "Bal"}}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "x" * 65, "name": "Bal"}}, 400, "INVALID_REQUEST"),
    # « \n » final : « $ » de re.match l'accepterait, et l'id stocké sortirait de l'alphabet promis
    ({"playlist": {"id": "back\n", "name": "Bal"}}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "back"}}, 400, "INVALID_NAME"),
    ({"playlist": {"id": "back", "name": "x" * 61}}, 400, "INVALID_NAME"),
    ({"playlist": {"id": "back", "name": "Bal", "tracks": {"url": "https://x.y"}}}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "back", "name": "Bal", "tracks": [yt(i) for i in range(501)]}}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "back", "name": "Bal", "tracks": [yt(0), {"url": "ftp://x"}]}}, 400, "INVALID_TRACK"),
    ({"playlist": {"id": "back", "name": "Bal"}, "index": "1"}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "back", "name": "Bal"}, "index": True}, 400, "INVALID_REQUEST"),
    ({"playlist": {"id": "back", "name": "Bal"}, "index": 1.5}, 400, "INVALID_REQUEST"),
])
def test_invalid_restore_is_400_before_any_redis_access(logged_client, fr, body, status, code):
    r = err(post(logged_client, "/library/playlists/restore", body), status, code)
    if code == "INVALID_TRACK":
        assert r["index"] == 1
    assert fr.log == []


def test_restore_playlist_limit_is_409_but_an_existing_id_still_succeeds(logged_client, fr):
    seed(fr, playlists=[{"id": f"p{i}", "name": f"P{i}", "tracks": [], "created_at": 1, "updated_at": 1}
                        for i in range(50)])
    body = err(post(logged_client, "/library/playlists/restore", {"playlist": {"id": "back", "name": "Bal"}}),
               409, "LIMIT_REACHED")
    assert body["limit"] == "playlists"
    ok(post(logged_client, "/library/playlists/restore", {"playlist": {"id": "p7", "name": "P7"}, "index": 0}))


def test_restore_over_the_byte_budget_is_409_size(logged_client, fr, monkeypatch):
    pid = create(logged_client, "Bal", tracks=[yt(1)])
    snap = _snapshot(logged_client, pid)
    ok(post(logged_client, "/library/playlists/delete", {"id": pid}))
    monkeypatch.setattr(store, "MAX_LIBRARY_BYTES", 10)
    body = err(post(logged_client, "/library/playlists/restore", {"playlist": snap, "index": 0}), 409, "LIMIT_REACHED")
    assert body["limit"] == "size"
    assert json.loads(fr.kv[KEY])["playlists"] == []


def test_restore_is_per_king(app, logged_client, login, fr):
    other = login(app.test_client(), 888)
    pid = create(logged_client, "À moi", tracks=[yt(1)])
    snap = _snapshot(logged_client, pid)
    # l'autre Roi qui rejoue l'instantané le restaure chez lui, jamais chez le premier
    ok(post(other, "/library/playlists/restore", {"playlist": snap, "index": 0}))
    assert [p["id"] for p in ok(other.get(f"{BASE}/library"))["library"]["playlists"]] == [pid]
    assert len(json.loads(fr.kv[KEY])["playlists"]) == 1


# ── Corps invalides : 400, jamais 500 ──

@pytest.mark.parametrize("path", MUTATION_PATHS)
def test_non_object_json_body_is_400(logged_client, fr, path):
    err(post(logged_client, path, [1, 2]), 400, "INVALID_REQUEST")
    err(logged_client.post(f"{BASE}{path}", data="track=x", content_type="application/x-www-form-urlencoded"),
        403, "CSRF_FAILED")
    err(logged_client.post(f"{BASE}{path}", data="{pas du json", content_type="application/json"),
        400, "INVALID_REQUEST")
    assert fr.log == []


# ── Redis ──

@pytest.mark.parametrize("method,path,body", LIBRARY_ROUTES, ids=_IDS)
def test_redis_down_is_503_without_details(logged_client, fr, method, path, body):
    fr.fail = redis.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")
    kw = {"json": body} if body is not None else {}
    r = getattr(logged_client, method)(f"{BASE}{path}", **kw)
    assert r.status_code == 503
    assert r.get_json() == {"ok": False, "error": "STORAGE_UNAVAILABLE", "message": store.MSG_STORAGE_UNAVAILABLE}


def test_invalid_input_is_400_even_when_redis_is_down(logged_client, fr):
    fr.fail = redis.ConnectionError("down")
    err(post(logged_client, "/library/likes/add", {"track": {"url": "nope"}}), 400, "INVALID_TRACK")


def test_concurrent_write_from_another_tab_is_merged(logged_client, fr):
    ok(post(logged_client, "/library/likes/add", {"track": yt(1)}))
    pid = create(logged_client, "Bal")
    current = json.loads(fr.kv[KEY])

    def other_tab():
        # L'autre onglet ajoute un coup de cœur pendant que celui-ci ajoute un titre à la playlist.
        doc = json.loads(json.dumps(current))
        doc["likes"].insert(0, store.clean_track(yt(2), 5))
        fr.write(KEY, json.dumps(doc))

    fr.interleave.append(other_tab)
    body = ok(post(logged_client, "/library/playlists/add", {"id": pid, "tracks": [yt(3)]}))
    assert [t["url"] for t in body["library"]["likes"]] == [yt(2)["url"], yt(1)["url"]]
    assert [t["url"] for t in body["library"]["playlists"][0]["tracks"]] == [yt(3)["url"]]
    assert json.loads(fr.kv[KEY])["likes"][0]["url"] == yt(2)["url"]


def test_endless_conflicts_are_503(logged_client, fr):
    fr.interleave.extend([lambda i=i: seed(fr, likes=[store.clean_track(yt(100 + i))]) for i in range(5)])
    body = err(post(logged_client, "/library/likes/add", {"track": yt(1)}), 503, "STORAGE_UNAVAILABLE")
    assert body["message"] == store.MSG_STORAGE_BUSY


def test_corrupt_value_reads_empty_then_is_backed_up(logged_client, fr):
    fr.write(KEY, "\x00\x01 pas du json")
    lib = ok(logged_client.get(f"{BASE}/library"))["library"]
    assert lib["likes"] == [] and lib["playlists"] == []
    ok(post(logged_client, "/library/likes/add", {"track": yt(1)}))
    backups = [k for k in fr.kv if k.startswith(f"{KEY}:corrupt:")]
    assert len(backups) == 1 and fr.kv[backups[0]] == "\x00\x01 pas du json"
    assert json.loads(fr.kv[KEY])["v"] == 1
