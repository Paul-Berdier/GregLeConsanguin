# extractors/__init__.py

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)


# ─── Erreurs partagées ───
# Définies AVANT l'import des sous-modules : youtube.py / soundcloud.py les
# importent via `from . import …` pendant l'initialisation du package.

class BundleError(Exception):
    """Échec d'expansion d'une playlist/mix/set.

    `code` ∈ {PLAYLIST_UNAVAILABLE, PLAYLIST_EMPTY, UNSUPPORTED_SOURCE}
    `message` : texte FR affichable tel quel à l'utilisateur.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TrackUnavailable(RuntimeError):
    """Titre définitivement illisible (supprimé, privé, géo-bloqué, membres,
    DRM, lien Spotify, lien de playlist passé à stream…) : ne pas réessayer."""

    permanent = True


# ─── Normalisation des liens ───
# Lien sans schéma vers un hôte connu → on préfixe https:// (le "/" ou "?"
# après l'hôte est exigé pour ne pas toucher à une recherche "youtube.com tuto").
_SCHEMELESS_LINK_RE = re.compile(
    r"^(?:(?:www\.|m\.|music\.)?youtube\.com|youtu\.be"
    r"|(?:www\.|on\.|m\.)?soundcloud\.com"
    r"|open\.spotify\.com|spotify\.link)[/?]",
    re.IGNORECASE,
)
_HAS_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_YT_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def normalize_link(s: str) -> str:
    """Nettoie un lien collé : espaces, <…> Discord, schéma manquant, youtu.be+list."""
    t = (s or "").strip()
    if len(t) >= 2 and t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    if (
        t
        and not _HAS_SCHEME_RE.match(t)
        and not any(c.isspace() for c in t)
        and _SCHEMELESS_LINK_RE.match(t)
    ):
        t = "https://" + t

    # youtu.be/ID?list=L[&index=N] → watch?v=ID&list=L[&index=N]
    try:
        u = urlparse(t)
        if u.scheme in ("http", "https") and (u.hostname or "").lower() in ("youtu.be", "www.youtu.be"):
            q = parse_qs(u.query)
            list_id = (q.get("list") or [None])[0]
            vid = (u.path or "").strip("/").split("/")[0]
            if list_id and _YT_VIDEO_ID_RE.fullmatch(vid):
                params = [("v", vid), ("list", list_id)]
                index = (q.get("index") or [None])[0]
                if index:
                    params.append(("index", index))
                t = "https://www.youtube.com/watch?" + urlencode(params)
    except Exception:
        pass
    return t


def is_url(s: str) -> bool:
    return normalize_link(s).lower().startswith(("http://", "https://"))


def is_spotify_url(s: str) -> bool:
    t = normalize_link(s)
    if t.lower().startswith("spotify:"):
        return True
    try:
        host = (urlparse(t).hostname or "").lower()
    except Exception:
        return False
    return host in ("open.spotify.com", "play.spotify.com", "spotify.link") or host.endswith(".spotify.link")


# Import des sous-modules APRÈS les classes/helpers ci-dessus (ils les importent).
from . import soundcloud, youtube
from .token_fetcher import fetch_po_token  # noqa: F401  # facultatif

EXTRACTORS: List[Any] = [youtube, soundcloud]


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
    for mod in EXTRACTORS:
        if getattr(mod, "__name__", "").lower().endswith(name):
            return mod
    return youtube

# ---- Wrappers playlist/mix attendus par music.py ----
def is_bundle_url(url: str) -> bool:
    link = normalize_link(url)
    try:
        return bool(youtube.is_playlist_or_mix_url(link) or soundcloud.is_playlist_url(link))
    except Exception:
        return False

def expand_bundle(
    url: str,
    *,
    limit: int = 10,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> list[dict]:
    """Liste RAPIDE (flat) des titres d'une playlist/mix/set.

    SYNCHRONE : l'appelant la lance dans un thread. Lève BundleError en cas
    d'échec (jamais de [] silencieux) ; PLAYLIST_EMPTY si rien de lisible.
    """
    link = normalize_link(url)
    if is_spotify_url(link):
        raise BundleError(
            "UNSUPPORTED_SOURCE",
            "Les liens Spotify ne sont pas pris en charge : colle un lien YouTube ou SoundCloud.",
        )
    try:
        if youtube.is_playlist_or_mix_url(link):
            entries = youtube.expand_bundle(
                link,
                limit=limit,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
            )
        elif soundcloud.is_playlist_url(link) or soundcloud.is_short_link(link):
            # on.soundcloud.com : résolu d'abord (set → ses titres, titre → lui seul)
            entries = soundcloud.expand_bundle(link, limit=limit)
        else:
            raise BundleError("UNSUPPORTED_SOURCE", "Ce lien n'est pas une playlist prise en charge.")
    except BundleError as e:
        if e.code != "UNSUPPORTED_SOURCE":
            logger.warning("expand_bundle(%s) → %s : %s", link, e.code, e.__cause__ or e.message)
        raise
    except Exception as e:
        logger.exception("expand_bundle(%s) a échoué", link)
        raise BundleError(
            "PLAYLIST_UNAVAILABLE", "Impossible de lire cette playlist pour le moment."
        ) from e
    if not entries:
        raise BundleError("PLAYLIST_EMPTY", "Cette playlist est vide ou ne contient aucun titre lisible.")
    return list(entries)
