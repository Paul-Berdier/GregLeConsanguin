# api/auth/blueprint.py
from __future__ import annotations

import secrets
import string
import time
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, redirect, request, session, url_for

from .discord_oauth import make_authorize_url, exchange_code_for_token, fetch_user_me
from .session import (
    set_user_session,
    set_oauth_session,
    clear_session,
    current_user,
)

bp = Blueprint("auth", __name__)

# ---------------------------------------------------------------------------
# Device Flow (Overwolf)
# - Start -> returns device_id + login_url (opened in external browser)
# - Callback -> marks device_id ready + stores tokens/user in memory
# - Poll -> transfers tokens/user into the poller session (overlay/webview)
# ---------------------------------------------------------------------------

_DEVICE_FLOWS: Dict[str, Dict[str, Any]] = {}
DEVICE_TTL_SECONDS = 10 * 60  # 10 min


def _rand_state(n: int = 32) -> str:
    alpha = string.ascii_letters + string.digits
    return "".join(secrets.choice(alpha) for _ in range(n))


def _safe_next(url: Optional[str]) -> str:
    """
    Prevent open-redirect: only allow relative paths starting with "/".
    """
    if not url:
        return "/"
    u = str(url).strip()
    return u if u.startswith("/") else "/"


def _cleanup_device_flows() -> None:
    now = int(time.time())
    dead = []
    for device_id, st in _DEVICE_FLOWS.items():
        created_at = int(st.get("created_at") or 0)
        if created_at and now - created_at > DEVICE_TTL_SECONDS:
            dead.append(device_id)
    for d in dead:
        _DEVICE_FLOWS.pop(d, None)


# =========================
# OAuth Discord (Web)
# =========================

@bp.get("/auth/login")
def auth_login():
    """
    GET /api/v1/auth/login
    Optional query:
      - device_id : if using device flow (Overwolf)
      - next      : where to redirect after success (default "/")
    """
    _cleanup_device_flows()

    device_id = (request.args.get("device_id") or "").strip()
    next_url = _safe_next(request.args.get("next") or "/")

    state = _rand_state()
    session["oauth_state"] = state
    session["oauth_next"] = next_url

    if device_id:
        session["device_id"] = device_id

    url = make_authorize_url(state, extra_params={"state": state})
    return redirect(url, code=302)


@bp.get("/auth/callback")
def auth_callback():
    """
    GET /api/v1/auth/callback
    Discord redirects here with ?code=...&state=...
    """
    _cleanup_device_flows()

    err = request.args.get("error")
    if err:
        return jsonify({"ok": False, "error": err}), 400

    state = (request.args.get("state") or "").strip()
    code = (request.args.get("code") or "").strip()

    sess_state = session.pop("oauth_state", None)
    if not sess_state or sess_state != state:
        return jsonify({"ok": False, "error": "invalid_state"}), 400

    if not code:
        return jsonify({"ok": False, "error": "missing_code"}), 400

    try:
        tokens = exchange_code_for_token(code)
        user = fetch_user_me(tokens["access_token"])
    except Exception as e:
        return jsonify({"ok": False, "error": f"oauth_failed: {e}"}), 400

    # ✅ store in session (cookie)
    set_oauth_session(tokens)
    set_user_session(user)

    # If initiated via device flow, mark device ready + store payload in memory
    device_id = session.pop("device_id", None)
    if device_id:
        _DEVICE_FLOWS[device_id] = {
            "created_at": int(time.time()),
            "ready": True,
            "user": user,
            "tokens": tokens,
        }
        return (
            "<html><body style='font-family:system-ui'>"
            "<h3>Connexion réussie ✅</h3>"
            "<p>Vous pouvez revenir dans l’overlay.</p>"
            "</body></html>"
        )

    # ✅ IMPORTANT: after web login, go back to UI (not /me json)
    next_url = _safe_next(session.pop("oauth_next", "/"))
    return redirect(next_url, code=302)


@bp.post("/auth/logout")
def auth_logout():
    """
    POST /api/v1/auth/logout
    """
    clear_session()
    return jsonify({"ok": True})


# =========================
# Session debug / compat
# =========================

@bp.get("/me")
def me():
    """
    GET /api/v1/me
    (compat & debug) returns current session user
    """
    return jsonify(current_user() or {}), 200


@bp.get("/auth/me")
def auth_me():
    """
    GET /api/v1/auth/me
    Same as /me, kept for clarity.
    """
    return jsonify(current_user() or {}), 200


# =========================
# Device Flow (Overwolf)
# =========================

@bp.post("/auth/device/start")
def auth_device_start():
    """
    POST /api/v1/auth/device/start
    returns:
      { device_id, login_url }
    """
    _cleanup_device_flows()

    device_id = secrets.token_urlsafe(24)
    _DEVICE_FLOWS[device_id] = {
        "created_at": int(time.time()),
        "ready": False,
        "user": None,
        "tokens": None,
    }

    # Overlay opens this in external browser (same host)
    login_url = url_for("auth.auth_login", device_id=device_id, _external=True)
    return jsonify({"device_id": device_id, "login_url": login_url})


@bp.get("/auth/device/poll")
def auth_device_poll():
    """
    GET /api/v1/auth/device/poll?device_id=...
    If ready, transfers tokens/user into the poller's session cookie.
    """
    _cleanup_device_flows()

    device_id = (request.args.get("device_id") or "").strip()
    if not device_id or device_id not in _DEVICE_FLOWS:
        return jsonify({"ok": False, "error": "invalid_device"}), 400

    st = _DEVICE_FLOWS[device_id]
    if not st.get("ready"):
        return jsonify({"ok": False, "ready": False}), 200

    # Transfer into current session (poller)
    tokens = st.get("tokens")
    user = st.get("user")
    if tokens:
        set_oauth_session(tokens)
    if user:
        set_user_session(user)

    # Invalidate device token (one-shot)
    _DEVICE_FLOWS.pop(device_id, None)

    return jsonify({"ok": True, "ready": True}), 200
