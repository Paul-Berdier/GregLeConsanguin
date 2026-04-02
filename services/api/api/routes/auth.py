from __future__ import annotations

import os
import traceback

import requests as req
from flask import Blueprint, jsonify, redirect, request, session

from greg_shared.config import settings

bp = Blueprint("auth", __name__)


@bp.get("/auth/login")
def login():
    try:
        client_id = getattr(settings, "discord_client_id", None)
        redirect_uri = getattr(settings, "discord_redirect_uri", None)
        scopes_raw = getattr(settings, "discord_oauth_scopes", None)

        if not isinstance(client_id, str) or not client_id.strip():
            return jsonify({
                "ok": False,
                "error": "missing_or_invalid_discord_client_id",
                "value": repr(client_id),
            }), 500

        if not isinstance(redirect_uri, str) or not redirect_uri.strip():
            return jsonify({
                "ok": False,
                "error": "missing_or_invalid_discord_redirect_uri",
                "value": repr(redirect_uri),
            }), 500

        if not isinstance(scopes_raw, str) or not scopes_raw.strip():
            return jsonify({
                "ok": False,
                "error": "missing_or_invalid_discord_oauth_scopes",
                "value": repr(scopes_raw),
            }), 500

        client_id = client_id.strip()
        redirect_uri = redirect_uri.strip()
        scopes = scopes_raw.strip().replace(" ", "%20")

        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope={scopes}"
        )
        return redirect(url)

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "auth_login_crash",
            "message": str(e),
            "trace": traceback.format_exc(),
        }), 500


@bp.get("/auth/callback")
def callback():
    try:
        code = request.args.get("code")
        if not code:
            return jsonify({"ok": False, "error": "missing_code"}), 400

        client_id = getattr(settings, "discord_client_id", None)
        client_secret = getattr(settings, "discord_client_secret", None)
        redirect_uri = getattr(settings, "discord_redirect_uri", None)

        if not isinstance(client_id, str) or not client_id.strip():
            return jsonify({"ok": False, "error": "missing_or_invalid_discord_client_id"}), 500
        if not isinstance(client_secret, str) or not client_secret.strip():
            return jsonify({"ok": False, "error": "missing_or_invalid_discord_client_secret"}), 500
        if not isinstance(redirect_uri, str) or not redirect_uri.strip():
            return jsonify({"ok": False, "error": "missing_or_invalid_discord_redirect_uri"}), 500

        data = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri.strip(),
        }

        r = req.post("https://discord.com/api/oauth2/token", data=data, timeout=20)
        if r.status_code != 200:
            return jsonify({
                "ok": False,
                "error": "token_exchange_failed",
                "details": r.text[:500],
            }), 400

        token_data = r.json()
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

        front_url = os.getenv("WEB_URL", "https://greg-le-consanguin.up.railway.app")
        return redirect(front_url)

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "auth_callback_crash",
            "message": str(e),
            "trace": traceback.format_exc(),
        }), 500


@bp.post("/auth/logout")
def logout():
    try:
        session.clear()
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "auth_logout_crash",
            "message": str(e),
            "trace": traceback.format_exc(),
        }), 500


@bp.get("/auth/me")
@bp.get("/users/me")
def me():
    try:
        user = session.get("discord_user")
        if not user:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        return jsonify({"ok": True, "user": user}), 200
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "auth_me_crash",
            "message": str(e),
            "trace": traceback.format_exc(),
        }), 500