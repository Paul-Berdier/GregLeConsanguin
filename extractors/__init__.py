# extractors/__init__.py
# Factory d’extracteurs pour Greg le Consanguin
# - get_extractor(url) -> instance avec .stream(), .download(), et éventuellement .get_playlist()
# - get_search_module(name) -> module de recherche minimal (optionnel)

from .youtube import YouTubeExtractor
from . import soundcloud as sc_mod

def get_extractor(url: str):
    """Retourne l’extracteur adapté à l’URL ou None si inconnu."""
    if not url:
        return None

    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return YouTubeExtractor()
    if "soundcloud.com" in u:
        # On réutilise le module SoundCloud sous forme de wrapper simple
        return _SoundCloudExtractorWrapper()
    return None


def get_search_module(name: str):
    """Optionnel: expose un module de recherche pour /play 'texte' si tu veux garder la recherche."""
    if not name:
        return None
    name = name.lower()
    if name == "soundcloud":
        return _SoundCloudSearchWrapper()
    return None


# ---- Wrappers légers autour du module soundcloud.py existant ----

class _SoundCloudExtractorWrapper:
    async def stream(self, url: str, ffmpeg_path: str):
        return await sc_mod.stream(url, ffmpeg_path)

    async def download(self, url: str, ffmpeg_path: str, cookies_file: str = None):
        return await sc_mod.download(url, ffmpeg_path, cookies_file)

    def get_playlist(self, url: str):
        """
        SoundCloud playlists (si besoin) : ici on peut implémenter plus tard.
        On renvoie une 'playlist' mono-item pour rester compatible avec l’API.
        """
        return [{"title": url, "url": url}]


class _SoundCloudSearchWrapper:
    def search(self, query: str):
        return sc_mod.search(query)
