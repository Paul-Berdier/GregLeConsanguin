# api/services/discord.py

from __future__ import annotations

from typing import Any, Dict, List

from flask import abort, current_app, session

from ..auth.session import current_user


def _discord_token() -> str:
    tokens = session.get("auth_tokens") or {}
    discord = tokens.get("discord") or {}
    token = discord.get("access_token")
    if not token:
        abort(401, description="Discord token missing. Login required.")
    return token


def get_me() -> Dict[str, Any]:
    user = current_user()
    if not user:
        abort(401, description="Not authenticated.")
    return user


def get_guilds() -> List[Dict[str, Any]]:
    # Guilds ont été récupérés à l'auth, mais pour simplifier on renvoie "best-effort"
    from ..auth.discord_oauth import get_user_guilds

    token = _discord_token()
    return get_user_guilds(token)
