# extractors/__init__.py
from __future__ import annotations
from typing import Any, List, Optional

# Extracteurs de base
from . import youtube, soundcloud

# Liste ordonnée d'extracteurs (ordre = priorité URL matching)
EXTRACTORS: List[Any] = [youtube, soundcloud]

# Import Spotify de façon optionnelle (ne casse pas si absent)
try:
    from . import spotify as _spotify
    SPOTIFY_AVAILABLE = True
    # On met Spotify en tête pour matcher d'abord les URLs Spotify
    EXTRACTORS.insert(0, _spotify)
except Exception:
    _spotify = None
    SPOTIFY_AVAILABLE = False


def get_extractor(url_or_query: str) -> Any:
    """
    Retourne le module extracteur à utiliser en fonction d'une URL.
    - Si l'URL correspond à Spotify/SoundCloud/YouTube → renvoie le bon module
    - Sinon (pas une URL connue) → fallback YouTube (recherche)
    """
    s = (url_or_query or "").strip()
    for mod in EXTRACTORS:
        try:
            if hasattr(mod, "is_valid") and mod.is_valid(s):
                return mod
        except Exception:
            # Un extractor ne doit jamais tout faire planter
            continue
    # Pas de match URL → on considère que c'est une recherche → YouTube prioritaire
    return youtube


def get_search_module(provider: Optional[str]) -> Any:
    """
    Retourne le module de recherche demandé par la source (provider).
    - provider in {"youtube", "soundcloud", "spotify"} (insensible à la casse)
    - provider in {"", None, "auto"} → YouTube par défaut (priorité sur SoundCloud)
    - Si Spotify indisponible, on ignore la demande et on retombe sur YouTube.
    """
    name = (provider or "").strip().lower()
    if name in ("", "auto", "default", "yt"):
        return youtube

    # Match par nom de module: "extractors.youtube" → endswith("youtube")
    for mod in EXTRACTORS:
        mod_name = getattr(mod, "__name__", "")
        if mod_name.lower().endswith(name):
            if mod is _spotify and not SPOTIFY_AVAILABLE:
                break  # on cassera plus bas vers YouTube
            return mod

    # Alias explicites
    if name in ("youtube", "ytdlp"):
        return youtube
    if name in ("soundcloud", "sc"):
        return soundcloud
    if name in ("spotify", "sp") and SPOTIFY_AVAILABLE:
        return _spotify

    # Fallback final → YouTube
    return youtube
