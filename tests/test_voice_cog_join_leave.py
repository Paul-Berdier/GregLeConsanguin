# tests/test_voice_cog_join_leave.py
import types
import importlib
import pytest
import asyncio

@pytest.mark.asyncio
async def test_join_and_leave(fake_interaction):
    v = importlib.import_module("commands.voice")
    cog = v.Voice(bot=types.SimpleNamespace())
    # join
    await cog.join(fake_interaction)
    # leave
    await cog.leave(fake_interaction)
    # Pas d'exception = OK
