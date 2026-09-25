"""GregBot — handler d'erreurs des slash commands (CommandTree) et clé greg:bot:guilds (C5)."""
from __future__ import annotations

import types

import pytest
from discord import app_commands

import bot.greg_bot as gb
from greg_shared.config import settings

pytestmark = pytest.mark.asyncio


class FakeResponse:
    def __init__(self, done=False):
        self.done = done
        self.sent = []

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kw):
        self.sent.append((content, kw))


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))


def make_inter(done):
    return types.SimpleNamespace(
        response=FakeResponse(done),
        followup=FakeFollowup(),
        user=types.SimpleNamespace(id=7, mention="<@7>"),
        command=types.SimpleNamespace(qualified_name="play"),
    )


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(settings, "discord_client_id", "123456789")
    b = gb.GregBot()
    calls = {"guilds": 0, "ready": 0}

    async def publish_bot_guilds():
        calls["guilds"] += 1

    async def publish_bot_ready():
        calls["ready"] += 1

    b.redis_bridge.publish_bot_guilds = publish_bot_guilds
    b.redis_bridge.publish_bot_ready = publish_bot_ready
    b._calls = calls
    return b


async def test_titles_can_never_mass_mention(bot):
    # Un titre « @everyone » / mention de rôle dans /play ou /playlist ne doit pas pinger.
    am = bot.allowed_mentions
    assert am is not None
    assert am.everyone is False and am.roles is False
    assert am.users is True  # les mentions {user} des réponses de Greg restent actives


async def test_setup_hook_registers_a_tree_error_handler(bot, monkeypatch):
    async def noop(*a, **k):
        return []

    async def no_listen():
        return None

    monkeypatch.setattr(bot, "_load_cogs", noop)
    monkeypatch.setattr(bot.tree, "sync", noop)
    monkeypatch.setattr(bot.redis_bridge, "start_listening", no_listen)
    default = type(bot.tree).on_error
    await bot.setup_hook()
    assert getattr(bot.tree.on_error, "__func__", bot.tree.on_error) is not default


async def test_error_handler_answers_via_followup_after_defer(bot):
    inter = make_inter(done=True)
    err = app_commands.CommandInvokeError(types.SimpleNamespace(name="play", qualified_name="play"), TypeError("int(None)"))
    await bot._on_app_command_error(inter, err)
    assert len(inter.followup.sent) == 1 and inter.response.sent == []
    assert inter.followup.sent[0][1].get("ephemeral") is True


async def test_error_handler_answers_check_failures_directly(bot):
    inter = make_inter(done=False)
    await bot._on_app_command_error(inter, app_commands.CheckFailure("nope"))
    assert len(inter.response.sent) == 1 and inter.followup.sent == []


async def test_error_handler_never_raises_when_interaction_expired(bot):
    inter = make_inter(done=True)

    async def boom(*a, **k):
        raise RuntimeError("Unknown interaction")

    inter.followup.send = boom
    await bot._on_app_command_error(inter, app_commands.CheckFailure("nope"))


async def test_guild_presence_is_published_on_ready_join_and_remove(bot, monkeypatch):
    monkeypatch.setattr(type(bot), "user", property(lambda self: types.SimpleNamespace(id=1)), raising=False)
    await bot.on_ready()
    await bot.on_guild_join(types.SimpleNamespace(id=5))
    await bot.on_guild_remove(types.SimpleNamespace(id=5))
    assert bot._calls["guilds"] == 3
    assert bot._calls["ready"] == 1
