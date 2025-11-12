# api/schemas/track.py
from __future__ import annotations

from pydantic import BaseModel


class TrackOut(BaseModel):
    title: str
    url: str
    duration: int | None = None
    requested_by: str | None = None
