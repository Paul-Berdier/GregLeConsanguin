# api/blueprints/guilds.py
from __future__ import annotations
import time
from flask import Blueprint, jsonify, current_app
from ..auth.session import require_login, get_access_token
from ..auth.discord_oauth import fetch_user_me, fetch_user_guilds
from requests import HTTPError

bp = Blueprint("guilds", __name__)
TTL = 60

@bp.get("/guilds")
@require_login
def guilds():
    token = get_access_token()
    if not token:
        return jsonify({"ok": False, "error": "no_token"}), 401

    cache = current_app.extensions.setdefault("caches", {}).setdefault("guilds", {})
    key = token[:24]
    now = time.time()
    entry = cache.get(key)
    if entry and now - entry["t"] < TTL:
        return jsonify(entry["data"]), 200

    try:
        data = fetch_user_guilds(token)
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 429 and entry:
            # Serve cache si on en a un
            return jsonify(entry["data"]), 200
        raise  # laisser l’error handler global logguer

    payload = {"ok": True, "guilds": data}
    cache[key] = {"t": now, "data": payload}
    return jsonify(payload), 200