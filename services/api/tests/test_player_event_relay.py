"""Relais de l'activité (spec §3.6) : `greg:player:event` → `player_event` à la salle `guild:<id>`,
et `guild_id` dans les ticks relayés."""
from __future__ import annotations

import threading

import pytest

from api import socketio
from api.services import redis_listener as rl
from api.services.redis_listener import _handle_message
from test_socketio import FakeBot, _events, fake_bot, member_sio  # noqa: F401
from test_sync_relay import FakeSio

EV = {"guild_id": "42", "action": "add", "actor": {"id": "7", "display_name": "Kévin"}, "title": "Thunderstruck", "at_ms": 1790846494123}


def test_listener_subscribes_player_event():
    assert rl.CHANNEL_PLAYER_EVENT == "greg:player:event" and rl.CHANNEL_PLAYER_EVENT in rl.CHANNELS


def test_player_event_goes_to_its_guild_room_only():
    sio = FakeSio(); rl._handle_message(sio, rl.CHANNEL_PLAYER_EVENT, {**EV, "secret": "x"})
    assert sio.emits == [("player_event", EV, "guild:42")]


@pytest.mark.parametrize("bad", [{**EV, "action": "jumpscare"}, {**EV, "guild_id": ""}, {**EV, "actor": "Kévin"},
                                 {**EV, "action": ["add"]}, {**EV, "actor": {"display_name": "Kévin"}}])
def test_player_event_drops_unknown_or_malformed(bad):
    sio = FakeSio(); rl._handle_message(sio, rl.CHANNEL_PLAYER_EVENT, bad); assert sio.emits == []


def test_tick_guild_id_keeps_snowflake_precision():                              # Review Focus 4
    sio = FakeSio(); rl._handle_message(sio, rl.CHANNEL_PROGRESS, {"guild_id": 1234567890123456789, "position": 1})
    assert sio.emits[0][1]["guild_id"] == "1234567890123456789"


def test_member_socket_receives_player_event(member_sio, fake_bot):
    member_sio.emit("join_guild", {"guild_id": "42"}); member_sio.get_received()
    t = threading.Thread(target=_handle_message, args=(socketio, rl.CHANNEL_PLAYER_EVENT, EV)); t.start(); t.join(5)
    assert [e["args"][0] for e in _events(member_sio.get_received(), "player_event")] == [EV]
