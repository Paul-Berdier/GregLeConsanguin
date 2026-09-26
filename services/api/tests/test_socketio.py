"""Socket.IO — mode threading, relais Redis depuis un thread natif, handlers tolérants."""
from __future__ import annotations

import threading

import pytest

from api import socketio


def test_create_app_uses_threading_mode(app):
    assert socketio.async_mode == "threading"
    assert socketio.server.eio.async_mode == "threading"


@pytest.fixture()
def sio_client(app):
    c = socketio.test_client(app)
    assert c.is_connected()
    yield c
    if c.is_connected():
        c.disconnect()


def _events(received, name):
    return [m for m in received if m["name"] == name]


def test_overlay_register_joins_room_and_acks(sio_client):
    sio_client.emit("overlay_register", {"guild_id": "42"})
    assert _events(sio_client.get_received(), "overlay_ack")


def test_redis_listener_relay_from_native_thread_reaches_room(sio_client):
    from api.services.redis_listener import (
        CHANNEL_PROGRESS,
        CHANNEL_STATE,
        _handle_message,
    )

    sio_client.emit("overlay_register", {"guild_id": "42"})
    sio_client.get_received()

    def relay():
        _handle_message(socketio, CHANNEL_STATE, {"guild_id": 42, "state": {"queue": [1, 2]}})
        _handle_message(socketio, CHANNEL_PROGRESS, {"guild_id": 42, "position": 7, "duration": 100})

    t = threading.Thread(target=relay, daemon=True)
    t.start()
    t.join(5)

    updates = _events(sio_client.get_received(), "playlist_update")
    assert len(updates) == 2
    assert updates[0]["args"][0] == {"queue": [1, 2]}
    assert updates[1]["args"][0]["position"] == 7

    # Les réponses « normales » continuent d'arriver après un emit cross-thread.
    sio_client.emit("overlay_ping", {"t": 1})
    pongs = _events(sio_client.get_received(), "overlay_pong")
    assert pongs and pongs[0]["args"][0]["t"] == 1


@pytest.mark.parametrize("event", ["join_guild", "leave_guild", "overlay_register",
                                   "overlay_subscribe_guild", "overlay_unsubscribe_guild",
                                   "overlay_ping", "request_state"])
@pytest.mark.parametrize("payload", ["str", [1, 2], None, 5])
def test_handlers_tolerate_non_dict_payloads(sio_client, monkeypatch, event, payload):
    import api.services.bot_bridge as bb

    monkeypatch.setattr(bb, "send_command", lambda *a, **k: pytest.fail("send_command inattendu"))
    if payload is None:
        sio_client.emit(event)
    else:
        sio_client.emit(event, payload)
    # Le client reste connecté et le serveur répond encore.
    sio_client.get_received()
    sio_client.emit("overlay_ping", {"t": "alive"})
    pongs = _events(sio_client.get_received(), "overlay_pong")
    assert pongs and pongs[-1]["args"][0]["t"] == "alive"


def test_request_state_bad_guild_id_does_not_call_bot(sio_client, monkeypatch):
    import api.services.bot_bridge as bb

    monkeypatch.setattr(bb, "send_command", lambda *a, **k: pytest.fail("send_command inattendu"))
    sio_client.emit("request_state", {"guild_id": "abc"})
    assert not _events(sio_client.get_received(), "playlist_update")


def test_request_state_emits_state(sio_client, monkeypatch):
    import api.services.bot_bridge as bb

    monkeypatch.setattr(bb, "send_command",
                        lambda *a, **k: {"ok": True, "state": {"current": None, "queue": []}})
    sio_client.emit("request_state", {"guild_id": "42"})
    ups = _events(sio_client.get_received(), "playlist_update")
    assert ups and ups[0]["args"][0] == {"current": None, "queue": []}
