from __future__ import annotations

import traceback

from flask import Blueprint, jsonify, session

bp = Blueprint("guilds", __name__)


@bp.get("/guilds")
def list_guilds():
    try:
        user = session.get("discord_user")
        token = session.get("discord_token")

        if not user or not token:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401

        import requests as req

        headers = {"Authorization": f"Bearer {token}"}
        r = req.get("https://discord.com/api/users/@me/guilds", headers=headers, timeout=20)

        if r.status_code != 200:
            return jsonify({
                "ok": False,
                "error": "guilds_fetch_failed",
                "details": r.text[:500],
            }), 400

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

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "guilds_crash",
            "message": str(e),
            "trace": traceback.format_exc(),
        }), 500