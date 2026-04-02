"""Guilds routes — liste des serveurs."""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session

bp = Blueprint("guilds", __name__)


@bp.get("/guilds")
def list_guilds():
    """Retourne les guildes de l'utilisateur connecté."""
    user = session.get("discord_user")
    token = session.get("discord_token")
    if not user or not token:
        return jsonify({"ok": False, "error": "not_authenticated"}), 401

    import requests as req
    headers = {"Authorization": f"Bearer {token}"}
    r = req.get("https://discord.com/api/users/@me/guilds", headers=headers)
    if r.status_code != 200:
        return jsonify({"ok": False, "error": "guilds_fetch_failed"}), 400

    guilds = r.json()
    out = []
    for g in guilds:
        out.append({
            "id": g.get("id"),
            "name": g.get("name"),
            "icon": g.get("icon"),
            "owner": g.get("owner", False),
        })

    return jsonify({"ok": True, "guilds": out}), 200
