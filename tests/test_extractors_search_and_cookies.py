# tests/test_extractors_search_and_cookies.py
import importlib
import os
import pytest

@pytest.fixture
def fake_youtubedl(monkeypatch):
    class DummyYDL:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, query, download=False):
            q = str(query)
            if q.startswith("ytsearch3:"):
                return {"entries":[
                    {"title":"Y1","url":"https://youtu.be/1"},
                    {"title":"Y2","url":"https://youtu.be/2"},
                    {"title":"Y3","url":"https://youtu.be/3"},
                ]}
            if q.startswith("scsearch3:"):
                return {"entries":[
                    {"title":"S1","url":"https://soundcloud.com/a/b"},
                ]}
            # metadata pour download()
            return {"title":"Z", "duration": 123, "ext":"webm"}
        def download(self, urls): return 0
        def prepare_filename(self, info): return "downloads/greg_audio.webm"
    # on ne patchera pas yt_dlp.YoutubeDL ici ; on patchera le symbole dans chaque module
    return DummyYDL

def test_youtube_search(fake_youtubedl, monkeypatch):
    m = importlib.import_module("extractors.youtube")
    monkeypatch.setattr(m, "YoutubeDL", fake_youtubedl)  # <- PATCH SUR LE MODULE
    out = m.search("rick astley")
    assert len(out) == 3 and out[0]["url"].startswith("https://youtu")

def test_soundcloud_search(fake_youtubedl, monkeypatch):
    m = importlib.import_module("extractors.soundcloud")
    monkeypatch.setattr(m, "YoutubeDL", fake_youtubedl)
    out = m.search("lofi")
    assert len(out) == 1 and out[0]["url"].startswith("https://soundcloud")

def test_youtube_download_injects_cookiefile(tmp_path, fake_youtubedl, monkeypatch):
    cookies = tmp_path / "youtube.com_cookies.txt"
    # header strict attendu par yt-dlp
    cookies.write_text("# Netscape HTTP Cookie File\n")
    m = importlib.import_module("extractors.youtube")
    captured = {}
    class SpyYDL(fake_youtubedl):
        def __init__(self, opts):
            captured["opts"] = opts
            super().__init__(opts)
    monkeypatch.setattr(m, "YoutubeDL", SpyYDL)
    # Forcer l'existence des chemins utilisés
    monkeypatch.setattr(os.path, "exists",
                        lambda p: True if str(p)==str(cookies) or "downloads" in str(p) else False)
    fn, title, duration = m.download("https://www.youtube.com/watch?v=abc",
                                     ffmpeg_path="ffmpeg", cookies_file=str(cookies))
    assert "cookiefile" in captured["opts"] and captured["opts"]["cookiefile"] == str(cookies)
    assert fn.endswith(".mp3") and title and duration == 123
