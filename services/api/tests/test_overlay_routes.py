"""Blueprint /overlay/* (spec 2026-11-25 §3.4) : parcours par code d'appareil (RFC 8628) pour tout compte connecté,
jetons listés et révocables par leur seul propriétaire, serveurs lus chez le bot. L'identité vient de la session ou
du jeton, jamais du corps ; Redis coupé donne 503 STORAGE_UNAVAILABLE, jamais 401.
"""
from __future__ import annotations

import api.routes.overlay as overlay_mod
import api.services.overlay_tokens as ot
import pytest
import redis
from api import web_url
from api.services import authz
from conftest import FakeSendCommand
from greg_shared.config import settings
from overlay_fakes import overlay_redis, issue_token  # noqa: F401

BASE = "/api/v1"
GUILD42 = {"id": "42", "name": "Taverne", "icon_url": None, "greg_voice": None, "user_voice": None, "playing": False}

@pytest.fixture()
def bot(monkeypatch):
    fake = FakeSendCommand({"ok": True, "guilds": [GUILD42]}); monkeypatch.setattr(overlay_mod, "send_command", fake)
    return fake

def start(client, **body): return client.post(f"{BASE}/overlay/device", json=body).get_json()
def approve(c, code, **kw): return c.post(f"{BASE}/overlay/device/approve", json={"user_code": code, "decision": "approve", **kw})

def test_device_start_shape(client, overlay_redis):
    d = start(client, client_name="GregLC")
    assert set(d) == {"ok", "device_code", "user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval"}
    assert d["verification_uri"] == web_url().rstrip("/") + "/lier"
    assert d["verification_uri_complete"] == web_url().rstrip("/") + "/lier?code=" + d["user_code"]
    assert (d["expires_in"], d["interval"]) == (600, 5)

def test_verification_uri_never_doubles_the_slash(client, overlay_redis, monkeypatch):
    monkeypatch.setenv("WEB_URL", "https://greg.example/")
    d = start(client)
    assert d["verification_uri"] == "https://greg.example/lier"
    assert d["verification_uri_complete"] == "https://greg.example/lier?code=" + d["user_code"]

@pytest.mark.parametrize("name", ["x" * 41, 12, ["a"]])
def test_device_start_rejects_bad_names(client, overlay_redis, name):
    r = client.post(f"{BASE}/overlay/device", json={"client_name": name})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "INVALID_REQUEST"}

def start_from(client, addr): return client.post(f"{BASE}/overlay/device", json={}, environ_base={"REMOTE_ADDR": addr}).status_code

def test_device_start_rate_limits(client, overlay_redis):
    codes = [client.post(f"{BASE}/overlay/device", json={}).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    assert client.post(f"{BASE}/overlay/device", json={}).get_json() == {"ok": False, "error": "RATE_LIMITED"}
    total = [start_from(client, f"10.0.{i // 250}.{i % 250}") for i in range(300)]
    assert total == [200] * 295 + [429] * 5                      # plafond global de 300 par heure, dont 5 déjà pris ci-dessus

def test_one_ip_never_exhausts_the_global_bucket(client, overlay_redis):
    admitted = []
    for minute in range(61):                                     # plus d'une heure, une fenêtre d'une minute après l'autre
        codes = [start_from(client, "203.0.113.7") for _ in range(6)]           # toujours au-delà de son seau par minute
        admitted.append(codes.count(200))
        assert start_from(client, f"198.51.100.{minute}") == 200                  # une autre IP passe toujours
        if minute == 0:
            assert overlay_redis.get("greg:ratelimit:device_start:all") == "6"    # refusées par IP : jamais comptées
        overlay_redis.now += 61
    assert admitted == [5] * 4 + [0] * 56 + [5]                  # 20 par heure au plus, puis l'heure suivante repart

def test_device_start_hourly_bucket_per_ip(client, overlay_redis):
    for _ in range(4):
        assert [start_from(client, "203.0.113.7") for _ in range(5)] == [200] * 5; overlay_redis.now += 61
    r = client.post(f"{BASE}/overlay/device", json={}, environ_base={"REMOTE_ADDR": "203.0.113.7"})
    assert r.status_code == 429 and r.get_json() == {"ok": False, "error": "RATE_LIMITED"}   # la 21e de l'heure
    assert overlay_redis.get("greg:ratelimit:device_start:all") == "20"
    assert start_from(client, "203.0.113.8") == 200

def test_device_start_counts_an_ipv6_by_its_64(client, overlay_redis):
    assert [start_from(client, f"2001:db8:1:2::{i:x}") for i in range(1, 7)] == [200] * 5 + [429]   # un même /64
    assert start_from(client, "2001:db8:1:3::1") == 200                                           # un autre /64

@pytest.mark.parametrize("addr,subject", [("203.0.113.7", "203.0.113.7"), ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
    ("2001:DB8:1:2::1", "2001:db8:1:2::/64"), ("::ffff:203.0.113.7", "203.0.113.7"), ("pas-une-ip", "pas-une-ip"),
    ("", "unknown"), (None, "unknown")])
def test_ip_subject(addr, subject):
    assert overlay_mod.ip_subject(addr) == subject

@pytest.mark.parametrize("path", ["/overlay/device", "/overlay/token"])
@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded"])
def test_device_and_token_require_json_before_any_counter(client, overlay_redis, path, ctype):
    r = client.post(f"{BASE}{path}", data='{"device_code": "x", "client_name": "x"}', content_type=ctype)
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "INVALID_REQUEST"}
    assert overlay_redis.kv == {}                                                # ni compteur greg:ratelimit:*, ni appareil

def test_lookup_needs_a_session_only(app, client, logged_client, login, overlay_redis):
    code = start(client, client_name="GregLC")["user_code"]
    want = {"ok": True, "client_name": "GregLC", "created_at": 1_800_000_000, "expires_in": 600}
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}").get_json() == want
    assert login(app.test_client(), 888).get(f"{BASE}/overlay/device/lookup?user_code={code}").get_json() == want
    assert app.test_client().get(f"{BASE}/overlay/device/lookup?user_code={code}").status_code == 401
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code=nope").status_code == 400
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code=BCDF-GHJK").get_json() == {"ok": False, "error": "CODE_EXPIRED"}

def test_lookup_is_rate_limited_per_account_before_reading_the_code(app, client, logged_client, login, overlay_redis):
    code = start(client)["user_code"]
    assert [logged_client.get(f"{BASE}/overlay/device/lookup?user_code=BCDF-GHJK").status_code for _ in range(30)] == [404] * 30
    reads = len(overlay_redis.log)
    r = logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}")
    assert r.status_code == 429 and r.get_json() == {"ok": False, "error": "RATE_LIMITED"}        # la 31e de la minute
    assert not [c for c in overlay_redis.log[reads:] if c[0] == "GET"]                            # le code n'est pas lu
    assert login(app.test_client(), 888).get(f"{BASE}/overlay/device/lookup?user_code={code}").status_code == 200
    overlay_redis.now += 61
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}").status_code == 200

def test_any_logged_in_user_links_its_own_account(app, client, logged_client, login, bot, overlay_redis, monkeypatch):
    monkeypatch.setattr(settings, "greg_owner_id", "999")                        # GREG_OWNER_ID ne joue aucun rôle
    other = login(app.test_client(), 888)
    d1, d2 = start(client, client_name="PC 777"), start(client, client_name="PC 888")
    assert approve(logged_client, d1["user_code"], guild_id="42").get_json() == {"ok": True}
    assert approve(other, d2["user_code"], guild_id="42").get_json() == {"ok": True}
    assert [c["user_id"] for c in bot.calls] == [777, 888]                       # serveurs de celui qui autorise
    overlay_redis.now += 5
    t1, t2 = (client.post(f"{BASE}/overlay/token", json={"device_code": d["device_code"]}).get_json() for d in (d1, d2))
    assert (t1["user"]["id"], t2["user"]["id"]) == ("777", "888")
    assert (ot.resolve(t1["access_token"]).uid, ot.resolve(t2["access_token"]).uid) == (777, 888)
    assert [r.label for r in ot.list_tokens(777)] == ["PC 777"] and [r.label for r in ot.list_tokens(888)] == ["PC 888"]
    assert [t["label"] for t in other.get(f"{BASE}/overlay/tokens").get_json()["tokens"]] == ["PC 888"]   # pas de croisement

def test_approve_then_token_ignores_identity_in_the_body(client, logged_client, bot, overlay_redis):
    d = start(client, client_name="GregLC")
    r = approve(logged_client, d["user_code"], guild_id="42", uid="999", user_id="999", user={"id": "999", "username": "pirate"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert bot.calls == [{"action": "user_guilds", "guild_id": 0, "user_id": 777, "data": None, "timeout": 5}]
    overlay_redis.now += 5
    t = client.post(f"{BASE}/overlay/token", json={"device_code": d["device_code"]}).get_json()
    assert t["ok"] is True and t["token_type"] == "Bearer" and t["expires_in"] == 15_552_000
    assert t["access_token"].startswith("greg_ow_") and t["default_guild_id"] == "42"
    assert t["user"] == {"id": "777", "username": "greg-fan", "global_name": None, "avatar": None}   # la session, jamais le corps
    assert ot.resolve(t["access_token"]).uid == 777 and ot.list_tokens(999) == []

def test_approve_csrf_and_guild_checks_keep_the_code(app, client, logged_client, bot, overlay_redis):
    code = start(client)["user_code"]
    form = logged_client.post(f"{BASE}/overlay/device/approve", data=f"user_code={code}&decision=approve",
                              content_type="application/x-www-form-urlencoded", headers={"Origin": "https://evil.example"})
    assert form.status_code == 403 and form.get_json()["error"] == "CSRF_FAILED"
    assert approve(app.test_client(), code).status_code == 401                    # sans session
    bot.result = {"ok": True, "guilds": []}
    assert approve(logged_client, code, guild_id="43").get_json()["error"] == "NOT_GUILD_MEMBER"
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}").status_code == 200   # pas consommé

@pytest.mark.parametrize("body", [{"user_code": "nope", "decision": "approve"}, {"user_code": "BCDF-GHJK", "decision": "oui"},
                                  {"user_code": "BCDF-GHJK", "decision": "approve", "guild_id": "abc"}])
def test_approve_invalid_bodies(logged_client, bot, overlay_redis, body):
    r = logged_client.post(f"{BASE}/overlay/device/approve", json=body)
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "INVALID_REQUEST"}

def test_approve_expired_used_and_rate_limited(app, client, logged_client, login, bot, overlay_redis):
    assert approve(logged_client, "BCDF-GHJK").status_code == 404
    code = start(client)["user_code"]
    assert approve(logged_client, code).status_code == 200
    r = approve(logged_client, code); assert r.status_code == 409 and r.get_json()["error"] == "ALREADY_USED"
    statuses = [approve(logged_client, "BCDF-GHJK").status_code for _ in range(4)]
    assert statuses[-1] == 429                                                    # 5 par minute et par uid
    assert approve(login(app.test_client(), 888), "BCDF-GHJK").status_code == 404  # un autre uid a son propre seau

def test_deny_then_access_denied(client, logged_client, overlay_redis):
    d = start(client)
    logged_client.post(f"{BASE}/overlay/device/approve", json={"user_code": d["user_code"], "decision": "deny"})
    r = client.post(f"{BASE}/overlay/token", json={"device_code": d["device_code"]})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "access_denied"}

def test_token_errors_follow_rfc8628(client, overlay_redis):
    d = start(client)
    poll = lambda body: client.post(f"{BASE}/overlay/token", json=body).get_json()["error"]
    assert poll({"device_code": d["device_code"]}) == "authorization_pending"
    assert poll({"device_code": d["device_code"]}) == "slow_down"
    assert poll({"device_code": "inconnu"}) == poll({}) == poll({"device_code": 5}) == "expired_token"

def test_me_tokens_revoke_and_logout(client, logged_client, overlay_redis, issue_token):
    tok = issue_token(); h = {"Authorization": f"Bearer {tok}"}
    me = client.get(f"{BASE}/overlay/me", headers=h).get_json()
    assert (me["via"], me["default_guild_id"], me["user"]["id"]) == ("overlay", "42", "777")
    sme = logged_client.get(f"{BASE}/overlay/me").get_json()
    assert (sme["via"], sme["default_guild_id"], sme["user"]["id"]) == ("session", None, "777")
    assert set(me) == set(sme) == {"ok", "via", "user", "default_guild_id"}                # pas d'is_owner
    [row] = client.get(f"{BASE}/overlay/tokens", headers=h).get_json()["tokens"]
    assert set(row) == {"id", "label", "created_at", "last_used_at", "expires_at", "current"} and row["current"] is True
    assert logged_client.get(f"{BASE}/overlay/tokens").get_json()["tokens"][0]["current"] is False
    assert client.post(f"{BASE}/overlay/tokens/revoke", json={"id": "autre"}, headers=h).status_code == 404
    form = logged_client.post(f"{BASE}/overlay/tokens/revoke", data=f"id={row['id']}",
                              content_type="application/x-www-form-urlencoded", headers={"Origin": "https://evil.example"})
    assert form.status_code == 403
    assert logged_client.post(f"{BASE}/overlay/tokens/revoke", json={"id": row["id"]}).get_json() == {"ok": True}
    assert client.get(f"{BASE}/overlay/me", headers=h).status_code == 401

def test_bearer_revokes_itself_and_logout(client, logged_client, overlay_redis, issue_token):
    a, b = issue_token(), issue_token()
    assert logged_client.post(f"{BASE}/overlay/logout", json={}).status_code == 401   # session seule : refusé
    assert client.post(f"{BASE}/overlay/logout", json={}, headers={"Authorization": f"Bearer {a}"}).get_json() == {"ok": True}
    assert client.get(f"{BASE}/overlay/me", headers={"Authorization": f"Bearer {a}"}).status_code == 401
    tid = ot.resolve(b).tid
    assert client.post(f"{BASE}/overlay/tokens/revoke", json={"id": tid},
                       headers={"Authorization": f"Bearer {b}"}).get_json() == {"ok": True}

def test_session_revokes_only_its_own_tokens(app, client, logged_client, login, overlay_redis, issue_token):
    mine, theirs = issue_token(uid=777), issue_token(uid=888)
    my_tid, their_tid = ot.resolve(mine).tid, ot.resolve(theirs).tid
    r = logged_client.post(f"{BASE}/overlay/tokens/revoke", json={"id": their_tid})
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "NOT_FOUND"}
    r = client.post(f"{BASE}/overlay/tokens/revoke", json={"id": their_tid}, headers={"Authorization": f"Bearer {mine}"})
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "NOT_FOUND"}   # un porteur : lui-même seulement
    assert ot.is_live(888, their_tid) and ot.is_live(777, my_tid)
    assert [t["id"] for t in logged_client.get(f"{BASE}/overlay/tokens").get_json()["tokens"]] == [my_tid]
    other = login(app.test_client(), 888)
    assert other.post(f"{BASE}/overlay/tokens/revoke", json={"id": their_tid}).get_json() == {"ok": True}
    assert not ot.is_live(888, their_tid) and ot.is_live(777, my_tid)

def test_guilds_come_from_the_bot(client, bot, overlay_redis, issue_token):
    r = client.get(f"{BASE}/overlay/guilds", headers={"Authorization": f"Bearer {issue_token(uid=4242)}"})
    assert r.get_json() == {"ok": True, "guilds": [GUILD42]}
    assert bot.calls[-1] == {"action": "user_guilds", "guild_id": 0, "user_id": 4242, "data": None, "timeout": 5}
    bot.result = {"ok": False, "error": "BOT_OFFLINE", "message": "Greg est hors ligne."}
    assert client.get(f"{BASE}/overlay/guilds", headers={"Authorization": f"Bearer {issue_token()}"}).status_code == 503

STORAGE_UNAVAILABLE = {"ok": False, "error": "STORAGE_UNAVAILABLE", "message": ot.MSG_STORAGE_UNAVAILABLE}

@pytest.mark.parametrize("method,path,body", [
    ("post", "/overlay/device", {}), ("post", "/overlay/token", {"device_code": "x"}), ("get", "/overlay/me", None),
    ("get", "/overlay/tokens", None), ("post", "/overlay/tokens/revoke", {"id": "x"}), ("post", "/overlay/logout", {}),
    ("get", "/overlay/guilds", None)])
def test_redis_down_with_a_bearer_is_503_never_401(client, bot, overlay_redis, issue_token, method, path, body):
    h = {"Authorization": f"Bearer {issue_token()}"}
    overlay_redis.fail = redis.ConnectionError("coupé")                         # l'appli effacerait son jeton sur un 401
    r = getattr(client, method)(f"{BASE}{path}", json=body, headers=h)
    assert r.status_code == 503 and r.get_json() == STORAGE_UNAVAILABLE

def test_require_bearer_itself_turns_redis_down_into_503(app, overlay_redis, issue_token):
    tok = issue_token(); overlay_redis.fail = redis.ConnectionError("coupé")   # sans le gestionnaire du blueprint
    with app.test_request_context(headers={"Authorization": f"Bearer {tok}"}):
        resp, status = authz.require_bearer(lambda: "vue")()
        assert status == 503 and resp.get_json() == STORAGE_UNAVAILABLE

def test_redis_down_on_the_session_routes_is_503(logged_client, bot, overlay_redis):
    overlay_redis.fail = redis.ConnectionError("coupé")
    r = logged_client.get(f"{BASE}/overlay/device/lookup?user_code=BCDF-GHJK")
    assert r.status_code == 503 and r.get_json() == STORAGE_UNAVAILABLE
    r = approve(logged_client, "BCDF-GHJK")
    assert r.status_code == 503 and r.get_json() == STORAGE_UNAVAILABLE
