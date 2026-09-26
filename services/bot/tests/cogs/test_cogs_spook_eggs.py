"""Tests Spook (spook-wrong-sfx-dir) et EasterEggs (no-app-command-error-handler)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from bot.cogs import eastereggs, spook

BOT_ROOT = Path(__file__).resolve().parents[2]   # services/bot


# ─────────────────────── spook-wrong-sfx-dir ───────────────────────

@pytest.mark.skipif(bool(os.getenv("SPOOK_SFX_DIR")), reason="SPOOK_SFX_DIR surchargé dans l'env")
def test_sfx_dir_is_where_the_image_ships_the_sounds():
    expected = (BOT_ROOT / "assets" / "sounds" / "spook").resolve()
    assert Path(spook.SFX_DIR).resolve() == expected


def test_list_sfx_finds_shipped_sounds(monkeypatch):
    monkeypatch.setattr(spook, "SFX_DIR", str(BOT_ROOT / "assets" / "sounds" / "spook"))
    cog = spook.Spook(SimpleNamespace())
    names = sorted(os.path.basename(p) for p in cog._list_sfx())
    assert names == ["chuchotements.mp3", "toc_toc.mp3"]


def test_list_sfx_does_not_create_missing_dir(monkeypatch, tmp_path):
    missing = tmp_path / "nope" / "spook"
    monkeypatch.setattr(spook, "SFX_DIR", str(missing))
    cog = spook.Spook(SimpleNamespace())
    assert cog._list_sfx() == []
    assert not missing.exists(), "un dossier vide est créé au mauvais endroit"


class IdleVC:
    def __init__(self):
        self.channel = SimpleNamespace(id=9, members=[])
        self.played = []

    def is_playing(self):
        return False

    def is_paused(self):
        return False

    def play(self, src, after=None):
        self.played.append(src)
        if after:
            after(None)   # fin immédiate du SFX


class FakePM:
    def __init__(self, n):
        self.n = n

    def length(self):
        return self.n


class FakePS:
    def __init__(self, *, playing=False, intro=False, queued=0, gid=1001):
        self.is_playing = {gid: playing}
        self.intro_playing = {gid: intro}
        self.pm_map = {gid: FakePM(queued)}
        self.play_next_calls = []

    async def play_next(self, guild):
        self.play_next_calls.append(guild)


@pytest.mark.parametrize("kw", [{"playing": True}, {"intro": True}, {"queued": 2}])
def test_music_activity_comes_from_player_service(kw):
    guild = SimpleNamespace(id=1001, voice_client=IdleVC())
    bot = SimpleNamespace(player_service=FakePS(**kw), get_cog=lambda name: None)
    cog = spook.Spook(bot)
    assert cog._is_music_active(guild) is True


def test_music_inactive_when_player_service_idle():
    guild = SimpleNamespace(id=1001, voice_client=IdleVC())
    bot = SimpleNamespace(player_service=FakePS(), get_cog=lambda name: None)
    assert spook.Spook(bot)._is_music_active(guild) is False


def test_queue_resumes_after_sfx(monkeypatch, tmp_path):
    sfx = tmp_path / "boo.mp3"
    sfx.write_bytes(b"\x00")
    monkeypatch.setattr(spook, "SFX_DIR", str(tmp_path))
    monkeypatch.setattr(spook.discord, "FFmpegPCMAudio", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(spook.discord, "PCMVolumeTransformer", lambda src, volume=1.0: src)

    vc = IdleVC()
    guild = SimpleNamespace(id=1001, voice_client=vc)
    # Un /play est arrivé pendant le SFX : titre en file mais rien ne joue.
    ps = FakePS(queued=1)
    bot = SimpleNamespace(player_service=ps, get_cog=lambda name: None)
    cog = spook.Spook(bot)

    async def _go():
        ok = await asyncio.wait_for(cog._play_sfx_once(guild), timeout=2)
        await asyncio.sleep(0)   # laisse tourner la tâche de reprise
        await asyncio.sleep(0)
        return ok
    assert asyncio.run(_go()) is True
    assert ps.play_next_calls == [guild], "la file reste bloquée après le SFX"


def test_queue_not_touched_after_sfx_when_empty(monkeypatch, tmp_path):
    (tmp_path / "boo.mp3").write_bytes(b"\x00")
    monkeypatch.setattr(spook, "SFX_DIR", str(tmp_path))
    monkeypatch.setattr(spook.discord, "FFmpegPCMAudio", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(spook.discord, "PCMVolumeTransformer", lambda src, volume=1.0: src)
    guild = SimpleNamespace(id=1001, voice_client=IdleVC())
    ps = FakePS(queued=0)
    cog = spook.Spook(SimpleNamespace(player_service=ps, get_cog=lambda name: None))

    async def _go():
        ok = await asyncio.wait_for(cog._play_sfx_once(guild), timeout=2)
        await asyncio.sleep(0)
        return ok
    assert asyncio.run(_go()) is True
    assert ps.play_next_calls == []


# ─────────────────────── no-app-command-error-handler ───────────────────────

def test_eastereggs_has_no_dead_app_command_error_listener():
    names = [name for name, _ in eastereggs.EasterEggs.__cog_listeners__]
    assert "on_app_command_error" not in names, (
        "discord.py ne dispatch jamais 'app_command_error' : listener mort "
        "(le handler global est CommandTree.on_error, côté greg_bot)"
    )
