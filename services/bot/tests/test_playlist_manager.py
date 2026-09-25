"""PlaylistManager — pas de fichier créé en lecture, insertions atomiques, garde-fous."""
from __future__ import annotations

import threading

from bot.services.playlist_manager import PlaylistManager


def _it(i, **kw):
    d = {"title": f"t{i}", "url": f"https://www.youtube.com/watch?v=vid{i:08d}"}
    d.update(kw)
    return d


def test_reload_does_not_create_a_file(tmp_path):
    pm = PlaylistManager(1, playlist_dir=tmp_path)
    assert pm.get_queue() == []
    assert not (tmp_path / "playlist_1.json").exists()
    pm.add(_it(1))
    assert (tmp_path / "playlist_1.json").exists()


def test_insert_at_coerces_and_rejects_items_without_url(tmp_path):
    pm = PlaylistManager(2, playlist_dir=tmp_path)
    assert pm.insert_at(0, {}) is None
    assert pm.get_queue() == []
    obj = pm.insert_at(0, {"url": " https://x.y/z; ", "duration": "12"})
    assert obj["url"] == "https://x.y/z" and obj["duration"] == 12 and obj["title"]
    assert pm.get_queue()[0]["url"] == "https://x.y/z"


def test_insert_by_computes_position_under_lock(tmp_path):
    pm = PlaylistManager(3, playlist_dir=tmp_path)
    pm.add(_it(1))
    pm.add(_it(2))
    seen = []

    def pos(q):
        seen.append([x["url"] for x in q])
        return 1

    idx = pm.insert_by(_it(9), pos)
    assert idx == 1
    assert seen == [[_it(1)["url"], _it(2)["url"]]]
    assert [x["url"] for x in pm.get_queue()] == [_it(1)["url"], _it(9)["url"], _it(2)["url"]]


def test_insert_by_concurrent_threads_never_lose_items(tmp_path):
    pm = PlaylistManager(4, playlist_dir=tmp_path)

    def worker(base):
        for i in range(20):
            pm.insert_by(_it(base + i), lambda q: len(q))

    ts = [threading.Thread(target=worker, args=(k * 100,)) for k in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(pm.get_queue()) == 80


def test_remove_and_move_with_expected_item(tmp_path):
    pm = PlaylistManager(5, playlist_dir=tmp_path)
    for i in range(3):
        pm.add(_it(i))
    q = pm.get_queue()
    assert pm.remove_at(0, expected=q[1]) is False  # la file a « bougé » : on ne supprime rien
    assert len(pm.get_queue()) == 3
    assert pm.remove_at(1, expected=q[1]) is True
    q = pm.get_queue()
    assert pm.move(1, 0, expected=q[0]) is False
    assert pm.move(1, 0, expected=q[1]) is True
    assert [x["url"] for x in pm.get_queue()] == [_it(2)["url"], _it(0)["url"]]


def test_remove_last_where(tmp_path):
    pm = PlaylistManager(6, playlist_dir=tmp_path)
    pm.add(_it(1, repeat_tag="a"))
    pm.add(_it(2))
    pm.add(_it(1, repeat_tag="b"))
    removed = pm.remove_last_where(lambda it: it.get("repeat_tag") == "b")
    assert removed and removed["repeat_tag"] == "b"
    assert pm.remove_last_where(lambda it: it.get("repeat_tag") == "zzz") is None
    assert [x.get("repeat_tag") for x in pm.get_queue()] == ["a", None]
