"""Identité « session ou jeton porteur » (spec 2026-11-25 §3.1) sur le lecteur, l'historique et la recherche :
le porteur l'emporte sur le cookie, un en-tête `Authorization` invalide ne se rabat jamais sur le cookie, les
requêtes porteuses passent la garde CSRF, Redis coupé donne 503 (jamais 401), le chansonnier reste en session seule.
"""
from __future__ import annotations

import api.routes.search as search_mod
import api.services.overlay_tokens as ot
import flask
import pytest
import redis
from api.services import authz
from overlay_fakes import overlay_redis, issue_token  # noqa: F401
from test_authz import GUILD_ROUTES, NOT_AUTHENTICATED_BODY, _IDS, _call

BASE = "/api/v1"
def bearer(tok): return {"Authorization": f"Bearer {tok}"}

@pytest.mark.parametrize("method,path,body", GUILD_ROUTES, ids=_IDS)
def test_every_guild_route_accepts_a_bearer(client, fake_send, issue_token, method, path, body):
    fake_send.result = {"ok": True, "state": {"current": None, "queue": []}}
    _call(client, method, path, body, headers=bearer(issue_token(uid=4242)))
    assert fake_send.calls and all(c["user_id"] == 4242 for c in fake_send.calls)

def test_bearer_wins_over_the_cookie(logged_client, fake_send, issue_token):
    logged_client.post(f"{BASE}/queue/skip", json={"guild_id": "5"}, headers=bearer(issue_token(uid=4242)))
    assert fake_send.calls[-1]["user_id"] == 4242

@pytest.mark.parametrize("value", ["Bearer greg_ow_nope", "Bearer ", "Basic abc", "bearer", "Token greg_ow_x", ""])
def test_bad_authorization_never_falls_back_to_the_cookie(logged_client, fake_send, overlay_redis, value):
    r = logged_client.post(f"{BASE}/queue/skip", json={"guild_id": "5"}, headers={"Authorization": value})
    assert r.status_code == 401 and r.get_json() == NOT_AUTHENTICATED_BODY and fake_send.calls == []

def test_bearer_requests_skip_csrf(client, fake_send, issue_token):
    r = client.post(f"{BASE}/queue/skip", json={"guild_id": "5"},
                    headers={**bearer(issue_token()), "Origin": "https://evil.example"})
    assert r.status_code == 200

def test_revoked_token_is_401(client, fake_send, issue_token):
    tok = issue_token(); rec = ot.resolve(tok); ot.revoke(rec.uid, rec.tid)
    assert client.get(f"{BASE}/playlist?guild_id=5", headers=bearer(tok)).status_code == 401

def test_redis_down_on_bearer_is_503_never_401(client, fake_send, issue_token, overlay_redis):  # Review Focus 1
    tok = issue_token(); overlay_redis.fail = redis.ConnectionError("down")
    r = client.post(f"{BASE}/queue/skip", json={"guild_id": "5"}, headers=bearer(tok))
    assert r.status_code == 503 and r.get_json()["error"] == "STORAGE_UNAVAILABLE" and fake_send.calls == []

def test_identity_is_resolved_once_per_request(app, issue_token, monkeypatch):
    tok = issue_token(uid=4242); seen = []; real = ot.resolve
    monkeypatch.setattr(ot, "resolve", lambda t: seen.append(t) or real(t))
    with app.test_request_context("/", headers=bearer(tok)):
        assert authz.current_identity() == authz.current_identity()
        assert authz.current_identity().via == "overlay" and authz.current_user_id() == 4242
    assert len(seen) == 1

def test_socket_context_ignores_the_header_and_reads_the_socket_identity(app, overlay_redis):
    with app.test_request_context("/", headers=bearer("greg_ow_nope")):
        flask.request.sid = "sid-1"; flask.session["discord_user"] = {"id": "777"}
        assert authz.current_identity() == authz.Identity(777, "session")
        flask.session["_ident"] = {"via": "overlay", "uid": 4242, "tid": "t1"}
        assert authz.current_identity() == authz.Identity(4242, "overlay", "t1")  # rien en cache

def test_search_requires_identity_and_clamps_limit(client, issue_token, monkeypatch):
    limits = []
    monkeypatch.setattr(search_mod, "_innertube_search", lambda q, limit=8: limits.append(limit) or [{"title": "t"}])
    assert client.get(f"{BASE}/search/autocomplete?q=abba").status_code == 401
    assert client.get(f"{BASE}/search/suggest?q=abba").status_code == 401
    for lim in ("50", "0", "-4", "7"):
        assert client.get(f"{BASE}/search/autocomplete?q=abba&limit={lim}", headers=bearer(issue_token())).status_code == 200
    assert limits == [10, 1, 1, 7]

def test_library_stays_session_only(client, issue_token):
    assert client.get(f"{BASE}/library", headers=bearer(issue_token())).status_code == 401

def test_session_only_route_refuses_an_authorization_header_even_with_a_cookie(logged_client):
    r = logged_client.get(f"{BASE}/library", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401 and r.get_json() == NOT_AUTHENTICATED_BODY
