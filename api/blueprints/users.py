# backend/api/blueprints/users.py
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth.session import current_user, require_login

bp = Blueprint("users", __name__)


@bp.get("/me")
@require_login
def me():
    return jsonify({"ok": True, "user": current_user()})
