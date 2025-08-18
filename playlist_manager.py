# playlist_manager.py

import os
import json
import time
import tempfile
from threading import RLock
from typing import List, Dict, Optional, Any


class PlaylistManager:
    """
    Gestion d'une playlist *par serveur Discord (guild)*.
    - Stockage JSON {queue: [ {title, url, added_by, ts}, ... ]}
    - Thread-safe via RLock (re-entrant, pour éviter l'auto-deadlock)
    - Écriture ATOMIQUE (tempfile + rename) pour éviter de corrompre le fichier
    """

    # Schéma minimum attendu pour un item de playlist
    REQUIRED_KEYS = {"title", "url", "artist", "thumb", "duration"}

    def __init__(self, guild_id: str | int):
        os.makedirs("playlists", exist_ok=True)
        self.guild_id = str(guild_id)
        self.file = os.path.join(os.path.dirname(__file__), f"playlists/playlist_{self.guild_id}.json")
        self.queue: List[Dict[str, Any]] = []
        self.lock = RLock()
        self.reload()

    # ------------------------- I/O SÉCURISÉ -------------------------

    def _safe_write(self, data: Any) -> None:
        directory = os.path.dirname(self.file)
        os.makedirs(directory, exist_ok=True)
        payload = {"queue": data} if isinstance(data, list) else data
        with tempfile.NamedTemporaryFile("w", delete=False, dir=directory, suffix=".tmp", encoding="utf-8") as tf:
            json.dump(payload, tf, ensure_ascii=False)
            tmp_name = tf.name
        os.replace(tmp_name, self.file)
        print(
            f"[PlaylistManager {self.guild_id}] 💾 Sauvegarde atomique effectuée ({len(payload.get('queue', []))} items).")

    def reload(self) -> None:
        """Recharge la playlist depuis le disque, avec migration si nécessaire."""
        with self.lock:
            if not os.path.exists(self.file):
                self.queue = []
                self._safe_write(self.queue)
                print(f"[PlaylistManager {self.guild_id}] 📂 Nouveau fichier de playlist créé (vide).")
                return

            try:
                with open(self.file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Migration: ancien format [str_url, ...] -> [{title,url}, ...]
                if isinstance(data, dict) and "queue" in data:
                    q = data["queue"]
                elif isinstance(data, list):
                    q = data
                else:
                    q = []
                self.queue = [self._coerce_item(x) for x in q]
                print(f"[PlaylistManager {self.guild_id}] 🔄 Playlist rechargée ({len(self.queue)} items).")
            except Exception as e:
                print(f"[PlaylistManager {self.guild_id}] ⚠️ ERREUR lecture JSON, reset à vide. {e}")
                self.queue = []
                self._safe_write(self.queue)

    def save(self) -> None:
        """Sauvegarde la queue actuelle sur disque (atomique)."""
        with self.lock:
            self._safe_write(self.queue)

    # ------------------------- UTILITAIRES -------------------------

    def _coerce_item(self, x: Any) -> Dict[str, Any]:
        if isinstance(x, dict):
            item = {**x}
            if not self.REQUIRED_KEYS.issubset(item.keys()):
                url = item.get("url") or item.get("webpage_url") or item.get("link")
                title = item.get("title") or url or "Titre inconnu"
                item["title"] = title
                item["url"] = url or "about:blank"

            # ✅ conserver toutes les métadonnées si présentes
            item.setdefault("artist", None)
            item.setdefault("thumb", None)
            item.setdefault("duration", None)
            item.setdefault("added_by", None)
            item.setdefault("ts", int(time.time()))
            return item

        # Ancien format: string = url
        if isinstance(x, str):
            return {
                "title": x,
                "url": x,
                "added_by": None,
                "ts": int(time.time()),
            }

        # Inconnu: on jette, mais on logue
        print(f"[PlaylistManager {self.guild_id}] 🙄 Élément illisible, ignoré: {x!r}")
        return {
            "title": "Inconnu",
            "url": "about:blank",
            "added_by": None,
            "ts": int(time.time()),
        }

    # ------------------------- API PUBLIQUE -------------------------

    def add(self, item: Dict[str, Any] | str, added_by: Optional[str | int] = None) -> None:
        """Ajoute un *seul* item (url ou dict)."""
        with self.lock:
            obj = self._coerce_item(item)
            if added_by is not None:
                obj["added_by"] = str(added_by)
            self.queue.append(obj)
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ➕ Ajouté: {obj.get('title')} — {obj.get('url')} "
                  f"(oui oui, encore… *soupir*)")

    def add_many(self, items: List[Dict[str, Any] | str], added_by: Optional[str | int] = None) -> int:
        """Ajoute plusieurs items d’un coup. Renvoie le nombre ajoutés."""
        with self.lock:
            count = 0
            for it in items:
                obj = self._coerce_item(it)
                if added_by is not None:
                    obj["added_by"] = str(added_by)
                self.queue.append(obj)
                count += 1
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ➕➕ Ajouté {count} éléments à la queue.")
            return count

    def pop_next(self) -> Optional[Dict[str, Any]]:
        """Retire et renvoie le prochain item (tête de file)."""
        with self.lock:
            if not self.queue:
                print(f"[PlaylistManager {self.guild_id}] 💤 pop_next sur queue vide, quelle tristesse.")
                return None
            item = self.queue.pop(0)
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⏭️ Prochain: {item.get('title')}")
            return item

    def skip(self) -> None:
        """Alias pratique pour *retirer* le premier élément."""
        with self.lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager {self.guild_id}] ⏩ Skip: {skipped.get('title')} — {skipped.get('url')}")
            else:
                print(f"[PlaylistManager {self.guild_id}] ⏩ Skip demandé mais c’est vide, évidemment.")
            self.save()

    def stop(self) -> None:
        """Vide entièrement la playlist."""
        with self.lock:
            self.queue = []
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⛔ Playlist vidée (stop). Le silence… enfin.")

    def remove_at(self, index: int) -> bool:
        """Supprime l’élément à l’index donné. Renvoie True si OK."""
        with self.lock:
            if 0 <= index < len(self.queue):
                removed = self.queue.pop(index)
                self.save()
                print(f"[PlaylistManager {self.guild_id}] 🗑️ Supprimé #{index+1}: {removed.get('title')}")
                return True
            print(f"[PlaylistManager {self.guild_id}] ❌ remove_at index hors bornes: {index}")
            return False

    def move(self, src: int, dst: int) -> bool:
        """Déplace l’élément de `src` vers `dst` (réordonnancement)."""
        with self.lock:
            n = len(self.queue)
            if not (0 <= src < n and 0 <= dst < n):
                print(f"[PlaylistManager {self.guild_id}] ❌ move invalide: src={src}, dst={dst}, n={n}")
                return False
            item = self.queue.pop(src)
            self.queue.insert(dst, item)
            self.save()
            print(f"[PlaylistManager {self.guild_id}] 🔀 Déplacé '{item.get('title')}' de {src} vers {dst}.")
            return True

    # ------------------------- LECTURE & ÉTAT -------------------------

    def get_queue(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.queue)

    def get_current(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.queue[0] if self.queue else None

    def length(self) -> int:
        with self.lock:
            return len(self.queue)

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "queue": list(self.queue),
                "current": self.queue[0] if self.queue else None,
            }


# Test rapide (synchrone)
if __name__ == "__main__":
    pm = PlaylistManager(123456789)
    pm.add("https://soundcloud.com/truc/chanson1", added_by="42")
    pm.add({"title": "Test YT", "url": "https://youtu.be/abc", "added_by": "me"})
    print("QUEUE :", [q["title"] for q in pm.get_queue()])
    print("CURRENT :", (pm.get_current() or {}).get("title"))
    pm.skip()
    print("APRÈS SKIP, CURRENT :", (pm.get_current() or {}).get("title"))
    pm.move(0, 0)  # no-op
    pm.stop()
    print("VIDÉ :", pm.get_queue())
