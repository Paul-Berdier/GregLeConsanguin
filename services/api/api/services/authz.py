"""Autorisation — l'identité vient de la session Flask ou d'un jeton porteur de l'appli, jamais du corps (SEC-C1).

La session est posée par /auth/callback (OAuth Discord) : `session["discord_user"]["id"]`.
Le `user_id` du corps JSON et le header `X-User-ID` ne sont JAMAIS lus : n'importe qui
pourrait s'y faire passer pour un autre membre. L'appartenance à la guild est ensuite
vérifiée par le bot (NOT_GUILD_MEMBER, contrat SEC-C2).

Jeton porteur (spec 2026-11-25 §3.1) : un en-tête `Authorization` présent doit valoir
`Bearer <jeton valide>` (api.services.overlay_tokens), sinon 401, sans jamais se rabattre
sur le cookie. Les routes en session seule (`require_session_user`) refusent tout en-tête
`Authorization`.

Utilisable aussi dans les handlers Socket.IO : Flask-SocketIO y expose une copie de la
session HTTP prise à la connexion.

CSRF (spec §3.2) : avec SameSite=None et le `guild_id` lu dans l'URL, un formulaire d'un site
tiers pouvait piloter Greg avec le cookie. Les méthodes non sûres en session exigent donc un
corps JSON (qu'un formulaire ne sait pas envoyer) et, si le navigateur les donne, un `Origin`
ou un `Referer` du site (`WEB_ORIGINS`).
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Literal, Optional

from flask import current_app, g, jsonify, request, session

from api.services import overlay_tokens as ot

MSG_NOT_AUTHENTICATED = "Connecte-toi avec Discord pour contrôler Greg."
MSG_CSRF_FAILED = "Requête refusée : elle ne vient pas du site de Greg."

# Méthodes sans effet : jamais soumises à la garde CSRF.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Room Socket.IO des sockets connectés avec une session Discord (bot_status, SEC-C4).
ROOM_AUTHENTICATED = "authenticated"

# `^Bearer (\S+)$`, schéma insensible à la casse ; fullmatch, car « $ » accepterait un saut de ligne final.
_BEARER_RE = re.compile(r"Bearer (\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class Identity:
    """Qui fait la requête : un compte Discord, par sa session ou par un jeton de l'appli (`tid`)."""

    uid: int
    via: Literal["session", "overlay"]
    tid: Optional[str] = None


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


def _session_identity() -> Optional[Identity]:
    uid = session_user_id()
    return None if uid is None else Identity(uid, "session")


def _socket_identity() -> Optional[Identity]:
    """Socket : l'identité du jeton liée à la copie de session du socket à la connexion, sinon la session."""
    ident = session.get("_ident")
    if isinstance(ident, dict) and ident.get("via") == "overlay":
        return Identity(int(ident["uid"]), "overlay", str(ident["tid"]))
    return _session_identity()


def _http_identity() -> Optional[Identity]:
    header = request.headers.get("Authorization")
    if header is None:
        return _session_identity()
    m = _BEARER_RE.fullmatch(header)
    if m is None:
        return None
    rec = ot.resolve(m.group(1))  # OverlayError (Redis injoignable) remonte telle quelle
    return None if rec is None else Identity(rec.uid, "overlay", rec.tid)


def current_identity() -> Optional[Identity]:
    """Identité de la requête, ou None.

    HTTP : en-tête `Authorization` présent → `Bearer <jeton>` résolu par le magasin, sinon None (jamais le
    cookie) ; absent → la session. Résolue une fois par requête (cache `g._greg_identity`).
    Socket.IO (`request.sid`) : `session["_ident"]` posé à la connexion, sinon la session ; l'en-tête y est
    ignoré et rien n'est mis en cache.
    """
    if getattr(request, "sid", None) is not None:
        return _socket_identity()
    if "_greg_identity" not in g:
        g._greg_identity = _http_identity()
    return g._greg_identity


def current_user_id() -> Optional[int]:
    """Id Discord de l'identité de la requête (session ou jeton), ou None."""
    ident = current_identity()
    return None if ident is None else ident.uid


def not_authenticated():
    """Réponse HTTP 401 NOT_AUTHENTICATED (ni session Discord, ni jeton porteur valide)."""
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

    Un en-tête `Authorization` présent donne toujours 401, cookie ou pas : ces routes n'acceptent
    jamais de jeton porteur, et un en-tête présent ne se rabat jamais sur le cookie.

    Posé sur la vue (et non en before_request) : le preflight CORS (OPTIONS, jamais de
    cookie) est géré par Flask sans appeler la vue, donc il n'est pas bloqué.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if "Authorization" in request.headers or session_user_id() is None:
            return not_authenticated()
        if request.method not in SAFE_METHODS and not csrf_ok():
            return csrf_failed()
        return view(*args, **kwargs)

    return wrapper


def require_identity(view):
    """Décorateur de route : session ou jeton porteur (spec §3.1).

    503 STORAGE_UNAVAILABLE si Redis ne peut vérifier le jeton (jamais 401 : l'appli effacerait son
    jeton), 401 NOT_AUTHENTICATED sans identité, puis, en session seulement, 403 CSRF_FAILED pour une
    méthode non sûre qui ne vient pas du site : un navigateur ne joint jamais `Authorization` tout seul.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        try:
            ident = current_identity()
        except ot.OverlayError as e:
            return jsonify(e.body()), e.status
        if ident is None:
            return not_authenticated()
        if ident.via == "session" and request.method not in SAFE_METHODS and not csrf_ok():
            return csrf_failed()
        return view(*args, **kwargs)

    return wrapper


def require_bearer(view):
    """Décorateur de route : jeton porteur de l'appli seul (POST /overlay/logout).

    L'identité est résolue comme pour `require_identity` : 503 STORAGE_UNAVAILABLE si Redis ne peut vérifier le
    jeton (jamais 401 : l'appli effacerait son jeton), puis 401 NOT_AUTHENTICATED sans identité ou pour une
    session. Pas de garde CSRF : un navigateur ne joint jamais `Authorization` tout seul.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        try:
            ident = current_identity()
        except ot.OverlayError as e:
            return jsonify(e.body()), e.status
        if ident is None or ident.via != "overlay":
            return not_authenticated()
        return view(*args, **kwargs)

    return wrapper
