"""Extractor dispatch for Greg refonte.

This module centralises access to audio extraction back‑ends for the bot.
It exposes simple helper functions to obtain an extractor class based on
either a provider name (e.g. ``soundcloud``) or a URL.  Each extractor
implements a common interface with ``search()``, ``download()`` and
``stream()`` methods.

See :mod:`greg_refonte.extractors.youtube` and
    :mod:`greg_refonte.extractors.soundcloud` for implementation details.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Import the concrete extractor classes.  If additional back‑ends are added
# in the future they should be imported and dispatched here.
from .youtube import YouTubeExtractor
from .soundcloud import SoundCloudExtractor


def get_search_module(name: str) -> Any:
    """Return an extractor instance for search operations by name.

    Parameters
    ----------
    name: str
        The provider name (e.g. ``"soundcloud"`` or ``"youtube"``).

    Returns
    -------
    object
        An extractor object implementing a ``search()`` method.
    """
    key = name.lower()
    if key in {"soundcloud", "sc"}:
        return SoundCloudExtractor()
    if key in {"youtube", "yt", "ytsearch"}:
        return YouTubeExtractor()
    raise ValueError(f"Unknown search module: {name}")


def get_extractor(url: str) -> Optional[Any]:
    """Return an extractor instance for a given URL.

    The URL is inspected to determine which back‑end should handle it.
    Currently supports YouTube (``youtube.com``, ``youtu.be``) and
    SoundCloud (``soundcloud.com``).  Returns ``None`` if no suitable
    extractor is found.

    Parameters
    ----------
    url: str
        The media URL.

    Returns
    -------
    object or None
        An extractor object implementing ``download`` and ``stream`` or
        ``None`` if the URL cannot be handled.
    """
    u = url.lower()
    if "soundcloud.com" in u or "sndcdn.com" in u:
        return SoundCloudExtractor()
    if "youtube.com" in u or "youtu.be" in u or "yewtu.be" in u:
        return YouTubeExtractor()
    return None
