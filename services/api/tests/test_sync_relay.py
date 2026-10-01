"""Synchro son/vidéo côté API (spec §5) : relay_at_ms sur les états et les ticks, clock relayé, time_sync."""
from __future__ import annotations

import time

import pytest

from api import socketio
from api.services import redis_listener as rl
from api.services.relay_clock import now_ms, with_relay_at

CLOCK = {"play_id": "a1b2c3d4", "status": "playing", "position_ms": 83460.0, "sampled_at_ms": 1790846494123}


class FakeSio:
    def __init__(self):
        self.emits = []

    def emit(self, event, data, room=None):
        self.emits.append((event, data, room))


def _between(v, t0, t1):
    return isinstance(v, int) and not isinstance(v, bool) and t0 <= v <= t1


# ── A1 : relais Redis ──

def test_now_ms_is_the_api_wall_clock_in_ms():
    t0 = int(time.time() * 1000)
    assert _between(now_ms(), t0, int(time.time() * 1000))


def test_with_relay_at_returns_a_copy():
    st = {"queue": []}
    assert with_relay_at(st, 5) == {"queue": [], "relay_at_ms": 5}
    assert st == {"queue": []}


def test_state_channel_is_stamped_and_keeps_the_clock():
    sio = FakeSio()
    state = {"current": {"title": "A"}, "position": 83, "clock": CLOCK}
    t0 = now_ms()
    rl._handle_message(sio, rl.CHANNEL_STATE, {"guild_id": 42, "state": state})
    t1 = now_ms()
    (event, data, room), = sio.emits
    assert (event, room) == ("playlist_update", "guild:42")
    assert _between(data.pop("relay_at_ms"), t0, t1)
    assert data == state
    assert "relay_at_ms" not in state, "l'état reçu n'est pas modifié"


def test_progress_channel_relays_the_clock_and_the_relay_time():
    sio = FakeSio()
    t0 = now_ms()
    rl._handle_message(sio, rl.CHANNEL_PROGRESS,
                       {"guild_id": 42, "position": 83, "duration": 200, "paused": False, "clock": CLOCK})
    t1 = now_ms()
    (event, data, room), = sio.emits
    assert (event, room) == ("playlist_update", "guild:42")
    assert _between(data.pop("relay_at_ms"), t0, t1)
    assert data == {"only_elapsed": True, "paused": False, "is_paused": False, "position": 83, "duration": 200,
                    "progress": {"elapsed": 83, "duration": 200}, "clock": CLOCK}


@pytest.mark.parametrize("clock", [None, "playing", 42, ["a"]])
def test_progress_without_a_clock_object_keeps_the_old_payload(clock):
    sio = FakeSio()
    data = {"guild_id": 42, "position": 7, "duration": 100}
    if clock is not None:
        data["clock"] = clock
    rl._handle_message(sio, rl.CHANNEL_PROGRESS, data)
    (_, out, _), = sio.emits
    assert "clock" not in out and isinstance(out["relay_at_ms"], int)
    assert out["position"] == 7 and out["progress"] == {"elapsed": 7, "duration": 100}
