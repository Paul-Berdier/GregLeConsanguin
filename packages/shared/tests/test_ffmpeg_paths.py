# ffmpeg présent seulement dans le PATH : un indice nu "ffmpeg" doit fonctionner.

from __future__ import annotations

import os
import shutil

import pytest
from greg_shared.extractors import soundcloud, youtube

FAKE = os.path.join(os.sep, "opt", "ffbin", "ffmpeg")


@pytest.fixture
def ffmpeg_only_in_path(monkeypatch):
    def fake_which(name, *a, **k):
        return FAKE if name in ("ffmpeg", "ffmpeg.exe") else None

    monkeypatch.setattr(shutil, "which", fake_which)


@pytest.mark.parametrize("mod", [youtube, soundcloud])
def test_bare_ffmpeg_hint_resolved_through_path(mod, ffmpeg_only_in_path):
    exe, loc = mod._resolve_ffmpeg_paths("ffmpeg")
    assert exe == FAKE
    assert loc == os.path.dirname(FAKE)


@pytest.mark.parametrize("mod", [youtube, soundcloud])
def test_missing_ffmpeg_still_raises(mod, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    with pytest.raises(FileNotFoundError):
        mod._resolve_ffmpeg_paths("ffmpeg")
