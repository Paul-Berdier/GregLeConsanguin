"""CORS (SEC-C5) — seules les origines du front (CORS_ORIGINS ∪ WEB_URL) sont autorisées,
pour les routes HTTP (flask-cors, avec cookies) comme pour Socket.IO (engine.io)."""
from __future__ import annotations

import pytest

import api
from api import socketio

BASE = "/api/v1"
FOREIGN = "https://evil.example"


@pytest.fixture()
def clean_env(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("WEB_URL", raising=False)
    monkeypatch.setattr(api.settings, "web_url", "")


def test_default_origin_is_the_public_web_url(clean_env):
    assert api.cors_origins() == ["https://greg-le-consanguin.up.railway.app"]


def test_origins_are_normalized_and_deduplicated(clean_env, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:3001/ ,https://Foo.Example.com/app/x,"
                                       "https://web.example:443,, http://[::1]:3000 ")
    monkeypatch.setenv("WEB_URL", "https://web.example/")
    assert api.cors_origins() == [
        "http://localhost:3001",
        "https://foo.example.com",
        "https://web.example",
        "http://[::1]:3000",
    ]


@pytest.mark.parametrize("bad", ["*", "localhost:3001", "ftp://files.example", "https://", "null"])
def test_invalid_or_wildcard_origins_are_ignored(clean_env, monkeypatch, bad):
    monkeypatch.setenv("CORS_ORIGINS", bad)
    assert api.cors_origins() == ["https://greg-le-consanguin.up.railway.app"]


def test_web_url_env_wins_over_settings(clean_env, monkeypatch):
    monkeypatch.setattr(api.settings, "web_url", "https://from-settings.example")
    assert api.cors_origins() == ["https://from-settings.example"]
    monkeypatch.setenv("WEB_URL", "http://localhost:3001")
    assert api.cors_origins() == ["http://localhost:3001"]
    assert api.web_url() == "http://localhost:3001"


# ── Application réelle ──

def test_app_uses_the_same_list_for_http_and_socketio(app):
    origins = app.config["ALLOWED_ORIGINS"]
    assert origins and "*" not in origins
    assert socketio.server.eio.cors_allowed_origins == origins


def test_allowed_origin_is_echoed_with_credentials(app, client):
    origin = app.config["ALLOWED_ORIGINS"][0]
    r = client.get(f"{BASE}/health", headers={"Origin": origin})
    assert r.headers.get("Access-Control-Allow-Origin") == origin
    assert r.headers.get("Access-Control-Allow-Credentials") == "true"


def test_foreign_origin_is_not_echoed(client):
    r = client.get(f"{BASE}/health", headers={"Origin": FOREIGN})
    assert r.status_code == 200  # la requête passe, mais le navigateur n'aura pas la réponse
    assert "Access-Control-Allow-Origin" not in r.headers
    assert "Access-Control-Allow-Credentials" not in r.headers


def test_preflight_on_guild_route_is_not_blocked_by_auth(app, client, fake_send):
    # Un preflight n'envoie jamais de cookie : il ne doit pas finir en 401.
    origin = app.config["ALLOWED_ORIGINS"][0]
    r = client.options(f"{BASE}/queue/add", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert 200 <= r.status_code < 300
    assert r.headers.get("Access-Control-Allow-Origin") == origin
    assert fake_send.calls == []


def test_socketio_handshake_rejects_foreign_origin(client):
    r = client.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": FOREIGN})
    assert r.status_code == 400
    assert "Access-Control-Allow-Origin" not in r.headers


def test_socketio_handshake_accepts_web_origin(app, client):
    origin = app.config["ALLOWED_ORIGINS"][0]
    r = client.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") == origin
