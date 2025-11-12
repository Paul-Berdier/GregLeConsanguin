# api/schemas/guild.py
from __future__ import annotations

from pydantic import BaseModel


class GuildOut(BaseModel):
    id: str
    name: str
    icon: str | None = None
