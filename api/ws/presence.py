# api/ws/presence.py

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Dict, List, Optional, Any


@dataclass
class PresenceEntry:
    sid: str
    user_id: Optional[str] = None
    guild_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=lambda: time.time())

    def touch(self) -> None:
        self.last_seen = time.time()


class PresenceRegistry:
    """
    Registre simple in-memory avec TTL + lock.
    - Utilisé pour debug/diagnostic overlay/web (qui est connecté à quelle guilde)
    - Ne sert PAS à la sécurité (juste observation)
    """

    def __init__(self, ttl_seconds: int = 45):
        self.ttl = int(ttl_seconds)
        self.by_sid: Dict[str, PresenceEntry] = {}
        self._lock = RLock()

    def register(
        self,
        sid: str,
        user_id: Optional[str] = None,
        guild_id: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> PresenceEntry:
        with self._lock:
            e = PresenceEntry(
                sid=str(sid),
                user_id=str(user_id) if user_id is not None and str(user_id).strip() else None,
                guild_id=str(guild_id) if guild_id is not None and str(guild_id).strip() else None,
                meta=dict(meta or {}),
            )
            self.by_sid[str(sid)] = e
            return e

    def update(
        self,
        sid: str,
        user_id: Optional[str] = None,
        guild_id: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        with self._lock:
            e = self.by_sid.get(str(sid))
            if not e:
                self.register(sid=sid, user_id=user_id, guild_id=guild_id, meta=meta)
                return

            if user_id is not None and str(user_id).strip():
                e.user_id = str(user_id).strip()
            if guild_id is not None:
                e.guild_id = str(guild_id).strip() if str(guild_id).strip() else None
            if meta:
                try:
                    e.meta.update(dict(meta))
                except Exception:
                    pass
            e.touch()

    def ping(self, sid: str) -> None:
        with self._lock:
            e = self.by_sid.get(str(sid))
            if e:
                e.touch()

    def remove(self, sid: str) -> None:
        with self._lock:
            self.by_sid.pop(str(sid), None)

    def sweep(self) -> int:
        """Supprime les entrées expirées. Retourne le nombre supprimé."""
        with self._lock:
            now = time.time()
            to_del = [sid for sid, e in self.by_sid.items() if now - e.last_seen > self.ttl]
            for sid in to_del:
                self.by_sid.pop(sid, None)
            return len(to_del)

    def list_by_guild(self, guild_id: str) -> List[PresenceEntry]:
        gid = str(guild_id).strip()
        with self._lock:
            return [e for e in self.by_sid.values() if (e.guild_id or "") == gid]

    def stats(self) -> dict:
        with self._lock:
            by_guild: Dict[str, int] = {}
            for e in self.by_sid.values():
                g = e.guild_id or "-"
                by_guild[g] = by_guild.get(g, 0) + 1
            return {
                "total": len(self.by_sid),
                "by_guild": by_guild,
                "ttl": self.ttl,
                "ts": time.time(),
            }

    def snapshot(self) -> List[dict]:
        """Debug: entrée par entrée (attention: potentiellement verbeux)."""
        with self._lock:
            return [
                {
                    "sid": e.sid,
                    "user_id": e.user_id,
                    "guild_id": e.guild_id,
                    "meta": e.meta,
                    "last_seen": e.last_seen,
                }
                for e in self.by_sid.values()
            ]


# ✅ Singleton (simple et efficace)
presence = PresenceRegistry(ttl_seconds=45)
