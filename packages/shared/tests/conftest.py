# packages/shared/tests/conftest.py
#
# Tests unitaires de greg_shared (extracteurs). Aucun accès réseau : les
# connexions sortantes sont bloquées (seul le loopback reste autorisé, requis
# par asyncio sous Windows pour son socketpair interne).

from __future__ import annotations

import os
import socket
import sys
from typing import ClassVar

import pytest

_SHARED_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

# Logs [YTDBG]/[SCDBG] silencieux pendant les tests (lus à l'import des modules).
os.environ.setdefault("YTDBG", "0")
os.environ.setdefault("SC_DEBUG", "0")

_ORIG_CONNECT = socket.socket.connect
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

_ENV_KEYS = (
    "YT_PO_TOKEN",
    "YTDLP_PO_TOKEN",
    "YT_PO_TOKEN_PREFIXED",
    "YT_PO_AUTOFETCH",
    "YTDLP_COOKIES_FILE",
    "YOUTUBE_COOKIES_PATH",
    "YTDLP_COOKIES_B64",
    "YTDLP_COOKIES_BROWSER",
    "SOUNDCLOUD_CLIENT_ID",
    "PLAYWRIGHT_AUTOINSTALL",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK:
            return _ORIG_CONNECT(self, address)
        raise RuntimeError(f"Accès réseau interdit dans les tests unitaires : {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Env propre + CWD temporaire (youtube.com_cookies.txt, .sc_client_ids.json…)."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)

    from greg_shared.extractors import token_fetcher, youtube

    youtube.invalidate_po_cache()
    token_fetcher.invalidate_negative_cache()
    yield
    youtube.invalidate_po_cache()
    token_fetcher.invalidate_negative_cache()


class FakeYDL:
    """Faux yt_dlp.YoutubeDL : délègue extract_info à un `responder(url, opts)`.

    Tous les appels sont enregistrés dans `FakeYDL.calls` [(url, opts), …].
    """

    calls: ClassVar[list] = []
    responder = None

    def __init__(self, opts=None):
        self.opts = dict(opts or {})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        type(self).calls.append((url, dict(self.opts)))
        return type(self).responder(url, self.opts)


@pytest.fixture
def fake_ydl(monkeypatch):
    """Remplace YoutubeDL dans youtube.py ; renvoie la classe à configurer."""
    from greg_shared.extractors import youtube

    cls = type("FakeYDLInst", (FakeYDL,), {"calls": [], "responder": None})
    monkeypatch.setattr(youtube, "YoutubeDL", cls)
    return cls
