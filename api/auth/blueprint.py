# api/auth/blueprint.py

from __future__ import annotations

import secrets
import time
from typing import Any, Dict

from flask import Blueprint, abort, current_app, jsonify, redirect, request, session

from ..core.security import make_state, verify_state
from .discord_oauth import build_authorize_url, exchange_code_for_token, get_user_guilds, get_user_info
from .session import clear_session, set_current_user

bp = Blueprint("auth", __name__)


# --- Flux OAuth standard (navigateur) -------------------------------------------------
@bp.get("/login")
def login_redirect():
    _check_discord_config()
    state = make_state(current_app.config["SECRET_KEY"], "discord-login", ttl_seconds=600)
    session["oauth_state"] = state
    return redirect(build_authorize_url(state))


@bp.get("/callback")
def login_callback():
    state = request.args.get("state", "")
    if not state or not verify_state(current_app.config["SECRET_KEY"], state):
        abort(400, description="Invalid or expired state.")

    code = request.args.get("code")
    if not code:
        abort(400, description="Missing 'code'.")

    token = exchange_code_for_token(code)
    access_token = token["access_token"]

    user = get_user_info(access_token)
    guilds = get_user_guilds(access_token)

    # Restriction optionnelle à un serveur
    restrict = current_app.config.get("RESTRICT_TO_GUILD_ID")
    if restrict and not any(g.get("id") == restrict for g in guilds):
        abort(403, description="User is not in the required guild.")

    set_current_user(user, tokens={"discord": token})
    return redirect(request.args.get("next", "/"))


@bp.post("/logout")
def logout():
    clear_session()
    return jsonify({"ok": True})


# --- Device Code (simple "poor-man" flow" pour overlays) ------------------------------
# NOTE: Ce mini-flux n'est pas le vrai OAuth Device Code. Il génère un 'user_code'
# que l'overlay affiche et que l'utilisateur valide en se connectant sur /auth/login?u=CODE.
_DEVICE_TICKETS: dict[str, dict[str, Any]] = {}


@bp.post("/device/start")
def device_start():
    user_code = secrets.token_urlsafe(6)
    _DEVICE_TICKETS[user_code] = {"created": time.time(), "user": None}
    return jsonify({"ok": True, "user_code": user_code})


@bp.post("/device/poll")
def device_poll():
    data = request.get_json(silent=True) or {}
    user_code = data.get("user_code")
    if not user_code or user_code not in _DEVICE_TICKETS:
        abort(400, description="Invalid user_code.")

    ticket = _DEVICE_TICKETS[user_code]
    if ticket["user"]:
        return jsonify({"ok": True, "linked": True, "user": ticket["user"]})
    return jsonify({"ok": True, "linked": False})


@bp.get("/device/activate")
def device_activate():
    """
    Étape à utiliser après /auth/login classique:
    /auth/device/activate?u=<user_code>
    Associe le user courant au code pour permettre à l'overlay de se "lier".
    """
    ucode = request.args.get("u")
    if not ucode or ucode not in _DEVICE_TICKETS:
        abort(400, description="Invalid activation code.")

    user = session.get("auth_user")
    if not user:
        abort(401, description="Login required before activation.")

    _DEVICE_TICKETS[ucode]["user"] = user
    return jsonify({"ok": True, "linked": True})


def _check_discord_config():
    need = ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI")
    missing = [k for k in need if not current_app.config.get(k)]
    if missing:
        abort(501, description=f"Discord OAuth not configured. Missing: {', '.join(missing)}")
