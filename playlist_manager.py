# playlist_manager.py

import os
import json
from threading import Lock

playlist_lock = Lock()

class PlaylistManager:
    def __init__(self, guild_id):
        self.guild_id = str(guild_id)
        self.file = os.path.join(os.path.dirname(__file__), f"playlist_{self.guild_id}.json")
        self.reload()

    def reload(self):
        with playlist_lock:
            if not os.path.exists(self.file):
                self.queue = []
                self.save()
            else:
                with open(self.file, "r") as f:
                    try:
                        self.queue = json.load(f)
                    except Exception as e:
                        self.queue = []
                        print(f"[PlaylistManager] ERREUR: Playlist corrompue, init à vide. {e}")

    def save(self):
        with playlist_lock:
            with open(self.file, "w") as f:
                json.dump(self.queue, f)

    def add(self, url):
        with playlist_lock:
            self.queue.append(url)
            self.save()

    def skip(self):
        with playlist_lock:
            if self.queue:
                self.queue.pop(0)
            self.save()

    def stop(self):
        with playlist_lock:
            self.queue = []
            self.save()

    def get_queue(self):
        with playlist_lock:
            return list(self.queue)

    def get_current(self):
        with playlist_lock:
            return self.queue[0] if self.queue else None

    def to_dict(self):
        with playlist_lock:
            return {
                "queue": list(self.queue),
                "current": self.queue[0] if self.queue else None
            }


