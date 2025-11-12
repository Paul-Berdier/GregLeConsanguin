from __future__ import annotations
from pydantic import BaseModel
from typing import Optional


class TrackOut(BaseModel):
    title: str
    url: str
    # Durée en secondes si connue
    duration: Optional[int] = None
    # Affiché côté UI : la “chaîne”/artiste (ex: YouTube uploader)
    artist: Optional[str] = None
    # Miniature si connue
    thumb: Optional[str] = None
    # Provider (youtube, soundcloud, etc.) si disponible
    provider: Optional[str] = None
    # Qui a demandé la piste (id user Discord sous forme de str)
    requested_by: Optional[str] = None
    # Poids/priorité calculé à l’enqueue
    priority: Optional[int] = None
    # Timestamp d’ajout (epoch seconds)
    ts: Optional[int] = None


class TrackPriorityOut(BaseModel):
    """Payload minimal quand on remonte l’info de priorité au front."""
    url: str
    title: str
    priority: int
    requested_by: Optional[str] = None
