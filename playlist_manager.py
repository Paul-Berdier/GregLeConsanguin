# playlist_manager.py

import os
import json
from threading import Lock

print("[DEBUG] Début playlist_manager.py")

# Chemin vers le fichier playlist.json (toujours la source de vérité)
PLAYLIST_FILE = os.path.join(os.path.dirname(__file__), "playlist.json")
print(f"[DEBUG] PLAYLIST_FILE = {PLAYLIST_FILE}")

# Verrou pour accès thread-safe si web + bot tournent dans le même process (optionnel mais recommandé)
playlist_lock = Lock()

class PlaylistManager:
    def __init__(self):
        print("[DEBUG] Début __init__ PlaylistManager")
        self.reload()
        print("[DEBUG] Fin __init__ PlaylistManager")

    def reload(self):
        """Recharge la playlist depuis le fichier. À appeler après une MAJ externe."""
        print("[DEBUG] PlaylistManager.reload()")
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
                    except Exception as e:
                        self.queue = []
                        self.current = None
                        print(f"[PlaylistManager] ERREUR: Playlist corrompue, initialisation à vide. {e}")

    def save(self):
        """Sauvegarde la queue actuelle dans le fichier JSON."""
        print("[DEBUG] PlaylistManager.save()")
        with playlist_lock:
            with open(PLAYLIST_FILE, "w") as f:
                json.dump(self.queue, f)
                print(f"[PlaylistManager] Playlist sauvegardée: {self.queue}")

    def add(self, url):
        """Ajoute une musique à la file d'attente."""
        print(f"[DEBUG] PlaylistManager.add({url})")
        with playlist_lock:
            self.queue.append(url)
            self.current = self.queue[0] if self.queue else None
            self.save()
            print(f"[PlaylistManager] Ajout: {url}")

    def skip(self):
        """Passe à la musique suivante."""
        print("[DEBUG] PlaylistManager.skip()")
        with playlist_lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager] Skip: {skipped}")
            self.current = self.queue[0] if self.queue else None
            self.save()

    def stop(self):
        """Vide la playlist."""
        print("[DEBUG] PlaylistManager.stop()")
        with playlist_lock:
            self.queue = []
            self.current = None
            self.save()
            print("[PlaylistManager] Playlist vidée (stop)")

    def get_queue(self):
        """Renvoie la file d'attente complète (copie)."""
        print("[DEBUG] PlaylistManager.get_queue()")
        with playlist_lock:
            return list(self.queue)

    def get_current(self):
        """Renvoie la musique en cours, ou None."""
        print("[DEBUG] PlaylistManager.get_current()")
        with playlist_lock:
            return self.current

    def to_dict(self):
        """Pour API / WebSocket : serialisable en JSON."""
        print("[DEBUG] PlaylistManager.to_dict()")
        with playlist_lock:
            return {
                "queue": list(self.queue),
                "current": self.current
            }

# Utilisation typique :
if __name__ == "__main__":
    print("[DEBUG] main() PlaylistManager test")
    pm = PlaylistManager()
    pm.add("https://soundcloud.com/quelquechose/track1")
    pm.add("https://soundcloud.com/quelquechose/track2")
    print("QUEUE :", pm.get_queue())
    pm.skip()
    print("CURRENT :", pm.get_current())
    pm.stop()
    print("VIDÉ :", pm.get_queue())

