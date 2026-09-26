"""GET /guilds — bot_present depuis la clé Redis greg:bot:guilds (C5), pas de traceback exposée."""
from __future__ import annotations

import pytest
import requests

import api.services.bot_bridge as bb

BASE = "/api/v1"


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


DISCORD_GUILDS = [
    {"id": "111", "name": "Avec Greg", "icon": None, "owner": False},
    {"id": "222", "name": "Sans Greg", "icon": "abc", "owner": True},
]


@pytest.fixture()
def logged_client(client):
    with client.session_transaction() as sess:
        sess["discord_user"] = {"id": "9", "username": "paul"}
        sess["discord_token"] = "tok"
    return client


@pytest.fixture()
def discord_ok(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(200, DISCORD_GUILDS))


def test_guilds_adds_bot_present_when_key_exists(logged_client, discord_ok, monkeypatch):
    monkeypatch.setattr(bb, "get_bot_guild_ids", lambda: {"111"})
    r = logged_client.get(f"{BASE}/guilds")
    assert r.status_code == 200
    guilds = {g["id"]: g for g in r.get_json()["guilds"]}
    assert guilds["111"]["bot_present"] is True
    assert guilds["222"]["bot_present"] is False
    # champs historiques conservés
    assert guilds["222"]["name"] == "Sans Greg" and guilds["222"]["owner"] is True


def test_guilds_omits_bot_present_when_key_missing(logged_client, discord_ok, monkeypatch):
    monkeypatch.setattr(bb, "get_bot_guild_ids", lambda: None)
    r = logged_client.get(f"{BASE}/guilds")
    assert r.status_code == 200
    for g in r.get_json()["guilds"]:
        assert "bot_present" not in g


def test_guilds_never_fails_because_of_bot_presence(logged_client, discord_ok, monkeypatch):
    def boom():
        raise RuntimeError("redis HS")

    monkeypatch.setattr(bb, "get_bot_guild_ids", boom)
    r = logged_client.get(f"{BASE}/guilds")
    assert r.status_code == 200
    assert len(r.get_json()["guilds"]) == 2


def test_guilds_crash_does_not_leak_traceback(logged_client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(requests, "get", boom)
    r = logged_client.get(f"{BASE}/guilds")
    assert r.status_code == 500
    body = r.get_json()
    assert body["ok"] is False
    assert body["error"] == "guilds_crash"
    assert "trace" not in body
    assert "secret internal detail" not in r.get_data(as_text=True)


def test_guilds_requires_auth(client):
    r = client.get(f"{BASE}/guilds")
    assert r.status_code == 401
