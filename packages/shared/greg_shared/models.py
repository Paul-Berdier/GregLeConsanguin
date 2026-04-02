"""Modèles Pydantic — schémas partagés entre tous les services."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────── Track ───────────────────────────

class Track(BaseModel):
    """Un morceau de musique dans la queue."""
    url: str = ""
    title: str = "Sans titre"
    artist: Optional[str] = None
    duration: Optional[int] = None  # secondes
    thumbnail: Optional[str] = Field(None, alias="thumb")
    provider: Optional[str] = "youtube"
    added_by: Optional[str] = None
    priority: int = 0
    ts: Optional[int] = None

    model_config = {"populate_by_name": True}

    @property
    def thumb(self) -> Optional[str]:
        return self.thumbnail


# ─────────────────────────── User ───────────────────────────

class UserInfo(BaseModel):
    """Info utilisateur Discord exposée à l'UI."""
    id: str
    username: str = ""
    display_name: str = ""
    global_name: str = ""
    avatar_url: str = ""
    roles: List[str] = []
    weight: int = 0
    weight_key: str = "__DEFAULT__"
    is_admin: bool = False
    is_owner: bool = False


# ─────────────────────────── Player State ───────────────────────────

class Progress(BaseModel):
    elapsed: int = 0
    duration: Optional[int] = None


class PlayerState(BaseModel):
    """État complet du player pour une guild."""
    guild_id: int = 0
    current: Optional[Dict[str, Any]] = None
    queue: List[Dict[str, Any]] = []
    paused: bool = False
    position: int = 0
    duration: Optional[int] = None
    progress: Progress = Progress()
    thumbnail: Optional[str] = None
    repeat_all: bool = False
    requested_by_user: Optional[Dict[str, Any]] = None
    queue_users: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────── API Requests ───────────────────────────

class EnqueueRequest(BaseModel):
    """Requête d'ajout à la queue."""
    query: str = ""
    url: str = ""
    guild_id: int
    user_id: int
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    provider: Optional[str] = None


class PlayerActionRequest(BaseModel):
    """Requête d'action player (skip, stop, pause, etc.)."""
    guild_id: int
    user_id: int


class MoveRequest(BaseModel):
    """Requête de déplacement dans la queue."""
    guild_id: int
    user_id: int
    src: int
    dst: int


class RemoveRequest(BaseModel):
    """Requête de suppression dans la queue."""
    guild_id: int
    user_id: int
    index: int


# ─────────────────────────── Redis Commands ───────────────────────────

class BotCommand(BaseModel):
    """Commande envoyée de l'API vers le Bot via Redis."""
    action: str  # enqueue, skip, stop, pause, resume, repeat, move, remove, join, leave
    guild_id: int
    user_id: int = 0
    data: Dict[str, Any] = {}
    request_id: str = ""  # Pour corréler requête/réponse


class BotResponse(BaseModel):
    """Réponse du Bot vers l'API via Redis."""
    request_id: str = ""
    ok: bool = True
    error: Optional[str] = None
    data: Dict[str, Any] = {}
