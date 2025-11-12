# api/auth/session.py
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional

from flask import abort, current_app, g, request, session


USER_SESSION_KEY = "auth_user"
TOKEN_SESSION_KEY = "auth_tokens"  # pour stocker 'discord', 'spotify' etc.


def set_current_user(user: Dict[str, Any], tokens: Optional[Dict[str, Any]] = None) -> None:
    session[USER_SESSION_KEY] = user
    if tokens:
        session.setdefault(TOKEN_SESSION_KEY, {}).update(tokens)


def clear_session() -> None:
    session.pop(USER_SESSION_KEY, None)
    session.pop(TOKEN_SESSION_KEY, None)


def current_user() -> Optional[Dict[str, Any]]:
    return session.get(USER_SESSION_KEY)


def require_login(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            abort(401, description="Authentication required.")
        return fn(*args, **kwargs)

    return wrapper
