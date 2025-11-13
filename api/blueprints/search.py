# api/blueprints/search.py
from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request, current_app

from api.services.search import autocomplete as search_autocomplete

bp = Blueprint("search", __name__)


@bp.get("/autocomplete")
def api_autocomplete():
    """
    Endpoint utilisé par l'overlay:
      GET /api/v1/autocomplete?q=...&limit=...

    Réponse attendue par desktop.js :
    {
      "ok": true,
      "results": [
        {
          "title": "...",
          "url": "https://...",
          "duration": 123,
          "thumb": "https://...",
          "artist": ""
        },
        ...
      ]
    }
    """
    q = (request.args.get("q") or "").strip()
    limit_raw = request.args.get("limit", "8")

    try:
        limit = int(limit_raw)
    except Exception:
        limit = 8

    if not q:
        return jsonify({"ok": True, "results": []}), 200

    try:
        items = search_autocomplete(q, limit=limit)
    except Exception as e:
        current_app.logger.exception("autocomplete failed for %r", q)
        # on renvoie ok=False pour que l’overlay n’explose pas
        return jsonify({"ok": False, "error": str(e), "results": []}), 500

    results: List[Dict[str, Any]] = []
    for it in items or []:
        # items vient de api.services.search.autocomplete
        # keys typiques: title, url, duration, source, thumbnail
        results.append(
            {
                "title": it.get("title") or "",
                "url": it.get("url") or "",
                "duration": it.get("duration"),
                "thumb": it.get("thumbnail") or it.get("thumb") or "",
                # pas d’info d’artiste côté YouTube search pour l’instant
                "artist": it.get("artist") or "",
            }
        )

    return jsonify({"ok": True, "results": results}), 200
