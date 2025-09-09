# extractors/__init__.py

from __future__ import annotations
from typing import Any, List, Optional
from . import youtube, soundcloud

try:
    from . import spotify as _spotify
    SPOTIFY_AVAILABLE = True
except Exception:
    _spotify = None
    SPOTIFY_AVAILABLE = False

EXTRACTORS: List[Any] = []
if SPOTIFY_AVAILABLE:
    EXTRACTORS.append(_spotify)
EXTRACTORS += [youtube, soundcloud]

def infer_provider_from_url(url_or_query: str) -> Optional[str]:
    s = (url_or_query or "").strip()
    for mod in EXTRACTORS:
        try:
            if hasattr(mod, "is_valid") and mod.is_valid(s):
                return getattr(mod, "__name__", "").split(".")[-1]
        except Exception:
            pass
    return "youtube"

def get_extractor(url_or_query: str) -> Any:
    s = (url_or_query or "").strip()
    for mod in EXTRACTORS:
        try:
            if hasattr(mod, "is_valid") and mod.is_valid(s):
                return mod
        except Exception:
            pass
    return youtube

def get_search_module(provider: Optional[str]) -> Any:
    name = (provider or "").strip().lower()
    if name in ("", "auto", "default", "yt", "youtube"):
        return youtube
    if name in ("soundcloud", "sc"):
        return soundcloud
    if name in ("spotify", "sp") and SPOTIFY_AVAILABLE:
        return _spotify
    for mod in EXTRACTORS:
        if getattr(mod, "__name__", "").lower().endswith(name):
            return mod
    return youtube

# ---- Wrappers playlist/mix attendus par music.py ----
def is_bundle_url(url: str) -> bool:
    prov = infer_provider_from_url(url)
    try:
        if prov == "youtube" and hasattr(youtube, "is_playlist_or_mix_url"):
            return bool(youtube.is_playlist_or_mix_url(url))
        if prov == "soundcloud" and hasattr(soundcloud, "is_playlist_url"):
            return bool(soundcloud.is_playlist_url(url))
        if prov == "spotify" and SPOTIFY_AVAILABLE and hasattr(_spotify, "is_playlist_url"):
            return bool(_spotify.is_playlist_url(url))
    except Exception:
        pass
    return False

def expand_bundle(
    url: str,
    *,
    limit: int = 10,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> list[dict]:
    prov = infer_provider_from_url(url)
    try:
        if prov == "youtube" and hasattr(youtube, "expand_bundle"):
            return youtube.expand_bundle(
                url,
                limit=limit,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
            ) or []
        if prov == "soundcloud" and hasattr(soundcloud, "expand_bundle"):
            return soundcloud.expand_bundle(url, limit=limit) or []
        if prov == "spotify" and SPOTIFY_AVAILABLE and hasattr(_spotify, "expand_bundle"):
            return _spotify.expand_bundle(url, limit=limit) or []
    except Exception:
        pass
    return []
