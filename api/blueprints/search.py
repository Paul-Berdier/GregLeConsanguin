from __future__ import annotations

from flask import Blueprint, jsonify, request
from api.services import search as svc

bp = Blueprint("search", __name__)

@bp.get("/autocomplete")
def autocomplete():
    q = (request.args.get("q") or request.args.get("query") or "").strip()
    limit = request.args.get("limit", 8, type=int)
    if not q:
        return jsonify({"ok": True, "results": []}), 200

    # svc.autocomplete → items normalisés: {title, url, duration, source, thumbnail}
    items = svc.autocomplete(q, limit=limit) or []

    out = []
    for it in items:
        out.append({
            "title": it.get("title") or "",
            "url": it.get("url") or "",
            "webpage_url": it.get("url") or "",
            "artist": it.get("artist") or it.get("uploader") or "",
            "duration": it.get("duration"),
            # IMPORTANT: le front attend `thumb`
            "thumb": it.get("thumbnail") or it.get("thumb") or "",
        })
    return jsonify({"ok": True, "results": out}), 200
