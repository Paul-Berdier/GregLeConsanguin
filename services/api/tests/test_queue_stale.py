"""Garde `expected` (spec §3.6) : l'élément attendu n'est transmis au bot que s'il est fourni,
un `STALE` du bot devient 409 avec un message français, un `expected` mal formé 400 sans appel au bot."""
from __future__ import annotations

import pytest

BASE = "/api/v1"

E = {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "added_by": "7", "ts": 1700000000}
ROUTES = [("post", "/queue/remove", {"index": 1}, "remove", {"index": 1}),
          ("delete", "/player/queue/1", {}, "remove", {"index": 1}),
          ("post", "/player/move", {"src": 1, "dst": 0}, "move", {"src": 1, "dst": 0}),
          ("post", "/playlist/play_at", {"index": 1}, "play_at", {"index": 1})]


@pytest.mark.parametrize("method,path,body,action,data", ROUTES)
def test_expected_is_forwarded_only_when_given(logged_client, fake_send, method, path, body, action, data):
    getattr(logged_client, method)(f"{BASE}{path}", json={"guild_id": "5", **body})
    assert fake_send.calls[-1]["data"] == data
    getattr(logged_client, method)(f"{BASE}{path}", json={"guild_id": "5", **body, "expected": E})
    assert fake_send.calls[-1]["data"] == {**data, "expected": E}


@pytest.mark.parametrize("method,path,body,action,data", ROUTES)
def test_stale_is_409_with_french_message(logged_client, fake_send, method, path, body, action, data):
    fake_send.result = {"ok": False, "error": "STALE"}
    r = getattr(logged_client, method)(f"{BASE}{path}", json={"guild_id": "5", **body, "expected": E})
    assert r.status_code == 409 and r.get_json() == {"ok": False, "error": "STALE", "message": "La file a bougé : réessayez."}


@pytest.mark.parametrize("bad", ["x", [1], {"url": 5}, {"url": "u", "ts": "abc"}, {"url": "u", "ts": True}, {"url": "u", "added_by": [1]}])
def test_invalid_expected_is_400_without_calling_the_bot(logged_client, fake_send, bad):
    r = logged_client.post(f"{BASE}/queue/remove", json={"guild_id": "5", "index": 1, "expected": bad})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "invalid expected"} and fake_send.calls == []
