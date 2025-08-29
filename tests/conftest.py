# tests/conftest.py
import io
import types
import pytest

class DummyAudio:
    """Remplace discord.FFmpegPCMAudio pour ne pas lancer ffmpeg."""
    def __init__(self, source, *, before_options=None, options=None, executable=None, pipe=False):
        self.source = source
        self.before_options = before_options
        self.options = options
        self.executable = executable
        self.pipe = pipe

class DummyStderr:
    def __iter__(self):
        return iter([])

class DummyPopen:
    """Remplace subprocess.Popen dans le test du mode PIPE."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.stdout = io.BytesIO(b"FAKEAUDIO")
        self.stderr = DummyStderr()

    def poll(self):
        return 0

    def terminate(self):
        pass

@pytest.fixture(autouse=True)
def _no_env_side_effects(monkeypatch):
    # Neutralise des variables d'env parfois utilisées par l’extracteur
    for k in ("YTDLP_COOKIES_BROWSER", "YTDBG", "YTDBG_HTTP_PROBE"):
        monkeypatch.delenv(k, raising=False)

@pytest.fixture
def patch_ffmpeg(monkeypatch):
    # Remplace FFmpegPCMAudio par un stub
    from extractors import youtube as yt
    monkeypatch.setattr(yt.discord, "FFmpegPCMAudio", DummyAudio)
    return DummyAudio

@pytest.fixture
def patch_popen(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", DummyPopen)
    return DummyPopen

@pytest.fixture
def fake_ydl_factory(monkeypatch):
    """
    Permet de fournir une fabrique YoutubeDL custom par test.
    Usage:
      ydl_instances = [Fake1(), Fake2()]
      def factory(_opts): return ydl_instances.pop(0)
      fake_ydl_factory(factory)
    """
    def _apply(factory_callable):
        from extractors import youtube as yt
        monkeypatch.setattr(yt, "YoutubeDL", factory_callable)
    return _apply
