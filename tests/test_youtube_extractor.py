# tests/test_youtube_extractor.py
import asyncio
import os
import io
import pytest

from yt_dlp.utils import DownloadError  # nécessaire pour simuler le fallback itag=18
from extractors import youtube as yt

pytestmark = pytest.mark.asyncio

# --------------------- helpers locaux ---------------------

def make_fake_search_entries():
    return {
        "entries": [
            {"id": "AAA", "title": "T1", "duration": 100, "thumbnail": "th1", "uploader": "up1"},
            {"id": "BBB", "title": "T2", "duration": 200, "thumbnail": "th2", "uploader": "up2"},
        ]
    }

# --------------------- tests de base ----------------------

def test_is_valid_urls():
    assert yt.is_valid("https://www.youtube.com/watch?v=abc")
    assert yt.is_valid("https://youtu.be/xyz")
    assert yt.is_valid("https://www.youtube.com/shorts/xyz")
    assert not yt.is_valid("https://example.com/video")

def test_redact_headers():
    red = yt._redact_headers({
        "Cookie": "verysecret",
        "Authorization": "Bearer x",
        "x-YouTube-Identity-Token": "tok",
        "Other": "ok"
    })
    assert red["Cookie"].startswith("<redacted:")
    assert red["Authorization"].startswith("<redacted:")
    assert red["x-YouTube-Identity-Token"].startswith("<redacted:")
    assert red["Other"] == "ok"

def test_parse_qs_and_fmt_epoch():
    q = yt._parse_qs("https://x?itag=18&expire=1756473627&dur=222.586")
    assert q["itag"] == "18"
    assert "expire" in q
    # _fmt_epoch should not crash
    _ = yt._fmt_epoch(q["expire"])

# --------------------- search (ytsearch5) -----------------

def test_search_flat(monkeypatch, fake_ydl_factory):
    class FakeYDL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, query, download=False):
            assert download is False
            assert "ytsearch5:" in query
            return make_fake_search_entries()

    fake_ydl_factory(lambda _opts: FakeYDL(_opts))

    res = yt.search("valdo")
    assert len(res) == 2
    assert res[0]["url"].startswith("https://www.youtube.com/watch?v=")
    assert res[0]["title"] == "T1"

# --------------------- stream direct ----------------------

async def test_stream_direct_success(monkeypatch, patch_ffmpeg):
    # _best_info_with_fallbacks renvoie une URL directe exploitable
    def fake_best(query, **kwargs):
        return {
            "title": "Song",
            "url": "https://googlevideo.test/videoplayback?...&itag=18&dur=222.5",
            "http_headers": {"User-Agent": "UAx", "Referer": "https://www.youtube.com/"},
            "_dbg_client_used": "auto",
        }
    monkeypatch.setattr(yt, "_best_info_with_fallbacks", fake_best)

    src, title = await yt.stream("https://youtube.com/watch?v=abc", ffmpeg_path="ffmpeg")
    assert title == "Song"
    assert hasattr(src, "before_options")
    assert "-headers" in src.before_options
    # on veut au minimum UA + Referer dans la ligne headers
    assert "User-Agent" in src.before_options and "Referer" in src.before_options
    assert src.options and "-vn" in src.options

# ----------------- fallback par clients -------------------

def test__best_info_with_fallbacks_client_order(monkeypatch):
    # auto -> pas d'URL, ios -> pas d'URL, web -> pas d'URL, web_mobile -> URL OK
    def fake_probe(query, cookies_file, cookies_from_browser, ffmpeg_path, ratelimit_bps, client=None):
        if client is None:
            return {"title": "auto-no-url"}  # pas de 'url' -> continue
        if client in ("ios", "web", "web_creator"):
            return {"title": f"{client}-no-url"}
        if client == "web_mobile":
            return {"title": "ok", "url": "https://googlevideo/ok", "_dbg_client_used": client}
        return {"title": f"{client}-no-url"}

    monkeypatch.setattr(yt, "_probe_with_client", fake_probe)

    info = yt._best_info_with_fallbacks(
        "https://youtube.com/watch?v=abc",
        cookies_file=None, cookies_from_browser=None,
        ffmpeg_path=None, ratelimit_bps=None
    )
    assert info and info.get("url")
    assert info.get("_dbg_client_used") == "web_mobile"

# -------------- stream: aucun flux trouvable ----------------

async def test_stream_raises_when_no_info(monkeypatch):
    monkeypatch.setattr(yt, "_best_info_with_fallbacks", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        await yt.stream("https://youtube.com/watch?v=notfound", ffmpeg_path="ffmpeg")

# --------------------- stream PIPE ------------------------

async def test_stream_pipe_success(monkeypatch, patch_ffmpeg, patch_popen):
    monkeypatch.setattr(yt, "_best_info_with_fallbacks", lambda *a, **k: {"title": "PipeSong"})
    # Evite toute dépendance à yt-dlp binaire
    monkeypatch.setattr(yt, "_resolve_ytdlp_cli", lambda: ["echo"])
    src, title = await yt.stream_pipe("https://youtube.com/watch?v=abc", ffmpeg_path="ffmpeg")
    assert title == "PipeSong"
    # la source est le stdout du DummyPopen
    assert hasattr(src, "source")

# ---------------------- download OK -----------------------

def test_download_ok(fake_ydl_factory, tmp_path):
    class FakeYDL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            assert download is True
            return {
                "title": "DL Song",
                "duration": 180,
                "requested_downloads": [{"filepath": str(tmp_path / "song.mp3")}],
            }
        def prepare_filename(self, info):
            return str(tmp_path / "dummy.webm")

    fake_ydl_factory(lambda _opts: FakeYDL(_opts))

    path, title, dur = yt.download(
        "https://youtube.com/watch?v=abc",
        ffmpeg_path="ffmpeg",
        out_dir=str(tmp_path),
    )
    assert os.path.basename(path) == "song.mp3"
    assert title == "DL Song"
    assert dur == 180

# --------- download: fallback itag=18 si DownloadError ------

def test_download_fallback_itag18(fake_ydl_factory, tmp_path, monkeypatch):
    class YDLFirst:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            raise DownloadError("Requested format is not available")

    class YDLSecond:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            return {
                "title": "DL Fallback",
                "duration": 200,
                "requested_downloads": [{"filepath": str(tmp_path / "fallback.mp3")}],
            }
        def prepare_filename(self, info):
            return str(tmp_path / "other.webm")

    instances = [YDLFirst(None), YDLSecond(None)]
    def factory(_opts):
        inst = instances.pop(0)
        inst.opts = _opts
        return inst

    fake_ydl_factory(factory)

    path, title, dur = yt.download(
        "https://youtube.com/watch?v=abc",
        ffmpeg_path="ffmpeg",
        out_dir=str(tmp_path),
    )
    assert os.path.basename(path) == "fallback.mp3"
    assert title == "DL Fallback"
    assert dur == 200
