import pytest
from api.services.authz import MSG_CSRF_FAILED

BASE = "/api/v1"
EVIL = "https://evil.example"
CSRF_BODY = {"ok": False, "error": "CSRF_FAILED", "message": MSG_CSRF_FAILED}
# Formulaire tiers (guild_id dans l'URL) : passait avant le correctif (spec §3.2)
FORM_TARGETS = [("post", "/player/skip"), ("post", "/queue/skip"), ("post", "/player/stop"), ("post", "/queue/stop"),
                ("post", "/player/pause"), ("post", "/playlist/toggle_pause"), ("post", "/player/repeat"),
                ("post", "/playlist/repeat"), ("post", "/playlist/restart"), ("post", "/voice/join"),
                ("post", "/playlist/play_at"), ("post", "/queue/remove"), ("post", "/player/move"),
                ("delete", "/player/queue/0"), ("post", "/queue/add")]

@pytest.mark.parametrize("method,path", FORM_TARGETS)
def test_cross_site_form_is_refused_before_the_bot(logged_client, fake_send, method, path):
    r = getattr(logged_client, method)(f"{BASE}{path}?guild_id=5", data="src=1&dst=0&index=0&query=x",
                                       content_type="application/x-www-form-urlencoded", headers={"Origin": EVIL})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY
    assert fake_send.calls == []

def test_text_plain_body_is_refused_even_without_origin(logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/skip?guild_id=5", data='{"guild_id": "5"}', content_type="text/plain")
    assert r.status_code == 403 and fake_send.calls == []

@pytest.mark.parametrize("origin", [EVIL, "null", "https://greg-le-consanguin.up.railway.app.evil.example"])
def test_json_from_a_foreign_or_null_origin_is_refused(logged_client, fake_send, origin):
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Origin": origin})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY and fake_send.calls == []

def test_json_from_the_site_is_accepted(app, logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Origin": app.config["WEB_ORIGINS"][0]})
    assert r.status_code == 200 and fake_send.calls[-1]["action"] == "skip"

def test_json_without_origin_nor_referer_is_accepted(logged_client, fake_send):
    assert logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}).status_code == 200

def test_referer_is_checked_when_origin_is_absent(app, logged_client, fake_send):
    web = app.config["WEB_ORIGINS"][0]
    assert logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"},
                              headers={"Referer": f"{web}/lier?code=BCDF-GHJK"}).status_code == 200
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Referer": f"{EVIL}/page"})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY

def test_safe_methods_are_never_checked(logged_client, fake_send):
    fake_send.result = {"ok": True, "state": {"queue": []}}
    assert logged_client.get(f"{BASE}/playlist?guild_id=5", headers={"Origin": EVIL}).status_code == 200

def test_without_session_identity_still_comes_first(client, fake_send):
    r = client.post(f"{BASE}/player/skip?guild_id=5", data="a=1", content_type="application/x-www-form-urlencoded",
                    headers={"Origin": EVIL})
    assert r.status_code == 401 and r.get_json()["error"] == "NOT_AUTHENTICATED"

def test_logout_form_from_another_site_keeps_the_session(logged_client):
    r = logged_client.post(f"{BASE}/auth/logout", data="x=1", content_type="application/x-www-form-urlencoded",
                           headers={"Origin": EVIL})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY
    with logged_client.session_transaction() as s:
        assert s["discord_user"]["id"] == "777"

def test_logout_json_from_the_site_clears_the_session(app, logged_client):
    r = logged_client.post(f"{BASE}/auth/logout", json={}, headers={"Origin": app.config["WEB_ORIGINS"][0]})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    with logged_client.session_transaction() as s:
        assert "discord_user" not in s

@pytest.mark.parametrize("method,ctype,headers,expected", [
    ("GET", None, {"Origin": EVIL}, True), ("OPTIONS", None, {"Origin": EVIL}, True),
    ("POST", "application/json", {}, True), ("POST", "application/json", {"Origin": "{web}"}, True),
    ("POST", "application/json", {"Origin": "{web}/"}, True), ("POST", "application/json", {"Origin": EVIL}, False),
    ("POST", "application/json", {"Origin": "null"}, False), ("POST", "text/plain", {}, False),
    ("POST", "application/x-www-form-urlencoded", {"Origin": "{web}"}, False),
    ("DELETE", "application/json", {"Referer": "{web}/x"}, True), ("PUT", "application/json", {"Referer": EVIL}, False),
])
def test_csrf_ok_rules(app, method, ctype, headers, expected):
    from api.services.authz import csrf_ok
    web = app.config["WEB_ORIGINS"][0]
    hdrs = {k: v.replace("{web}", web) for k, v in headers.items()}
    with app.test_request_context("/", method=method, content_type=ctype, data="{}" if ctype else None, headers=hdrs):
        assert csrf_ok() is expected
