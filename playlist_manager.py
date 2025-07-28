# playlist_manager.py

import os
import json
from threading import Lock

# Chemin vers le fichier playlist.json (toujours la source de vérité)
PLAYLIST_FILE = os.path.join(os.path.dirname(__file__), "playlist.json")

# Verrou pour accès thread-safe si web + bot tournent dans le même process (optionnel mais recommandé)
playlist_lock = Lock()

class PlaylistManager:
    def __init__(self):
        self.reload()

    def reload(self):
        """Recharge la playlist depuis le fichier. À appeler après une MAJ externe."""
        with playlist_lock:
            if not os.path.exists(PLAYLIST_FILE):
                self.queue = []
                self.current = None
                self.save()
                print("[PlaylistManager] Nouvelle playlist créée (vide)")
            else:
                with open(PLAYLIST_FILE, "r") as f:
                    try:
                        self.queue = json.load(f)
                        self.current = self.queue[0] if self.queue else None
                        print(f"[PlaylistManager] Playlist rechargée: {self.queue}")
                    except Exception:
                        self.queue = []
                        self.current = None
                        print("[PlaylistManager] ERREUR: Playlist corrompue, initialisation à vide.")

    def save(self):
        """Sauvegarde la queue actuelle dans le fichier JSON."""
        with playlist_lock:
            with open(PLAYLIST_FILE, "w") as f:
                json.dump(self.queue, f)
                print(f"[PlaylistManager] Playlist sauvegardée: {self.queue}")

    def add(self, url):
        """Ajoute une musique à la file d'attente."""
        with playlist_lock:
            self.queue.append(url)
            self.current = self.queue[0] if self.queue else None
            self.save()
            print(f"[PlaylistManager] Ajout: {url}")

    def skip(self):
        """Passe à la musique suivante."""
        with playlist_lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager] Skip: {skipped}")
            self.current = self.queue[0] if self.queue else None
            self.save()

    def stop(self):
        """Vide la playlist."""
        with playlist_lock:
            self.queue = []
            self.current = None
            self.save()
            print("[PlaylistManager] Playlist vidée (stop)")

    def get_queue(self):
        """Renvoie la file d'attente complète (copie)."""
        with playlist_lock:
            return list(self.queue)

    def get_current(self):
        """Renvoie la musique en cours, ou None."""
        with playlist_lock:
            return self.current

    def to_dict(self):
        """Pour API / WebSocket : serialisable en JSON."""
        with playlist_lock:
            return {
                "queue": list(self.queue),
                "current": self.current
            }

# Utilisation typique :
if __name__ == "__main__":
    pm = PlaylistManager()
    pm.add("https://soundcloud.com/quelquechose/track1")
    pm.add("https://soundcloud.com/quelquechose/track2")
    print("QUEUE :", pm.get_queue())
    pm.skip()
    print("CURRENT :", pm.get_current())
    pm.stop()
    print("VIDÉ :", pm.get_queue())
