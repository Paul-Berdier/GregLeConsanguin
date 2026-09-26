"""greg_shared.priority.validate_move — invariant des 2 zones (prioritaire / normale)."""
from __future__ import annotations

import pytest

import greg_shared.priority as prio


@pytest.fixture(autouse=True)
def _clean_priority_env(monkeypatch):
    for var in ("GREG_OWNER_ID", "PRIORITY_THRESHOLD", "PRIORITY_ROLE_WEIGHTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(prio, "_overrides", {"weights": {}, "cap": None})
    monkeypatch.setattr(prio, "_initialized", True)


class _Bot:
    def get_guild(self, gid):
        return None  # membre introuvable → poids par défaut, pas admin


def P(name):
    return {"title": name, "priority": 80}


def N(name):
    return {"title": name, "priority": 10}


def _allowed(queue, src, dst):
    return prio.validate_move(queue, src, dst, requester_id=5, bot=_Bot(), guild_id=1).allowed


def _simulate(queue, src, dst):
    q = list(queue)
    q.insert(dst, q.pop(src))
    return q


def test_priority_item_can_move_to_last_slot_of_priority_zone():
    q = [P("p0"), P("p1"), P("p2"), N("n3")]
    assert _allowed(q, 1, 2) is True  # [p0, p2, p1, n3] : toujours dans la zone


def test_all_priority_queue_move_to_last_index():
    q = [P("p0"), P("p1"), P("p2")]
    assert _allowed(q, 0, 2) is True


def test_priority_item_cannot_be_demoted():
    q = [P("p0"), P("p1"), N("n2"), N("n3")]
    assert _allowed(q, 1, 2) is False
    assert prio.validate_move(q, 1, 3, 5, _Bot(), 1).reason == "cannot_demote_from_priority_zone"


def test_normal_item_cannot_be_promoted_but_can_move_within_normal_zone():
    q = [P("p0"), P("p1"), N("n2"), N("n3")]
    assert _allowed(q, 3, 2) is True
    assert _allowed(q, 3, 1) is False
    assert prio.validate_move(q, 2, 0, 5, _Bot(), 1).reason == "cannot_promote_to_priority_zone"


def test_exhaustive_sorted_queues_match_the_zone_invariant():
    for n_prio in range(0, 5):
        for n_norm in range(0, 5):
            q = [P(f"p{i}") for i in range(n_prio)] + [N(f"n{i}") for i in range(n_norm)]
            for src in range(len(q)):
                for dst in range(len(q)):
                    if src == dst:
                        continue
                    after = _simulate(q, src, dst)
                    flags = [prio.is_priority_item(it) for it in after]
                    sorted_ok = flags == sorted(flags, reverse=True)
                    assert _allowed(q, src, dst) is sorted_ok, (n_prio, n_norm, src, dst)


def test_unsorted_queue_move_inside_priority_block_is_allowed():
    # Un item normal remis en tête (retry) ne doit pas bloquer les moves légitimes.
    q = [N("n0"), P("p1"), P("p2"), N("n3")]
    assert _allowed(q, 2, 1) is True
    assert _allowed(q, 1, 3) is False
