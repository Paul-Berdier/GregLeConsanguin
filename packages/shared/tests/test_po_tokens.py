# PO tokens : liste (pas une chaîne jointe), résolution instantanée sans id vidéo,
# auto-fetch Playwright opt-in (YT_PO_AUTOFETCH=1) + cache négatif global.

from __future__ import annotations

import threading
import time

import pytest
from greg_shared.extractors import token_fetcher, youtube
from yt_dlp import YoutubeDL

TOKENS = ["mweb.gvs+AAAABBBBCCCCDDDD", "web.gvs+AAAABBBBCCCCDDDD"]


def test_mk_opts_passes_po_tokens_as_a_list():
    opts = youtube._mk_opts(po_tokens=TOKENS)
    assert opts["extractor_args"]["youtube"]["po_token"] == TOKENS


def test_ytdlp_sees_full_po_tokens():
    # Sans réseau : on vérifie ce que l'extracteur YouTube lit réellement.
    with YoutubeDL(youtube._mk_opts(po_tokens=TOKENS)) as ydl:
        ie = ydl.get_info_extractor("Youtube")
        seen = ie._configuration_arg("po_token", [], casesense=True)
    assert seen == TOKENS


def test_no_video_id_returns_immediately_without_extraction(monkeypatch, fake_ydl):
    def responder(u, o):
        raise AssertionError("aucune extraction pour résoudre un PO token")

    fake_ydl.responder = responder
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex",
                        lambda *a, **k: pytest.fail("pas de Playwright sans id vidéo"))
    monkeypatch.setenv("YT_PO_AUTOFETCH", "1")
    t0 = time.monotonic()
    assert youtube._resolve_po_tokens_for(
        "https://www.youtube.com/playlist?list=PLlaN88a7y2_plecYoJxvRFTLHVbIVAOoc") == []
    assert time.monotonic() - t0 < 0.5
    assert fake_ydl.calls == []


def test_env_tokens_returned_even_without_video_id(monkeypatch):
    monkeypatch.setenv("YT_PO_TOKEN", "RAWTOKEN1234567890")
    toks = youtube._resolve_po_tokens_for("https://www.youtube.com/playlist?list=PLabc")
    assert "mweb.gvs+RAWTOKEN1234567890" in toks


def test_autofetch_is_opt_in(monkeypatch):
    calls = []
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex", lambda vid, timeout_ms=0: calls.append(vid))
    assert youtube._resolve_po_tokens_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == []
    assert calls == []


def test_autofetch_enabled_calls_fetcher(monkeypatch):
    calls = []

    def fake_fetch(vid, timeout_ms=0):
        calls.append(vid)
        return "T" * 40, "ok"

    monkeypatch.setenv("YT_PO_AUTOFETCH", "1")
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex", fake_fetch)
    toks = youtube._resolve_po_tokens_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert calls == ["dQw4w9WgXcQ"]
    assert toks and all(t.endswith("T" * 40) for t in toks)


def test_busy_fetcher_result_is_not_cached(monkeypatch):
    """Un autre fetch occupait Chromium : rien n'a été tenté pour CETTE vidéo,
    donc pas de [] en cache (sinon plus aucun essai pendant 30 min)."""
    answers = [(None, "busy"), ("T" * 40, "ok")]
    calls = []

    def fake_fetch(vid, timeout_ms=0):
        calls.append(vid)
        return answers.pop(0)

    monkeypatch.setenv("YT_PO_AUTOFETCH", "1")
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex", fake_fetch)
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert youtube._resolve_po_tokens_for(url) == []
    assert youtube._po_cache_get("dQw4w9WgXcQ") is None
    toks = youtube._resolve_po_tokens_for(url)
    assert calls == ["dQw4w9WgXcQ", "dQw4w9WgXcQ"]
    assert toks and all(t.endswith("T" * 40) for t in toks)


def test_negative_cache_skip_is_not_cached_per_video(monkeypatch):
    # Cache négatif GLOBAL (10 min) : rien tenté pour cette vidéo → pas de [] pour 30 min
    answers = [(None, "negative_cache:timeout"), ("T" * 40, "ok")]
    monkeypatch.setenv("YT_PO_AUTOFETCH", "1")
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex", lambda vid, timeout_ms=0: answers.pop(0))
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert youtube._resolve_po_tokens_for(url) == []
    assert youtube._po_cache_get("dQw4w9WgXcQ") is None
    assert youtube._resolve_po_tokens_for(url)


def test_not_found_result_is_cached_per_video(monkeypatch):
    calls = []

    def fake_fetch(vid, timeout_ms=0):
        calls.append(vid)
        return None, "not_found"

    monkeypatch.setenv("YT_PO_AUTOFETCH", "1")
    monkeypatch.setattr(token_fetcher, "fetch_po_token_ex", fake_fetch)
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert youtube._resolve_po_tokens_for(url) == []
    assert youtube._resolve_po_tokens_for(url) == []
    assert calls == ["dQw4w9WgXcQ"]


def test_invalidate_keeps_negative_entries():
    youtube._po_cache_set("aaaaaaaaaaa", [])
    youtube._po_cache_set("bbbbbbbbbbb", TOKENS)
    youtube.invalidate_po_cache("aaaaaaaaaaa")
    youtube.invalidate_po_cache("bbbbbbbbbbb")
    assert youtube._po_cache_get("aaaaaaaaaaa") == []  # Playwright n'est pas relancé
    assert youtube._po_cache_get("bbbbbbbbbbb") is None
    youtube.invalidate_po_cache()
    assert youtube._po_cache_get("aaaaaaaaaaa") is None


# ── token_fetcher : cache négatif global, sérialisation ──

def test_not_found_is_negative_cached(monkeypatch):
    runs = []

    def fake_worker(video_id, timeout_ms, out, stop=None):
        runs.append(video_id)
        out["token"] = None
        out["why"] = "not_found"

    monkeypatch.setattr(token_fetcher, "_worker_fetch", fake_worker)
    assert token_fetcher.fetch_po_token("aaaaaaaaaaa", timeout_ms=100) is None
    assert token_fetcher.fetch_po_token("bbbbbbbbbbb", timeout_ms=100) is None
    assert runs == ["aaaaaaaaaaa"], "le cache négatif doit être global (pas par vidéo)"


def test_timeout_is_negative_cached_and_stops_worker(monkeypatch):
    stopped = threading.Event()
    runs = []

    def slow_worker(video_id, timeout_ms, out, stop=None):
        runs.append(video_id)
        if stop is not None and stop.wait(5):
            stopped.set()

    monkeypatch.setattr(token_fetcher, "_worker_fetch", slow_worker)
    monkeypatch.setattr(token_fetcher, "_JOIN_GRACE_S", 0.05)
    t0 = time.monotonic()
    assert token_fetcher.fetch_po_token("aaaaaaaaaaa", timeout_ms=50) is None
    assert time.monotonic() - t0 < 2
    assert stopped.wait(2), "le worker doit être prié de fermer Chromium après le timeout"
    assert token_fetcher.fetch_po_token("bbbbbbbbbbb", timeout_ms=50) is None
    assert runs == ["aaaaaaaaaaa"]


def test_concurrent_fetch_does_not_start_a_second_browser(monkeypatch):
    release = threading.Event()
    started = threading.Event()
    runs = []

    def blocking_worker(video_id, timeout_ms, out, stop=None):
        runs.append(video_id)
        started.set()
        release.wait(5)
        out["token"] = "Z" * 40
        out["why"] = "ok"

    monkeypatch.setattr(token_fetcher, "_worker_fetch", blocking_worker)
    results = {}
    th = threading.Thread(target=lambda: results.setdefault(
        "first", token_fetcher.fetch_po_token("aaaaaaaaaaa", timeout_ms=5000)))
    th.start()
    assert started.wait(2)
    assert token_fetcher.fetch_po_token("bbbbbbbbbbb", timeout_ms=5000) is None
    assert token_fetcher.fetch_po_token_ex("ccccccccccc", timeout_ms=5000) == (None, "busy")
    release.set()
    th.join(5)
    assert results["first"] == "Z" * 40
    assert runs == ["aaaaaaaaaaa"]


def test_fetch_po_token_ex_reports_reason(monkeypatch):
    def fake_worker(video_id, timeout_ms, out, stop=None):
        out["token"] = "Q" * 40
        out["why"] = "ok"

    monkeypatch.setattr(token_fetcher, "_worker_fetch", fake_worker)
    assert token_fetcher.fetch_po_token_ex("aaaaaaaaaaa", timeout_ms=100) == ("Q" * 40, "ok")
    assert token_fetcher.fetch_po_token("aaaaaaaaaaa", timeout_ms=100) == "Q" * 40
    token_fetcher._set_negative_cache("not_found")
    tok, why = token_fetcher.fetch_po_token_ex("aaaaaaaaaaa", timeout_ms=100)
    assert tok is None and why.startswith("negative_cache")
