# utils/playlist_manager.py

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional


class PlaylistManager:
    """
    Gestion d'une playlist *par serveur Discord (guild)*.

    Format JSON:
      {
        "now_playing": { ... } | null,
        "queue": [ {title, url, artist, thumb, duration, ...}, ... ]
      }

    Garanties:
    - Thread-safe via RLock
    - Écriture ATOMIQUE (tempfile + replace)
    - Source de vérité = mémoire (pas de reload pendant save)
    """

    def __init__(self, guild_id: str | int, playlist_dir: str | os.PathLike | None = None):
        self.guild_id = str(guild_id).strip()

        # ✅ chemin robuste : par défaut ./playlists (racine process)
        base_dir = Path(playlist_dir) if playlist_dir else Path(os.getenv("PLAYLIST_DIR", "playlists"))
        base_dir.mkdir(parents=True, exist_ok=True)

        self.file = str(base_dir / f"playlist_{self.guild_id}.json")
        self.queue: List[Dict[str, Any]] = []
        self.now_playing: Optional[Dict[str, Any]] = None
        self.lock = RLock()

        # Log minimal mais utile
        print(f"[PlaylistManager {self.guild_id}] ⚙️ Init — file={self.file}")
        self.reload()

    # ------------------------- I/O SÉCURISÉ -------------------------

    def _safe_write(self) -> None:
        """
        Écrit *seulement* l'état courant en mémoire dans un tmp file, puis replace atomique.
        """
        directory = Path(self.file).parent
        directory.mkdir(parents=True, exist_ok=True)

        payload = {
            "now_playing": self.now_playing if isinstance(self.now_playing, (dict, type(None))) else None,
            "queue": self.queue if isinstance(self.queue, list) else [],
        }

        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(directory),
            suffix=".tmp",
            encoding="utf-8",
        ) as tf:
            json.dump(payload, tf, ensure_ascii=False)
            tmp_name = tf.name

        os.replace(tmp_name, self.file)
        print(f"[PlaylistManager {self.guild_id}] 💾 Sauvegarde atomique ({len(payload['queue'])} items).")

    def reload(self) -> None:
        """
        Recharge la playlist depuis le disque (migration OK).
        """
        with self.lock:
            if not os.path.exists(self.file):
                self.queue = []
                self.now_playing = None
                self._safe_write()
                print(f"[PlaylistManager {self.guild_id}] 📂 Nouveau fichier créé (vide).")
                return

            try:
                with open(self.file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Migration & normalisation
                if isinstance(data, dict):
                    q = data.get("queue", [])
                    np_raw = data.get("now_playing", None)
                elif isinstance(data, list):
                    # vieux format: le fichier = liste directement
                    q = data
                    np_raw = None
                else:
                    q = []
                    np_raw = None

                self.queue = [self._coerce_item(x) for x in (q or [])]
                self.now_playing = self._coerce_item(np_raw) if isinstance(np_raw, dict) else None

                print(
                    f"[PlaylistManager {self.guild_id}] 🔄 Reload "
                    f"({len(self.queue)} items, now_playing={'oui' if self.now_playing else 'non'})."
                )
            except Exception as e:
                print(f"[PlaylistManager {self.guild_id}] ⚠️ JSON invalide → reset vide. {e}")
                self.queue = []
                self.now_playing = None
                self._safe_write()

    def save(self) -> None:
        """Sauvegarde l'état courant sur disque (atomique)."""
        with self.lock:
            self._safe_write()

    # ------------------------- UTILITAIRES -------------------------

    @staticmethod
    def _clean_url_value(u: Any) -> str:
        if not u:
            return "about:blank"
        s = str(u).strip().strip('\'"')
        while s.endswith(";"):
            s = s[:-1]
        return s

    @staticmethod
    def _to_int_or_none(v: Any) -> Optional[int]:
        try:
            iv = int(float(v))
            return iv if iv >= 0 else None
        except Exception:
            return None

    def _coerce_item(self, x: Any) -> Dict[str, Any]:
        """
        Normalise un track en dict standard.
        """
        ts = int(time.time())

        if isinstance(x, dict):
            item = {**x}

            url = item.get("url") or item.get("webpage_url") or item.get("link")
            url = self._clean_url_value(url)

            title = item.get("title") or url or "Titre inconnu"
            dur = self._to_int_or_none(item.get("duration"))

            item["title"] = title
            item["url"] = url
            item["artist"] = item.get("artist") or item.get("uploader") or item.get("channel") or None
            item["thumb"] = item.get("thumb") or item.get("thumbnail") or None
            item["duration"] = dur

            item.setdefault("added_by", None)
            item.setdefault("priority", item.get("priority"))
            item.setdefault("provider", item.get("provider"))
            item.setdefault("ts", ts)
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
                "priority": None,
                "provider": None,
                "ts": ts,
            }

        if x is not None:
            print(f"[PlaylistManager {self.guild_id}] 🙄 Élément illisible ignoré: {x!r}")

        return {
            "title": "Inconnu",
            "url": "about:blank",
            "artist": None,
            "thumb": None,
            "duration": None,
            "added_by": None,
            "priority": None,
            "provider": None,
            "ts": ts,
        }

    # ------------------------- API PUBLIQUE -------------------------

    def add(self, item: Dict[str, Any] | str, added_by: Optional[str | int] = None) -> Dict[str, Any]:
        """Ajoute un *seul* item (url ou dict). Retourne l'item normalisé."""
        with self.lock:
            obj = self._coerce_item(item)
            if added_by is not None and str(added_by).strip():
                obj["added_by"] = str(added_by)
            self.queue.append(obj)
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ➕ Ajouté: {obj.get('title')} — {obj.get('url')}")
            return obj

    def add_many(self, items: List[Dict[str, Any] | str], added_by: Optional[str | int] = None) -> int:
        """Ajoute plusieurs items. Retourne le nombre ajoutés."""
        with self.lock:
            count = 0
            for it in items:
                obj = self._coerce_item(it)
                if added_by is not None and str(added_by).strip():
                    obj["added_by"] = str(added_by)
                self.queue.append(obj)
                count += 1
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ➕➕ Ajouté {count} éléments.")
            return count

    def pop_next(self) -> Optional[Dict[str, Any]]:
        """
        Retire et renvoie le prochain item (tête de file) et définit now_playing.
        """
        with self.lock:
            if not self.queue:
                print(f"[PlaylistManager {self.guild_id}] 💤 pop_next sur queue vide.")
                return None
            item = self.queue.pop(0)
            self.now_playing = item
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⏭️ Prochain: {item.get('title')}")
            return item

    def skip(self) -> Optional[Dict[str, Any]]:
        """
        Supprime le 1er élément de queue (pas le now_playing).
        Retourne l'élément supprimé ou None.
        """
        with self.lock:
            if not self.queue:
                print(f"[PlaylistManager {self.guild_id}] ⏩ Skip demandé mais queue vide.")
                return None
            skipped = self.queue.pop(0)
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⏩ Skip: {skipped.get('title')} — {skipped.get('url')}")
            return skipped

    def stop(self) -> None:
        """Vide entièrement la playlist et oublie now_playing."""
        with self.lock:
            self.queue = []
            self.now_playing = None
            self.save()
            print(f"[PlaylistManager {self.guild_id}] ⛔ Playlist vidée (stop).")

    def remove_at(self, index: int) -> bool:
        """Supprime l’élément à l’index donné. True si OK."""
        with self.lock:
            if 0 <= index < len(self.queue):
                removed = self.queue.pop(index)
                self.save()
                print(f"[PlaylistManager {self.guild_id}] 🗑️ Supprimé #{index+1}: {removed.get('title')}")
                return True
            print(f"[PlaylistManager {self.guild_id}] ❌ remove_at hors bornes: {index}")
            return False

    def move(self, src: int, dst: int) -> bool:
        """Déplace l’élément de `src` vers `dst`."""
        with self.lock:
            if src == dst:
                return False
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
        def _expose(track: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not isinstance(track, dict):
                return None
            t = dict(track)
            t["requested_by"] = t.get("added_by")
            return t

        with self.lock:
            now_play = _expose(self.now_playing)
            return {
                "now_playing": now_play,
                "current": now_play,
                "queue": [_expose(it) for it in self.queue],
            }

        # ------------------------- COMPAT / LEGACY -------------------------

        def peek_all(self) -> List[Dict[str, Any]]:
            """
            Compat rétro : historiquement `peek_all()` renvoyait la LISTE de la queue.
            Certains services (priority rules) l'utilisent comme une liste indexable.
            """
            return self.get_queue()

        def peek_queue(self) -> List[Dict[str, Any]]:
            """
            Compat éventuelle : renvoie une copie de la queue.
            """
            return self.get_queue()

        def peek_state(self) -> Dict[str, Any]:
            """
            Snapshot complet (now_playing/current/queue) si besoin côté API/overlay.
            """
            return self.to_dict()


if __name__ == "__main__":
    pm = PlaylistManager(123456789)
    pm.add("https://youtu.be/abc", added_by="42")
    pm.add({"title": "Test YT", "url": "https://youtu.be/def", "added_by": "me", "duration": "215;"})
    print("QUEUE :", [q["title"] for q in pm.get_queue()])
    it = pm.pop_next()
    print("POPPED :", it and it.get("title"))
    print("CURRENT (after pop) :", (pm.get_current() or {}).get("title"))
    pm.stop()
