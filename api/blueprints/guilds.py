# api/blueprints/guilds.py
from __future__ import annotations
from flask import Blueprint, jsonify, g
from ..auth.session import require_login  # ou ton décorateur actuel
from ..services.discord import get_guilds, RateLimited

bp = Blueprint("guilds", __name__)

@bp.get("/guilds")
@require_login
def guilds():
    # Récupère le token utilisateur depuis ta session (exemple)
    token = g.session["oauth"]["access_token"]  # adapte à ta structure
    try:
        guild_list = get_guilds(token)  # déjà caché + gère 429
        return jsonify(guild_list), 200
    except RateLimited as e:
        # JSON propre et code 429; le front se dégrade sur le cache
        return jsonify({
            "ok": False,
            "error": "discord_rate_limited",
            "retry_after": e.retry_after or 1.0
        }), 429
