"""queue_item_matches : comparaison de l'élément attendu (tests synchrones, hors du pytestmark asyncio)."""
from __future__ import annotations

import pytest
from bot.services.playlist_manager import queue_item_matches


@pytest.mark.parametrize("item,exp,ok", [
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": "2", "ts": 1700000000}, True),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": 2, "ts": 1700000000.0}, True),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "v", "added_by": "2", "ts": 1700000000}, False),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": "3", "ts": 1700000000}, False),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": "2", "ts": None}, False),
    ({"url": None, "added_by": None, "ts": 5}, {"url": "", "added_by": None, "ts": "5"}, True)])
def test_queue_item_matches(item, exp, ok):
    assert queue_item_matches(item, exp) is ok

def test_two_missing_ts_match():                     # plan B : expectedOf envoie ts: null pour un titre sans ts
    assert queue_item_matches({"url": "u", "added_by": "2", "ts": None}, {"url": "u", "added_by": "2", "ts": None}) is True
    assert queue_item_matches({"url": "u", "added_by": None}, {"url": "u", "added_by": None, "ts": None}) is True
