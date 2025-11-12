# backend/api/blueprints/guilds.py
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth.session import require_login
from ..services.discord import get_guilds

bp = Blueprint("guilds", __name__)


@bp.get("/guilds")
@require_login
def guilds():
    return jsonify({"ok": True, "guilds": get_guilds()})
