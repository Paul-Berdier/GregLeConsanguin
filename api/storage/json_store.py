# api/storage/json_store.py

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

from .base import TokenStore


class JsonTokenStore(TokenStore):
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _read(self) -> Dict[str, Any]:
        with self._lock, open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        tmp = self.path + ".tmp"
        with self._lock, open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        return data.get(user_id, {}).get(provider)

    def set(self, user_id: str, provider: str, token: Dict[str, Any]) -> None:
        data = self._read()
        data.setdefault(user_id, {})[provider] = token
        self._write(data)

    def delete(self, user_id: str, provider: str) -> None:
        data = self._read()
        if user_id in data and provider in data[user_id]:
            del data[user_id][provider]
            self._write(data)
