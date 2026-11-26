"""overlay_tokens — magasin Redis des codes d'appareil et des jetons de l'appli Overwolf (spec 2026-11-25 §3.4) :
parcours RFC 8628 (usage unique, slow_down, refus, expiration), jetons porteurs (dernière utilisation, liste,
révocation), limites de débit, Redis coupé.
"""
from __future__ import annotations

import re

import api.services.overlay_tokens as ot
import pytest
import redis
from overlay_fakes import overlay_redis, issue_token  # noqa: F401

T0 = 1_800_000_000

DEV = "greg:overlay:device:"; IDX = "greg:overlay:user_code:"; TOK = "greg:overlay:token:"; TOKS = "greg:overlay:tokens:"
USER = {"id": "777", "username": "paul", "global_name": "Paul", "avatar": None}

def _approved(fr, guild_id="42"):
    d = ot.start_device("GregLC"); ot.poll(d.device_code); fr.now += 5
    ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=guild_id)
    return d

def test_start_device_shape_and_ttls(overlay_redis):
    d = ot.start_device("GregLC")
    assert re.fullmatch(r"[BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}", d.user_code)
    assert (d.expires_in, d.interval) == (600, 5) and len(d.device_code) >= 43
    assert overlay_redis.ttl(DEV + ot.hash_secret(d.device_code)) == 600
    assert overlay_redis.ttl(IDX + d.user_code.replace("-", "")) == 600
    assert d.device_code not in repr(overlay_redis.kv)          # jamais en clair

@pytest.mark.parametrize("raw,code", [("bcdf-ghjk", "BCDFGHJK"), ("BCDF GHJK", "BCDFGHJK"), (" bcdfghjk ", "BCDFGHJK"),
    ("BCDF—GHJK", "BCDFGHJK"), ("BCDF-GHJ", None), ("BCDF-GHJA", None), ("", None), (None, None), (12345678, None)])
def test_normalize_user_code(raw, code):
    assert ot.normalize_user_code(raw) == code

def test_user_code_collision_draws_another(overlay_redis, monkeypatch):
    overlay_redis.set(IDX + "BCDFGHJK", "x", ex=600)
    draws = iter(["BCDFGHJK", "BCDFGHJL"]); monkeypatch.setattr(ot, "_draw_user_code", lambda: next(draws))
    assert ot.start_device("GregLC").user_code == "BCDF-GHJL"

def test_lookup_returns_name_age_and_remaining_time(overlay_redis):
    d = ot.start_device("GregLC"); overlay_redis.now += 100
    assert ot.lookup_user_code(d.user_code.lower()) == {"client_name": "GregLC", "created_at": T0, "expires_in": 500}
    assert ot.lookup_user_code("BCDF-GHJK") is None

def test_full_flow_mints_one_bearer_token(overlay_redis):
    d = ot.start_device("GregLC")
    assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 5; ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id="42"); overlay_redis.now += 5
    m = ot.poll(d.device_code)
    assert isinstance(m, ot.Minted) and m.access_token.startswith("greg_ow_") and len(m.access_token) == 51
    assert (m.record.uid, m.record.default_guild_id, m.record.user, m.record.label) == (777, "42", USER, "GregLC")
    assert m.expires_in == 15_552_000 and overlay_redis.ttl(TOK + ot.hash_secret(m.access_token)) == 15_552_000
    assert overlay_redis.hgetall(TOKS + "777") == {m.record.tid: ot.hash_secret(m.access_token)}
    assert m.access_token not in repr(overlay_redis.kv) and not overlay_redis.exists(DEV + ot.hash_secret(d.device_code))
    assert ot.poll(d.device_code) == "expired_token" and ot.lookup_user_code(d.user_code) is None

def test_concurrent_polls_mint_exactly_one_token(overlay_redis):
    d = _approved(overlay_redis); overlay_redis.now += 5
    other = []; overlay_redis.interleave.append(lambda: other.append(ot.poll(d.device_code)))
    first = ot.poll(d.device_code)
    assert sorted(type(x).__name__ for x in (first, other[0])) == ["Minted", "str"]
    assert len(overlay_redis.hgetall(TOKS + "777")) == 1

def test_poll_never_overwrites_a_concurrent_approval(overlay_redis):
    d = ot.start_device("GregLC"); overlay_redis.now += 5
    overlay_redis.interleave.append(lambda: ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=None))
    assert isinstance(ot.poll(d.device_code), ot.Minted)

def test_poll_faster_than_interval_is_slow_down_and_adds_5s(overlay_redis):
    d = ot.start_device("GregLC"); assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 2; assert ot.poll(d.device_code) == "slow_down"        # intervalle passé à 10 s
    overlay_redis.now += 9.5; assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 5; assert ot.poll(d.device_code) == "slow_down"        # resté à 10 s, passe à 15 s

def test_poll_jitter_within_one_second_is_not_slow_down(overlay_redis):          # Review Focus 3
    d = ot.start_device("GregLC"); ot.poll(d.device_code)
    overlay_redis.now += 4.1; assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 3.9; assert ot.poll(d.device_code) == "slow_down"

def test_denied_is_access_denied_once(overlay_redis):
    d = ot.start_device("GregLC"); ot.decide(d.user_code, approve=False, uid=777, user=USER, guild_id=None)
    assert ot.poll(d.device_code) == "access_denied"; overlay_redis.now += 5
    assert ot.poll(d.device_code) == "expired_token"

def test_expired_device_and_unknown_code(overlay_redis):
    d = ot.start_device("GregLC"); overlay_redis.now += 601
    assert ot.poll(d.device_code) == "expired_token" and ot.poll("inconnu") == "expired_token"
    with pytest.raises(ot.OverlayError) as e:
        ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=None)
    assert (e.value.code, e.value.status) == ("CODE_EXPIRED", 404)

def test_code_is_single_use(overlay_redis):
    d = ot.start_device("GregLC"); ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=None)
    for approve in (True, False):
        with pytest.raises(ot.OverlayError) as e:
            ot.decide(d.user_code, approve=approve, uid=777, user=USER, guild_id=None)
        assert (e.value.code, e.value.status) == ("ALREADY_USED", 409)

def test_resolve_updates_last_used_at_at_most_every_5_min(overlay_redis, issue_token):
    tok = issue_token(); minted_at = int(overlay_redis.now)
    overlay_redis.now += 10; assert ot.resolve(tok).last_used_at == minted_at
    overlay_redis.now += 300; assert ot.resolve(tok).last_used_at == int(overlay_redis.now)
    assert overlay_redis.ttl(TOK + ot.hash_secret(tok)) == 15_552_000 - 310        # TTL gardé

@pytest.mark.parametrize("bad", ["", "greg_ow_inconnu", "Bearer greg_ow_x", "x" * 51])
def test_resolve_rejects_unknown_and_malformed(overlay_redis, bad):
    assert ot.resolve(bad) is None

def test_last_used_write_never_recreates_a_revoked_token(overlay_redis, issue_token):  # Review Focus 2
    tok = issue_token(); key = TOK + ot.hash_secret(tok); overlay_redis.now += 301
    overlay_redis.on_get = lambda k: overlay_redis.delete(k) if k == key else None
    ot.resolve(tok)
    assert not overlay_redis.exists(key)

def test_list_revoke_and_is_live(overlay_redis, issue_token):
    a = ot.resolve(issue_token()); overlay_redis.now += 1; b = ot.resolve(issue_token())
    assert [r.tid for r in ot.list_tokens(777)] == [b.tid, a.tid]
    assert set(a.public()) == {"id", "label", "created_at", "last_used_at", "expires_at"}
    assert ot.revoke(888, a.tid) is False and ot.is_live(777, a.tid)
    assert ot.revoke(777, a.tid) is True and not ot.is_live(777, a.tid)
    assert not overlay_redis.exists(TOK + a.token_hash) and a.tid not in overlay_redis.hgetall(TOKS + "777")
    overlay_redis.delete(TOK + b.token_hash)                                       # expiré
    assert ot.list_tokens(777) == [] and overlay_redis.hgetall(TOKS + "777") == {}

def test_rate_limit_counts_per_window(overlay_redis):
    assert [ot.hit_rate_limit("approve", "777", 5, 60) for _ in range(6)] == [False] * 5 + [True]
    assert overlay_redis.ttl("greg:ratelimit:approve:777") == 60
    overlay_redis.now += 61; assert ot.hit_rate_limit("approve", "777", 5, 60) is False

def test_rate_limit_counter_always_gets_an_expiry(overlay_redis):
    key = "greg:ratelimit:device_start:all"
    overlay_redis.set(key, "40"); assert overlay_redis.ttl(key) == -1             # compteur resté sans échéance
    assert ot.hit_rate_limit("device_start", "all", 30, 3600) is True and overlay_redis.ttl(key) == 3600
    overlay_redis.now += 100; ot.hit_rate_limit("device_start", "all", 30, 3600)
    assert overlay_redis.ttl(key) == 3500                                          # NX : la fenêtre n'est jamais prolongée
    assert overlay_redis.get(key) == "42"

@pytest.mark.parametrize("call", [lambda: ot.start_device("x"), lambda: ot.lookup_user_code("BCDFGHJK"),
    lambda: ot.poll("d"), lambda: ot.resolve("greg_ow_" + "a" * 43), lambda: ot.list_tokens(777),
    lambda: ot.revoke(777, "t"), lambda: ot.is_live(777, "t"), lambda: ot.hit_rate_limit("b", "s", 1, 60),
    lambda: ot.decide("BCDFGHJK", approve=True, uid=777, user=USER, guild_id=None)])
def test_redis_down_is_storage_unavailable(overlay_redis, call):
    overlay_redis.fail = redis.ConnectionError("Error 111 connecting to redis:6379")
    with pytest.raises(ot.OverlayError) as e:
        call()
    assert e.value.status == 503 and e.value.body() == {"ok": False, "error": "STORAGE_UNAVAILABLE",
                                                        "message": ot.MSG_STORAGE_UNAVAILABLE}
    assert "redis" not in str(e.value.body()).lower()

@pytest.mark.parametrize("env,ttl", [(None, 15_552_000), ("30", 2_592_000), ("abc", 15_552_000), ("0", 15_552_000), ("-3", 15_552_000)])
def test_token_ttl_env(monkeypatch, env, ttl):
    if env is None: monkeypatch.delenv("OVERLAY_TOKEN_TTL_DAYS", raising=False)
    else: monkeypatch.setenv("OVERLAY_TOKEN_TTL_DAYS", env)
    assert ot.token_ttl_s() == ttl
