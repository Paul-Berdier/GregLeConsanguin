"""Search routes — autocomplete YouTube."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

bp = Blueprint("search", __name__)


def _do_autocomplete():
    q = (request.args.get("q") or request.args.get("query") or "").strip()
    limit = request.args.get("limit", 8, type=int)
    if not q:
        return jsonify({"ok": True, "results": []}), 200

    try:
        from greg_shared.extractors.youtube import search as yt_search
        items = yt_search(q, limit=limit) or []
    except Exception:
        items = []

    out = []
    for it in items:
        out.append({
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "artist": it.get("artist") or it.get("uploader", ""),
            "duration": it.get("duration"),
            "thumb": it.get("thumbnail") or it.get("thumb", ""),
            "thumbnail": it.get("thumbnail") or it.get("thumb", ""),
            "source": it.get("source", "yt"),
        })
    return jsonify({"ok": True, "results": out}), 200


@bp.get("/search/autocomplete")
def autocomplete():
    return _do_autocomplete()


@bp.get("/autocomplete")
def autocomplete_compat():
    return _do_autocomplete()
