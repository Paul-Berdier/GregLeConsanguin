"""RedisBridge — contrat C3 (commandes concurrentes, ordre par guild, lectures jamais bloquées),
clients Redis robustes, clé greg:bot:guilds (C5), politique 'join' (C7),
appartenance à la guild (SEC-C2) et une seule instance par commande (SEC-C3)."""
from __future__ import annotations

import asyncio
import json
import time
import types
from typing import Any, Dict, List

import discord
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

import bot.services.redis_bridge as rb

pytestmark = pytest.mark.asyncio


class FakeSvc:
    """PlayerService minimal : chaque action est journalisée, play_for_user peut être bloquée."""

    def __init__(self):
        self.log: List[tuple] = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.is_playing: Dict[int, bool] = {}
        self.busy = None
        self.connected: List[Any] = []
        self.started: List[Any] = []
        self.pfu_kwargs: List[dict] = []

    async def play_for_user(self, gid, uid, item, **kw):
        self.log.append(("play_for_user:start", gid))
        self.pfu_kwargs.append(kw)
        await self.gate.wait()
        self.log.append(("play_for_user:end", gid))
        return {"ok": True, "added": 1, "requested": 1, "truncated": None, "playlist": False, "title": "t"}

    async def skip(self, gid, requester_id=None):
        self.log.append(("skip", gid))
        return True

    async def stop(self, gid, requester_id=None):
        self.log.append(("stop", gid))
        return True

    def get_state(self, gid):
        self.log.append(("get_state", gid))
        return {"guild_id": gid, "queue": [], "current": None}

    def get_history(self, gid, mode="top", limit=20):
        self.log.append(("get_history", gid))
        return {"ok": True, "items": [], "mode": mode}

    async def play_at(self, gid, uid, index):
        raise PermissionError("insufficient_rank")

    def busy_elsewhere(self, guild, channel):
        return self.busy

    def busy_elsewhere_error(self, channel):
        return {"ok": False, "error": "BOT_IN_OTHER_CHANNEL", "message": f"Greg joue déjà dans <#{channel.id}>…"}

    async def ensure_connected(self, guild, channel):
        self.connected.append(channel)
        return True

    async def connect_for_user(self, guild, channel):
        # Politique C7 re-vérifiée sous le verrou vocal (après une éventuelle reconnexion).
        if self.busy is not None:
            return self.busy_elsewhere_error(self.busy)
        self.connected.append(channel)
        return None

    def ensure_playing(self, guild):
        self.started.append(guild)


class FakeBot:
    def __init__(self, svc, guilds=()):
        self.player_service = svc
        self._guilds = {g.id: g for g in guilds}
        self.emits: List[int] = []
        self.user = types.SimpleNamespace(id=1)

    @property
    def guilds(self):
        return list(self._guilds.values())

    def get_guild(self, gid):
        return self._guilds.get(int(gid))

    def emit_state_update(self, gid, payload=None):
        self.emits.append(gid)


MEMBER = 7


class FakeGuild:
    """Guild connue du bot : membres en cache (get_member) + fetch_member (appel API Discord)."""

    def __init__(self, gid, cached=(MEMBER,)):
        self.id = gid
        self.voice_client = None
        self.cached = set(cached)
        self.remote = set()  # membres absents du cache mais connus de Discord
        self.fetch_calls: List[int] = []
        self.fetch_exc = None
        self.fetch_gate = None  # asyncio.Event optionnel : fetch_member bloqué tant qu'il n'est pas posé

    def get_member(self, uid):
        return types.SimpleNamespace(id=uid, voice=None) if uid in self.cached else None

    async def fetch_member(self, uid):
        self.fetch_calls.append(uid)
        if self.fetch_gate is not None:
            await self.fetch_gate.wait()
        if self.fetch_exc is not None:
            raise self.fetch_exc
        if uid in self.remote:
            return types.SimpleNamespace(id=uid, voice=None)
        raise _http_error(discord.NotFound, 404, 10007, "Unknown Member")


def _http_error(cls, status, code, message):
    return cls(types.SimpleNamespace(status=status, reason="x"), {"code": code, "message": message})


class FakeCmdRedis:
    """Client Redis « commandes » partagé entre instances : SET NX EX (dédoublonnage SEC-C3)."""

    def __init__(self):
        self.store: Dict[str, str] = {}
        self.calls: List[dict] = []
        self.exc = None
        self.delays: Dict[str, float] = {}  # clé → délai avant la réponse de Redis

    async def set(self, key, value, ex=None, nx=False, **kw):
        self.calls.append({"key": key, "value": value, "ex": ex, "nx": nx})
        if self.exc is not None:
            raise self.exc
        if self.delays.get(key):
            await asyncio.sleep(self.delays[key])
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


def _make_bridge(cmd_redis=None):
    svc = FakeSvc()
    b = rb.RedisBridge(FakeBot(svc, guilds=[FakeGuild(1), FakeGuild(2)]))
    b.published = []
    b.cmd_redis = cmd_redis if cmd_redis is not None else FakeCmdRedis()

    async def fake_publish(channel, data):
        b.published.append((channel, data))

    async def fake_get_redis():
        return b.cmd_redis

    b._publish = fake_publish
    b._get_redis = fake_get_redis
    return b


@pytest.fixture
def bridge():
    return _make_bridge()


def _cmd(action, gid=1, rid="r", **data):
    return {"action": action, "guild_id": gid, "user_id": MEMBER, "request_id": rid, "data": data}


def _responses(b):
    return {d["request_id"]: d for ch, d in b.published if ch.startswith("greg:response:")}


async def _wait_response(b, rid, timeout=3.0):
    """Attend la réponse `rid` (échéance en temps réel : sous Windows/Python 3.12,
    asyncio.sleep(0.01) peut rendre la main bien plus tôt que prévu)."""
    end = time.monotonic() + timeout
    while rid not in _responses(b) and time.monotonic() < end:
        await asyncio.sleep(0.01)
    return rid in _responses(b)


async def test_read_only_commands_never_wait_behind_a_slow_command(bridge):
    svc = bridge.bot.player_service
    svc.gate.clear()
    bridge._dispatch(_cmd("play_for_user", rid="p", item={"url": "x"}))
    await asyncio.sleep(0.05)
    t = bridge._dispatch(_cmd("get_state", rid="s"))
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["s"]["ok"] is True
    assert "p" not in _responses(bridge)
    svc.gate.set()
    await asyncio.sleep(0.05)
    assert _responses(bridge)["p"]["added"] == 1


async def test_same_guild_mutations_are_serialized_in_arrival_order(bridge):
    svc = bridge.bot.player_service
    svc.gate.clear()
    bridge._dispatch(_cmd("play_for_user", rid="p", item={"url": "x"}))
    bridge._dispatch(_cmd("skip", rid="k"))
    bridge._dispatch(_cmd("stop", rid="s"))
    await asyncio.sleep(0.05)
    assert [e[0] for e in svc.log] == ["play_for_user:start"]
    svc.gate.set()
    await asyncio.sleep(0.05)
    assert [e[0] for e in svc.log] == ["play_for_user:start", "play_for_user:end", "skip", "stop"]


async def test_other_guilds_are_not_blocked(bridge):
    svc = bridge.bot.player_service
    svc.gate.clear()
    bridge._dispatch(_cmd("play_for_user", gid=1, rid="p", item={"url": "x"}))
    t = bridge._dispatch(_cmd("skip", gid=2, rid="k"))
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["k"] == {"request_id": "k", "ok": True}
    svc.gate.set()


async def test_command_expired_while_waiting_is_dropped(bridge, monkeypatch):
    """L'API a déjà répondu TIMEOUT (champ `timeout`, relatif à la réception) : le skip
    resté en attente derrière un play_for_user lent n'est PAS exécuté en retard."""
    monkeypatch.setattr(rb, "_EXPIRY_MARGIN", 0.05)
    svc = bridge.bot.player_service
    svc.gate.clear()
    bridge._dispatch(_cmd("play_for_user", rid="p", item={"url": "x"}))
    bridge._dispatch({**_cmd("skip", rid="k"), "timeout": 0.3})
    bridge._dispatch({**_cmd("stop", rid="s"), "timeout": 5.0})
    await asyncio.sleep(0.5)
    svc.gate.set()
    await asyncio.sleep(0.05)
    assert [e[0] for e in svc.log] == ["play_for_user:start", "play_for_user:end", "stop"]
    res = _responses(bridge)
    assert res["k"]["ok"] is False and res["k"]["error"] == "EXPIRED" and res["k"]["message"]
    assert res["s"] == {"request_id": "s", "ok": True}
    assert bridge.bot.emits.count(1) == 2  # play_for_user + stop, rien pour le skip abandonné


async def test_play_for_user_gets_the_budget_left_after_waiting(bridge):
    svc = bridge.bot.player_service
    svc.gate.clear()
    bridge._dispatch({**_cmd("play_for_user", rid="p1", item={"url": "x"}), "timeout": 25.0})
    t = bridge._dispatch({**_cmd("play_for_user", rid="p2", item={"url": "y"}), "timeout": 25.0})
    await asyncio.sleep(0.3)
    svc.gate.set()
    await asyncio.wait_for(t, 1)
    first, second = svc.pfu_kwargs
    assert 21.5 < first["budget"] <= 22.0
    assert 21.0 < second["budget"] < first["budget"] - 0.2
    # Sans `timeout` (ancienne API, fire-and-forget) : budget par défaut du PlayerService.
    await bridge._handle_command(_cmd("play_for_user", rid="p3", item={"url": "z"}))
    assert svc.pfu_kwargs[-1] == {}


async def test_unknown_guild_mutation_is_refused_without_state(bridge):
    svc = bridge.bot.player_service
    t = bridge._dispatch({**_cmd("skip", gid=987654321, rid="k"), "timeout": 8.0})
    await asyncio.wait_for(t, 1)
    res = _responses(bridge)["k"]
    assert res["ok"] is False and res["error"] == "GUILD_NOT_FOUND" and res["message"]
    assert svc.log == [] and bridge._cmd_locks == {}
    assert bridge.bot.emits == []


async def test_response_shape_and_permission_error(bridge):
    await bridge._handle_command(_cmd("play_at", rid="a", index=2))
    assert _responses(bridge)["a"] == {"request_id": "a", "ok": False, "error": "PRIORITY_FORBIDDEN"}


async def test_join_refuses_when_greg_plays_in_another_channel(bridge):
    svc = bridge.bot.player_service
    ch_user = types.SimpleNamespace(id=222)
    member = types.SimpleNamespace(voice=types.SimpleNamespace(channel=ch_user))
    guild = types.SimpleNamespace(id=1, get_member=lambda uid: member)
    bridge.bot._guilds[1] = guild
    svc.busy = types.SimpleNamespace(id=111)
    await bridge._handle_command(_cmd("join", rid="j"))
    res = _responses(bridge)["j"]
    assert res["ok"] is False and res["error"] == "BOT_IN_OTHER_CHANNEL" and "<#111>" in res["message"]
    assert svc.connected == []

    svc.busy = None
    await bridge._handle_command(_cmd("join", rid="j2"))
    assert _responses(bridge)["j2"]["ok"] is True
    assert svc.connected == [ch_user] and svc.started == [guild]


# ─────────────────────────── Listener ───────────────────────────


class FakePubSub:
    def __init__(self, messages, fail_first=False):
        self.messages = list(messages)
        self.fail_first = fail_first
        self.subscribed = []
        self.closed = False
        self.pings = []

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def get_message(self, ignore_subscribe_messages=False, timeout=0.0):
        if self.fail_first:
            self.fail_first = False
            raise ConnectionError("Connection reset by peer")
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(min(timeout or 0.01, 0.01))
        return None

    async def ping(self, message=None):
        self.pings.append(message)

    async def aclose(self):
        self.closed = True


class FakeRedis:
    def __init__(self, pubsub):
        self._ps = pubsub
        self.closed = False

    def pubsub(self, **kw):
        return self._ps

    async def aclose(self):
        self.closed = True


def _msg(data):
    return {"type": "message", "channel": rb.CHANNEL_COMMANDS, "data": json.dumps(data)}


async def test_listener_dispatches_each_command_in_its_own_task(bridge, monkeypatch):
    svc = bridge.bot.player_service
    svc.gate.clear()
    ps = FakePubSub([_msg(_cmd("play_for_user", rid="p", item={"url": "x"})), _msg(_cmd("get_state", rid="s"))])

    async def get_sub():
        return FakeRedis(ps)

    monkeypatch.setattr(bridge, "_get_redis_sub", get_sub)
    task = asyncio.create_task(bridge.start_listening())
    try:
        assert await _wait_response(bridge, "s", 1.0), "get_state bloqué derrière play_for_user"
        assert "p" not in _responses(bridge)
    finally:
        svc.gate.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listener_reconnects_and_closes_the_dead_connection(bridge, monkeypatch):
    dead = FakePubSub([], fail_first=True)
    alive = FakePubSub([_msg(_cmd("get_state", rid="s"))])
    clients = [FakeRedis(dead), FakeRedis(alive)]
    made = []

    async def get_sub():
        c = clients.pop(0) if clients else FakeRedis(FakePubSub([]))
        made.append(c)
        bridge._redis_sub = c
        return c

    monkeypatch.setattr(bridge, "_get_redis_sub", get_sub)
    monkeypatch.setattr(rb, "_RECONNECT_BACKOFF_MIN", 0.01, raising=False)
    task = asyncio.create_task(bridge.start_listening())
    try:
        assert await _wait_response(bridge, "s", 2.0)
        assert dead.closed and made[0].closed
        assert alive.subscribed == [rb.CHANNEL_COMMANDS]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listener_watchdog_pings_and_reconnects_on_silence(bridge, monkeypatch):
    silent = FakePubSub([])
    alive = FakePubSub([_msg(_cmd("get_state", rid="s"))])
    clients = [FakeRedis(silent), FakeRedis(alive)]

    async def get_sub():
        c = clients.pop(0) if clients else FakeRedis(FakePubSub([]))
        bridge._redis_sub = c
        return c

    monkeypatch.setattr(bridge, "_get_redis_sub", get_sub)
    monkeypatch.setattr(rb, "_WATCHDOG_PING_EVERY", 0.05)
    monkeypatch.setattr(rb, "_WATCHDOG_DEAD_AFTER", 0.2)
    monkeypatch.setattr(rb, "_RECONNECT_BACKOFF_MIN", 0.01, raising=False)
    task = asyncio.create_task(bridge.start_listening())
    try:
        await _wait_response(bridge, "s", 3.0)
        assert silent.pings, "aucun ping de surveillance envoyé"
        assert silent.closed
        assert "s" in _responses(bridge)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ─────────────────────────── Clients & clé guilds ───────────────────────────


async def test_redis_clients_have_keepalive_health_check_and_retry(monkeypatch):
    calls = []

    def fake_from_url(url, **kw):
        calls.append(kw)
        return FakeRedis(FakePubSub([]))

    monkeypatch.setattr(rb.aioredis, "from_url", fake_from_url)
    b = rb.RedisBridge(FakeBot(FakeSvc()))
    await b._get_redis()
    await b._get_redis_sub()
    pub, sub = calls
    for kw in (pub, sub):
        assert kw.get("socket_keepalive") is True
        assert kw.get("health_check_interval")
        assert kw.get("retry") is not None and kw.get("retry_on_error")
    assert pub.get("socket_timeout")


async def test_publish_bot_guilds_writes_the_key(monkeypatch):
    store = {}

    class R:
        async def set(self, key, value):
            store[key] = value

    b = rb.RedisBridge(FakeBot(FakeSvc(), guilds=[types.SimpleNamespace(id=12), types.SimpleNamespace(id=34)]))

    async def get_redis():
        return R()

    monkeypatch.setattr(b, "_get_redis", get_redis)
    await b.publish_bot_guilds()
    assert json.loads(store["greg:bot:guilds"]) == ["12", "34"]


async def test_publish_bot_guilds_failure_is_only_logged(monkeypatch):
    b = rb.RedisBridge(FakeBot(FakeSvc()))

    async def boom():
        raise ConnectionError("down")

    monkeypatch.setattr(b, "_get_redis", boom)
    await b.publish_bot_guilds()  # ne lève pas


# ─────────────────────────── SEC-C2 : appartenance à la guild ───────────────────────────


_NOT_MEMBER = {"ok": False, "error": "NOT_GUILD_MEMBER", "message": "Tu n'es pas membre de ce serveur."}
_CHECK_FAILED = {"ok": False, "error": "MEMBER_CHECK_FAILED",
                 "message": "Vérification impossible, réessaie dans un instant."}


@pytest.mark.parametrize("action", ["skip", "play_for_user", "get_state", "get_history"])
async def test_non_member_is_rejected_and_nothing_runs(bridge, action):
    svc = bridge.bot.player_service
    guild = bridge.bot.get_guild(1)
    t = bridge._dispatch({**_cmd(action, rid="x", item={"url": "x"}), "user_id": 666})
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["x"] == {"request_id": "x", **_NOT_MEMBER}
    assert svc.log == [] and bridge.bot.emits == []
    assert guild.fetch_calls == [666]  # absent du cache → vérifié auprès de Discord


@pytest.mark.parametrize("uid", [0, None, "abc"])
async def test_missing_user_is_never_a_member(bridge, uid):
    svc = bridge.bot.player_service
    for action, rid in (("get_state", "s"), ("skip", "k")):
        t = bridge._dispatch({**_cmd(action, rid=rid), "user_id": uid})
        await asyncio.wait_for(t, 1)
        assert _responses(bridge)[rid] == {"request_id": rid, **_NOT_MEMBER}
    assert svc.log == [] and bridge.bot.get_guild(1).fetch_calls == []


async def test_cached_member_is_accepted_without_api_call(bridge):
    svc = bridge.bot.player_service
    for action, rid in (("skip", "k"), ("get_state", "s")):
        t = bridge._dispatch(_cmd(action, rid=rid))
        await asyncio.wait_for(t, 1)
    res = _responses(bridge)
    assert res["k"] == {"request_id": "k", "ok": True}
    assert res["s"]["ok"] is True and res["s"]["state"]["guild_id"] == 1
    assert [e[0] for e in svc.log] == ["skip", "get_state"]
    assert bridge.bot.get_guild(1).fetch_calls == []


async def test_cache_miss_member_is_fetched_then_accepted(bridge):
    svc = bridge.bot.player_service
    guild = bridge.bot.get_guild(1)
    guild.remote.add(55)
    for action, rid in (("skip", "k"), ("get_state", "s")):
        t = bridge._dispatch({**_cmd(action, rid=rid), "user_id": 55})
        await asyncio.wait_for(t, 1)
    res = _responses(bridge)
    assert res["k"] == {"request_id": "k", "ok": True} and res["s"]["ok"] is True
    assert [e[0] for e in svc.log] == ["skip", "get_state"]
    assert guild.fetch_calls == [55, 55]


@pytest.mark.parametrize("exc", [
    _http_error(discord.HTTPException, 500, 0, "Internal Server Error"),
    _http_error(discord.Forbidden, 403, 50001, "Missing Access"),
    RuntimeError("session fermée"),
])
async def test_member_lookup_failure_is_reported_and_nothing_runs(bridge, exc):
    svc = bridge.bot.player_service
    guild = bridge.bot.get_guild(1)
    guild.fetch_exc = exc
    for action, rid in (("skip", "k"), ("get_state", "s")):
        t = bridge._dispatch({**_cmd(action, rid=rid), "user_id": 55})
        await asyncio.wait_for(t, 1)
        assert _responses(bridge)[rid] == {"request_id": rid, **_CHECK_FAILED}
    assert svc.log == [] and bridge.bot.emits == []


async def test_member_lookup_that_hangs_is_reported_as_check_failed(bridge, monkeypatch):
    monkeypatch.setattr(rb, "_MEMBER_CHECK_TIMEOUT", 0.05, raising=False)
    guild = bridge.bot.get_guild(1)
    guild.fetch_gate = asyncio.Event()  # jamais posé : Discord ne répond pas
    t = bridge._dispatch({**_cmd("skip", rid="k"), "user_id": 55})
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["k"] == {"request_id": "k", **_CHECK_FAILED}
    assert bridge.bot.player_service.log == []


async def test_unknown_guild_behaviour_is_unchanged(bridge):
    """Guild inconnue : pas de vérification d'appartenance (état vide, GUILD_NOT_FOUND…)."""
    t = bridge._dispatch({**_cmd("get_state", gid=987654321, rid="s"), "user_id": 0})
    await asyncio.wait_for(t, 1)
    res = _responses(bridge)["s"]
    assert res["ok"] is True and res["state"]["guild_id"] == 987654321
    t = bridge._dispatch({**_cmd("skip", gid=987654321, rid="k"), "user_id": 0})
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["k"]["error"] == "GUILD_NOT_FOUND"


async def test_member_check_never_waits_behind_the_guild_lock(bridge):
    svc = bridge.bot.player_service
    guild = bridge.bot.get_guild(1)
    guild.remote.add(55)
    svc.gate.clear()
    bridge._dispatch(_cmd("play_for_user", rid="p", item={"url": "x"}))
    await asyncio.sleep(0.05)
    # Lecture d'un membre hors cache : vérifiée et servie pendant le play_for_user lent.
    t = bridge._dispatch({**_cmd("get_state", rid="s"), "user_id": 55})
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["s"]["ok"] is True
    # Non-membre : refusé tout de suite, sans attendre son tour derrière le play_for_user.
    bridge._dispatch({**_cmd("skip", rid="k"), "user_id": 666})
    assert await _wait_response(bridge, "k", 1.0)
    assert _responses(bridge)["k"]["error"] == "NOT_GUILD_MEMBER"
    assert "p" not in _responses(bridge)
    svc.gate.set()
    assert await _wait_response(bridge, "p", 1.0)
    assert [e[0] for e in svc.log] == ["play_for_user:start", "get_state", "play_for_user:end"]


async def test_slow_member_lookup_never_blocks_the_listener(bridge, monkeypatch):
    guild = bridge.bot.get_guild(1)
    guild.remote.add(55)
    guild.fetch_gate = asyncio.Event()
    ps = FakePubSub([
        _msg({**_cmd("get_state", rid="slow"), "user_id": 55}),
        _msg(_cmd("get_state", rid="s")),
    ])

    async def get_sub():
        return FakeRedis(ps)

    monkeypatch.setattr(bridge, "_get_redis_sub", get_sub)
    task = asyncio.create_task(bridge.start_listening())
    try:
        assert await _wait_response(bridge, "s", 1.0), "écoute bloquée par la vérification d'appartenance"
        assert "slow" not in _responses(bridge)
        guild.fetch_gate.set()
        assert await _wait_response(bridge, "slow", 1.0)
        assert _responses(bridge)["slow"]["ok"] is True
    finally:
        guild.fetch_gate.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ─────────────────────────── SEC-C3 : une seule instance par commande ───────────────────────────


@pytest.mark.parametrize("action", ["skip", "get_state"])
async def test_a_command_runs_on_one_instance_only(bridge, action):
    other = _make_bridge(cmd_redis=bridge.cmd_redis)  # 2e instance du bot, même Redis
    t1 = bridge._dispatch(_cmd(action, rid="k"))
    t2 = other._dispatch(_cmd(action, rid="k"))
    await asyncio.wait_for(asyncio.gather(t1, t2), 1)
    assert [e[0] for e in bridge.bot.player_service.log] == [action]
    assert other.bot.player_service.log == []
    assert other.published == [] and other.bot.emits == []  # rien, pas même une réponse
    assert len(_responses(bridge)) == 1 and _responses(bridge)["k"]["ok"] is True
    assert bridge.instance_id and bridge.instance_id != other.instance_id
    first = bridge.cmd_redis.calls[0]
    assert first == {"key": "greg:req:k", "value": bridge.instance_id, "ex": 120, "nx": True}
    assert bridge.cmd_redis.store == {"greg:req:k": bridge.instance_id}


async def test_rejections_are_not_duplicated_across_instances(bridge):
    other = _make_bridge(cmd_redis=bridge.cmd_redis)
    cmd = {**_cmd("skip", rid="k"), "user_id": 666}
    await asyncio.wait_for(asyncio.gather(bridge._dispatch(dict(cmd)), other._dispatch(dict(cmd))), 1)
    assert _responses(bridge)["k"]["error"] == "NOT_GUILD_MEMBER"
    assert other.published == []
    unknown = _cmd("skip", gid=987654321, rid="u")
    await asyncio.wait_for(asyncio.gather(bridge._dispatch(dict(unknown)), other._dispatch(dict(unknown))), 1)
    assert _responses(bridge)["u"]["error"] == "GUILD_NOT_FOUND"
    assert other.published == []


async def test_claim_redis_error_fails_open(bridge):
    bridge.cmd_redis.exc = RedisConnectionError("Connection refused")
    svc = bridge.bot.player_service
    for action, rid in (("skip", "k"), ("get_state", "s")):
        t = bridge._dispatch(_cmd(action, rid=rid))
        await asyncio.wait_for(t, 1)
    assert _responses(bridge)["k"] == {"request_id": "k", "ok": True}
    assert _responses(bridge)["s"]["ok"] is True
    assert [e[0] for e in svc.log] == ["skip", "get_state"]


async def test_claim_fails_open_when_redis_client_is_unavailable(bridge):
    async def boom():
        raise RedisConnectionError("down")

    bridge._get_redis = boom
    t = bridge._dispatch(_cmd("skip", rid="k"))
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["k"] == {"request_id": "k", "ok": True}


async def test_claim_that_hangs_fails_open(bridge, monkeypatch):
    monkeypatch.setattr(rb, "_CLAIM_TIMEOUT", 0.05, raising=False)
    bridge.cmd_redis.delays["greg:req:k"] = 5.0
    t = bridge._dispatch(_cmd("skip", rid="k"))
    await asyncio.wait_for(t, 1)
    assert _responses(bridge)["k"] == {"request_id": "k", "ok": True}


async def test_command_without_request_id_is_not_claimed(bridge):
    t = bridge._dispatch(_cmd("skip", rid=""))
    await asyncio.wait_for(t, 1)
    assert bridge.bot.player_service.log == [("skip", 1)]
    assert bridge.cmd_redis.calls == []


async def test_arrival_order_is_kept_when_claims_answer_out_of_order(bridge):
    """Les vérifications (Redis, Discord) n'ont pas le droit de réordonner une même guild."""
    svc = bridge.bot.player_service
    bridge.cmd_redis.delays = {"greg:req:p": 0.15, "greg:req:k": 0.05}
    bridge._dispatch(_cmd("play_for_user", rid="p", item={"url": "x"}))
    bridge._dispatch(_cmd("skip", rid="k"))
    t = bridge._dispatch(_cmd("stop", rid="s"))
    await asyncio.wait_for(t, 1)
    assert [e[0] for e in svc.log] == ["play_for_user:start", "play_for_user:end", "skip", "stop"]


# ─────────────────────────── Synchro son/vidéo : tick + clock ───────────────────────────


async def test_publish_progress_carries_the_clock_and_keeps_its_fields(bridge):
    clock = {"play_id": "a1b2c3d4", "status": "playing", "position_ms": 83460.0, "sampled_at_ms": 1790846494123}
    await bridge.publish_progress(1, 83, 200, False, clock=clock)
    await bridge.publish_progress(1, 84, 200, True)
    (ch1, d1), (ch2, d2) = bridge.published
    assert ch1 == ch2 == rb.CHANNEL_PROGRESS
    assert d1 == {"guild_id": 1, "position": 83, "duration": 200, "paused": False, "clock": clock}
    assert d2 == {"guild_id": 1, "position": 84, "duration": 200, "paused": True}, "sans clock : payload d'avant"
