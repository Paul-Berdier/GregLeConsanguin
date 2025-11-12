# api/storage/redis_store.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .base import TokenStore

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None


class RedisTokenStore(TokenStore):
    def __init__(self, url: str, prefix: str = "greg:tokens:"):
        if redis is None:
            raise RuntimeError("redis-py not installed.")
        self.r = redis.from_url(url)
        self.prefix = prefix

    def _key(self, user_id: str) -> str:
        return f"{self.prefix}{user_id}"

    def get(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        raw = self.r.hget(self._key(user_id), provider)
        return json.loads(raw) if raw else None

    def set(self, user_id: str, provider: str, token: Dict[str, Any]) -> None:
        self.r.hset(self._key(user_id), provider, json.dumps(token, ensure_ascii=False))

    def delete(self, user_id: str, provider: str) -> None:
        self.r.hdel(self._key(user_id), provider)
