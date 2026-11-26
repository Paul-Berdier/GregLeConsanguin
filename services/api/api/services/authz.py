"""Autorisation — l'identité de l'utilisateur vient UNIQUEMENT de la session Flask (contrat SEC-C1).

La session est posée par /auth/callback (OAuth Discord) : `session["discord_user"]["id"]`.
Le `user_id` du corps JSON et le header `X-User-ID` ne sont JAMAIS lus : n'importe qui
pourrait s'y faire passer pour un autre membre. L'appartenance à la guild est ensuite
vérifiée par le bot (NOT_GUILD_MEMBER, contrat SEC-C2).

Utilisable aussi dans les handlers Socket.IO : Flask-SocketIO y expose une copie de la
session HTTP prise à la connexion.

CSRF (spec §3.2) : avec SameSite=None et le `guild_id` lu dans l'URL, un formulaire d'un site
tiers pouvait piloter Greg avec le cookie. Les méthodes non sûres en session exigent donc un
corps JSON (qu'un formulaire ne sait pas envoyer) et, si le navigateur les donne, un `Origin`
ou un `Referer` du site (`WEB_ORIGINS`).
"""
from __future__ import annotations

import functools
from typing import Optional

from flask import current_app, jsonify, request, session

MSG_NOT_AUTHENTICATED = "Connecte-toi avec Discord pour contrôler Greg."
MSG_CSRF_FAILED = "Requête refusée : elle ne vient pas du site de Greg."

# Méthodes sans effet : jamais soumises à la garde CSRF.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

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


def _from_web_origin(raw: str) -> bool:
    """Vrai si l'origine de `raw` (Origin ou Referer, normalisé) est une origine du site."""
    from api import _normalize_origin  # import local : `api` importe ce module via ses routes

    origin = _normalize_origin(raw)
    return origin is not None and origin in current_app.config["WEB_ORIGINS"]


def csrf_ok() -> bool:
    """Garde CSRF des requêtes en session (spec §3.2).

    GET/HEAD/OPTIONS : toujours admises. Sinon : corps JSON obligatoire, puis `Origin`
    (s'il est présent) dans `WEB_ORIGINS`, sinon `Referer` (s'il est présent) dans ces
    mêmes origines, sinon admise. « null » ou une origine illisible est refusée.
    """
    if request.method in SAFE_METHODS:
        return True
    if not request.is_json:
        return False
    origin = request.headers.get("Origin")
    if origin is not None:
        return _from_web_origin(origin)
    referer = request.headers.get("Referer")
    if referer is not None:
        return _from_web_origin(referer)
    return True


def csrf_failed():
    """Réponse HTTP 403 CSRF_FAILED (requête non sûre qui ne vient pas du site)."""
    return jsonify({
        "ok": False,
        "error": "CSRF_FAILED",
        "message": MSG_CSRF_FAILED,
    }), 403


def require_session_user(view):
    """Décorateur de route : 401 NOT_AUTHENTICATED sans session Discord, avant toute validation,
    puis 403 CSRF_FAILED pour une méthode non sûre qui ne vient pas du site.

    Posé sur la vue (et non en before_request) : le preflight CORS (OPTIONS, jamais de
    cookie) est géré par Flask sans appeler la vue, donc il n'est pas bloqué.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if session_user_id() is None:
            return not_authenticated()
        if request.method not in SAFE_METHODS and not csrf_ok():
            return csrf_failed()
        return view(*args, **kwargs)

    return wrapper
