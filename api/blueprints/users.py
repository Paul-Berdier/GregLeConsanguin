# backend/api/blueprints/users.py
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth.session import current_user, require_login

bp = Blueprint("users", __name__)

@bp.get("/users/me")
@require_login
def users_me():
    # Le front attend directement {id, username, ...}
    return jsonify(current_user() or {}), 200

@bp.get("/_routes")
def _routes():
    from flask import current_app
    out = []
    for r in current_app.url_map.iter_rules():
        methods = sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS"))
        out.append({"rule": str(r), "endpoint": r.endpoint, "methods": methods})
    out.sort(key=lambda x: x["rule"])
    return jsonify(out), 200
