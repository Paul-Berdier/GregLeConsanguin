"""Appli Overwolf côté bot : user_guilds, greg:player:event, expected et STALE."""
from __future__ import annotations

import asyncio
import types

import pytest
from test_redis_bridge import MEMBER, _cmd, _make_bridge, _responses

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
