"""Autocomplete : un lien collé ne déclenche jamais de recherche InnerTube."""
from __future__ import annotations

import pytest

import api.routes.search as search_mod

BASE = "/api/v1"


@pytest.fixture()
def no_network(monkeypatch):
    calls = []

    def fake_innertube(q, limit=8):
        calls.append(("innertube", q))
        return [{"title": "t", "url": "https://www.youtube.com/watch?v=abc", "source": "yt"}]

    def fake_scrape(q, limit=8):
        calls.append(("scrape", q))
        return []

    def fake_suggest(q, limit=8):
        calls.append(("suggest", q))
        return ["s"]

    monkeypatch.setattr(search_mod, "_innertube_search", fake_innertube)
    monkeypatch.setattr(search_mod, "_scrape_search", fake_scrape)
    monkeypatch.setattr(search_mod, "_yt_suggest", fake_suggest)
    return calls


URLS = [
    "https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ",
    "http://youtu.be/dQw4w9WgXcQ",
    "  <https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M>  ",
    "youtube.com/playlist?list=PL123",
    "www.youtube.com/watch?v=abc&list=PL1",
    "m.youtube.com/watch?v=abc",
    "music.youtube.com/playlist?list=OLAK5uy_x",
    "youtu.be/abc?list=PL1",
    "soundcloud.com/artist/sets/album",
    "on.soundcloud.com/AbCd",
    "m.soundcloud.com/artist/sets/x",
    "open.spotify.com/album/xyz",
    "spotify.link/abc",
    "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
    "HTTPS://WWW.YOUTUBE.COM/playlist?list=PL1",
]


@pytest.mark.parametrize("q", URLS)
@pytest.mark.parametrize("path", ["/search/autocomplete", "/autocomplete"])
def test_autocomplete_skips_search_for_urls(client, no_network, q, path):
    r = client.get(f"{BASE}{path}", query_string={"q": q, "limit": 6})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "results": []}
    assert no_network == []


@pytest.mark.parametrize("q", ["daft punk around the world", "youtube rewind", "soundcloud rap fr", "https"])
def test_autocomplete_still_searches_text(client, no_network, q):
    r = client.get(f"{BASE}/search/autocomplete", query_string={"q": q, "limit": 6})
    assert r.status_code == 200
    assert len(r.get_json()["results"]) == 1
    assert no_network[0] == ("innertube", q)


def test_suggest_skips_urls(client, no_network):
    r = client.get(f"{BASE}/search/suggest", query_string={"q": "https://youtu.be/abc"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "suggestions": []}
    assert no_network == []
