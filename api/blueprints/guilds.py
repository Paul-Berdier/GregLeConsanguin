# api/blueprints/guilds.py
from __future__ import annotations

from flask import Blueprint, jsonify
from ..auth.session import login_required, get_access_token
from ..auth.discord_oauth import fetch_user_guilds

bp = Blueprint("guilds", __name__)

@bp.get("/guilds")
@login_required
def guilds():
    token = get_access_token(auto_refresh=True)
    if not token:
        return jsonify({"error": "auth_required"}), 401
    try:
        guilds = fetch_user_guilds(token)
    except Exception as e:
        # L’overlay tolère un tableau vide si rate-limité (évite 500)
        return jsonify([]), 200
    # L’overlay-core.js attend un tableau JSON
    return jsonify(guilds), 200
