"""Autorisation — l'identité de l'utilisateur vient UNIQUEMENT de la session Flask (contrat SEC-C1).

La session est posée par /auth/callback (OAuth Discord) : `session["discord_user"]["id"]`.
Le `user_id` du corps JSON et le header `X-User-ID` ne sont JAMAIS lus : n'importe qui
pourrait s'y faire passer pour un autre membre. L'appartenance à la guild est ensuite
vérifiée par le bot (NOT_GUILD_MEMBER, contrat SEC-C2).

Utilisable aussi dans les handlers Socket.IO : Flask-SocketIO y expose une copie de la
session HTTP prise à la connexion.
"""
from __future__ import annotations

import functools
from typing import Optional

from flask import jsonify, session

MSG_NOT_AUTHENTICATED = "Connecte-toi avec Discord pour contrôler Greg."

# Room Socket.IO des sockets connectés avec une session Discord (bot_status, SEC-C4).
ROOM_AUTHENTICATED = "authenticated"


def session_user_id() -> Optional[int]:
    """Id Discord de l'utilisateur de la session, ou None (pas connecté / session illisible)."""
    user = session.get("discord_user")
    if not isinstance(user, dict):
        return None
    try:
        uid = int(user.get("id"))
    except (TypeError, ValueError):
        return None
    return uid if uid > 0 else None


def not_authenticated():
    """Réponse HTTP 401 NOT_AUTHENTICATED (pas de session Discord)."""
    return jsonify({
        "ok": False,
        "error": "NOT_AUTHENTICATED",
        "message": MSG_NOT_AUTHENTICATED,
    }), 401


def require_session_user(view):
    """Décorateur de route : 401 NOT_AUTHENTICATED sans session Discord, avant toute validation.

    Posé sur la vue (et non en before_request) : le preflight CORS (OPTIONS, jamais de
    cookie) est géré par Flask sans appeler la vue, donc il n'est pas bloqué.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if session_user_id() is None:
            return not_authenticated()
        return view(*args, **kwargs)

    return wrapper
