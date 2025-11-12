# api/schemas/user.py
from __future__ import annotations

from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    username: str
    avatar: str | None = None
    discriminator: str | None = None  # legacy Discord
