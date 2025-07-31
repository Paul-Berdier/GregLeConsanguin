import os
import json
from threading import Lock

playlist_lock = Lock()

class PlaylistManager:
    """
    Playlist unique PAR serveur Discord (guild).
    Chaque playlist est stockée dans un fichier JSON par serveur.
    Toutes les méthodes sont thread-safe (web + bot tournent en même temps).
    """

    def __init__(self, guild_id):
        self.guild_id = str(guild_id)
        self.file = os.path.join(os.path.dirname(__file__), f"playlist_{self.guild_id}.json")
        self.reload()

    def reload(self):
        """Recharge la playlist depuis le fichier (après modif externe, ou au boot)."""
        with playlist_lock:
            if not os.path.exists(self.file):
                self.queue = []
                self.save()
            else:
                print(f"[DEBUG][{self.guild_id}] Lock acquis pour add()")

                with open(self.file, "r") as f:
                    try:
                        self.queue = json.load(f)
                        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

                    except Exception as e:
                        print(f"[PlaylistManager {self.guild_id}] ERREUR: Playlist corrompue, reset à vide. {e}")
                        self.queue = []

    def save(self):
        """Sauvegarde la file d'attente actuelle."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            with open(self.file, "w") as f:
                json.dump(self.queue, f)
                print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

    def add(self, url):
        """Ajoute une musique à la queue."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            self.queue.append(url)
            self.save()
            print(f"[PlaylistManager {self.guild_id}] Ajouté: {url}")
            print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

    def skip(self):
        """Passe à la musique suivante."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager {self.guild_id}] Skip: {skipped}")
                print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

            self.save()

    def stop(self):
        """Vide la playlist."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            self.queue = []
            self.save()
            print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

            print(f"[PlaylistManager {self.guild_id}] Playlist vidée (stop)")

    def get_queue(self):
        """Renvoie la queue complète (copie)."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

            return list(self.queue)

    def get_current(self):
        """Renvoie la musique en cours, ou None."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

            return self.queue[0] if self.queue else None

    def to_dict(self):
        """Pour API / WebSocket : serialisable en JSON."""
        print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

        with playlist_lock:
            print(f"[DEBUG][{self.guild_id}] Lock relâché pour add()")

            return {
                "queue": list(self.queue),
                "current": self.queue[0] if self.queue else None
            }

# Test rapide
if __name__ == "__main__":
    pm = PlaylistManager(123456789)
    pm.add("https://soundcloud.com/truc/chanson1")
    print("QUEUE :", pm.get_queue())
    pm.skip()
    print("CURRENT :", pm.get_current())
    pm.stop()
    print("VIDÉ :", pm.get_queue())
