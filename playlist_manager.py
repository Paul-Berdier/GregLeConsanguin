import os
import json
import asyncio

playlist_lock = asyncio.Lock()

class PlaylistManager:
    """
    Playlist unique PAR serveur Discord (guild).
    Chaque playlist est stockée dans un fichier JSON par serveur.
    Toutes les méthodes sont thread-safe avec asyncio.Lock (pour Discord).
    """

    def __init__(self, guild_id):
        self.guild_id = str(guild_id)
        self.file = os.path.join(os.path.dirname(__file__), f"playlist_{self.guild_id}.json")
        self.queue = []

    async def reload(self):
        async with playlist_lock:
            if not os.path.exists(self.file):
                self.queue = []
                await self.save()
            else:
                try:
                    with open(self.file, "r") as f:
                        self.queue = json.load(f)
                    print(f"[PlaylistManager {self.guild_id}] Playlist rechargée ({len(self.queue)} sons)")
                except Exception as e:
                    print(f"[PlaylistManager {self.guild_id}] ERREUR: Playlist corrompue, reset à vide. {e}")
                    self.queue = []

    async def save(self):
        async with playlist_lock:
            with open(self.file, "w") as f:
                json.dump(self.queue, f)
            print(f"[PlaylistManager {self.guild_id}] Playlist sauvegardée ({len(self.queue)} sons)")

    async def add(self, url):
        async with playlist_lock:
            self.queue.append(url)
            await self.save()
            print(f"[PlaylistManager {self.guild_id}] Ajouté: {url}")

    async def skip(self):
        async with playlist_lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager {self.guild_id}] Skip: {skipped}")
            await self.save()

    async def stop(self):
        async with playlist_lock:
            self.queue = []
            await self.save()
            print(f"[PlaylistManager {self.guild_id}] Playlist vidée (stop)")

    async def get_queue(self):
        async with playlist_lock:
            return list(self.queue)

    async def get_current(self):
        async with playlist_lock:
            return self.queue[0] if self.queue else None

    async def to_dict(self):
        async with playlist_lock:
            return {
                "queue": list(self.queue),
                "current": self.queue[0] if self.queue else None
            }

# Test rapide en async
if __name__ == "__main__":
    import asyncio
    async def test():
        pm = PlaylistManager(123456789)
        await pm.reload()
        await pm.add("https://soundcloud.com/truc/chanson1")
        print("QUEUE :", await pm.get_queue())
        await pm.skip()
        print("CURRENT :", await pm.get_current())
        await pm.stop()
        print("VIDÉ :", await pm.get_queue())
    asyncio.run(test())
