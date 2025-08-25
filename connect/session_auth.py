# connect/session_auth.py
from __future__ import annotations
from typing import Optional, Dict, Any
from flask import session, redirect, url_for, jsonify, request
from functools import wraps
import os

SESSION_KEY = "discord_user"
STATE_KEY = "oauth_state"

def set_user_session(user: Dict[str, Any]) -> None:
    """Stocke l'utilisateur Discord (payload /users/@me) dans la session Flask."""
    session[SESSION_KEY] = {
        "id": str(user.get("id")),
        "username": user.get("username"),
        "global_name": user.get("global_name"),
        "discriminator": user.get("discriminator"),
        "avatar": user.get("avatar"),
    }

def clear_user_session() -> None:
    session.pop(SESSION_KEY, None)
    session.pop(STATE_KEY, None)

def current_user() -> Optional[Dict[str, Any]]:
    return session.get(SESSION_KEY)

def is_logged_in() -> bool:
    u = current_user()
    return bool(u and u.get("id"))

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            # 401 pour que le front déclenche le bouton "Se connecter"
            if request.path.startswith("/api/"):
                return jsonify({"error": "auth_required"}), 401
            return redirect(url_for("auth_login", next=request.url))
        return fn(*args, **kwargs)
    return wrapper

def save_oauth_state(value: str) -> None:
    session[STATE_KEY] = value

def pop_oauth_state() -> Optional[str]:
    return session.pop(STATE_KEY, None)
