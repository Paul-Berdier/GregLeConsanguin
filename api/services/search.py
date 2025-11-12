# api/services/search.py
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers

_YT_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{6,})")
_HMS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")  # HH:MM:SS ou M:SS


def _to_seconds(duration: Any) -> Optional[int]:
    if duration is None:
        return None
    if isinstance(duration, int):
        return duration
    if isinstance(duration, float):
        return int(duration)
    if isinstance(duration, str):
        s = duration.strip()
        if s.isdigit():
            return int(s)
        m = _HMS_RE.match(s)
        if m:
            h = int(m.group(1) or 0)
            mm = int(m.group(2))
            ss = int(m.group(3))
            return h * 3600 + mm * 60 + ss
    return None


def _canon_youtube_url(url: str) -> str:
    if "youtu" not in (url or ""):
        return url
    m = _YT_ID_RE.search(url)
    if not m:
        return url
    vid = m.group(1)
    return f"https://www.youtube.com/watch?v={vid}"


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        key = (it.get("url") or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _norm_from_ytextractor(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalise un item renvoyé par extractors.youtube.search(), cf. youtube._normalize_search_entries()
    attendu: title, url/webpage_url, duration, thumb, uploader...
    """
    if not isinstance(item, dict):
        return None
    title = item.get("title") or ""
    url = item.get("webpage_url") or item.get("url") or ""
    if not title or not url:
        return None
    url = _canon_youtube_url(url)
    duration = _to_seconds(item.get("duration"))
    thumb = item.get("thumb") or item.get("thumbnail")
    return {
        "title": str(title),
        "url": str(url),
        "duration": duration,
        "source": "yt",
        "thumbnail": thumb,
    }


# ---------------------------------------------------------------------------
# Imports prudents (évite de casser si extractors/__init__.py importe d'autres modules)
def _try_import_extractors_youtube():
    try:
        # Attention: importer "extractors.youtube" charge d'abord extractors/__init__.py
        # Si ce dernier importe des modules absents (ex: soundcloud), ça peut échouer.
        import importlib
        return importlib.import_module("extractors.youtube")
    except Exception as e:
        log.debug("extractors.youtube indisponible (%s) — fallback yt_dlp", e)
        return None


def _yt_dlp_search(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fallback direct via yt_dlp si l'import de l'extracteur échoue."""
    try:
        from yt_dlp import YoutubeDL
    except Exception as e:
        log.warning("yt_dlp non disponible pour le fallback: %s", e)
        return []

    n = max(1, min(int(limit or 5), 15))
    opts = {
        "quiet": True,
        "no_warnings": True,
        "default_search": f"ytsearch{n}",
        "extract_flat": True,
        "noplaylist": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            data = ydl.extract_info(query, download=False)
            entries = (data or {}).get("entries") or []
    except Exception as e:
        log.debug("yt_dlp search error: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for e in entries:
        title = e.get("title") or ""
        url = e.get("webpage_url") or e.get("url") or ""
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            vid = e.get("id")
            if vid:
                url = f"https://www.youtube.com/watch?v={vid}"
        norm = _norm_from_ytextractor({
            "title": title,
            "webpage_url": url,
            "duration": e.get("duration"),
            "thumb": (e.get("thumbnails") or [{}])[-1].get("url") if isinstance(e.get("thumbnails"), list) else e.get("thumbnail"),
        })
        if norm:
            out.append(norm)
    return out


# ---------------------------------------------------------------------------
# API publique

def autocomplete(q: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    Recherche YouTube unifiée (extracteur natif si possible, sinon fallback yt_dlp).
    Retour: liste d'items normalisés: {title, url, duration, source='yt', thumbnail}
    """
    q = (q or "").strip()
    if not q:
        return []

    # Cas URL collée directement
    if q.startswith("http://") or q.startswith("https://"):
        item = _norm_from_ytextractor({"title": q, "webpage_url": q, "duration": None, "thumb": None})
        return [item] if item else []

    results: List[Dict[str, Any]] = []

    # 1) Tentative via ton extracteur YouTube (préféré)
    yt = _try_import_extractors_youtube()
    if yt and hasattr(yt, "search"):
        try:
            raw = yt.search(q)  # renvoie 5 entrées normalisées par _normalize_search_entries() :contentReference[oaicite:1]{index=1}
            for r in raw or []:
                it = _norm_from_ytextractor(r)
                if it:
                    results.append(it)
        except Exception as e:
            log.debug("extractors.youtube.search() a échoué: %s", e)

    # 2) Fallback yt_dlp (utile si l'import a raté ou si on veut plus que 5 résultats)
    if (not results) or (limit and len(results) < limit):
        more = _yt_dlp_search(q, limit)
        # merge + dédup
        merged = {r["url"]: r for r in results}
        for m in more:
            merged.setdefault(m["url"], m)
        results = list(merged.values())

    # Tri simple: titre contenant la requête en premier
    q_low = q.lower()
    results.sort(key=lambda r: (0 if q_low in (r.get("title") or "").lower() else 1))

    # Coupe à 'limit'
    if limit and len(results) > limit:
        results = results[:limit]

    return _dedupe(results)
