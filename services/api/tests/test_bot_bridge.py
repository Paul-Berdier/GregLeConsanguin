"""bot_bridge — PUBLISH sans abonné → BOT_OFFLINE immédiat, TIMEOUT avec message, clé greg:bot:guilds."""
from __future__ import annotations

import json
import time

import pytest

import api.services.bot_bridge as bb


class FakePubSub:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.subscribed = []
        self.unsubscribed = []
        self.closed = False

    def subscribe(self, *channels):
        self.subscribed.extend(channels)

    def unsubscribe(self, *channels):
        self.unsubscribed.extend(channels)

    def close(self):
        self.closed = True

    def get_message(self, ignore_subscribe_messages=False, timeout=0.0):
        if self.messages:
            return self.messages.pop(0)
        time.sleep(min(timeout or 0.0, 0.02))
        return None


class FakeRedis:
    def __init__(self, receivers=1, messages=None, kv=None, get_exc=None):
        self.receivers = receivers
        self.published = []
        self._pubsub = FakePubSub(messages)
        self.kv = kv or {}
        self.get_exc = get_exc

    def pubsub(self):
        return self._pubsub

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return self.receivers

    def get(self, key):
        if self.get_exc:
            raise self.get_exc
        return self.kv.get(key)

    def close(self):
        pass


@pytest.fixture()
def fake_redis(monkeypatch):
    holder = {}

    def install(**kw):
        fr = FakeRedis(**kw)
        holder["r"] = fr
        monkeypatch.setattr(bb, "_get_redis", lambda: fr)
        return fr

    return install


def test_publish_with_zero_receivers_returns_bot_offline_immediately(fake_redis):
    fr = fake_redis(receivers=0)
    t0 = time.monotonic()
    res = bb.send_command("play_for_user", 1, 2, data={"item": {"url": "x"}}, timeout=25)
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, "ne doit pas attendre le timeout quand personne n'écoute"
    assert res["ok"] is False
    assert res["error"] == "BOT_OFFLINE"
    assert isinstance(res.get("message"), str) and res["message"]
    # la commande a bien été publiée une seule fois, et le pubsub est libéré
    assert len(fr.published) == 1
    assert fr._pubsub.closed is True


def test_response_is_returned_when_bot_answers(fake_redis):
    fr = fake_redis(receivers=1)
    # La réponse arrive sur le channel de réponse (request_id inconnu d'avance → on
    # renvoie le message quel que soit le channel, comme le fait Redis pour l'abonné).
    fr._pubsub.messages = [{"type": "message", "data": json.dumps({"request_id": "x", "ok": True, "added": 3})}]
    res = bb.send_command("play_for_user", 1, 2, data={"item": {}}, timeout=2)
    assert res["ok"] is True and res["added"] == 3
    channel, payload = fr.published[0]
    assert channel == bb.CHANNEL_COMMANDS
    cmd = json.loads(payload)
    assert cmd["action"] == "play_for_user"
    assert fr._pubsub.subscribed == [f"greg:response:{cmd['request_id']}"]


def test_timeout_carries_french_message(fake_redis):
    fake_redis(receivers=1)
    res = bb.send_command("get_state", 1, timeout=0.2)
    assert res["ok"] is False
    assert res["error"] == "TIMEOUT"
    assert res["message"].startswith("Greg met trop de temps à répondre…")


def test_command_carries_timeout_so_the_bot_can_drop_stale_commands(fake_redis):
    # Le bot sérialise les commandes d'une guild (C3) : il doit savoir combien de temps
    # l'API attend, pour ne pas exécuter en retard une commande déjà signalée TIMEOUT.
    fr = fake_redis(receivers=1)
    bb.send_command("skip", 1, 2, timeout=0.1)
    cmd = json.loads(fr.published[0][1])
    assert cmd["timeout"] == pytest.approx(0.1)
    assert isinstance(cmd["timeout"], float)
    # forme historique inchangée
    assert cmd["action"] == "skip" and cmd["guild_id"] == 1 and cmd["user_id"] == 2
    assert cmd["data"] == {} and cmd["request_id"]


def test_command_carries_absolute_deadline(fake_redis):
    # Échéance absolue (epoch, secondes) = envoi + timeout : le bot peut abandonner
    # une commande dont l'API n'attend plus la réponse (ex. skip derrière une playlist).
    fr = fake_redis(receivers=1, messages=[{"type": "message", "data": json.dumps({"ok": True})}])
    before = time.time()
    bb.send_command("skip", 1, 2, timeout=25)
    after = time.time()
    cmd = json.loads(fr.published[0][1])
    assert before <= cmd["sent_at"] <= after
    assert cmd["deadline"] == pytest.approx(cmd["sent_at"] + 25)
    assert isinstance(cmd["sent_at"], float) and isinstance(cmd["deadline"], float)


def test_fire_and_forget_has_no_timeout(fake_redis):
    # Personne n'attend de réponse → le bot ne doit jamais l'abandonner.
    fr = fake_redis(receivers=1)
    bb.send_fire_and_forget("emit_state", 1)
    cmd = json.loads(fr.published[0][1])
    assert "timeout" not in cmd
    assert "deadline" not in cmd and "sent_at" not in cmd


def test_fire_and_forget_has_unique_request_id_for_dedup(fake_redis):
    # SEC-C3 : chaque instance du bot fait SET greg:req:<request_id> NX avant d'exécuter →
    # sans request_id, chaque instance exécuterait la commande (double exécution).
    fr = fake_redis(receivers=2)
    bb.send_fire_and_forget("emit_state", 1)
    bb.send_fire_and_forget("emit_state", 1)
    ids = [json.loads(p)["request_id"] for _, p in fr.published]
    assert all(isinstance(i, str) and len(i) >= 16 for i in ids)
    assert ids[0] != ids[1]


def test_command_request_id_is_long_enough_to_never_collide(fake_redis):
    # Une collision de request_id ferait ignorer la 2e commande par la dédup du bot.
    fr = fake_redis(receivers=0)
    bb.send_command("skip", 1, 2, timeout=1)
    cmd = json.loads(fr.published[0][1])
    assert len(cmd["request_id"]) >= 16


# ── greg:bot:guilds (C5) ──

def _install_fast(monkeypatch, fr):
    monkeypatch.setattr(bb, "_get_redis_fast", lambda: fr)


def test_bot_guild_ids_reads_json_array(monkeypatch):
    fr = FakeRedis(kv={"greg:bot:guilds": json.dumps(["1", "22", 333])})
    _install_fast(monkeypatch, fr)
    assert bb.get_bot_guild_ids() == {"1", "22", "333"}


def test_bot_guild_ids_missing_key_is_none(monkeypatch):
    _install_fast(monkeypatch, FakeRedis(kv={}))
    assert bb.get_bot_guild_ids() is None


@pytest.mark.parametrize("raw", ["not json", json.dumps({"a": 1}), json.dumps("x")])
def test_bot_guild_ids_unreadable_is_none(monkeypatch, raw):
    _install_fast(monkeypatch, FakeRedis(kv={"greg:bot:guilds": raw}))
    assert bb.get_bot_guild_ids() is None


def test_bot_guild_ids_redis_error_is_none(monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnectionError

    _install_fast(monkeypatch, FakeRedis(get_exc=RedisConnectionError("down")))
    assert bb.get_bot_guild_ids() is None
