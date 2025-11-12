# api/services/oembed.py
from __future__ import annotations

import functools
import requests
from urllib.parse import urlparse

_YT_OEMBED = "https://www.youtube.com/oembed"
_SC_OEMBED = "https://soundcloud.com/oembed"

@functools.lru_cache(maxsize=512)
def oembed(page_url: str, timeout: float = 4.0) -> dict:
    """
    Renvoie {title, author_name, thumbnail_url} ou {}.
    LRU cache pour ne pas re-taper les mêmes URLs.
    """
    if not page_url:
        return {}
    host = (urlparse(page_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    params = {"format": "json", "url": page_url}
    try:
        if "youtube" in host or "youtu.be" in host or "music.youtube.com" in host:
            r = requests.get(_YT_OEMBED, params=params, timeout=timeout)
            if r.ok:
                return r.json()
        elif "soundcloud.com" in host or "sndcdn.com" in host:
            r = requests.get(_SC_OEMBED, params=params, timeout=timeout)
            if r.ok:
                return r.json()
    except Exception:
        pass
    return {}
