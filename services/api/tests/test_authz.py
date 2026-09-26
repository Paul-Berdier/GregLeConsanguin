"""SEC-C1 — l'identité vient UNIQUEMENT de la session Discord (jamais du corps ni de X-User-ID).

Toute route qui lit / agit sur une guild : 401 NOT_AUTHENTICATED sans session, l'id de session
est transmis au bot pour chaque commande, NOT_GUILD_MEMBER du bot → 403.
"""
from __future__ import annotations

import pytest

BASE = "/api/v1"

NOT_AUTHENTICATED_BODY = {
    "ok": False,
    "error": "NOT_AUTHENTICATED",
    "message": "Connecte-toi avec Discord pour contrôler Greg.",
}

# (méthode, chemin, corps JSON) — toutes les routes qui lisent ou pilotent une guild.
GUILD_ROUTES = [
    ("get", "/player/state?guild_id=5", None),
    ("get", "/playlist?guild_id=5", None),
    ("post", "/player/enqueue", {"query": "x"}),
    ("post", "/queue/add", {"query": "x"}),
    ("post", "/player/skip", {}),
    ("post", "/queue/skip", {}),
    ("post", "/player/stop", {}),
    ("post", "/queue/stop", {}),
    ("post", "/player/pause", {}),
    ("post", "/playlist/toggle_pause", {}),
    ("post", "/player/repeat", {"mode": "toggle"}),
    ("post", "/playlist/repeat", {}),
    ("post", "/player/move", {"src": 1, "dst": 0}),
    ("delete", "/player/queue/1", {}),
    ("post", "/queue/remove", {"index": 1}),
    ("post", "/playlist/play_at", {"index": 1}),
    ("post", "/playlist/restart", {}),
    ("post", "/voice/join", {}),
    ("get", "/history?guild_id=5", None),
    ("get", "/history/top?guild_id=5", None),
    ("get", "/history/recent?guild_id=5", None),
]
_IDS = [f"{m} {p}" for m, p, _ in GUILD_ROUTES]


def _call(client, method, path, body, headers=None):
    kw = {"headers": headers or {}}
    if body is not None:
        kw["json"] = {"guild_id": "5", **body}
    return getattr(client, method)(f"{BASE}{path}", **kw)


# ── session_user_id ──

@pytest.mark.parametrize("user,expected", [
    ({"id": "123456789012345678"}, 123456789012345678),
    ({"id": 42}, 42),
    ({"id": "abc"}, None),
    ({"id": ""}, None),
    ({"id": "0"}, None),
    ({"username": "sans id"}, None),
    ("pas un dict", None),
    (None, None),
])
def test_session_user_id(app, user, expected):
    from flask import session

    from api.services.authz import session_user_id

    with app.test_request_context("/"):
        if user is not None:
            session["discord_user"] = user
        assert session_user_id() == expected


# ── 401 sans session, sur TOUTES les routes de guild ──

@pytest.mark.parametrize("method,path,body", GUILD_ROUTES, ids=_IDS)
def test_guild_route_without_session_is_401(client, fake_send, method, path, body):
    # Le corps et X-User-ID ne suffisent pas à s'identifier.
    extra = dict(body or {}, user_id="456")
    r = _call(client, method, path, extra if body is not None else None,
              headers={"X-User-ID": "456"})
    assert r.status_code == 401
    assert r.get_json() == NOT_AUTHENTICATED_BODY
    assert fake_send.calls == []


# ── Usurpation : user_id du corps / X-User-ID ignorés, id de session transmis ──

@pytest.mark.parametrize("method,path,body", GUILD_ROUTES, ids=_IDS)
def test_body_and_header_user_id_are_ignored(logged_client, fake_send, monkeypatch, session_uid,
                                             method, path, body):
    fake_send.result = {"ok": True, "state": {"current": {"title": "T", "artist": "A"},
                                              "queue": [{"title": "Q", "artist": "B"}]}}
    victim = "111111111111111111"
    extra = dict(body or {}, user_id=victim)
    _call(logged_client, method, path, extra if body is not None else None,
          headers={"X-User-ID": victim})

    assert fake_send.calls, "la route n'a rien envoyé au bot"
    for call in fake_send.calls:
        assert call["user_id"] == session_uid
        assert call["guild_id"] == 5


# ── NOT_GUILD_MEMBER (vérifié par le bot, SEC-C2) → 403 ──

@pytest.mark.parametrize("method,path,body", GUILD_ROUTES, ids=_IDS)
def test_not_guild_member_is_403(logged_client, fake_send, monkeypatch, method, path, body):
    fake_send.result = {"ok": False, "error": "NOT_GUILD_MEMBER",
                        "message": "Tu n'es pas membre de ce serveur."}
    r = _call(logged_client, method, path, body)
    assert r.status_code == 403
    out = r.get_json()
    assert out["ok"] is False
    assert out["error"] == "NOT_GUILD_MEMBER"
    assert out["message"] == "Tu n'es pas membre de ce serveur."


@pytest.mark.parametrize("error,status", [("NOT_AUTHENTICATED", 401), ("NOT_GUILD_MEMBER", 403),
                                          ("PRIORITY_FORBIDDEN", 403), ("TIMEOUT", 504),
                                          ("BOT_OFFLINE", 503), ("AUTRE", 409)])
def test_error_status_mapping(error, status):
    from api.routes.player import error_status

    assert error_status({"ok": False, "error": error}) == status
