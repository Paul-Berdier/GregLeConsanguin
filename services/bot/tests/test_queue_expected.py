"""PlayerService : title_at, puis la garde expected (tâche 9)."""
from __future__ import annotations

import core_fakes
import pytest
from core_fakes import BOT_CHANNEL, yt_entry

harness = core_fakes.harness  # fixture du harnais rendue visible ici, comme dans test_play_many.py

pytestmark = pytest.mark.asyncio

A, B, C = yt_entry(1, title="A"), yt_entry(2, title="B"), yt_entry(3, title="C")


async def test_title_at_reads_current_and_queue(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    await h.svc.enqueue(h.gid, 2, A); await h.svc.enqueue(h.gid, 2, B)
    assert len(h.queue()) == 2
    assert [h.svc.title_at(h.gid, i) for i in range(len(h.queue()))] == [it["title"] for it in h.queue()]
    assert h.svc.title_at(h.gid, 99) is None and h.svc.title_at(424242, 0) is None
    h.svc.now_playing[h.gid] = {"title": "En cours"}
    assert h.svc.title_at(h.gid) == "En cours"
