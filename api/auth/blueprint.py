# api/auth/blueprint.py
from __future__ import annotations

import secrets
import string
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, redirect, request, session, url_for

from .discord_oauth import (
    make_authorize_url,
    exchange_code_for_token,
    fetch_user_me,
)
from .session import (
    set_user_session,
    set_oauth_session,
    clear_session,
    current_user,
    get_access_token,
)

bp = Blueprint("auth", __name__)

# Petit "device flow" maison pour Overwolf : le callback marque un device_id comme "prêt".
_DEVICE_FLOWS: Dict[str, Dict[str, Any]] = {}


def _rand_state(n: int = 32) -> str:
    alpha = string.ascii_letters + string.digits
    return "".join(secrets.choice(alpha) for _ in range(n))


@bp.get("/auth/login")
def auth_login():
    # Optionnel : on passe device_id pour corréler avec le poll côté overlay
    device_id = request.args.get("device_id", "")
    state = _rand_state()
    session["oauth_state"] = state
    if device_id:
        session["device_id"] = device_id
    url = make_authorize_url(state, extra_params={"state": state})
    return redirect(url, code=302)


@bp.get("/auth/callback")
def auth_callback():
    err = request.args.get("error")
    if err:
        return jsonify({"ok": False, "error": err}), 400

    state = request.args.get("state") or ""
    code = request.args.get("code") or ""
    sess_state = session.pop("oauth_state", None)
    if not sess_state or sess_state != state:
        return jsonify({"ok": False, "error": "invalid_state"}), 400

    try:
        tokens = exchange_code_for_token(code)
        user = fetch_user_me(tokens["access_token"])
    except Exception as e:
        return jsonify({"ok": False, "error": f"oauth_failed: {e}"}), 400

    set_oauth_session(tokens)
    set_user_session(user)

    # Si la connexion a été initiée via device flow (Overwolf), marque le device_id comme prêt
    device_id = session.pop("device_id", None)
    if device_id:
        _DEVICE_FLOWS[device_id] = {
            "user": user,
            "tokens": tokens,
            "ready": True,
        }
        # Affiche une petite page simple côté navigateur système
        return (
            "<html><body><h3>Connexion réussie ✅</h3>"
            "<p>Vous pouvez revenir dans l'overlay.</p></body></html>"
        )

    # Sinon, renvoie vers une route "OK" générique
    return redirect(url_for("auth.me"), code=302)


@bp.post("/auth/logout")
def auth_logout():
    clear_session()
    return jsonify({"ok": True})


@bp.get("/api/v1/me")
def me():
    return jsonify(current_user() or {}), 200


# === Device Flow (utilisé par l'overlay-core.js) =============================

@bp.post("/auth/device/start")
def auth_device_start():
    device_id = secrets.token_urlsafe(24)
    _DEVICE_FLOWS[device_id] = {"ready": False, "user": None, "tokens": None}
    # L'overlay va ouvrir cette URL dans un navigateur externe
    login_url = url_for("auth.auth_login", device_id=device_id, _external=True)
    return jsonify({"device_id": device_id, "login_url": login_url})


@bp.get("/auth/device/poll")
def auth_device_poll():
    device_id = request.args.get("device_id") or ""
    if not device_id or device_id not in _DEVICE_FLOWS:
        return jsonify({"ok": False, "error": "invalid_device"}), 400

    st = _DEVICE_FLOWS[device_id]
    if not st.get("ready"):
        return jsonify({"ok": False, "ready": False}), 200

    # TRANSFERT des droits dans **la session de l'overlay** (celle qui poll)
    if st.get("tokens"):
        set_oauth_session(st["tokens"])
    if st.get("user"):
        set_user_session(st["user"])

    # On invalide le device token en mémoire
    st["ready"] = False
    st["tokens"] = None
    st["user"] = None

    return jsonify({"ok": True, "ready": True})
