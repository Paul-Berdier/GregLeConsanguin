# utils/spotify_auth.py
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Dict, Any

_STORE = Path(".spotify_users.json")

def _load() -> Dict[str, Any]:
    if _STORE.exists():
        try:
            return json.loads(_STORE.read_text("utf-8"))
        except Exception:
            pass
    return {"users": {}}

def _save(data: Dict[str, Any]) -> None:
    _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

def allow(user_id: int | str, note: str | None = None) -> None:
    d = _load()
    d["users"][str(user_id)] = {"authorized": True, "note": note, "ts": int(time.time())}
    _save(d)

def disallow(user_id: int | str) -> None:
    d = _load()
    d["users"].pop(str(user_id), None)
    _save(d)

def is_allowed(user_id: int | str) -> bool:
    d = _load()
    u = d["users"].get(str(user_id))
    return bool(u and u.get("authorized"))
