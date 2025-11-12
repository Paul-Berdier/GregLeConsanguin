# api/storage/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class TokenStore(ABC):
    @abstractmethod
    def get(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def set(self, user_id: str, provider: str, token: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def delete(self, user_id: str, provider: str) -> None:
        ...
