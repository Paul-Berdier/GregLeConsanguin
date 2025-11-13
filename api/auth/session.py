# api/auth/session.py
from __future__ import annotations

import time
from functools import wraps
from typing import Any, Dict, Optional

from flask import session, jsonify, request

from .discord_oauth import refresh_access_token

SESSION_USER_KEY = "discord_user"
SESSION_OAUTH_KEY = "oauth"  # {access_token, refresh_token, expires_at, ...}


def set_user_session(user: Dict[str, Any]) -> None:
    session[SESSION_USER_KEY] = {
        "id": str(user.get("id")),
        "username": user.get("username"),
        "global_name": user.get("global_name"),
        "discriminator": user.get("discriminator"),
        "avatar": user.get("avatar"),
    }


def set_oauth_session(tokens: Dict[str, Any]) -> None:
    session[SESSION_OAUTH_KEY] = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type"),
        "scope": tokens.get("scope"),
        "expires_at": int(tokens.get("expires_at", 0)),
    }


def get_oauth_payload() -> Dict[str, Any]:
    return session.get("oauth", {})  # stocké via set_oauth_session()

def clear_session() -> None:
    session.pop(SESSION_USER_KEY, None)
    session.pop(SESSION_OAUTH_KEY, None)


def current_user() -> Optional[Dict[str, Any]]:
    return session.get(SESSION_USER_KEY)


def is_logged_in() -> bool:
    u = current_user()
    return bool(u and u.get("id"))


def _need_refresh(oauth: Dict[str, Any]) -> bool:
    try:
        return int(oauth.get("expires_at", 0)) <= int(time.time())
    except Exception:
        return True


def get_access_token(auto_refresh: bool = True) -> Optional[str]:
    oauth = session.get(SESSION_OAUTH_KEY) or {}
    token = oauth.get("access_token")
    if not token:
        return None
    if auto_refresh and _need_refresh(oauth):
        rtok = oauth.get("refresh_token")
        if not rtok:
            return None
        newtok = refresh_access_token(rtok)
        set_oauth_session(newtok)
        token = newtok.get("access_token")
    return token


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            if request.path.startswith("/api/"):
                return jsonify({"error": "auth_required"}), 401
            return jsonify({"error": "auth_required"}), 401
        return fn(*args, **kwargs)

    return wrapper
