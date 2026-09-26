"""Fixtures communes aux tests des cogs (services/bot/bot/cogs).

- sys.path idempotent : `bot` (services/bot) et `greg_shared` (packages/shared)
  s'importent depuis l'arbre source, sans installation.
- Faux objets discord minimalistes (Interaction, réponse, followup…) : aucun
  appel réseau, aucune connexion Discord.
- `fake_youtube` : remplace `greg_shared.extractors.youtube` par un module
  factice (contrat C6 : cookies_upload_path / _pick_cookiefile) pour ne pas
  dépendre de yt-dlp ni du package extractors pendant les tests des cogs.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

_HERE = Path(__file__).resolve()
BOT_ROOT = _HERE.parents[2]            # services/bot
REPO_ROOT = _HERE.parents[4]           # racine du monorepo
SHARED_ROOT = REPO_ROOT / "packages" / "shared"

for _p in (str(BOT_ROOT), str(SHARED_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─────────────────────────── Faux discord ───────────────────────────

class FakeResponse:
    """Imite InteractionResponse : une seule réponse initiale autorisée."""

    def __init__(self):
        self._done = False
        self.deferred = False
        self.messages = []          # [(content, kwargs)]

    def is_done(self) -> bool:
        return self._done

    async def defer(self, **kwargs):
        if self._done:
            raise RuntimeError("InteractionResponded")
        self._done = True
        self.deferred = True

    async def send_message(self, content=None, **kwargs):
        if self._done:
            raise RuntimeError("InteractionResponded")
        self._done = True
        self.messages.append((content, kwargs))


class FakeFollowup:
    def __init__(self):
        self.messages = []          # [(content, kwargs)]

    async def send(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class FakeClient:
    def __init__(self, app_owner_id: int = 999_999):
        self.app_owner_id = app_owner_id

    async def application_info(self):
        return SimpleNamespace(owner=SimpleNamespace(id=self.app_owner_id))


class FakeInteraction:
    def __init__(self, *, user_id: int = 1, manage_guild: bool = False, guild=None,
                 voice_channel=None, app_owner_id: int = 999_999):
        self.user = SimpleNamespace(
            id=user_id,
            mention=f"<@{user_id}>",
            bot=False,
            guild_permissions=SimpleNamespace(manage_guild=manage_guild),
            voice=SimpleNamespace(channel=voice_channel) if voice_channel is not None else None,
        )
        self.guild = guild
        self.guild_id = getattr(guild, "id", None)
        self.client = FakeClient(app_owner_id)
        self.response = FakeResponse()
        self.followup = FakeFollowup()

    def all_texts(self):
        out = [c for c, _ in self.response.messages] + [c for c, _ in self.followup.messages]
        return [c for c in out if c]


@pytest.fixture
def make_inter():
    return FakeInteraction


# ─────────────────────── Faux greg_shared.extractors ───────────────────────

@pytest.fixture
def fake_youtube(monkeypatch, tmp_path):
    """Installe un faux `greg_shared.extractors.youtube` (+ token_fetcher).

    - `cookies_upload_path()` → fake.upload_path (modifiable par le test)
    - `_pick_cookiefile(arg)` → fake.picked (str | callable), appels dans fake.pick_calls
    """
    import greg_shared

    pkg = types.ModuleType("greg_shared.extractors")
    pkg.__path__ = []  # package factice
    yt = types.ModuleType("greg_shared.extractors.youtube")
    tf = types.ModuleType("greg_shared.extractors.token_fetcher")

    yt.upload_path = str(tmp_path / "data" / "youtube.com_cookies.txt")
    yt.picked = None
    yt.pick_calls = []
    yt.po_invalidations = 0

    def cookies_upload_path():
        return yt.upload_path

    def _pick_cookiefile(cookies_file):
        yt.pick_calls.append(cookies_file)
        return yt.picked() if callable(yt.picked) else yt.picked

    def invalidate_po_cache(video_id=None):
        yt.po_invalidations += 1

    yt.cookies_upload_path = cookies_upload_path
    yt._pick_cookiefile = _pick_cookiefile
    yt.invalidate_po_cache = invalidate_po_cache

    tf.negative_invalidations = 0

    def invalidate_negative_cache():
        tf.negative_invalidations += 1

    tf.invalidate_negative_cache = invalidate_negative_cache

    pkg.youtube = yt
    pkg.token_fetcher = tf
    monkeypatch.setitem(sys.modules, "greg_shared.extractors", pkg)
    monkeypatch.setitem(sys.modules, "greg_shared.extractors.youtube", yt)
    monkeypatch.setitem(sys.modules, "greg_shared.extractors.token_fetcher", tf)
    monkeypatch.setattr(greg_shared, "extractors", pkg, raising=False)
    return yt
