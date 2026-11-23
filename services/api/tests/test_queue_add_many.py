"""POST /queue/add_many — une playlist du chansonnier d'un geste (spec 2026-11-23 §3) : 1 à 100 titres
nettoyés comme ceux du chansonnier, une seule commande play_for_user (item = {"items": [...], "title": label}),
même délai et même réponse HTTP que /player/enqueue."""
from __future__ import annotations

import pytest

BASE = "/api/v1"
PATH = f"{BASE}/queue/add_many"
ITEM_KEYS = {"url", "title", "artist", "duration", "thumb", "provider"}


def yt(i: int, **kw) -> dict:
    t = {"url": f"https://www.youtube.com/watch?v=vid{i:08d}", "title": f"Titre {i}", "artist": "Artiste",
         "duration": 180, "thumb": None, "provider": "youtube", "added_at": 1700000000}
    t.update(kw)
    return t


def test_forwards_one_play_for_user_with_the_cleaned_items(logged_client, fake_send, session_uid):
    fake_send.result = {"ok": True, "added": 2, "requested": 2, "truncated": None,
                        "playlist": True, "title": "Bal du Roi"}
    r = logged_client.post(PATH, json={
        "guild_id": "123", "user_id": "456", "label": "  Bal du\nRoi ",
        "items": [yt(1), {"url": " https://soundcloud.com/a/b ", "title": " Le  Barde ",
                          "thumbnail": "https://img/x.jpg", "duration": 61.5}],
    })
    assert r.status_code == 200
    assert r.get_json() == fake_send.result

    [call] = fake_send.calls
    assert call["action"] == "play_for_user"
    assert call["guild_id"] == 123 and call["user_id"] == session_uid  # SEC-C1 : jamais le user_id du corps
    assert call["timeout"] == 25
    item = call["data"]["item"]
    assert set(item) == {"items", "title"} and item["title"] == "Bal du Roi"
    assert [set(it) for it in item["items"]] == [ITEM_KEYS, ITEM_KEYS]  # ni added_at ni champ inconnu
    assert item["items"][0] == {"url": yt(1)["url"], "title": "Titre 1", "artist": "Artiste", "duration": 180,
                                "thumb": None, "provider": "youtube"}
    assert item["items"][1] == {"url": "https://soundcloud.com/a/b", "title": "Le Barde", "artist": None,
                                "duration": 61, "thumb": "https://img/x.jpg", "provider": "soundcloud"}


def test_label_is_optional(logged_client, fake_send):
    r = logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1)]})
    assert r.status_code == 200
    assert fake_send.calls[-1]["data"]["item"]["title"] is None
    logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1)], "label": "   "})
    assert fake_send.calls[-1]["data"]["item"]["title"] is None


def test_guild_id_from_header(logged_client, fake_send):
    r = logged_client.post(PATH, json={"items": [yt(1)]}, headers={"X-Guild-ID": "77"})
    assert r.status_code == 200 and fake_send.calls[-1]["guild_id"] == 77


def test_hundred_items_is_the_maximum(logged_client, fake_send):
    r = logged_client.post(PATH, json={"guild_id": 1, "items": [yt(i) for i in range(100)]})
    assert r.status_code == 200
    assert len(fake_send.calls[-1]["data"]["item"]["items"]) == 100


@pytest.mark.parametrize("items", [[], [yt(i) for i in range(101)], None, {"url": yt(1)["url"]}, yt(1)["url"]])
def test_item_count_outside_1_to_100_is_400(logged_client, fake_send, items):
    body = {"guild_id": 1} if items is None else {"guild_id": 1, "items": items}
    r = logged_client.post(PATH, json=body)
    assert r.status_code == 400
    out = r.get_json()
    assert out["ok"] is False and out["error"] == "INVALID_REQUEST" and "100" in out["message"]
    assert fake_send.calls == []


@pytest.mark.parametrize("bad", [{"url": "javascript:alert(1)"}, {"title": "sans lien"}, "https://youtu.be/x",
                                 {"url": "https://x.y/a", "duration": "3:00"}, {"url": "https://x.y/" + "a" * 500}])
def test_invalid_item_is_400_with_its_index(logged_client, fake_send, bad):
    r = logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1), bad]})
    assert r.status_code == 400
    out = r.get_json()
    assert out["ok"] is False and out["error"] == "INVALID_TRACK" and out["index"] == 1 and out["message"]
    assert fake_send.calls == []


@pytest.mark.parametrize("label", [3, ["Bal"], {"n": 1}])
def test_non_text_label_is_400(logged_client, fake_send, label):
    r = logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1)], "label": label})
    assert r.status_code == 400 and r.get_json()["error"] == "INVALID_REQUEST"
    assert fake_send.calls == []


def test_long_label_is_cut(logged_client, fake_send):
    logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1)], "label": "L" * 300})
    assert fake_send.calls[-1]["data"]["item"]["title"] == "L" * 200


@pytest.mark.parametrize("body", [{"items": [yt(1)]}, {"guild_id": "abc", "items": [yt(1)]}])
def test_missing_guild_is_400(logged_client, fake_send, body):
    r = logged_client.post(PATH, json=body)
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "missing guild_id"}
    assert fake_send.calls == []


def test_non_object_json_body_is_400(logged_client, fake_send):
    r = logged_client.post(PATH, json=[yt(1)])
    assert r.status_code == 400
    assert fake_send.calls == []


def test_requires_a_session(client, fake_send):
    r = client.post(PATH, json={"guild_id": 1, "user_id": "456", "items": [yt(1)]}, headers={"X-User-ID": "456"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "NOT_AUTHENTICATED"
    assert fake_send.calls == []


# ── Même réponse HTTP que /player/enqueue (play_for_user_response) ──

def test_timeout_is_504_with_the_enqueue_message(logged_client, fake_send):
    fake_send.result = {"ok": False, "error": "TIMEOUT"}
    r = logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1)]})
    assert r.status_code == 504
    assert r.get_json()["message"].startswith("Greg met trop de temps à répondre…")


@pytest.mark.parametrize("error,status", [("BOT_OFFLINE", 503), ("PRIORITY_FORBIDDEN", 403),
                                          ("NOT_GUILD_MEMBER", 403), ("NOT_AUTHENTICATED", 401),
                                          ("QUOTA_EXCEEDED", 409), ("USER_NOT_IN_VOICE", 409),
                                          ("PLAYLIST_EMPTY", 409)])
def test_bot_errors_use_the_enqueue_mapping(logged_client, fake_send, error, status):
    fake_send.result = {"ok": False, "error": error, "message": "Message FR."}
    r = logged_client.post(PATH, json={"guild_id": 1, "items": [yt(1)]})
    assert r.status_code == status
    assert r.get_json() == {"ok": False, "error": error, "message": "Message FR."}


def test_enqueue_route_is_unchanged(logged_client, fake_send):
    # /queue/add garde ses 6 clés et un seul titre : le lot passe uniquement par /queue/add_many.
    logged_client.post(f"{BASE}/queue/add", json={"guild_id": 1, "query": "x", "items": [yt(1)]})
    item = fake_send.calls[-1]["data"]["item"]
    assert set(item) == ITEM_KEYS and item["url"] == "x"
