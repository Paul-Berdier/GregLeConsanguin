# tests/test_playlist_manager_ext.py
import json
import os
import time
from playlist_manager import PlaylistManager

def test_persistence_order_and_clear(tmp_path):
    pm = PlaylistManager('g1')
    pm.file = os.path.join(tmp_path, 'playlist.json')
    pm.save()
    tracks = [{"title": f"T{i}", "url": f"https://u/{i}"} for i in range(5)]
    for t in tracks: pm.add(t)
    # ordre respecté
    q = pm.get_queue()
    assert [t["title"] for t in q] == [f"T{i}" for i in range(5)]
    # persistance disque
    with open(pm.file) as f: data = json.load(f)
    assert len(data) == 5
    # skip décale bien
    pm.skip()
    assert pm.get_queue()[0]["title"] == "T1"
    # stop vide
    pm.stop()
    assert pm.get_queue() == []

def test_idempotent_save_load(tmp_path):
    pm = PlaylistManager('g2')
    pm.file = os.path.join(tmp_path, 'pl.json')
    pm.save()
    pm.add({"title":"X", "url":"u://x"})
    pm.save(); pm.save()
    # Vérifie le disque directement
    with open(pm.file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1 and data[0]["title"] == "X"
