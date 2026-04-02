"""Auth routes — Discord OAuth2."""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, redirect, request, session

from greg_shared.config import settings

bp = Blueprint("auth", __name__)


@bp.get("/auth/login")
def login():
    """Redirige vers Discord OAuth."""
    client_id = settings.discord_client_id
    redirect_uri = settings.discord_redirect_uri
    scopes = settings.discord_oauth_scopes.replace(" ", "%20")
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes}"
    )
    return redirect(url)


@bp.get("/auth/callback")
def callback():
    """Callback OAuth Discord."""
    code = request.args.get("code")
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    import requests as req

    # Échanger le code contre un token
    data = {
        "client_id": settings.discord_client_id,
        "client_secret": settings.discord_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.discord_redirect_uri,
    }
    r = req.post("https://discord.com/api/oauth2/token", data=data)
    if r.status_code != 200:
        return jsonify({"ok": False, "error": "token_exchange_failed"}), 400

    token_data = r.json()
    access_token = token_data.get("access_token")

    # Récupérer l'utilisateur
    headers = {"Authorization": f"Bearer {access_token}"}
    user_r = req.get("https://discord.com/api/users/@me", headers=headers)
    if user_r.status_code != 200:
        return jsonify({"ok": False, "error": "user_fetch_failed"}), 400

    user = user_r.json()
    session["discord_user"] = user
    session["discord_token"] = access_token

    # Rediriger vers le front
    front_url = os.getenv("WEB_URL", "/")
    return redirect(front_url)


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
