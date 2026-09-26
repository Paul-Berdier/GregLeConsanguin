# Contrat C1 : expand_bundle YouTube rapide (flat), URLs canoniques, X en tête,
# erreurs typées (BundleError) — jamais de résolution PO / Playwright / non-flat.

from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, urlparse

import greg_shared.extractors as ext
import pytest
from greg_shared.extractors import youtube
from yt_dlp.utils import DownloadError

PL = "PLlaN88a7y2_plecYoJxvRFTLHVbIVAOoc"


def _vid(i: int) -> str:
    return f"v{i:010d}"  # 11 caractères, comme un vrai id YouTube


def _flat_entry(i: int, **extra) -> dict:
    vid = _vid(i)
    e = {
        "_type": "url",
        "ie_key": "Youtube",
        "id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": f"Titre {i}",
        "duration": 200.0 + i,
        "uploader": "Artiste",
        "thumbnails": [{"url": f"https://i.ytimg.com/vi/{vid}/default.jpg"},
                       {"url": f"https://i.ytimg.com/vi/{vid}/hq.jpg"}],
    }
    e.update(extra)
    return e


def _playlist_responder(total=60, entries=None):
    """Simule un listing flat qui respecte playliststart / playlistend."""
    all_entries = entries if entries is not None else [_flat_entry(i) for i in range(1, total + 1)]

    def responder(url, opts):
        start = int(opts.get("playliststart") or 1)
        end = opts.get("playlistend")
        sl = all_entries[start - 1:(int(end) if end else None)]
        return {"_type": "playlist", "id": "PL", "title": "Ma playlist", "entries": list(sl)}

    return responder


@pytest.fixture(autouse=True)
def _forbid_po_and_playwright(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("expand_bundle ne doit jamais résoudre de PO token ni lancer Playwright")

    monkeypatch.setattr(youtube, "_resolve_po_tokens_for", boom)
    from greg_shared.extractors import token_fetcher
    monkeypatch.setattr(token_fetcher, "fetch_po_token", boom)
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex", boom)


def _ids(entries):
    return [parse_qs(urlparse(e["url"]).query)["v"][0] for e in entries]


def test_playlist_url_is_flat_fast_and_uses_shared_opts(fake_ydl, monkeypatch, tmp_path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(youtube, "_HTTP_PROXY", "http://proxy.local:3128")
    monkeypatch.setattr(youtube, "_FORCE_IPV4", True)
    listing = _playlist_responder()
    copies = []

    def responder(url, opts):
        with open(opts["cookiefile"], encoding="utf-8") as f:
            copies.append(f.read())
        return listing(url, opts)

    fake_ydl.responder = responder

    out = ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}", limit=5,
                            cookies_file=str(cookie))

    assert len(out) == 5
    assert len(fake_ydl.calls) == 1, "un seul listing flat attendu"
    url, opts = fake_ydl.calls[0]
    assert url == f"https://www.youtube.com/playlist?list={PL}"
    assert opts["extract_flat"] == "in_playlist"
    assert opts["playlistend"] >= 5
    assert opts.get("noplaylist") is False
    assert opts["proxy"] == "http://proxy.local:3128"
    assert opts["source_address"] == "0.0.0.0"
    # Copie privée du fichier cookies (yt-dlp réécrit son cookiejar à la fermeture)
    assert opts["cookiefile"] != str(cookie)
    assert copies == ["# Netscape HTTP Cookie File\n"]
    assert not os.path.exists(opts["cookiefile"]), "la copie privée doit être supprimée après usage"
    assert "format" not in opts
    assert "po_token" not in (opts.get("extractor_args") or {}).get("youtube", {})


def test_entries_are_canonical_single_track_urls(fake_ydl):
    fake_ydl.responder = _playlist_responder()
    out = ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}", limit=3)
    first = out[0]
    assert set(first) >= {"title", "url", "webpage_url", "artist", "thumb", "duration", "provider"}
    for e in out:
        assert e["url"].startswith("https://www.youtube.com/watch?v=")
        assert "list=" not in e["url"] and "list=" not in e["webpage_url"]
        assert e["provider"] == "youtube"
        assert isinstance(e["duration"], int)
    assert first["title"] == "Titre 1"
    assert first["artist"] == "Artiste"
    assert first["thumb"].endswith("/hq.jpg")


def test_music_youtube_entries_are_canonicalised(fake_ydl):
    ents = [_flat_entry(i, url=f"https://music.youtube.com/watch?v={_vid(i)}") for i in range(1, 6)]
    fake_ydl.responder = _playlist_responder(entries=ents)
    out = ext.expand_bundle(f"https://music.youtube.com/playlist?list={PL}", limit=3)
    assert all(e["url"].startswith("https://www.youtube.com/watch?v=") for e in out)


def test_watch_with_index_puts_x_first_then_followers(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=60)
    x = _vid(25)
    out = ext.expand_bundle(f"https://www.youtube.com/watch?v={x}&list={PL}&index=25", limit=10)
    assert _ids(out) == [_vid(i) for i in range(25, 35)]
    # jamais de fallback vers le début de la playlist
    assert fake_ydl.calls[0][1].get("playliststart") == 25


def test_watch_without_index_locates_x(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=60)
    x = _vid(40)
    out = ext.expand_bundle(f"https://www.youtube.com/watch?v={x}&list={PL}", limit=5)
    assert _ids(out) == [_vid(i) for i in range(40, 45)]


def test_watch_with_stale_index_still_starts_at_x(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=60)
    x = _vid(30)
    out = ext.expand_bundle(f"https://www.youtube.com/watch?v={x}&list={PL}&index=12", limit=4)
    assert _ids(out) == [_vid(i) for i in range(30, 34)]


def test_watch_x_not_in_list_is_prepended_without_duplicate(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=8)
    x = "XXXXXXXXXXX"
    out = ext.expand_bundle(f"https://www.youtube.com/watch?v={x}&list={PL}", limit=4)
    assert _ids(out) == [x, _vid(1), _vid(2), _vid(3)]
    assert out[0]["url"] == f"https://www.youtube.com/watch?v={x}"


def test_youtu_be_with_list_behaves_like_watch(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=30)
    x = _vid(7)
    out = ext.expand_bundle(f"https://youtu.be/{x}?list={PL}&si=abc", limit=3)
    assert _ids(out) == [_vid(7), _vid(8), _vid(9)]


def test_mix_is_extracted_inline_from_watch_page(fake_ydl):
    x = "dQw4w9WgXcQ"
    mix = [_flat_entry(0, id=x, url=f"https://www.youtube.com/watch?v={x}")] + \
          [_flat_entry(i) for i in range(1, 30)]
    fake_ydl.responder = _playlist_responder(entries=mix)
    out = ext.expand_bundle(f"https://youtu.be/{x}?list=RD{x}", limit=10)
    assert len(out) == 10
    assert _ids(out)[0] == x
    called_url = fake_ydl.calls[0][0]
    assert "/playlist" not in called_url, "un mix n'a pas de page /playlist"
    assert f"v={x}" in called_url and f"list=RD{x}" in called_url


def test_mix_without_x_first_is_reordered(fake_ydl):
    x = "dQw4w9WgXcQ"
    mix = [_flat_entry(1), _flat_entry(0, id=x), _flat_entry(2)]
    fake_ydl.responder = _playlist_responder(entries=mix)
    out = ext.expand_bundle(f"https://www.youtube.com/watch?v={x}&list=RD{x}", limit=10)
    assert _ids(out) == [x, _vid(1), _vid(2)]


def test_unavailable_entries_are_skipped(fake_ydl):
    ents = [
        _flat_entry(1, title="[Private video]", duration=None),
        _flat_entry(2, title="[Deleted video]", duration=None),
        _flat_entry(3, availability="subscriber_only"),
        _flat_entry(4, availability="needs_auth"),
        _flat_entry(5),
        _flat_entry(6, availability="premium_only"),
        _flat_entry(7),
        _flat_entry(8, availability="private"),
        _flat_entry(9),
    ]
    fake_ydl.responder = _playlist_responder(entries=ents)
    out = ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}", limit=3)
    assert _ids(out) == [_vid(5), _vid(7), _vid(9)]


def test_channel_tab_is_expanded(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=10)
    out = ext.expand_bundle("https://www.youtube.com/@RickAstleyYT/videos", limit=4)
    assert len(out) == 4


def _channel_home_responder(videos, live=(), shorts=()):
    """Chaîne sans onglet : yt-dlp renvoie UNE playlist PAR onglet (Vidéos, Live, Shorts)."""
    def tab(title, idx):
        return {"_type": "playlist", "id": "UCuAXFkgsw1L7xaCfnd5JJOw", "title": title,
                "entries": [_flat_entry(i) for i in idx]}

    def responder(url, opts):
        entries = [tab("Rick Astley - Videos", videos)]
        if live:
            entries.append(tab("Rick Astley - Live", live))
        if shorts:
            entries.append(tab("Rick Astley - Shorts", shorts))
        return {"_type": "playlist", "id": "UCuAXFkgsw1L7xaCfnd5JJOw",
                "title": "Rick Astley", "entries": entries}

    return responder


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/@RickAstleyYT",
    "https://youtube.com/@RickAstleyYT?si=abcdef",
    "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
    "https://www.youtube.com/user/RickAstleyVEVO",
])
def test_bare_channel_nested_tab_playlists_are_flattened(fake_ydl, url):
    fake_ydl.responder = _channel_home_responder(range(1, 11), live=(20, 21), shorts=(30,))
    out = ext.expand_bundle(url, limit=4)
    # Onglet Vidéos d'abord (derniers uploads)
    assert _ids(out) == [_vid(i) for i in range(1, 5)]
    assert len(fake_ydl.calls) == 1


def test_bare_channel_fills_with_next_tabs_in_order(fake_ydl):
    fake_ydl.responder = _channel_home_responder(range(1, 3), live=(20,), shorts=(30, 31))
    out = ext.expand_bundle("https://www.youtube.com/@RickAstleyYT", limit=10)
    assert _ids(out) == [_vid(1), _vid(2), _vid(20), _vid(30), _vid(31)]


def test_music_album_browse_mpreb_is_listed_flat(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=12)
    url = "https://music.youtube.com/browse/MPREb_gTAcphH99wE"
    assert ext.is_bundle_url(url) is True
    out = ext.expand_bundle(url, limit=3)
    assert len(out) == 3
    called, opts = fake_ydl.calls[0]
    assert called == url  # yt-dlp résout l'album vers sa playlist OLAK5uy_…
    assert opts["extract_flat"] == "in_playlist"


def test_ytdlp_cookie_writeback_never_touches_the_shared_file(fake_ydl, monkeypatch, tmp_path):
    """yt-dlp réécrit son cookiejar à la fermeture : un upload fait pendant
    l'extraction ne doit jamais être écrasé par les anciens cookies."""
    shared = tmp_path / "data" / "yt.txt"
    shared.parent.mkdir()
    shared.write_text("# Netscape HTTP Cookie File\nOLD\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(shared))
    seen = []

    class _WritingYDL(fake_ydl):
        def __exit__(self, *exc):
            ck = self.opts.get("cookiefile")
            seen.append(ck)
            # upload concurrent pendant l'extraction…
            shared.write_text("# Netscape HTTP Cookie File\nNEW\n", encoding="utf-8")
            # …puis save_cookies() de yt-dlp avec l'ancien cookiejar
            with open(ck, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\nOLD (réécrit par yt-dlp)\n")
            return False

    monkeypatch.setattr(youtube, "YoutubeDL", _WritingYDL)
    _WritingYDL.responder = _playlist_responder(total=5)
    ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}", limit=2)
    assert seen and seen[0] and seen[0] != str(shared)
    assert shared.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\nNEW\n"
    assert not os.path.exists(seen[0])


def test_music_browse_vl_is_a_playlist(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=10)
    out = ext.expand_bundle(f"https://music.youtube.com/browse/VL{PL}", limit=2)
    assert len(out) == 2
    assert fake_ydl.calls[0][0] == f"https://www.youtube.com/playlist?list={PL}"


def test_schemeless_playlist_link(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=10)
    out = ext.expand_bundle(f"www.youtube.com/playlist?list={PL}", limit=2)
    assert len(out) == 2


def test_extraction_error_raises_bundle_error_and_logs(fake_ydl, caplog):
    def responder(url, opts):
        raise DownloadError("ERROR: [youtube:tab] PLzzz: Unable to download API page: HTTP Error 400: Bad Request")

    fake_ydl.responder = responder
    with caplog.at_level(logging.WARNING), pytest.raises(ext.BundleError) as ei:
        ext.expand_bundle("https://www.youtube.com/playlist?list=PLzzzzzzzzzzzzzzzz", limit=5)
    assert ei.value.code == "PLAYLIST_UNAVAILABLE"
    assert ei.value.message
    assert caplog.records, "l'échec d'expansion doit être journalisé"


def test_unexpected_exception_is_wrapped(fake_ydl):
    def responder(url, opts):
        raise OSError("réseau KO")

    fake_ydl.responder = responder
    with pytest.raises(ext.BundleError) as ei:
        ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}")
    assert ei.value.code == "PLAYLIST_UNAVAILABLE"


def test_empty_playlist_raises_playlist_empty(fake_ydl):
    fake_ydl.responder = _playlist_responder(entries=[_flat_entry(1, title="[Deleted video]")])
    with pytest.raises(ext.BundleError) as ei:
        ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}")
    assert ei.value.code == "PLAYLIST_EMPTY"


def test_spotify_and_unknown_sources_are_unsupported(fake_ydl):
    fake_ydl.responder = _playlist_responder()
    for url in ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
                "https://example.com/some/page"):
        with pytest.raises(ext.BundleError) as ei:
            ext.expand_bundle(url)
        assert ei.value.code == "UNSUPPORTED_SOURCE"
    assert fake_ydl.calls == []


def test_limit_is_respected(fake_ydl):
    fake_ydl.responder = _playlist_responder(total=100)
    out = ext.expand_bundle(f"https://www.youtube.com/playlist?list={PL}", limit=25)
    assert len(out) == 25
