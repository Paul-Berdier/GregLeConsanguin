# api/schemas/spotify.py

from __future__ import annotations

from pydantic import BaseModel


class SpotifyStatus(BaseModel):
    linked: bool
