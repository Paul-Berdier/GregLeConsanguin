# tests/test_music_cog_core.py
import types
import importlib
import asyncio
import os
import pytest

@pytest.mark.asyncio
async def test_detect_ffmpeg(monkeypatch):
    m = importlib.import_module("commands.music")
    monkeypatch.setattr(os.path, "exists", lambda p: True if p=="/usr/bin/ffmpeg" else False)
    monkeypatch.setattr(os, "access", lambda p, mode: True)
    cog = m.Music(bot=types.SimpleNamespace(loop=asyncio.get_event_loop()))
    assert cog.ffmpeg_path == "/usr/bin/ffmpeg"

@pytest.mark.asyncio
async def test_play_next_stream_then_fallback(monkeypatch, tmp_path, fake_interaction):
    m = importlib.import_module("commands.music")

    # Fake extractor retourné par get_extractor
    fake_source = object()
    async def _stream(url, ffmpeg): return fake_source, "TitreStreamé"
    async def _download(url, ffmpeg_path, cookies_file=None):
        fn = tmp_path/"x.mp3"; fn.write_text("x");
        return str(fn), "TitreDL", 111

    def fake_get_extractor(url):
        class E: pass
        e = E()
        e.stream = _stream
        e.download = _download
        return e

    monkeypatch.setattr(m, "get_extractor", lambda url: fake_get_extractor(url))
    # Voice client factice
    vc = fake_interaction.guild.voice_client
    # instancie le cog
    cog = m.Music(bot=types.SimpleNamespace(loop=asyncio.get_event_loop()))
    # queue → forcer un élément
    cog.queue = ["https://soundcloud.com/a/b"]
    await cog.play_next(fake_interaction)
    # stream appelé -> current_song défini
    assert cog.current_song == "TitreStreamé"
    # simulate fallback: supprime stream, force download
    def fake_get_extractor_dl(url):
        class E: pass
        e = E()
        e.download = _download
        return e
    cog.queue = ["https://youtu.be/xyz"]
    monkeypatch.setattr(m, "get_extractor", lambda url: fake_get_extractor_dl(url))
    await cog.play_next(fake_interaction)
    assert cog.current_song == "TitreDL"
