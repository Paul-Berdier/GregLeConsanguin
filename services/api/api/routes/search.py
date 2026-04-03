"""Search routes — autocomplete YouTube (fast).

Stratégie en 2 niveaux :
1) yt-dlp flat search (rapide, ~1-2s, avec thumbs/durées)
2) Fallback: yt-dlp full search (lent, ~3-5s)
"""
from __future__ import annotations

import logging
import re
import json
from typing import List, Dict, Any
from urllib.parse import quote_plus

from flask import Blueprint, jsonify, request

logger = logging.getLogger("greg.api.search")

bp = Blueprint("search", __name__)


def _yt_suggest(query: str, limit: int = 8) -> List[str]:
    """YouTube suggest API (instantané, ~50ms)."""
    import requests as req
    url = f"https://suggestqueries-clients6.youtube.com/complete/search?client=youtube&ds=yt&q={quote_plus(query)}"
    try:
        r = req.get(url, timeout=3, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0"
        })
        if r.status_code != 200:
            return []
        text = r.text.strip()
        m = re.search(r'\[.*\]', text)
        if not m:
            return []
        data = json.loads(m.group())
        if not data or len(data) < 2 or not isinstance(data[1], list):
            return []
        return [str(item[0]).strip() for item in data[1] if isinstance(item, list) and item][:limit]
    except Exception as e:
        logger.debug("yt_suggest failed: %s", e)
        return []


def _yt_search_flat(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Flat YouTube search — rapide, avec thumbs."""
    try:
        from yt_dlp import YoutubeDL
        opts = {
            "quiet": True,
            "no_warnings": True,
            "default_search": f"ytsearch{limit}",
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": 8,
        }
        with YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            entries = (data or {}).get("entries") or []

        out = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id") or ""
            url = e.get("url") or e.get("webpage_url") or ""
            if vid and not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={vid}"
            thumb = e.get("thumbnail") or ""
            if not thumb and e.get("thumbnails"):
                thumbs = e["thumbnails"]
                if isinstance(thumbs, list) and thumbs:
                    thumb = thumbs[-1].get("url", "")
            if not thumb and vid:
                thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

            out.append({
                "title": e.get("title") or "Titre inconnu",
                "url": url,
                "artist": e.get("uploader") or e.get("channel") or "",
                "duration": e.get("duration"),
                "thumb": thumb,
                "thumbnail": thumb,
                "source": "yt",
            })
        return out[:limit]
    except Exception as e:
        logger.warning("yt_search_flat failed: %s", e)
        return []


def _yt_search_rich(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Rich search via greg_shared extractors (plus lent mais plus fiable)."""
    try:
        from greg_shared.extractors.youtube import search as yt_search
        items = yt_search(query) or []  # search() doesn't accept limit
    except Exception:
        items = []
    out = []
    for it in items:
        out.append({
            "title": it.get("title", ""),
            "url": it.get("url") or it.get("webpage_url", ""),
            "artist": it.get("artist") or it.get("uploader", ""),
            "duration": it.get("duration"),
            "thumb": it.get("thumbnail") or it.get("thumb", ""),
            "thumbnail": it.get("thumbnail") or it.get("thumb", ""),
            "source": it.get("source", "yt"),
        })
    return out[:limit]


def _do_autocomplete():
    q = (request.args.get("q") or request.args.get("query") or "").strip()
    limit = request.args.get("limit", 8, type=int)
    if not q:
        return jsonify({"ok": True, "results": []}), 200

    # Flat search (rapide + métadonnées)
    results = _yt_search_flat(q, limit)
    if not results:
        results = _yt_search_rich(q, limit)
    return jsonify({"ok": True, "results": results}), 200


@bp.get("/search/autocomplete")
def autocomplete():
    return _do_autocomplete()


@bp.get("/autocomplete")
def autocomplete_compat():
    return _do_autocomplete()


@bp.get("/search/suggest")
def suggest():
    """Endpoint dédié typeahead instantané (text only, ~50ms)."""
    q = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", 6, type=int)
    if not q:
        return jsonify({"ok": True, "suggestions": []}), 200
    suggestions = _yt_suggest(q, limit)
    return jsonify({"ok": True, "suggestions": suggestions}), 200
