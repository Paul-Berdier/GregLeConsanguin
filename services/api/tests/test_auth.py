"""OAuth Discord (SEC-C6) — state anti-CSRF en session, plus de flux popup overlay, aucune fuite."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

import api.routes.auth as auth_mod

BASE = "/api/v1"


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeDiscordHttp:
    """Remplace le module `requests` importé par auth.py (req) : aucun appel réseau."""

    def __init__(self):
        self.calls = []
        self.token_resp = FakeResp(200, {"access_token": "discord-access"})
        self.user_resp = FakeResp(200, {"id": "123456789", "username": "paul"})

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.token_resp

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.user_resp


@pytest.fixture()
def discord_configured(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "discord_client_id", "cid")
    monkeypatch.setattr(auth_mod.settings, "discord_client_secret", "csecret")
    monkeypatch.setattr(auth_mod.settings, "discord_redirect_uri",
                        "https://web.example/api/v1/auth/callback")
    monkeypatch.setattr(auth_mod.settings, "discord_oauth_scopes", "identify guilds")
    monkeypatch.setenv("WEB_URL", "https://web.example")


@pytest.fixture()
def http(monkeypatch):
    fake = FakeDiscordHttp()
    monkeypatch.setattr(auth_mod, "req", fake)
    return fake


def _login_state(client, path="/auth/login"):
    r = client.get(f"{BASE}{path}")
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert loc.startswith("https://discord.com/api/oauth2/authorize")
    return parse_qs(urlsplit(loc).query)["state"][0]


def test_login_stores_random_state_in_session(client, discord_configured):
    state = _login_state(client)
    assert len(state) >= 24
    with client.session_transaction() as sess:
        assert sess["oauth_state"] == state
    assert _login_state(client) != state


def test_overlay_popup_flow_is_gone(client, discord_configured, http):
    # `?return=overlay` n'a plus d'effet : state aléatoire, jamais « overlay »
    state = _login_state(client, "/auth/login?return=overlay")
    assert state not in ("overlay", "web")
    assert not hasattr(auth_mod, "_CLOSE_PAGE")
    r = client.get(f"{BASE}/auth/callback?code=c0de&state={state}")
    assert r.status_code == 302  # redirection vers le front, pas de page HTML auto-fermante


def test_callback_with_matching_state_logs_in(client, discord_configured, http):
    state = _login_state(client)
    r = client.get(f"{BASE}/auth/callback?code=c0de&state={state}")
    assert r.status_code == 302
    assert r.headers["Location"] == "https://web.example"
    with client.session_transaction() as sess:
        assert sess["discord_user"]["id"] == "123456789"
        assert sess["discord_token"] == "discord-access"
        assert "oauth_state" not in sess  # usage unique


@pytest.mark.parametrize("bad_state", [None, "", "web", "overlay", "forged-state", "é"])
def test_callback_with_bad_state_is_rejected(client, discord_configured, http, bad_state):
    _login_state(client)
    qs = {"code": "c0de"}
    if bad_state is not None:
        qs["state"] = bad_state
    r = client.get(f"{BASE}/auth/callback", query_string=qs)
    assert r.status_code == 400
    assert r.get_json() == {"ok": False, "error": "invalid_state"}
    assert http.calls == []  # aucun échange de code chez Discord
    with client.session_transaction() as sess:
        assert "discord_user" not in sess
        assert "discord_token" not in sess


def test_callback_without_login_is_rejected(client, discord_configured, http):
    r = client.get(f"{BASE}/auth/callback?code=c0de&state=whatever")
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_state"
    assert http.calls == []


def test_callback_state_cannot_be_replayed(client, discord_configured, http):
    state = _login_state(client)
    assert client.get(f"{BASE}/auth/callback?code=c0de&state={state}").status_code == 302
    with client.session_transaction() as sess:
        sess.pop("discord_user", None)
    r = client.get(f"{BASE}/auth/callback?code=c0de&state={state}")
    assert r.status_code == 400
    with client.session_transaction() as sess:
        assert "discord_user" not in sess


def test_callback_crash_does_not_leak_traceback(client, discord_configured, monkeypatch):
    class Boom:
        def post(self, *a, **k):
            raise RuntimeError("detail interne csecret")

    monkeypatch.setattr(auth_mod, "req", Boom())
    state = _login_state(client)
    r = client.get(f"{BASE}/auth/callback?code=c0de&state={state}")
    assert r.status_code == 500
    text = r.get_data(as_text=True)
    assert "Traceback" not in text and "csecret" not in text and "detail interne" not in text
    body = r.get_json()
    assert body["ok"] is False and "trace" not in body


def test_login_missing_config_does_not_leak_value(client, monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "discord_client_id", "")
    r = client.get(f"{BASE}/auth/login")
    assert r.status_code == 500
    body = r.get_json()
    assert body["ok"] is False
    assert "value" not in body and "trace" not in body


def test_token_exchange_failure_does_not_echo_discord_body(client, discord_configured, http):
    http.token_resp = FakeResp(400, text='{"error": "invalid_grant", "secret": "csecret"}')
    state = _login_state(client)
    r = client.get(f"{BASE}/auth/callback?code=c0de&state={state}")
    assert r.status_code == 400
    assert "csecret" not in r.get_data(as_text=True)
    assert r.get_json()["error"] == "token_exchange_failed"
