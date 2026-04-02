from __future__ import annotations

from urllib.parse import quote

import requests as req
from flask import Blueprint, jsonify, redirect, request, session

from greg_shared.config import settings

bp = Blueprint("auth", __name__)


@bp.get("/auth/login")
def login():
    client_id = (settings.discord_client_id or "").strip()
    redirect_uri = (settings.discord_redirect_uri or "").strip()
    scopes = (settings.discord_oauth_scopes or "identify guilds").strip()

    if not client_id:
        return jsonify({"ok": False, "error": "missing_discord_client_id"}), 500
    if not redirect_uri:
        return jsonify({"ok": False, "error": "missing_discord_redirect_uri"}), 500

    url = (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={quote(client_id, safe='')}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        "&response_type=code"
        f"&scope={quote(scopes, safe='')}"
    )
    return redirect(url)


@bp.get("/auth/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"ok": False, "error": "missing_code"}), 400

    client_id = (settings.discord_client_id or "").strip()
    client_secret = (settings.discord_client_secret or "").strip()
    redirect_uri = (settings.discord_redirect_uri or "").strip()

    if not client_id:
        return jsonify({"ok": False, "error": "missing_discord_client_id"}), 500
    if not client_secret:
        return jsonify({"ok": False, "error": "missing_discord_client_secret"}), 500
    if not redirect_uri:
        return jsonify({"ok": False, "error": "missing_discord_redirect_uri"}), 500

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    token_r = req.post("https://discord.com/api/oauth2/token", data=data, timeout=20)
    if token_r.status_code != 200:
        return jsonify({
            "ok": False,
            "error": "token_exchange_failed",
            "details": token_r.text[:500],
        }), 400

    token_data = token_r.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return jsonify({"ok": False, "error": "missing_access_token"}), 400

    headers = {"Authorization": f"Bearer {access_token}"}
    user_r = req.get("https://discord.com/api/users/@me", headers=headers, timeout=20)
    if user_r.status_code != 200:
        return jsonify({
            "ok": False,
            "error": "user_fetch_failed",
            "details": user_r.text[:500],
        }), 400

    user = user_r.json()
    session["discord_user"] = user
    session["discord_token"] = access_token

    front_url = (settings.web_url if hasattr(settings, "web_url") else None) or "https://greg-le-consanguin.up.railway.app"
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