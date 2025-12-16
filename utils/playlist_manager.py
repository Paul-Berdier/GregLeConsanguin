import os
import json
import time
import tempfile
import logging
from threading import RLock
from typing import List, Dict, Optional, Any
from pathlib import Path

log = logging.getLogger(__name__)


class PlaylistManager:
    """
    Gestion d'une playlist *par serveur Discord (guild)*.
    - Stockage JSON: { now_playing: {...} | null, queue: [ {title, url, ...}, ... ] }
    - Thread-safe via RLock
    - Écriture ATOMIQUE (tempfile + rename)
    - Ne JAMAIS recharger depuis disque pendant save() (source de vérité = mémoire)
    """

    def __init__(self, guild_id: str | int, base_dir: Optional[str] = None):
        """
        base_dir:
          - si None -> env PLAYLIST_DIR -> ./playlists (à la racine d'exécution)
        """
        self.guild_id = str(guild_id)

        # Dossier playlists: env > param > default local
        root = Path(base_dir or os.getenv("PLAYLIST_DIR") or "playlists").expanduser()
        root.mkdir(parents=True, exist_ok=True)

        self.file = str(root / f"playlist_{self.guild_id}.json")
        self.queue: List[Dict[str, Any]] = []
        self.now_playing: Optional[Dict[str, Any]] = None
        self.lock = RLock()

        log.info("[PlaylistManager %s] Init — file=%s", self.guild_id, self.file)
        self.reload()

    # ------------------------- I/O SÉCURISÉ -------------------------

    def _safe_write(self, data: Any) -> None:
        """
        Écrit *seulement* l'état courant mémoire dans un tmp file, puis rename.
        `data` attendu: list (la queue). `now_playing` vient de self.now_playing.
        """
        directory = os.path.dirname(self.file)
        os.makedirs(directory, exist_ok=True)

        payload = {
            "now_playing": self.now_playing if isinstance(self.now_playing, (dict, type(None))) else None,
            "queue": data if isinstance(data, list) else [],
        }

        with tempfile.NamedTemporaryFile("w", delete=False, dir=directory, suffix=".tmp", encoding="utf-8") as tf:
            json.dump(payload, tf, ensure_ascii=False)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name

        os.replace(tmp_name, self.file)

        qlen = len(payload.get("queue", []))
        log.debug("[PlaylistManager %s] Sauvegarde atomique (%d items).", self.guild_id, qlen)

    def reload(self) -> None:
        """Recharge la playlist depuis le disque (migration OK)."""
        with self.lock:
            if not os.path.exists(self.file):
                self.queue = []
                self.now_playing = None
                self._safe_write(self.queue)
                log.info("[PlaylistManager %s] Nouveau fichier créé (vide).", self.guild_id)
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

                self.queue = [self._coerce_item(x) for x in (q or [])]
                self.now_playing = self._coerce_item(np_raw) if isinstance(np_raw, dict) else None

                log.debug(
                    "[PlaylistManager %s] Reload (%d items, now_playing=%s).",
                    self.guild_id, len(self.queue), "oui" if self.now_playing else "non"
                )

            except Exception as e:
                log.warning("[PlaylistManager %s] ERREUR lecture JSON -> reset. %s", self.guild_id, e)
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
        now_ts = int(time.time())

        if isinstance(x, dict):
            item = {**x}

            url = item.get("url") or item.get("webpage_url") or item.get("link")
            url = self._clean_url_value(url)

            title = (item.get("title") or "").strip() or url or "Titre inconnu"

            dur = self._to_int_or_none(item.get("duration", None))

            item["title"] = title
            item["url"] = url
            item["artist"] = item.get("artist") or item.get("uploader") or item.get("channel") or None
            item["thumb"] = item.get("thumb") or item.get("thumbnail") or None
            item["duration"] = dur

            item.setdefault("added_by", None)
            item.setdefault("priority", item.get("priority"))
            item.setdefault("provider", item.get("provider"))
            item.setdefault("ts", item.get("ts") or now_ts)

            # alias overlay
            item.setdefault("requested_by", item.get("added_by"))

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
                "requested_by": None,
                "priority": None,
                "provider": None,
                "ts": now_ts,
            }

        if x is not None:
            log.debug("[PlaylistManager %s] Élément illisible ignoré: %r", self.guild_id, x)

        return {
            "title": "Inconnu",
            "url": "about:blank",
            "artist": None,
            "thumb": None,
            "duration": None,
            "added_by": None,
            "requested_by": None,
            "priority": None,
            "provider": None,
            "ts": now_ts,
        }

    # ------------------------- API PUBLIQUE -------------------------

    def add(self, item: Dict[str, Any] | str, added_by: Optional[str | int] = None) -> None:
        with self.lock:
            obj = self._coerce_item(item)
            if added_by is not None:
                obj["added_by"] = str(added_by)
                obj["requested_by"] = str(added_by)
            self.queue.append(obj)
            self.save()

    def add_many(self, items: List[Dict[str, Any] | str], added_by: Optional[str | int] = None) -> int:
        with self.lock:
            count = 0
            for it in items:
                obj = self._coerce_item(it)
                if added_by is not None:
                    obj["added_by"] = str(added_by)
                    obj["requested_by"] = str(added_by)
                self.queue.append(obj)
                count += 1
            self.save()
            return count

    def pop_next(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if not self.queue:
                return None
            item = self.queue.pop(0)
            self.now_playing = item
            self.save()
            return dict(item)

    def skip(self) -> None:
        with self.lock:
            if self.queue:
                _ = self.queue.pop(0)
            self.save()

    def stop(self) -> None:
        with self.lock:
            self.queue = []
            self.now_playing = None
            self.save()

    def remove_at(self, index: int) -> bool:
        with self.lock:
            if 0 <= index < len(self.queue):
                _ = self.queue.pop(index)
                self.save()
                return True
            return False

    def move(self, src: int, dst: int) -> bool:
        with self.lock:
            if src == dst:
                return False
            n = len(self.queue)
            if not (0 <= src < n and 0 <= dst < n):
                return False
            item = self.queue.pop(src)
            self.queue.insert(dst, item)
            self.save()
            return True

    # ------------------------- LECTURE & ÉTAT -------------------------

    def peek_all(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(x) for x in self.queue]

    def get_queue(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(x) for x in self.queue]

    def get_current(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if self.now_playing:
                return dict(self.now_playing)
            return dict(self.queue[0]) if self.queue else None

    def length(self) -> int:
        with self.lock:
            return len(self.queue)

    def to_dict(self) -> Dict[str, Any]:
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    pm = PlaylistManager(123456789)
    pm.add("https://youtu.be/abc", added_by="42")
    pm.add({"title": "Test YT", "url": "https://youtu.be/def", "added_by": "me", "duration": "215;"})
    print("QUEUE :", [q["title"] for q in pm.get_queue()])
    it = pm.pop_next()
    print("POPPED :", it and it.get("title"))
    print("CURRENT (after pop) :", (pm.get_current() or {}).get("title"))
    pm.stop()
