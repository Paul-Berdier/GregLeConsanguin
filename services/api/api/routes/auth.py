"""Auth routes — OAuth Discord (login / callback / logout / me).

Sécurité (SEC-C6) :
- `state` OAuth aléatoire stocké en session et à usage unique : bloque le
  login-CSRF (un attaquant ne peut pas connecter la victime à SON compte).
- Aucune trace ni valeur de configuration renvoyée au client : tout part dans les logs.
"""
from __future__ import annotations

import hmac
import logging
import secrets
from urllib.parse import quote

import requests as req
from flask import Blueprint, jsonify, redirect, request, session

from greg_shared.config import settings

bp = Blueprint("auth", __name__)
logger = logging.getLogger("greg.api.auth")

_SESSION_STATE_KEY = "oauth_state"


def _setting(name: str) -> str:
    value = getattr(settings, name, None)
    return value.strip() if isinstance(value, str) else ""


def _config_error(name: str):
    logger.error("OAuth Discord : configuration manquante ou invalide (%s)", name)
    return jsonify({"ok": False, "error": f"missing_or_invalid_{name}"}), 500


@bp.get("/auth/login")
def login():
    try:
        client_id = _setting("discord_client_id")
        redirect_uri = _setting("discord_redirect_uri")
        scopes = _setting("discord_oauth_scopes")
        if not client_id:
            return _config_error("discord_client_id")
        if not redirect_uri:
            return _config_error("discord_redirect_uri")
        if not scopes:
            return _config_error("discord_oauth_scopes")

        # Nonce anti-CSRF, vérifié puis consommé par /auth/callback.
        state = secrets.token_urlsafe(24)
        session[_SESSION_STATE_KEY] = state

        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={quote(client_id)}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&response_type=code"
            f"&scope={quote(scopes)}"
            f"&state={state}"
        )
        return redirect(url)

    except Exception:
        logger.exception("auth/login a planté")
        return jsonify({"ok": False, "error": "auth_login_crash"}), 500


@bp.get("/auth/callback")
def callback():
    try:
        # Le state attendu est consommé AVANT tout : un callback rejoué échoue.
        expected = session.pop(_SESSION_STATE_KEY, None)
        state = request.args.get("state") or ""
        if not expected or not hmac.compare_digest(
            str(expected).encode("utf-8"), state.encode("utf-8")
        ):
            logger.warning("OAuth Discord : state invalide ou absent (login-CSRF ?)")
            return jsonify({"ok": False, "error": "invalid_state"}), 400

        code = request.args.get("code")
        if not code:
            return jsonify({"ok": False, "error": "missing_code"}), 400

        client_id = _setting("discord_client_id")
        client_secret = _setting("discord_client_secret")
        redirect_uri = _setting("discord_redirect_uri")
        if not client_id:
            return _config_error("discord_client_id")
        if not client_secret:
            return _config_error("discord_client_secret")
        if not redirect_uri:
            return _config_error("discord_redirect_uri")

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        r = req.post("https://discord.com/api/oauth2/token", data=data, timeout=20)
        if r.status_code != 200:
            logger.warning("OAuth Discord : échange du code refusé (%s) %s", r.status_code, r.text[:300])
            return jsonify({"ok": False, "error": "token_exchange_failed"}), 400

        access_token = (r.json() or {}).get("access_token")
        if not access_token:
            return jsonify({"ok": False, "error": "missing_access_token"}), 400

        headers = {"Authorization": f"Bearer {access_token}"}
        user_r = req.get("https://discord.com/api/users/@me", headers=headers, timeout=20)
        if user_r.status_code != 200:
            logger.warning("OAuth Discord : lecture du profil refusée (%s) %s",
                           user_r.status_code, user_r.text[:300])
            return jsonify({"ok": False, "error": "user_fetch_failed"}), 400

        session["discord_user"] = user_r.json()
        session["discord_token"] = access_token
        session.permanent = True

        from api import web_url
        return redirect(web_url())

    except Exception:
        logger.exception("auth/callback a planté")
        return jsonify({"ok": False, "error": "auth_callback_crash"}), 500


@bp.post("/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True}), 200


@bp.get("/auth/me")
@bp.get("/users/me")
def me():
    user = session.get("discord_user")
    if not user:
        return jsonify({"ok": False, "error": "not_authenticated"}), 401
    return jsonify({"ok": True, "user": user}), 200
