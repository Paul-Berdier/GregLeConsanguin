"""Routes /player/* et compat — play_for_user (C2/C3), get_state (C3), validation des entrées."""
from __future__ import annotations

import pytest

BASE = "/api/v1"


# ── play_for_user : timeout 25 s, TIMEOUT → 504, message transmis ──

def test_enqueue_sends_play_for_user_with_25s_timeout(logged_client, fake_send, session_uid):
    fake_send.result = {"ok": True, "added": 12, "requested": 12, "truncated": None,
                        "playlist": True, "title": "Ma playlist"}
    r = logged_client.post(f"{BASE}/queue/add", json={
        "guild_id": "123", "user_id": "456",
        "query": "https://www.youtube.com/playlist?list=PL123",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["added"] == 12 and body["playlist"] is True

    call = fake_send.calls[-1]
    assert call["action"] == "play_for_user"
    # SEC-C1 : l'utilisateur est celui de la session, jamais le user_id du corps
    assert call["guild_id"] == 123 and call["user_id"] == session_uid
    assert call["timeout"] == 25
    item = call["data"]["item"]
    assert item["url"] == "https://www.youtube.com/playlist?list=PL123"
    assert set(item) == {"url", "title", "artist", "duration", "thumb", "provider"}


def test_enqueue_timeout_maps_to_504_with_french_message(logged_client, fake_send):
    fake_send.result = {"ok": False, "error": "TIMEOUT"}
    r = logged_client.post(f"{BASE}/player/enqueue", json={"guild_id": 1, "user_id": 2, "query": "x"})
    assert r.status_code == 504
    body = r.get_json()
    assert body["ok"] is False
    assert body["error"] == "TIMEOUT"
    assert body["message"].startswith("Greg met trop de temps à répondre…")


def test_enqueue_bot_failure_keeps_409_and_passes_message(logged_client, fake_send):
    fake_send.result = {"ok": False, "error": "PLAYLIST_UNAVAILABLE",
                        "message": "Playlist privée ou supprimée."}
    r = logged_client.post(f"{BASE}/queue/add", json={"guild_id": 1, "user_id": 2, "query": "x"})
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "PLAYLIST_UNAVAILABLE"
    assert body["message"] == "Playlist privée ou supprimée."


def test_enqueue_priority_forbidden_is_403(logged_client, fake_send):
    fake_send.result = {"ok": False, "error": "PRIORITY_FORBIDDEN"}
    r = logged_client.post(f"{BASE}/queue/add", json={"guild_id": 1, "user_id": 2, "query": "x"})
    assert r.status_code == 403


def test_enqueue_bot_offline_is_503_with_message(logged_client, fake_send):
    fake_send.result = {"ok": False, "error": "BOT_OFFLINE", "message": "Greg est hors ligne."}
    r = logged_client.post(f"{BASE}/queue/add", json={"guild_id": 1, "user_id": 2, "query": "x"})
    assert r.status_code == 503
    body = r.get_json()
    assert body["error"] == "BOT_OFFLINE"
    assert body["message"] == "Greg est hors ligne."


# ── Commandes qui modifient l'état : le bot les sérialise par guild derrière un
#    play_for_user (C3) → même attente, et TIMEOUT/BOT_OFFLINE via error_status ──

# (méthode, chemin, corps en plus de guild_id/user_id, action bot, code par défaut en échec)
MUTATING_ROUTES = [
    ("post", "/player/skip", {}, "skip", 500),
    ("post", "/queue/skip", {}, "skip", 500),
    ("post", "/player/stop", {}, "stop", 500),
    ("post", "/queue/stop", {}, "stop", 500),
    ("post", "/player/pause", {}, "toggle_pause", 409),
    ("post", "/playlist/toggle_pause", {}, "toggle_pause", 409),
    ("post", "/player/repeat", {"mode": "toggle"}, "repeat", 409),
    ("post", "/player/move", {"src": 1, "dst": 0}, "move", 409),
    ("delete", "/player/queue/1", {}, "remove", 409),
    ("post", "/queue/remove", {"index": 1}, "remove", 409),
    ("post", "/playlist/play_at", {"index": 1}, "play_at", 409),
    ("post", "/playlist/restart", {}, "restart", 409),
    ("post", "/voice/join", {}, "join", 409),
]
_MUTATING_IDS = [f"{m} {p}" for m, p, *_ in MUTATING_ROUTES]


def _call(client, method, path, extra):
    return getattr(client, method)(f"{BASE}{path}", json={"guild_id": 1, "user_id": 2, **extra})


@pytest.mark.parametrize("method,path,extra,action,default", MUTATING_ROUTES, ids=_MUTATING_IDS)
def test_mutating_command_waits_as_long_as_play_for_user(logged_client, fake_send, method, path, extra,
                                                         action, default):
    import api.routes.player as player_mod

    r = _call(logged_client, method, path, extra)
    assert r.status_code == 200
    call = fake_send.calls[-1]
    assert call["action"] == action
    # Un skip derrière une playlist en cours d'ajout ne doit pas finir en TIMEOUT
    # (puis s'exécuter quand même) ; on reste sous le proxyTimeout de 30 s du front.
    assert player_mod.PLAY_FOR_USER_TIMEOUT <= call["timeout"] < 30


@pytest.mark.parametrize("method,path,extra,action,default", MUTATING_ROUTES, ids=_MUTATING_IDS)
@pytest.mark.parametrize("error,status", [("TIMEOUT", 504), ("BOT_OFFLINE", 503),
                                          ("PRIORITY_FORBIDDEN", 403),
                                          ("NOT_GUILD_MEMBER", 403),
                                          ("NOT_AUTHENTICATED", 401)])
def test_mutating_bridge_errors_use_error_status(logged_client, fake_send, method, path, extra, action,
                                                 default, error, status):
    fake_send.result = {"ok": False, "error": error, "message": "Message FR."}
    r = _call(logged_client, method, path, extra)
    assert r.status_code == status
    body = r.get_json()
    assert body["error"] == error
    assert body["message"] == "Message FR."


@pytest.mark.parametrize("method,path,extra,action,default", MUTATING_ROUTES, ids=_MUTATING_IDS)
def test_mutating_other_errors_keep_route_default(logged_client, fake_send, method, path, extra, action,
                                                  default):
    fake_send.result = {"ok": False, "error": "NOT_PLAYING"}
    r = _call(logged_client, method, path, extra)
    assert r.status_code == default


# ── get_state : échec → 200 {ok:false, stale:true, backend_error}, sans faux état ──

@pytest.mark.parametrize("path", ["/player/state", "/playlist"])
def test_get_state_failure_is_stale_without_fake_state(logged_client, fake_send, path):
    fake_send.result = {"ok": False, "error": "TIMEOUT"}
    r = logged_client.get(f"{BASE}{path}?guild_id=42")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False
    assert body["stale"] is True
    assert body["backend_error"] == "TIMEOUT"
    for fake_key in ("current", "queue", "is_paused", "repeat_all", "progress"):
        assert fake_key not in body


def test_get_state_success_passes_through(logged_client, fake_send):
    fake_send.result = {"ok": True, "state": {"current": {"title": "a"}, "queue": []}}
    r = logged_client.get(f"{BASE}/playlist?guild_id=42")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["state"]["current"]["title"] == "a"
    assert fake_send.calls[-1]["action"] == "get_state"


# ── Entrées invalides → 400 (plus de 500) ──

def test_move_non_int_is_400(logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/move", json={"guild_id": 1, "user_id": 1, "src": "a", "dst": 0})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert fake_send.calls == []


def test_move_valid_forwards_ints(logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/move", json={"guild_id": 1, "user_id": 1, "src": "2", "dst": 0})
    assert r.status_code == 200
    assert fake_send.calls[-1]["data"] == {"src": 2, "dst": 0}


@pytest.mark.parametrize("index", ["x", None, -1, [1]])
def test_queue_remove_bad_index_is_400(logged_client, fake_send, index):
    r = logged_client.post(f"{BASE}/queue/remove", json={"guild_id": 1, "user_id": 1, "index": index})
    assert r.status_code == 400
    assert fake_send.calls == []


def test_queue_remove_valid(logged_client, fake_send):
    r = logged_client.post(f"{BASE}/queue/remove", json={"guild_id": 1, "user_id": 1, "index": 3})
    assert r.status_code == 200
    assert fake_send.calls[-1]["data"] == {"index": 3}


@pytest.mark.parametrize("index", ["x", None, -2])
def test_play_at_bad_index_is_400(logged_client, fake_send, index):
    r = logged_client.post(f"{BASE}/playlist/play_at", json={"guild_id": 1, "user_id": 1, "index": index})
    assert r.status_code == 400
    assert fake_send.calls == []


@pytest.mark.parametrize("path", ["/player/skip", "/queue/add", "/player/move", "/playlist/play_at",
                                  "/queue/remove", "/voice/join", "/player/repeat"])
def test_non_object_json_body_is_400_not_500(logged_client, fake_send, path):
    r = logged_client.post(f"{BASE}{path}", json=[1, 2])
    assert r.status_code == 400
    assert fake_send.calls == []


def test_history_bad_guild_id_is_400(logged_client, fake_send):
    r = logged_client.get(f"{BASE}/history?guild_id=abc")
    assert r.status_code == 400
    r = logged_client.get(f"{BASE}/history/recent?guild_id=abc")
    assert r.status_code == 400
    assert fake_send.calls == []


def test_history_valid_guild_id(logged_client, fake_send):
    fake_send.result = {"ok": True, "items": []}
    r = logged_client.get(f"{BASE}/history?guild_id=77&mode=top&limit=5")
    assert r.status_code == 200
    call = fake_send.calls[-1]
    assert call["guild_id"] == 77
    assert call["data"] == {"mode": "top", "limit": 5}
