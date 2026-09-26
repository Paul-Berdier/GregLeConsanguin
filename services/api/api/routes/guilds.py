from __future__ import annotations

import logging

from flask import Blueprint, jsonify, session

from api.services import bot_bridge

logger = logging.getLogger("greg.api.guilds")

bp = Blueprint("guilds", __name__)


def _bot_guild_ids():
    """Guilds où Greg est présent (clé Redis greg:bot:guilds), ou None si inconnu."""
    try:
        return bot_bridge.get_bot_guild_ids()
    except Exception as e:  # noqa: BLE001 — /guilds ne doit jamais échouer à cause de ça
        logger.warning("Présence du bot illisible: %s", e)
        return None


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
        # Contrat C5 : bot_present seulement si la clé existe (sinon champ omis)
        bot_ids = _bot_guild_ids()
        out = []
        for g in guilds:
            row = {
                "id": g.get("id"),
                "name": g.get("name"),
                "icon": g.get("icon"),
                "owner": g.get("owner", False),
            }
            if bot_ids is not None:
                row["bot_present"] = str(g.get("id")) in bot_ids
            out.append(row)

        return jsonify({"ok": True, "guilds": out}), 200

    except Exception:
        # La trace reste dans les logs, jamais dans la réponse.
        logger.exception("GET /guilds a planté")
        return jsonify({
            "ok": False,
            "error": "guilds_crash",
            "message": "Impossible de récupérer tes serveurs Discord.",
        }), 500
