from extractors.youtube import is_valid as yt_is_valid
from extractors.soundcloud import is_valid as sc_is_valid


def test_youtube_is_valid():
    assert yt_is_valid('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
    assert yt_is_valid('https://youtu.be/dQw4w9WgXcQ')
    assert not yt_is_valid('https://soundcloud.com/artist/track')


def test_soundcloud_is_valid():
    assert sc_is_valid('https://soundcloud.com/artist/track')
    assert not sc_is_valid('https://www.youtube.com/watch?v=abc')