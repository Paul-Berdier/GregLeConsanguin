"""Search routes — autocomplete YouTube (HTTP-only, no yt-dlp).

Deux modes :
1) InnerTube API /youtubei/v1/search — résultats riches (titre, thumb, durée, artiste)
2) YouTube suggest API — typeahead instantané (~50ms)

Aucune dépendance yt-dlp côté API.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests as req

from flask import Blueprint, jsonify, request

logger = logging.getLogger("greg.api.search")

bp = Blueprint("search", __name__)

_YT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

# ─── YouTube InnerTube search (HTTP only, ~200-500ms) ───

_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"  # Public API key
_INNERTUBE_CLIENT = {
    "clientName": "WEB",
    "clientVersion": "2.20250401.00.00",
    "hl": "fr",
    "gl": "FR",
}


def _innertube_search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Recherche via YouTube InnerTube API — rapide, résultats riches."""
    try:
        body = {
            "context": {"client": _INNERTUBE_CLIENT},
            "query": query,
        }
        r = req.post(
            f"https://www.youtube.com/youtubei/v1/search?key={_INNERTUBE_KEY}",
            json=body,
            headers={"User-Agent": _YT_UA, "Content-Type": "application/json"},
            timeout=5,
        )
        if not r.ok:
            logger.debug("innertube search HTTP %s", r.status_code)
            return []

        data = r.json()
        contents = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        results = []
        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                vr = item.get("videoRenderer")
                if not vr:
                    continue

                vid = vr.get("videoId", "")
                if not vid:
                    continue

                title = ""
                title_runs = vr.get("title", {}).get("runs", [])
                if title_runs:
                    title = "".join(r.get("text", "") for r in title_runs)

                artist = ""
                artist_runs = vr.get("ownerText", {}).get("runs", [])
                if artist_runs:
                    artist = "".join(r.get("text", "") for r in artist_runs)
                # Also try longBylineText
                if not artist:
                    lbl = vr.get("longBylineText", {}).get("runs", [])
                    if lbl:
                        artist = "".join(r.get("text", "") for r in lbl)

                # Duration
                duration = None
                dur_text = (
                    vr.get("lengthText", {}).get("simpleText", "")
                    or vr.get("thumbnailOverlays", [{}])[0]
                    .get("thumbnailOverlayTimeStatusRenderer", {})
                    .get("text", {})
                    .get("simpleText", "")
                    if vr.get("thumbnailOverlays")
                    else ""
                )
                if dur_text:
                    duration = _parse_duration(dur_text)

                # Thumbnail
                thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
                thumb = thumbs[-1].get("url", "") if thumbs else ""
                if not thumb:
                    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                results.append({
                    "title": title or "Titre inconnu",
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "artist": artist,
                    "duration": duration,
                    "thumb": thumb,
                    "thumbnail": thumb,
                    "source": "yt",
                })

                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        return results

    except Exception as e:
        logger.warning("innertube search failed: %s", e)
        return []


def _parse_duration(text: str) -> Optional[int]:
    """Parse '3:42' or '1:02:15' into seconds."""
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


# ─── YouTube Suggest (instantané, ~50ms) ───

def _yt_suggest(query: str, limit: int = 8) -> List[str]:
    """YouTube suggest API — même que la barre de recherche."""
    url = (
        f"https://suggestqueries-clients6.youtube.com/complete/search"
        f"?client=youtube&ds=yt&q={quote_plus(query)}"
    )
    try:
        r = req.get(url, timeout=3, headers={"User-Agent": _YT_UA})
        if r.status_code != 200:
            return []
        text = r.text.strip()
        m = re.search(r"\[.*\]", text)
        if not m:
            return []
        data = json.loads(m.group())
        if not data or len(data) < 2 or not isinstance(data[1], list):
            return []
        return [
            str(item[0]).strip()
            for item in data[1]
            if isinstance(item, list) and item
        ][:limit]
    except Exception as e:
        logger.debug("yt_suggest failed: %s", e)
        return []


# ─── Fallback: scrape search page ───

def _scrape_search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Fallback: scrape la page de recherche YouTube (si InnerTube échoue)."""
    try:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        r = req.get(url, timeout=8, headers={"User-Agent": _YT_UA, "Accept-Language": "fr-FR,fr;q=0.9"})
        if not r.ok:
            return []

        # Extract ytInitialData JSON
        m = re.search(r"var ytInitialData\s*=\s*(\{.+?\});\s*</script>", r.text)
        if not m:
            return []

        data = json.loads(m.group(1))
        contents = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        results = []
        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                vr = item.get("videoRenderer")
                if not vr:
                    continue

                vid = vr.get("videoId", "")
                if not vid:
                    continue

                title = ""
                title_runs = vr.get("title", {}).get("runs", [])
                if title_runs:
                    title = "".join(run.get("text", "") for run in title_runs)

                artist = ""
                for key in ("ownerText", "longBylineText", "shortBylineText"):
                    runs = vr.get(key, {}).get("runs", [])
                    if runs:
                        artist = "".join(run.get("text", "") for run in runs)
                        break

                dur_text = vr.get("lengthText", {}).get("simpleText", "")
                duration = _parse_duration(dur_text) if dur_text else None

                thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
                thumb = thumbs[-1].get("url", "") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                results.append({
                    "title": title or "Titre inconnu",
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "artist": artist,
                    "duration": duration,
                    "thumb": thumb,
                    "thumbnail": thumb,
                    "source": "yt",
                })

                if len(results) >= limit:
                    return results

        return results
    except Exception as e:
        logger.warning("scrape_search failed: %s", e)
        return []


# ─── Routes ───

def _do_autocomplete():
    q = (request.args.get("q") or request.args.get("query") or "").strip()
    limit = request.args.get("limit", 8, type=int)
    if not q:
        return jsonify({"ok": True, "results": []}), 200

    # 1) InnerTube API (rapide, fiable)
    results = _innertube_search(q, limit)

    # 2) Fallback: scrape HTML
    if not results:
        results = _scrape_search(q, limit)

    return jsonify({"ok": True, "results": results}), 200


@bp.get("/search/autocomplete")
def autocomplete():
    return _do_autocomplete()


@bp.get("/autocomplete")
def autocomplete_compat():
    return _do_autocomplete()


@bp.get("/search/suggest")
def suggest():
    """Typeahead instantané (text only, ~50ms)."""
    q = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", 6, type=int)
    if not q:
        return jsonify({"ok": True, "suggestions": []}), 200
    suggestions = _yt_suggest(q, limit)
    return jsonify({"ok": True, "suggestions": suggestions}), 200
