from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class PresenceEntry:
    sid: str
    user_id: str
    guild_id: str | None
    meta: dict = field(default_factory=dict)
    last_seen: float = field(default_factory=lambda: time.time())

class PresenceRegistry:
    """
    Registre simple in-memory avec TTL.
    """

    def __init__(self, ttl_seconds: int = 45):
        self.ttl = ttl_seconds
        self.by_sid: Dict[str, PresenceEntry] = {}

    def register(self, sid: str, user_id: str, guild_id: Optional[str], meta: dict | None = None):
        self.by_sid[sid] = PresenceEntry(sid=sid, user_id=user_id, guild_id=guild_id, meta=meta or {})

    def ping(self, sid: str):
        if sid in self.by_sid:
            self.by_sid[sid].last_seen = time.time()

    def remove(self, sid: str):
        self.by_sid.pop(sid, None)

    def sweep(self):
        now = time.time()
        to_del = [sid for sid, e in self.by_sid.items() if now - e.last_seen > self.ttl]
        for sid in to_del:
            self.by_sid.pop(sid, None)

    def list_by_guild(self, guild_id: str) -> List[PresenceEntry]:
        return [e for e in self.by_sid.values() if e.guild_id == guild_id]

    def stats(self) -> dict:
        return {
            "total": len(self.by_sid),
            "by_guild": _count([e.guild_id or "-" for e in self.by_sid.values()]),
        }

def _count(items: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out
