# api/blueprints/search.py
from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from api.services import search as search_service

bp = Blueprint("search", __name__)


@bp.get("/autocomplete")
def autocomplete_route():
    """
    Endpoint utilisé par l'overlay pour l'autocomplétion.
    GET /api/v1/autocomplete?q=...&limit=...

    Réponse:
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
    try:
        limit = int(request.args.get("limit") or 8)
    except Exception:
        limit = 8

    if not q:
        return jsonify({"ok": True, "results": []})

    items: List[Dict[str, Any]] = search_service.autocomplete(q, limit=limit)

    results: List[Dict[str, Any]] = []
    for it in items or []:
        results.append(
            {
                "title": it.get("title") or "",
                "url": it.get("url") or "",
                "duration": it.get("duration"),
                # search.autocomplete renvoie "thumbnail"
                "thumb": it.get("thumbnail") or it.get("thumb") or "",
                # on n'a pas d'artiste côté YouTube natif → string vide
                "artist": it.get("artist") or "",
            }
        )

    return jsonify({"ok": True, "results": results})
