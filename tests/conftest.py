# tests/conftest.py
import os
import types
import pytest

@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/webhook")
    cookies = tmp_path / "youtube.com_cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")  # header valide
    return {"cookies_path": str(cookies)}

@pytest.fixture
def fake_interaction():
    class DummyFollowup:
        messages = []
        async def send(self, msg): self.messages.append(msg)
    class DummyResponse:
        async def send_message(self, msg): DummyFollowup.messages.append(msg)
    class DummyVoiceClient:
        def __init__(self): self._playing=False; self._paused=False
        def is_playing(self): return self._playing
        def is_paused(self): return self._paused
        def play(self, src, after=None): self._playing=True
        def pause(self): self._paused=True
        def resume(self): self._paused=False
        def stop(self): self._playing=False
    class DummyChannel:
        name="Trou à rats"
        async def connect(self, timeout=10): return
    class DummyUser:
        def __init__(self): self.voice=types.SimpleNamespace(channel=DummyChannel())

    class DummyGuild:
        def __init__(self):
            self.id = 1
            self.voice_client = DummyVoiceClient()

    class DummyInteraction:
        def __init__(self):
            self.user=DummyUser()
            self.guild=DummyGuild()
            self.response=DummyResponse()
            self.followup=DummyFollowup()
    return DummyInteraction()
