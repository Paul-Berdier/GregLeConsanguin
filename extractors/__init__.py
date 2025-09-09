from __future__ import annotations
from typing import Any, List, Optional

# Extracteurs concrets
from . import youtube, soundcloud

# Optionnel: Spotify (ne casse pas si absent)
try:
    from . import spotify as _spotify
    SPOTIFY_AVAILABLE = True
except Exception:
    _spotify = None
    SPOTIFY_AVAILABLE = False

# Ordre = priorité de matching d'URL
EXTRACTORS: List[Any] = []
if SPOTIFY_AVAILABLE:
    EXTRACTORS.append(_spotify)
EXTRACTORS += [youtube, soundcloud]


# ---------- Sélection d'extracteur ----------
def infer_provider_from_url(url_or_query: str) -> Optional[str]:
    s = (url_or_query or "").strip()
    for mod in EXTRACTORS:
        try:
            if hasattr(mod, "is_valid") and mod.is_valid(s):
                name = getattr(mod, "__name__", "").split(".")[-1]
                return name or None
        except Exception:
            continue
    # pas d’URL reconnue → on considérera YouTube par défaut (recherche)
    return "youtube"


def get_extractor(url_or_query: str) -> Any:
    """
    Retourne le module extracteur à utiliser en fonction d'une URL.
    Si pas d'URL connue, YouTube par défaut (recherche).
    """
    s = (url_or_query or "").strip()
    for mod in EXTRACTORS:
        try:
            if hasattr(mod, "is_valid") and mod.is_valid(s):
                return mod
        except Exception:
            continue
    return youtube


def get_search_module(provider: Optional[str]) -> Any:
    """
    'youtube' / 'soundcloud' / 'spotify' ; vide/auto → youtube.
    Si Spotify indisponible, fallback YouTube.
    """
    name = (provider or "").strip().lower()
    if name in ("", "auto", "default", "yt", "youtube"):
        return youtube
    if name in ("soundcloud", "sc"):
        return soundcloud
    if name in ("spotify", "sp") and SPOTIFY_AVAILABLE:
        return _spotify
    # tentative par nom de module (compat)
    for mod in EXTRACTORS:
        mod_name = getattr(mod, "__name__", "")
        if mod_name.lower().endswith(name):
            return mod
    return youtube


# ---------- Playlists / Mix (wrappers génériques) ----------
def is_bundle_url(url: str) -> bool:
    """
    True si l’URL correspond à une “liste” (playlist/mix) pour le provider détecté.
    Implémente aujourd’hui YouTube; autres providers → False si non supporté.
    """
    prov = infer_provider_from_url(url)
    try:
        if prov == "youtube" and hasattr(youtube, "is_playlist_or_mix_url"):
            return bool(youtube.is_playlist_or_mix_url(url))
        if prov == "soundcloud" and hasattr(soundcloud, "is_playlist_url"):
            return bool(soundcloud.is_playlist_url(url))  # existe si tu l’implémentes plus tard
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
) -> List[dict]:
    """
    Déplie une URL playlist/mix en items normalisés (title/url/artist/thumb/duration/provider).
    Route vers l’extracteur du provider détecté. Si non supporté → [].
    """
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
