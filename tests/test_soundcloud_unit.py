# tests/test_soundcloud_unit.py
import os
import types
import asyncio
import pytest

# On importe le module à tester
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "extractors" / "soundcloud.py"
spec = importlib.util.spec_from_file_location("soundcloud", str(MODULE_PATH))
soundcloud = importlib.util.module_from_spec(spec)
sys.modules["soundcloud"] = soundcloud  # pour que les patches qui importent trouvent le module
spec.loader.exec_module(soundcloud)


def test_is_valid_true_false():
    assert soundcloud.is_valid("https://soundcloud.com/artist/track") is True
    assert soundcloud.is_valid("https://example.com/whatever") is False


def test_sc_client_ids_parsing(monkeypatch):
    # différents séparateurs : espaces, virgules, points-virgules
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "id1, id2 ; id3  id4")
    ids = soundcloud._sc_client_ids()
    # L'ordre est random (shuffle), on valide l'ensemble
    assert set(ids) == {"id1", "id2", "id3", "id4"}

    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "")
    assert soundcloud._sc_client_ids() == []


def test_sc_resolve_track_success(monkeypatch):
    # Mock requests.Session.get -> retourne un JSON de track
    class OKResp:
        ok = True
        def json(self):
            return {"kind": "track", "title": "Mock title", "media": {"transcodings": []}, "duration": 123456}

    class FakeSession:
        def __init__(self): self.headers = {}
        def get(self, url, params=None, timeout=None): return OKResp()

    monkeypatch.setattr(soundcloud, "requests", types.SimpleNamespace(Session=lambda: FakeSession()))
    data = soundcloud._sc_resolve_track("https://soundcloud.com/foo/bar", client_id="abc")
    assert data and data.get("kind") == "track" and data.get("title") == "Mock title"


def test_sc_pick_progressive_stream_progressive_ok(monkeypatch):
    # track_json avec progressive
    track_json = {
        "title": "Titre P",
        "duration": 1000,
        "media": {
            "transcodings": [
                {"format": {"protocol": "progressive"}, "url": "https://api-v2.soundcloud.com/media/signed/prog"}
            ]
        },
    }

    class OKResp:
        ok = True
        def json(self): return {"url": "https://cdn.soundcloud.com/audio.mp3?sig=xyz"}

    class FakeSession:
        def __init__(self): self.headers = {}
        def get(self, url, params=None, timeout=None): return OKResp()

    monkeypatch.setattr(soundcloud, "requests", types.SimpleNamespace(Session=lambda: FakeSession()))
    stream_url, title, duration = soundcloud._sc_pick_progressive_stream(track_json, client_id="abc")
    assert stream_url.startswith("http")
    assert title == "Titre P"
    assert duration == 1  # 1000 ms arrondi -> 1 sec


def test_stream_progressive_path(monkeypatch):
    """Vérifie que stream() retourne un objet audio FFmpeg mocké quand progressive OK."""
    # 1) mock des helpers de résolution
    def fake_resolve(url, cid):  # renvoie un track_json minimal
        return {"title": "X", "duration": 2000, "media": {"transcodings": [{"format": {"protocol": "progressive"}, "url": "U"}]}}

    def fake_pick(track_json, cid, timeout=8.0):
        return "https://cdn.soundcloud.com/x.mp3", "X", 2

    monkeypatch.setattr(soundcloud, "_sc_client_ids", lambda: ["cid1"])
    monkeypatch.setattr(soundcloud, "_sc_resolve_track", fake_resolve)
    monkeypatch.setattr(soundcloud, "_sc_pick_progressive_stream", fake_pick)

    # 2) mock de discord.FFmpegPCMAudio
    class DummyFF:
        def __init__(self, url, before_options=None, options=None, executable=None):
            self.url = url
            self.executable = executable

    fake_discord = types.SimpleNamespace(FFmpegPCMAudio=DummyFF)
    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    loop = asyncio.new_event_loop()
    try:
        source, title = loop.run_until_complete(soundcloud.stream(
            "https://soundcloud.com/artist/track",
            ffmpeg_path="/usr/bin/ffmpeg"
        ))
    finally:
        loop.close()

    assert isinstance(source, DummyFF)
    assert source.url.startswith("http")
    assert title == "X"
    assert source.executable == "/usr/bin/ffmpeg"


def test_stream_fallback_yt_dlp(monkeypatch):
    """Vérifie le fallback via yt_dlp (download=False) sans importer yt_dlp réel."""
    # neutralise la 1ère branche (API)
    monkeypatch.setattr(soundcloud, "_sc_client_ids", lambda: [])

    # ⚠️ Patch **directement** l’attribut importé dans le module
    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url_or_query, download=False):
            return {"url": "https://hls.cdn/mock.m3u8", "title": "HLS Mock"}

    monkeypatch.setattr(soundcloud, "YoutubeDL", FakeYDL, raising=True)

    # mock de discord.FFmpegPCMAudio
    class DummyFF:
        def __init__(self, url, before_options=None, options=None, executable=None):
            self.url = url
            self.before_options = before_options
            self.options = options
            self.executable = executable

    fake_discord = types.SimpleNamespace(FFmpegPCMAudio=DummyFF)
    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    loop = asyncio.new_event_loop()
    try:
        source, title = loop.run_until_complete(soundcloud.stream(
            "ma recherche cool",
            ffmpeg_path="/usr/bin/ffmpeg"
        ))
    finally:
        loop.close()

    assert isinstance(source, DummyFF)
    assert source.url.endswith(".m3u8")
    assert title == "HLS Mock"
    assert "-reconnect 1" in source.before_options
    assert source.executable == "/usr/bin/ffmpeg"


def test_download_happy_path(monkeypatch, tmp_path):
    """Teste download() en simulant yt_dlp + conversion FFmpeg si .opus, puis .mp3 existant."""
    # ⚠️ Patch **directement** l’attribut importé dans le module
    class FakeYDL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            # Simule un .opus que le postprocess convertira ensuite
            return {"title": "DL Track", "duration": 12, "_filename": "downloads/greg_audio.opus"}
        def download(self, urls): pass
        def prepare_filename(self, info):
            # Simule un .mp3 déjà présent après postprocessor
            return "downloads/greg_audio.mp3"

    monkeypatch.setattr(soundcloud, "YoutubeDL", FakeYDL, raising=True)

    # Fake subprocess.run (conversion) + création du fichier
    def fake_run(cmd):
        # crée un fichier final .mp3
        out = "downloads/greg_audio.mp3"
        Path("downloads").mkdir(exist_ok=True)
        Path(out).write_bytes(b"fake-mp3")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(soundcloud, "subprocess", types.SimpleNamespace(run=fake_run))
    # s'assure que os.path.exists voit bien le fichier, même si p est un Path
    monkeypatch.setattr(soundcloud.os.path, "exists", lambda p: str(p).endswith(".mp3"))

    loop = asyncio.new_event_loop()
    try:
        filename, title, duration = loop.run_until_complete(soundcloud.download(
            url="https://soundcloud.com/a/b",
            ffmpeg_path="/usr/bin/ffmpeg"
        ))
    finally:
        loop.close()

    assert str(filename).endswith(".mp3")
    assert title == "DL Track"
    assert duration == 12

