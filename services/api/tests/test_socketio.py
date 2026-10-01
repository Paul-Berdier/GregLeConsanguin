"""Socket.IO — mode threading, relais Redis depuis un thread natif, handlers tolérants,
et autorisation des rooms de guild (SEC-C4) : session Discord + accès confirmé par le bot."""
from __future__ import annotations

import threading

import pytest

from api import socketio
from api.services.redis_listener import (
    CHANNEL_BOT_STATUS,
    CHANNEL_PROGRESS,
    CHANNEL_STATE,
    _handle_message,
)

GUILD_EVENTS = ["join_guild", "overlay_register", "overlay_subscribe_guild", "request_state"]
STATE = {"current": {"title": "Titre"}, "queue": []}


def test_create_app_uses_threading_mode(app):
    assert socketio.async_mode == "threading"
    assert socketio.server.eio.async_mode == "threading"


class FakeBot:
    """Remplace bot_bridge.send_command : enregistre les appels, renvoie une réponse fixée."""

    def __init__(self):
        self.result = {"ok": True, "state": dict(STATE)}
        self.calls = []

    def __call__(self, action, guild_id, user_id=0, data=None, timeout=15.0):
        self.calls.append({"action": action, "guild_id": guild_id, "user_id": user_id,
                           "data": data, "timeout": timeout})
        return dict(self.result)


@pytest.fixture()
def fake_bot(monkeypatch):
    import api.services.bot_bridge as bb

    fake = FakeBot()
    monkeypatch.setattr(bb, "send_command", fake)
    return fake


@pytest.fixture()
def no_bot(monkeypatch):
    import api.services.bot_bridge as bb

    monkeypatch.setattr(bb, "send_command", lambda *a, **k: pytest.fail("send_command inattendu"))


def _connect(app, flask_client=None):
    c = socketio.test_client(app, flask_test_client=flask_client)
    assert c.is_connected()
    c.get_received()
    return c


@pytest.fixture()
def sio_client(app):
    """Socket anonyme (aucune session Discord)."""
    c = _connect(app)
    yield c
    if c.is_connected():
        c.disconnect()


@pytest.fixture()
def member_sio(app, login):
    """Socket d'un utilisateur connecté à Discord (cookie de session)."""
    c = _connect(app, login(app.test_client()))
    yield c
    if c.is_connected():
        c.disconnect()


def _events(received, name):
    return [m for m in received if m["name"] == name]


def _relay_state(guild_id=42, state=None):
    """Publie un state update comme le Redis listener, depuis un thread natif."""
    t = threading.Thread(target=_handle_message, daemon=True, args=(
        socketio, CHANNEL_STATE, {"guild_id": guild_id, "state": state or {"queue": ["relay"]}}))
    t.start()
    t.join(5)


def _got_relay(client):
    return [u for u in _events(client.get_received(), "playlist_update")
            if u["args"][0] == {"queue": ["relay"]}]


# ── overlay_register : toujours un overlay_ack ──

def test_overlay_register_without_guild_acks_without_calling_bot(sio_client, no_bot):
    sio_client.emit("overlay_register", {"kind": "web_player"})
    received = sio_client.get_received()
    assert _events(received, "overlay_ack")
    assert not _events(received, "guild_join_error")


def test_overlay_register_anonymous_acks_but_does_not_join(sio_client, no_bot):
    sio_client.emit("overlay_register", {"guild_id": "42"})
    received = sio_client.get_received()
    assert _events(received, "overlay_ack")
    assert _events(received, "guild_join_error")
    _relay_state(42)
    assert not _got_relay(sio_client)


def test_overlay_register_member_acks_and_joins(member_sio, fake_bot):
    member_sio.emit("overlay_register", {"guild_id": "42"})
    received = member_sio.get_received()
    assert _events(received, "overlay_ack")
    assert _events(received, "playlist_update")
    _relay_state(42)
    assert _got_relay(member_sio)


# ── Autorisation des rooms guild:<id> ──

@pytest.mark.parametrize("event", GUILD_EVENTS)
def test_anonymous_socket_cannot_join_guild_room(sio_client, no_bot, event):
    sio_client.emit(event, {"guild_id": "42"})
    received = sio_client.get_received()
    assert not _events(received, "playlist_update")
    errors = _events(received, "guild_join_error")
    assert errors and errors[0]["args"][0] == {
        "guild_id": "42",
        "error": "NOT_AUTHENTICATED",
        "message": "Connecte-toi avec Discord pour contrôler Greg.",
        "retry": False,
    }
    _relay_state(42)
    assert not _got_relay(sio_client)


@pytest.mark.parametrize("event", GUILD_EVENTS)
def test_member_joins_room_and_gets_state(member_sio, fake_bot, session_uid, event):
    member_sio.emit(event, {"guild_id": "42", "user_id": "999"})  # user_id du payload ignoré
    received = member_sio.get_received()
    assert not _events(received, "guild_join_error")
    ups = _events(received, "playlist_update")
    assert ups and ups[0]["args"][0] == STATE

    assert fake_bot.calls == [{"action": "get_state", "guild_id": 42, "user_id": session_uid,
                               "data": None, "timeout": 5}]
    _relay_state(42)
    assert _got_relay(member_sio)


@pytest.mark.parametrize("event", GUILD_EVENTS)
def test_non_member_cannot_join_guild_room(member_sio, fake_bot, event):
    fake_bot.result = {"ok": False, "error": "NOT_GUILD_MEMBER",
                       "message": "Tu n'es pas membre de ce serveur."}
    member_sio.emit(event, {"guild_id": "42"})
    received = member_sio.get_received()
    assert not _events(received, "playlist_update")
    errors = _events(received, "guild_join_error")
    assert errors and errors[0]["args"][0] == {
        "guild_id": "42",
        "error": "NOT_GUILD_MEMBER",
        "message": "Tu n'es pas membre de ce serveur.",
        "retry": False,
    }
    _relay_state(42)
    assert not _got_relay(member_sio)


@pytest.mark.parametrize("error", ["TIMEOUT", "BOT_OFFLINE", "REDIS_UNAVAILABLE",
                                   "MEMBER_CHECK_FAILED"])
def test_transient_failure_does_not_join_and_asks_for_retry(member_sio, fake_bot, error):
    fake_bot.result = {"ok": False, "error": error, "message": "Réessaie."}
    member_sio.emit("overlay_subscribe_guild", {"guild_id": "42"})
    errors = _events(member_sio.get_received(), "guild_join_error")
    assert errors and errors[0]["args"][0] == {
        "guild_id": "42", "error": error, "message": "Réessaie.", "retry": True,
    }
    _relay_state(42)
    assert not _got_relay(member_sio)


def test_error_without_message_still_has_a_french_message(member_sio, fake_bot):
    fake_bot.result = {"ok": False, "error": "CHELOU"}
    member_sio.emit("join_guild", {"guild_id": "42"})
    err = _events(member_sio.get_received(), "guild_join_error")[0]["args"][0]
    assert err["error"] == "CHELOU" and err["retry"] is False
    assert isinstance(err["message"], str) and err["message"]


def test_bridge_exception_is_a_retryable_error(member_sio, monkeypatch):
    import api.services.bot_bridge as bb

    def boom(*a, **k):
        raise RuntimeError("redis HS")

    monkeypatch.setattr(bb, "send_command", boom)
    member_sio.emit("join_guild", {"guild_id": "42"})
    err = _events(member_sio.get_received(), "guild_join_error")[0]["args"][0]
    assert err["retry"] is True
    assert member_sio.is_connected()


def test_denied_resubscribe_leaves_previously_joined_room(member_sio, fake_bot):
    member_sio.emit("overlay_subscribe_guild", {"guild_id": "42"})
    member_sio.get_received()
    fake_bot.result = {"ok": False, "error": "NOT_GUILD_MEMBER", "message": "Plus membre."}
    member_sio.emit("overlay_subscribe_guild", {"guild_id": "42"})
    member_sio.get_received()
    _relay_state(42)
    assert not _got_relay(member_sio)


def test_unsubscribe_leaves_room(member_sio, fake_bot):
    member_sio.emit("overlay_subscribe_guild", {"guild_id": "42"})
    member_sio.get_received()
    member_sio.emit("overlay_unsubscribe_guild", {"guild_id": "42"})
    _relay_state(42)
    assert not _got_relay(member_sio)


def test_member_of_one_guild_does_not_get_another_guild(member_sio, fake_bot):
    member_sio.emit("join_guild", {"guild_id": "42"})
    member_sio.get_received()
    _relay_state(43)
    assert not _got_relay(member_sio)


# ── Relais Redis (thread natif) ──

def test_redis_listener_relay_from_native_thread_reaches_room(member_sio, fake_bot):
    member_sio.emit("overlay_register", {"guild_id": "42"})
    member_sio.get_received()

    def relay():
        _handle_message(socketio, CHANNEL_STATE, {"guild_id": 42, "state": {"queue": [1, 2]}})
        _handle_message(socketio, CHANNEL_PROGRESS, {"guild_id": 42, "position": 7, "duration": 100})

    t = threading.Thread(target=relay, daemon=True)
    t.start()
    t.join(5)

    updates = _events(member_sio.get_received(), "playlist_update")
    assert len(updates) == 2
    assert updates[0]["args"][0] == {"queue": [1, 2]}
    assert updates[1]["args"][0]["position"] == 7

    # Les réponses « normales » continuent d'arriver après un emit cross-thread.
    member_sio.emit("overlay_ping", {"t": 1})
    pongs = _events(member_sio.get_received(), "overlay_pong")
    assert pongs and pongs[0]["args"][0]["t"] == 1


def test_state_without_guild_is_not_broadcast(sio_client, member_sio):
    _handle_message(socketio, CHANNEL_STATE, {"state": {"queue": ["relay"]}})
    assert not _got_relay(sio_client)
    assert not _got_relay(member_sio)


def test_bot_status_only_reaches_authenticated_sockets(sio_client, member_sio):
    status = {"status": "ready", "guilds": [{"id": "1", "name": "Serveur privé"}]}
    t = threading.Thread(target=_handle_message, daemon=True,
                         args=(socketio, CHANNEL_BOT_STATUS, status))
    t.start()
    t.join(5)
    assert _events(member_sio.get_received(), "bot_status")
    assert not _events(sio_client.get_received(), "bot_status")


# ── Handlers tolérants ──

@pytest.mark.parametrize("event", ["join_guild", "leave_guild", "overlay_register",
                                   "overlay_subscribe_guild", "overlay_unsubscribe_guild",
                                   "overlay_ping", "request_state"])
@pytest.mark.parametrize("payload", ["str", [1, 2], None, 5])
@pytest.mark.parametrize("who", ["anonymous", "member"])
def test_handlers_tolerate_non_dict_payloads(app, login, no_bot, event, payload, who):
    c = _connect(app, login(app.test_client()) if who == "member" else None)
    try:
        if payload is None:
            c.emit(event)
        else:
            c.emit(event, payload)
        # Le client reste connecté et le serveur répond encore.
        c.get_received()
        c.emit("overlay_ping", {"t": "alive"})
        pongs = _events(c.get_received(), "overlay_pong")
        assert pongs and pongs[-1]["args"][0]["t"] == "alive"
    finally:
        c.disconnect()


@pytest.mark.parametrize("guild_id", ["abc", "", "-3", "0", "4.5", "²", None, True])
def test_request_state_bad_guild_id_does_not_call_bot(member_sio, no_bot, guild_id):
    member_sio.emit("request_state", {"guild_id": guild_id})
    received = member_sio.get_received()
    assert not _events(received, "playlist_update")
    assert not _events(received, "guild_join_error")


def test_request_state_emits_state(member_sio, fake_bot):
    fake_bot.result = {"ok": True, "state": {"current": None, "queue": []}}
    member_sio.emit("request_state", {"guild_id": "42"})
    ups = _events(member_sio.get_received(), "playlist_update")
    assert ups and ups[0]["args"][0] == {"current": None, "queue": []}
