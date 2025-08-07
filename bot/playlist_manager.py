"""Thread‑safe playlist management for each Discord guild.

Each guild has its own playlist file on disk.  The playlist is a list of
objects (dicts) containing at minimum ``title`` and ``url`` keys.  A per‑
instance :class:`threading.RLock` protects concurrent access to the queue.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List


class PlaylistManager:
    """Manages a per‑guild playlist persisted to disk.

    A playlist is a list of items, where each item is a mapping with keys
    ``title`` and ``url``.  If more metadata is added in the future the
    structure can be extended.  The underlying file is stored in
    ``data/playlists/playlist_{guild_id}.json`` relative to the package root.
    """

    def __init__(self, guild_id: str | int) -> None:
        self.guild_id = str(guild_id)
        # Determine a directory to persist playlist files.  Use a data
        # directory at the project root; ensure it exists.
        root_dir = Path(__file__).resolve().parent.parent.parent
        playlists_dir = root_dir / "data" / "playlists"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        self.file = playlists_dir / f"playlist_{self.guild_id}.json"
        self.queue: List[Dict[str, Any]] = []
        self.lock = RLock()
        self.reload()

    def reload(self) -> None:
        """Load the playlist from disk, resetting ``self.queue``.

        If the file does not exist an empty playlist is initialised and saved.
        Errors reading or parsing the file cause the queue to reset to empty.
        """
        with self.lock:
            if not self.file.exists():
                self.queue = []
                self.save()
                return
            try:
                with self.file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Ensure a list of dicts.  Coerce plain strings to an
                    # object with identical title and url for backwards compat.
                    new_queue: List[Dict[str, Any]] = []
                    for item in data:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("name") or item.get("id") or "Unk"
                            url = item.get("url") or item.get("href") or title
                            new_queue.append({"title": title, "url": url})
                        else:
                            new_queue.append({"title": str(item), "url": str(item)})
                    self.queue = new_queue
                print(f"[PlaylistManager {self.guild_id}] Playlist rechargée ({len(self.queue)} sons)")
            except Exception as e:
                print(f"[PlaylistManager {self.guild_id}] ERREUR: Playlist corrompue, reset à vide. {e}")
                self.queue = []

    def save(self) -> None:
        """Persist the current playlist to disk."""
        with self.lock:
            with self.file.open("w", encoding="utf-8") as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)
            print(f"[PlaylistManager {self.guild_id}] Playlist sauvegardée ({len(self.queue)} sons)")

    def add(self, item: Dict[str, Any]) -> None:
        """Append a track to the playlist and save.

        The ``item`` must be a mapping with at minimum ``title`` and ``url``.
        """
        with self.lock:
            # Coerce to the expected shape
            title = item.get("title") or item.get("name") or item.get("id") or str(item)
            url = item.get("url") or title
            self.queue.append({"title": title, "url": url})
            self.save()
            print(f"[PlaylistManager {self.guild_id}] Ajouté: {{'title': {title!r}, 'url': {url!r}}}")

    def skip(self) -> None:
        """Remove the first track from the queue and save."""
        with self.lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager {self.guild_id}] Skip: {skipped}")
            self.save()

    def stop(self) -> None:
        """Clear the entire queue and save."""
        with self.lock:
            self.queue = []
            self.save()
            print(f"[PlaylistManager {self.guild_id}] Playlist vidée (stop)")

    def get_queue(self) -> List[Dict[str, Any]]:
        """Return a shallow copy of the current queue."""
        with self.lock:
            return list(self.queue)

    def get_current(self) -> Dict[str, Any] | None:
        """Return the first track in the queue or ``None`` if empty."""
        with self.lock:
            return self.queue[0] if self.queue else None

    def to_dict(self) -> Dict[str, Any]:
        """Return the playlist as a serialisable dict including current track."""
        with self.lock:
            return {
                "queue": list(self.queue),
                "current": self.queue[0] if self.queue else None
            }