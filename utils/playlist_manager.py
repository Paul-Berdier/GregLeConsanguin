# utils/playlist_manager.py

import os
import json
import time
import tempfile
from threading import RLock
import traceback
from typing import List, Dict, Optional, Any


class PlaylistManager:
    """
    Gestion d'une playlist *par serveur Discord (guild)*.
    - Stockage JSON: { now_playing: {...} | null, queue: [ {title, url, ...}, ... ] }
    - Thread-safe via RLock
    - Écriture ATOMIQUE (tempfile + rename)
    - Ne JAMAIS recharger depuis disque pendant save() (source de vérité = mémoire)
    """

    REQUIRED_KEYS = {"title", "url", "artist", "thumb", "duration"}

    def __init__(self, guild_id: str | int):
        os.makedirs("../playlists", exist_ok=True)
        self.guild_id = str(guild_id)
        self.file = os.path.join("../playlists", f"playlist_{self.guild_id}.json")
        self.queue: List[Dict[str, Any]] = []
        self.now_playing: Optional[Dict[str, Any]] = None
        self.lock = RLock()
        print(f"[PlaylistManager {self.guild_id}] ⚙️ Init — file={self.file}")
        self.reload()

    # ------------------------- I/O SÉCURISÉ -------------------------

    def _safe_write(self, data: Any) -> None:
        """
        Écrit *seulement* l'état courant mémoire dans un tmp file, puis rename.
        `data` attendu: list (la queue). `now_playing` vient de self.now_playing.
        """
        directory = os.path.dirname(self.file)
        os.makedirs(directory, exist_ok=True)

        # On sérialise ce qu'on a EN MÉMOIRE (source de vérité)
        payload = {
            "now_playing": self.now_playing if isinstance(self.now_playing, (dict, type(None))) else None,
            "queue": data if isinstance(data, list) else []
        }

        with tempfile.NamedTemporaryFile("w", delete=False, dir=directory, suffix=".tmp", encoding="utf-8") as tf:
            json.dump(payload, tf, ensure_ascii=False)
            tmp_name = tf.name

        os.replace(tmp_name, self.file)

        qlen = len(payload.get("queue", []))
        print(f"[PlaylistManager {self.guild_id}] 💾 Sauvegarde atomique effectuée ({qlen} items).")

    def reload(self) -> None:
        """Recharge la playlist depuis le disque (migration OK)."""
        with self.lock:
            if not os.path.exists(self.file):
                self.queue = []
                self.now_playing = None
                self._safe_write(self.queue)
                print(f"[PlaylistManager {self.guild_id}] 📂 Nouveau fichier de playlist créé (vide).")
                return

            try:
                with open(self.file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Migration & normalisation
                if isinstance(data, dict):
                    q = data.get("queue", [])
                    np_raw = data.get("now_playing", None)
                elif isinstance(data, list):
                    # Très vieux format: le fichier = la liste directement
                    q = data
                    np_raw = None
                else:
                    q = []
                    np_raw = None

                self.queue = [self._coerce_item(x) for x in q]
                self.now_playing = self._coerce_item(np_raw) if isinstance(np_raw, dict) else None

                print(
                    f"[PlaylistManager {self.guild_id}] 🔄 Playlist rechargée "
                    f"({len(self.queue)} items, now_playing={'oui' if self.now_playing else 'non'})."
                )
                print(f"[DEBUG reload {self.guild_id}] Items: {[it.get('title') for it in self.queue]}")

            except Exception as e:
                print(f"[PlaylistManager {self.guild_id}] ⚠️ ERREUR lecture JSON → reset à vide. {e}")
                self.queue = []
                self.now_playing = None
                self._safe_write(self.queue)

    def save(self) -> None:
        """Sauvegarde l'état courant sur disque (atomique)."""
        with self.lock:
            self._safe_write(self.queue)

    # ------------------------- UTILITAIRES -------------------------

    @staticmethod
    def _clean_url_value(u: Any) -> str:
        if not u:
            return "about:blank"
        s = str(u).strip().strip('\'"')
        # Retire *tous* les ';' finaux (artefact UI)
        while s.endswith(';'):
            s = s[:-1]
        return s

    @staticmethod
    def _to_int_or_none(v: Any) -> Optional[int]:
        try:
            iv = int(float(v))  # accepte "215", 215.0, "215.0"
            return iv if iv >= 0 else None
        except Exception:
            return None

    def _coerce_item(self, x: Any) -> Dict[str, Any]:
        if isinstance(x, dict):
            item = {**x}

            # URL propre
            url = item.get("url") or item.get("webpage_url") or item.get("link")
            url = self._clean_url_value(url)

            # Titre
            title = item.get("title") or url or "Titre inconnu"

            # Duration propre (int ou None)
            dur = item.get("duration", None)
            dur = self._to_int_or_none(dur)

            # Normalisation
            item["title"] = title
            item["url"] = url
            item["artist"] = item.get("artist") or None
            item["thumb"] = item.get("thumb") or item.get("thumbnail") or None
            item["duration"] = dur
            item.setdefault("added_by", None)
            item.setdefault("ts", int(time.time()))
            return item

        if isinstance(x, str):
            url = self._clean_url_value(x)
            return {
                "title": url,
                "url": url,
                "artist": None,
                "thumb": None,
                "duration": None,
                "added_by": None,
                "ts": int(time.time()),
            }

        # Inconnu
        if x is not None:
            print(f"[PlaylistManager {self.guild_id}] 🙄 Élément illisible ignoré: {x!r}")
        return {
            "title": "Inconnu",
            "url": "about:blank",
            "artist": None,
            "thumb": None,
            "duration": None,
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
            print(f"[PlaylistManager {self.guild_id}] ➕ Ajouté: {obj.get('title')} — {obj.get('url')}")

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
        """Retire et renvoie le prochain item (tête de file) et définit now_playing."""
        with self.lock:
            if not self.queue:
                print(f"[PlaylistManager {self.guild_id}] 💤 pop_next sur queue vide.")
                return None
            item = self.queue.pop(0)
            self.now_playing = item  # ✅ trace du morceau courant
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⏭️ Prochain: {item.get('title')}")
            return item

    def skip(self) -> None:
        """Retire le premier élément (si présent)."""
        with self.lock:
            if self.queue:
                skipped = self.queue.pop(0)
                print(f"[PlaylistManager {self.guild_id}] ⏩ Skip: {skipped.get('title')} — {skipped.get('url')}")
            else:
                print(f"[PlaylistManager {self.guild_id}] ⏩ Skip demandé mais queue vide.")
            self.save()

    def stop(self) -> None:
        """Vide entièrement la playlist et oublie now_playing."""
        with self.lock:
            self.queue = []
            self.now_playing = None
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⛔ Playlist vidée (stop).")

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
        """Déplace l’élément de `src` vers `dst`."""
        with self.lock:
            if src == dst:
                return False  # no-op (évite save + log + broadcast)
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
        """Renvoie d'abord now_playing si présent, sinon la tête de queue."""
        with self.lock:
            if self.now_playing:
                return dict(self.now_playing)
            return dict(self.queue[0]) if self.queue else None

    def length(self) -> int:
        with self.lock:
            return len(self.queue)

    def to_dict(self) -> Dict[str, Any]:
        """Snapshot sérialisable pour l'API."""
        with self.lock:
            now_play = dict(self.now_playing) if isinstance(getattr(self, "now_playing", None), dict) else None
            payload = {
                # compat nouvelle/ancienne API
                "now_playing": now_play,
                "current": now_play,  # ← clé attendue par l’overlay/app
                "queue": [dict(it) for it in self.queue]
            }
            # DEBUG non intrusif
            try:
                print(
                    f"[DEBUG to_dict {self.guild_id}] queue={len(payload['queue'])} / current={'oui' if payload['current'] else 'non'}")
            except Exception:
                pass
            return payload


# Test rapide (synchrone)
if __name__ == "__main__":
    pm = PlaylistManager(123456789)
    pm.add("https://soundcloud.com/truc/chanson1", added_by="42")
    pm.add({"title": "Test YT", "url": "https://youtu.be/abc", "added_by": "me", "duration": "215;"})
    print("QUEUE :", [q["title"] for q in pm.get_queue()])
    print("CURRENT (before pop) :", (pm.get_current() or {}).get("title"))
    it = pm.pop_next()
    print("POPPED :", it and it.get("title"))
    print("CURRENT (after pop) :", (pm.get_current() or {}).get("title"))
    pm.skip()
    pm.stop()
    print("VIDÉ :", pm.get_queue())
