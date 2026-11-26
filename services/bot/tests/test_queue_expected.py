"""PlayerService : title_at, puis la garde expected (tâche 9)."""
from __future__ import annotations

import core_fakes
import pytest
from bot.services.playlist_manager import StaleQueueError
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

def _exp(it): return {"url": it["url"], "added_by": it["added_by"], "ts": it["ts"]}

async def test_matching_expected_acts(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    for x in (A, B, C): await h.svc.enqueue(h.gid, 2, x)
    q = h.queue()
    assert h.svc.remove_at(h.gid, 2, 0, expected=_exp(q[0])) is True
    q = h.queue(); assert h.svc.move(h.gid, 2, 1, 0, expected=_exp(q[1])) is True and h.urls()[0] == C["url"]

@pytest.mark.parametrize("op", ["remove", "move", "play_at", "out_of_bounds"])
async def test_stale_expected_raises_and_changes_nothing(harness, op):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    for x in (A, B): await h.svc.enqueue(h.gid, 2, x)
    before, wrong = h.urls(), _exp(h.queue()[0])
    with pytest.raises(StaleQueueError):
        if op == "remove": h.svc.remove_at(h.gid, 2, 1, expected=wrong)
        elif op == "move": h.svc.move(h.gid, 2, 1, 0, expected=wrong)
        elif op == "play_at": await h.svc.play_at(h.gid, 2, 1, expected=wrong)
        else: h.svc.remove_at(h.gid, 2, 5, expected=wrong)
    assert h.urls() == before

async def test_move_to_a_target_out_of_bounds_is_stale(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    for x in (A, B): await h.svc.enqueue(h.gid, 2, x)
    before = h.urls()
    with pytest.raises(StaleQueueError):                          # la file a raccourci : la cible n'existe plus
        h.svc.move(h.gid, 2, 1, 5, expected=_exp(h.queue()[1]))
    assert h.urls() == before

async def test_stale_is_checked_before_permissions(harness):
    h = harness; h.guild.add_member(1, admin=True, channel_id=BOT_CHANNEL); h.guild.add_member(2, channel_id=BOT_CHANNEL)
    await h.svc.enqueue(h.gid, 1, A)                               # titre de l'admin : 2 n'a pas le droit
    with pytest.raises(StaleQueueError):
        h.svc.remove_at(h.gid, 2, 0, expected={"url": "autre", "added_by": "1", "ts": 1})

async def test_without_expected_nothing_changes(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL); await h.svc.enqueue(h.gid, 2, A)
    assert h.svc.remove_at(h.gid, 2, 5) is False and h.svc.move(h.gid, 2, 0, 3) is False
