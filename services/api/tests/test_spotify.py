"""Routes Spotify — quickplay (même forme d'item que /player/enqueue), requêtes encodées, réponses vérifiées."""
from __future__ import annotations

import pytest

import api.routes.spotify as sp

BASE = "/api/v1"


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status_code < 300
        self.text = ""

    def json(self):
        return self._payload


class FakeHttp:
    """Remplace le module `requests` importé par spotify.py (req)."""

    def __init__(self):
        self.calls = []
        self.get_resp = FakeResp(200, {"tracks": {"items": [{"uri": "spotify:track:1"}]}})
        self.post_resp = FakeResp(201, {"snapshot_id": "s"})
        self.delete_resp = FakeResp(200)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.get_resp

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.post_resp

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw))
        return self.delete_resp


@pytest.fixture()
def http(monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(sp, "req", fake)
    return fake


@pytest.fixture()
def linked_client(client):
    with client.session_transaction() as sess:
        sess["spotify_token"] = "sp-tok"
    return client


# ── quickplay ──

def test_quickplay_sends_free_text_item_like_enqueue(client, fake_send):
    fake_send.result = {"ok": True, "added": 1, "requested": 1, "truncated": None,
                        "playlist": False, "title": "One More Time"}
    r = client.post(f"{BASE}/spotify/quickplay", json={
        "guild_id": "10", "user_id": "20",
        "track": {"name": "One More Time", "artists": [{"name": "Daft Punk"}],
                  "duration_ms": 320000, "album": {"images": [{"url": "http://img"}]}},
    })
    assert r.status_code == 200
    call = fake_send.calls[-1]
    assert call["action"] == "play_for_user"
    assert call["timeout"] == 25
    assert call["guild_id"] == 10 and call["user_id"] == 20
    item = call["data"]["item"]
    assert set(item) == {"url", "title", "artist", "duration", "thumb", "provider"}
    assert item["url"] == "One More Time Daft Punk"  # texte libre, résolu par le bot
    assert item["title"] == "One More Time"
    assert item["artist"] == "Daft Punk"
    assert item["duration"] == 320  # secondes, pas millisecondes
    assert item["thumb"] == "http://img"


def test_quickplay_timeout_is_504(client, fake_send):
    fake_send.result = {"ok": False, "error": "TIMEOUT"}
    r = client.post(f"{BASE}/spotify/quickplay", json={
        "guild_id": "10", "user_id": "20", "track": {"name": "x", "artists": "y"}})
    assert r.status_code == 504
    assert r.get_json()["message"].startswith("Greg met trop de temps à répondre…")


def test_quickplay_bad_ids_is_400(client, fake_send):
    r = client.post(f"{BASE}/spotify/quickplay", json={
        "guild_id": "abc", "user_id": "20", "track": {"name": "x"}})
    assert r.status_code == 400
    r = client.post(f"{BASE}/spotify/quickplay", json={
        "guild_id": "1", "user_id": "2", "track": "pas un objet"})
    assert r.status_code == 400
    assert fake_send.calls == []


# ── add_current_to_playlist ──

def test_add_current_encodes_query_and_checks_add_response(linked_client, fake_send, http):
    fake_send.result = {"ok": True, "state": {"current": {"title": "The Boxer", "artist": "Simon & Garfunkel"}}}
    http.post_resp = FakeResp(401, {"error": {"status": 401}})
    r = linked_client.post(f"{BASE}/spotify/add_current_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "5"})
    method, url, kw = http.calls[0]
    assert method == "GET"
    assert "?" not in url  # la query passe par params= (encodée par requests)
    assert kw["params"] == {"q": "The Boxer Simon & Garfunkel", "type": "track", "limit": 1}
    # l'ajout a échoué côté Spotify → pas de faux succès
    assert r.status_code >= 400
    assert r.get_json()["ok"] is False


def test_add_current_success(linked_client, fake_send, http):
    fake_send.result = {"ok": True, "state": {"current": {"title": "T", "artist": "A"}}}
    r = linked_client.post(f"{BASE}/spotify/add_current_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "5"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "added_uri": "spotify:track:1"}


def test_add_current_state_timeout_is_not_nothing_playing(linked_client, fake_send, http):
    fake_send.result = {"ok": False, "error": "TIMEOUT"}
    r = linked_client.post(f"{BASE}/spotify/add_current_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "5"})
    assert r.status_code == 504
    assert r.get_json()["error"] == "TIMEOUT"
    assert http.calls == []


def test_add_current_bad_gid_is_400(linked_client, fake_send, http):
    r = linked_client.post(f"{BASE}/spotify/add_current_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "abc"})
    assert r.status_code == 400


# ── add_queue_to_playlist ──

def test_add_queue_encodes_queries_and_checks_add_response(linked_client, fake_send, http):
    fake_send.result = {"ok": True, "state": {"queue": [
        {"title": "C# Minor", "artist": "X"}, {"title": "A+B", "artist": "Y & Z"}]}}
    http.post_resp = FakeResp(403)
    r = linked_client.post(f"{BASE}/spotify/add_queue_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "5", "max_items": 20})
    gets = [c for c in http.calls if c[0] == "GET"]
    assert [c[2]["params"]["q"] for c in gets] == ["C# Minor X", "A+B Y & Z"]
    assert all("?" not in c[1] for c in gets)
    assert r.status_code >= 400
    assert r.get_json()["ok"] is False


@pytest.mark.parametrize("max_items", ["abc", None, [1]])
def test_add_queue_bad_max_items_is_400(linked_client, fake_send, http, max_items):
    r = linked_client.post(f"{BASE}/spotify/add_queue_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "5", "max_items": max_items})
    assert r.status_code == 400


def test_add_queue_state_failure_passes_error(linked_client, fake_send, http):
    fake_send.result = {"ok": False, "error": "BOT_OFFLINE", "message": "Greg est hors ligne."}
    r = linked_client.post(f"{BASE}/spotify/add_queue_to_playlist",
                           json={"playlist_id": "pl1", "guild_id": "5"})
    assert r.status_code == 503
    assert r.get_json()["error"] == "BOT_OFFLINE"


# ── playlist_delete / playlist_remove_tracks ──

def test_playlist_delete_checks_response(linked_client, http):
    http.delete_resp = FakeResp(403)
    r = linked_client.post(f"{BASE}/spotify/playlist_delete", json={"playlist_id": "pl1"})
    assert r.status_code >= 400
    assert r.get_json()["ok"] is False


def test_playlist_delete_success(linked_client, http):
    r = linked_client.post(f"{BASE}/spotify/playlist_delete", json={"playlist_id": "pl1"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_remove_tracks_failure_body_is_not_ok(linked_client, http):
    http.delete_resp = FakeResp(404)
    r = linked_client.post(f"{BASE}/spotify/playlist_remove_tracks",
                           json={"playlist_id": "pl1", "track_uris": ["spotify:track:1"]})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
