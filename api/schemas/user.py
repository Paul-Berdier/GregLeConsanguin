# api/schemas/user.py
from __future__ import annotations

from pydantic import BaseModel
from typing import List, Optional


class UserOut(BaseModel):
    id: str
    username: str
    avatar: Optional[str] = None
    discriminator: Optional[str] = None  # legacy Discord

    # ---- Enrichissements priorité/affichage ----
    roles: Optional[List[str]] = None         # noms de rôles visibles sur le serveur
    weight: Optional[int] = None              # poids de priorité calculé (utils/priority_rules)
    is_admin: Optional[bool] = None           # True si administrator/manage_guild
    is_owner: Optional[bool] = None           # True si GREG_OWNER_ID == user_id
