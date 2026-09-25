"""Fixtures pytest de l'API — aucun accès réseau, aucun Redis réel.

sys.path : `api` (services/api) et `greg_shared` (packages/shared) sont importés
depuis l'arborescence source.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_API_ROOT = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(os.path.dirname(_API_ROOT))
_SHARED = os.path.join(_REPO_ROOT, "packages", "shared")

for p in (_API_ROOT, _SHARED):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest


@pytest.fixture(scope="session")
def app():
    # create_app() réutilise les singletons socketio/compress : une seule app par session.
    from api import create_app

    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


class FakeSendCommand:
    """Remplace bot_bridge.send_command : enregistre les appels, renvoie une réponse fixée."""

    def __init__(self, result=None):
        self.result = result if result is not None else {"ok": True}
        self.calls = []

    def __call__(self, action, guild_id, user_id=0, data=None, timeout=15.0):
        self.calls.append({
            "action": action,
            "guild_id": guild_id,
            "user_id": user_id,
            "data": data,
            "timeout": timeout,
        })
        return dict(self.result)


@pytest.fixture()
def fake_send(monkeypatch):
    """Patch send_command dans tous les modules de routes qui l'importent."""
    import api.routes.history as history_mod
    import api.routes.player as player_mod
    import api.routes.spotify as spotify_mod

    fake = FakeSendCommand()
    monkeypatch.setattr(player_mod, "send_command", fake)
    monkeypatch.setattr(history_mod, "send_command", fake)
    monkeypatch.setattr(spotify_mod, "send_command", fake)
    return fake
