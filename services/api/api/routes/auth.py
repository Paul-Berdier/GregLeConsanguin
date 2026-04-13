from __future__ import annotations

import os
import traceback

import requests as req
from flask import Blueprint, jsonify, redirect, request, session

from greg_shared.config import settings

bp = Blueprint("auth", __name__)


_CLOSE_PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Signed in</title>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; background: #0b1220;
         color: #f1f5f9; margin: 0; display: grid; place-items: center;
         height: 100vh; }
  .card { text-align: center; padding: 32px 40px; border-radius: 14px;
          background: #141d33; border: 1px solid #334155;
          box-shadow: 0 18px 40px rgba(0,0,0,.5); }
  h1 { margin: 0 0 8px; font-size: 18px; color: #34d399; }
  p { margin: 0; color: #94a3b8; font-size: 13px; }
</style></head>
<body>
  <div class="card">
    <h1>&#10003; Signed in</h1>
    <p>You can close this window.</p>
  </div>
  <script>
    try { if (window.opener) window.opener.focus(); } catch (e) {}
    // Auto-close for popup/Electron child windows.
    setTimeout(function(){ try { window.close(); } catch (e) {} }, 300);
  </script>
</body></html>
"""


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

        # `?return=overlay` signals the overlay/popup flow: callback should
        # show a self-closing HTML page instead of redirecting to the web UI.
        # We smuggle this through the OAuth `state` parameter (Discord echoes
        # it back to the callback URL unchanged).
        ret_mode = request.args.get("return", "").strip()
        state = "overlay" if ret_mode == "overlay" else "web"

        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope={scopes}"
            f"&state={state}"
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
        state = request.args.get("state", "web")
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
        session.permanent = True  # persist across browser/Electron restarts

        # Overlay/popup flow: show a self-closing HTML page.
        if state == "overlay":
            return _CLOSE_PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}

        # Default (web) flow: redirect to the front-end.
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