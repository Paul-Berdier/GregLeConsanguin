# Contrat C1 : normalize_link / is_url / is_spotify_url / is_bundle_url + exports.

from __future__ import annotations

import greg_shared.extractors as ext
import pytest


def test_public_exports():
    for name in (
        "normalize_link", "is_url", "is_spotify_url", "is_bundle_url", "expand_bundle",
        "BundleError", "TrackUnavailable", "get_extractor", "get_search_module",
        "infer_provider_from_url",
    ):
        assert hasattr(ext, name), name


def test_error_classes_contract():
    e = ext.BundleError("PLAYLIST_EMPTY", "Playlist vide")
    assert e.code == "PLAYLIST_EMPTY"
    assert e.message == "Playlist vide"
    assert str(e) == "Playlist vide"
    t = ext.TrackUnavailable("Vidéo privée")
    assert isinstance(t, RuntimeError)
    assert t.permanent is True
    assert ext.TrackUnavailable.permanent is True


def test_no_dead_spotify_import():
    assert not hasattr(ext, "_spotify")


@pytest.mark.parametrize("raw,expected", [
    ("  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("<https://www.youtube.com/watch?v=dQw4w9WgXcQ>", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("www.youtube.com/playlist?list=PLabc", "https://www.youtube.com/playlist?list=PLabc"),
    ("youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc", "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc"),
    ("m.youtube.com/watch?v=dQw4w9WgXcQ", "https://m.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("music.youtube.com/playlist?list=OLAK5uy_x", "https://music.youtube.com/playlist?list=OLAK5uy_x"),
    ("soundcloud.com/artist/sets/album", "https://soundcloud.com/artist/sets/album"),
    ("on.soundcloud.com/AbCd", "https://on.soundcloud.com/AbCd"),
    ("m.soundcloud.com/artist/track", "https://m.soundcloud.com/artist/track"),
    ("open.spotify.com/playlist/37i9", "https://open.spotify.com/playlist/37i9"),
    ("spotify.link/abc", "https://spotify.link/abc"),
    ("youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
    # youtu.be + list → watch?v=…&list=…[&index=…] (le reste, ex. si=, est retiré)
    ("https://youtu.be/dQw4w9WgXcQ?list=PLabc&si=xyz",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc"),
    ("youtu.be/dQw4w9WgXcQ?si=zz&list=RDdQw4w9WgXcQ&index=3",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&index=3"),
    # Texte libre : inchangé (juste strip)
    ("  daft punk around the world ", "daft punk around the world"),
    ("youtube.com tutorial", "youtube.com tutorial"),
    ("spotify:track:4uLU6hMCjMI75M1A2tKUQC", "spotify:track:4uLU6hMCjMI75M1A2tKUQC"),
    ("", ""),
])
def test_normalize_link(raw, expected):
    assert ext.normalize_link(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
    ("www.youtube.com/playlist?list=PLabc", True),
    ("<https://soundcloud.com/a/b>", True),
    ("daft punk", False),
    ("youtube.com tutorial", False),
    ("spotify:track:abc", False),
    ("", False),
])
def test_is_url(raw, expected):
    assert ext.is_url(raw) is expected


@pytest.mark.parametrize("raw,expected", [
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", True),
    ("open.spotify.com/track/abc", True),
    ("https://spotify.link/xyz", True),
    ("spotify:album:abc", True),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("spotify greatest hits", False),
])
def test_is_spotify_url(raw, expected):
    assert ext.is_spotify_url(raw) is expected


@pytest.mark.parametrize("raw,expected", [
    ("https://www.youtube.com/playlist?list=PLlaN88a7y2_plecYoJxvRFTLHVbIVAOoc", True),
    ("www.youtube.com/playlist?list=PLlaN88a7y2_plecYoJxvRFTLHVbIVAOoc", True),
    ("youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc", True),
    ("https://youtu.be/dQw4w9WgXcQ?list=RDdQw4w9WgXcQ", True),
    ("https://music.youtube.com/playlist?list=OLAK5uy_abc", True),
    ("https://music.youtube.com/browse/VLPLabcdef", True),
    ("https://www.youtube-nocookie.com/embed/videoseries?list=PLabc", True),
    ("https://www.youtube.com/@RickAstleyYT/videos", True),
    ("https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw", True),
    ("https://soundcloud.com/the-concept-band/sets/the-royal-concept-ep", True),
    ("soundcloud.com/the-concept-band/sets/the-royal-concept-ep", True),
    # Un titre joué « depuis » un set reste un titre
    ("https://soundcloud.com/artist/track?in=artist/sets/foo", False),
    ("https://soundcloud.com/artist/track", False),
    ("https://www.youtube.com/@RickAstleyYT", True),
    ("https://music.youtube.com/browse/MPREb_gTAcphH99wE", True),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://youtu.be/dQw4w9WgXcQ", False),
    ("https://www.youtube.com/clip/UgkxU2HSeGL_NvmDJ-nQJrlLwllwMDBdGZFs", False),
    ("https://www.youtube.com/watch/dQw4w9WgXcQ", False),
    ("https://on.soundcloud.com/AbCdEf123", False),  # hors ligne : titre ou set inconnu
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", False),
    ("daft punk", False),
])
def test_is_bundle_url(raw, expected):
    assert ext.is_bundle_url(raw) is expected
