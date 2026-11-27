"""Appli Overwolf côté bot : user_guilds, greg:player:event, expected et STALE."""
from __future__ import annotations

import asyncio
import types

import bot.services.redis_bridge as rb
import pytest
from bot.services.playlist_manager import StaleQueueError
from test_redis_bridge import MEMBER, FakeSvc, _cmd, _make_bridge, _responses

pytestmark = pytest.mark.asyncio


def _vc(ch, playing=False, paused=False):
    return types.SimpleNamespace(channel=ch, is_playing=lambda: playing, is_paused=lambda: paused)

def _guild(gid, name, members=(MEMBER,), user_ch=None, vc=None, icon=None):
    m = types.SimpleNamespace(id=MEMBER, display_name="Kévin", voice=types.SimpleNamespace(channel=user_ch) if user_ch else None)
    return types.SimpleNamespace(id=gid, name=name, icon=icon, voice_client=vc,
                                 get_member=lambda uid: m if uid in members else None)

TAVERNE = types.SimpleNamespace(id=11, name="Taverne")

def _bridge_with(*guilds):
    b = _make_bridge(); b.bot._guilds = {g.id: g for g in guilds}; return b

async def test_user_guilds_lists_shared_guilds_with_voice_and_playing():
    b = _bridge_with(_guild(2, "zèbre"), _guild(1, "Abbaye", user_ch=TAVERNE, vc=_vc(TAVERNE, paused=True),
                     icon=types.SimpleNamespace(url="https://cdn.discordapp.com/icons/1/a.png")), _guild(3, "Autre", members=()))
    assert b.user_guilds(MEMBER) == [
        {"id": "1", "name": "Abbaye", "icon_url": "https://cdn.discordapp.com/icons/1/a.png",
         "greg_voice": {"id": "11", "name": "Taverne"}, "user_voice": {"id": "11", "name": "Taverne"}, "playing": True},
        {"id": "2", "name": "zèbre", "icon_url": None, "greg_voice": None, "user_voice": None, "playing": False}]
    assert b.user_guilds(0) == []

async def test_user_guilds_ids_are_exact_strings():                            # Review Focus 4
    b = _bridge_with(_guild(1234567890123456789, "Grand"))
    assert b.user_guilds(MEMBER)[0]["id"] == "1234567890123456789"

async def test_user_guilds_command_is_read_only_and_never_member_checked():
    b = _bridge_with(_guild(1, "Abbaye"))
    await asyncio.wait_for(b._dispatch(_cmd("user_guilds", gid=0, rid="u")), 1)
    assert _responses(b)["u"]["ok"] is True and _responses(b)["u"]["guilds"][0]["id"] == "1"
    assert b._cmd_locks == {} and b.bot.emits == []
    assert [ch for ch, _ in b.published if not ch.startswith("greg:response:")] == []

class EventSvc(FakeSvc):
    """FakeSvc complété : chaque mutation réussit, title_at suit un « avant » modifiable."""
    def __init__(self): super().__init__(); self.titles = {None: "Avant", 0: "Q0", 1: "Q1"}
    def title_at(self, gid, index=None): return self.titles.get(index)
    def remove_at(self, gid, uid, index, expected=None): return True
    def move(self, gid, uid, src, dst, expected=None): return True
    async def play_at(self, gid, uid, index, expected=None): return True
    async def restart(self, gid, requester_id=None): return True
    async def pause(self, gid, requester_id=None): return True
    async def resume(self, gid, requester_id=None): return True
    async def toggle_repeat(self, gid, mode=None): return True

def _events_of(b): return [d for ch, d in b.published if ch == rb.CHANNEL_PLAYER_EVENT]

@pytest.fixture
def eb():
    b = _make_bridge(); b.bot.player_service = EventSvc()
    b.bot._guilds[1].get_member = lambda uid: types.SimpleNamespace(id=uid, display_name="Kévin", voice=None)
    return b

@pytest.mark.parametrize("action,data,ev,title", [
    ("play_for_user", {"item": {"url": "x"}}, "add", "t"), ("skip", {}, "skip", "Avant"), ("stop", {}, "stop", "Avant"),
    ("pause", {}, "pause", "Avant"), ("resume", {}, "resume", "Avant"), ("restart", {}, "restart", "Avant"),
    ("repeat", {"mode": "on"}, "repeat", None), ("remove", {"index": 1}, "remove", "Q1"),
    ("move", {"src": 1, "dst": 0}, "move", "Q1"), ("play_at", {"index": 1}, "play_at", "Q1")])
async def test_successful_mutation_publishes_one_player_event(eb, action, data, ev, title):
    await eb._handle_command(_cmd(action, rid="r", **data))
    [e] = _events_of(eb)
    at = e.pop("at_ms")
    assert isinstance(at, int) and e == {"guild_id": "1", "action": ev, "actor": {"id": str(MEMBER), "display_name": "Kévin"},
                                         "title": title}

async def test_toggle_pause_event_names_what_happened(eb):
    eb.bot._guilds[1].voice_client = types.SimpleNamespace(is_paused=lambda: True, is_playing=lambda: False)
    await eb._handle_command(_cmd("toggle_pause", rid="t"))
    assert _events_of(eb)[0]["action"] == "resume"

async def test_event_title_is_read_before_the_change(eb):
    async def skip(gid, requester_id=None): eb.bot.player_service.titles[None] = "Après"; return True
    eb.bot.player_service.skip = skip
    await eb._handle_command(_cmd("skip", rid="s"))
    assert _events_of(eb)[0]["title"] == "Avant"

@pytest.mark.parametrize("action,data", [("get_state", {}), ("join", {}), ("get_history", {})])
async def test_reads_and_join_publish_no_event(eb, action, data):
    await eb._handle_command(_cmd(action, rid="x", **data)); assert _events_of(eb) == []

async def test_failures_publish_no_event(eb):
    eb.bot.player_service.remove_at = lambda *a, **k: False
    async def forbidden(*a, **k): raise PermissionError("insufficient_rank")
    eb.bot.player_service.play_at = forbidden
    await eb._handle_command(_cmd("remove", rid="a", index=0)); await eb._handle_command(_cmd("play_at", rid="b", index=0))
    assert _events_of(eb) == []

async def test_actor_falls_back_to_the_id_and_title_errors_are_harmless(eb):
    eb.bot._guilds[1].get_member = lambda uid: None
    def boom(*a, **k): raise RuntimeError("cache")
    eb.bot.player_service.title_at = boom
    await eb._handle_command(_cmd("skip", rid="s"))
    assert _responses(eb)["s"]["ok"] is True
    assert _events_of(eb)[0]["actor"] == {"id": str(MEMBER), "display_name": str(MEMBER)} and _events_of(eb)[0]["title"] is None

async def test_publish_player_event_keeps_snowflake_as_string(eb):               # Review Focus 4
    await eb.publish_player_event(1234567890123456789, "add", 7, "T")
    assert _events_of(eb)[0]["guild_id"] == "1234567890123456789"

async def test_bridge_forwards_expected_and_maps_stale(eb):
    seen = {}
    def remove_at(gid, uid, index, expected=None): seen["expected"] = expected; raise StaleQueueError()
    eb.bot.player_service.remove_at = remove_at
    E = {"url": "u", "added_by": "7", "ts": 1700000000}
    await eb._handle_command(_cmd("remove", rid="r", index=1, expected=E))
    assert _responses(eb)["r"] == {"request_id": "r", "ok": False, "error": "STALE"}
    assert seen["expected"] == E and _events_of(eb) == []

async def test_bridge_ignores_a_non_object_expected(eb):
    seen = {}
    eb.bot.player_service.move = lambda gid, uid, s, d, expected=None: seen.setdefault("e", expected) or True
    await eb._handle_command(_cmd("move", rid="m", src=1, dst=0, expected="x"))
    assert seen["e"] is None
