"""Tests du cog Voice (cogs/voice.py) : join-leave-no-defer + politique C7 (busy_elsewhere)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from bot.cogs import voice
from greg_shared.constants import GREG_RESPONSES


class FakeVC:
    def __init__(self, channel=None, *, move_raises=None, connected=True):
        self.channel = channel
        self.moves = []
        self.disconnected = False
        self.stopped = False
        self._move_raises = move_raises
        self._connected = connected
        self.response_done_at_disconnect = None
        self.inter = None

    def is_connected(self):
        return self._connected

    def is_playing(self):
        return False

    def is_paused(self):
        return False

    def stop(self):
        self.stopped = True

    async def move_to(self, ch):
        if self._move_raises:
            raise self._move_raises
        self.moves.append(ch)

    async def disconnect(self, *, force=False):
        if self.inter is not None:
            self.response_done_at_disconnect = self.inter.response.is_done()
        self.disconnected = True


class FakeVoiceChannel:
    def __init__(self, cid, name="Salon", *, connect_raises=None):
        self.id = cid
        self.name = name
        self.members = []
        self.mention = f"<#{cid}>"
        self._connect_raises = connect_raises
        self.connects = 0
        self.response_done_at_connect = None
        self.inter = None

    async def connect(self, *, timeout=60.0, **kw):
        self.connects += 1
        if self.inter is not None:
            self.response_done_at_connect = self.inter.response.is_done()
        if self._connect_raises:
            raise self._connect_raises
        return FakeVC(self)


class FakePlayerService:
    """PlayerService minimal : busy_elsewhere (C7) + connect_for_user / ensure_playing."""

    def __init__(self, busy=None, *, connect_ok=True, connect_raises=None, busy_after_connect=None):
        self.busy = busy
        self.calls = []
        self.explicit = []
        self.connect_ok = connect_ok
        self.connect_raises = connect_raises
        # Salon occupé découvert seulement sous le verrou vocal (reconnexion 1006 en cours).
        self.busy_after_connect = busy_after_connect
        self.connect_calls = []
        self.playing_calls = []
        self.response_done_at_connect = None
        self.inter = None

    def busy_elsewhere(self, guild, channel):
        self.calls.append((guild, channel))
        return self.busy

    async def connect_for_user(self, guild, channel):
        self.connect_calls.append((guild, channel))
        if self.inter is not None:
            self.response_done_at_connect = self.inter.response.is_done()
        if self.connect_raises:
            raise self.connect_raises
        if self.busy_after_connect is not None:
            return {"ok": False, "error": "BOT_IN_OTHER_CHANNEL",
                    "message": f"Greg joue déjà dans <#{self.busy_after_connect}>…"}
        return None if self.connect_ok else {"ok": False, "error": "VOICE_CONNECT_FAILED", "message": "x"}

    def ensure_playing(self, guild):
        self.playing_calls.append(guild)

    def _mark_explicit_stop(self, gid):
        self.explicit.append(gid)


def _setup(make_inter, *, vc=None, busy=None, connect_raises=None, with_ps=True, ps_kwargs=None):
    ch = FakeVoiceChannel(222, "Chez moi", connect_raises=connect_raises)
    guild = SimpleNamespace(id=1001, voice_client=vc)
    inter = make_inter(user_id=5, guild=guild, voice_channel=ch)
    ch.inter = inter
    if vc is not None:
        vc.inter = inter
    if with_ps:
        ps = FakePlayerService(busy, **(ps_kwargs or {}))
        ps.inter = inter
        bot = SimpleNamespace(player_service=ps, loop=None)
    else:
        bot = SimpleNamespace(loop=None)
    cog = voice.Voice(bot)
    return cog, inter, ch, guild, bot


def _variants(key, **kw):
    return {t.format(**kw) for t in GREG_RESPONSES[key]}


@pytest.mark.parametrize("attr", ["join", "leave", "autodc"])
def test_voice_commands_are_guild_only(attr):
    assert getattr(voice.Voice, attr).guild_only is True


# ── Chemin nominal : PlayerService.connect_for_user / ensure_playing ──

def test_join_goes_through_player_service(make_inter):
    cog, inter, ch, guild, bot = _setup(make_inter)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    ps = bot.player_service
    assert ps.connect_calls == [(guild, ch)], "/join contourne PlayerService.connect_for_user"
    assert ch.connects == 0, "connect() direct : ni verrou vocal ni gestion du client fantôme"
    assert ps.response_done_at_connect is True, "connexion lancée avant la réponse initiale (fenêtre 3 s)"
    assert ps.playing_calls == [guild], "file en attente jamais relancée après /join"
    assert len(inter.followup.messages) == 1
    assert inter.followup.messages[0][0] in _variants("join_voice", channel="Chez moi", user="<@5>")


def test_join_move_goes_through_player_service(make_inter):
    vc = FakeVC(SimpleNamespace(id=333, members=[]))
    cog, inter, ch, guild, bot = _setup(make_inter, vc=vc)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    ps = bot.player_service
    assert ps.calls, "busy_elsewhere() non consulté"
    assert ps.connect_calls == [(guild, ch)]
    assert vc.moves == [], "move_to() direct sur un client peut-être fantôme"
    assert ps.playing_calls == [guild]
    assert inter.response.deferred
    assert len(inter.followup.messages) == 1
    assert inter.followup.messages[0][0] in _variants("move_voice", channel="Chez moi", user="<@5>")


def test_join_with_stale_voice_client_says_join_not_move(make_inter):
    # Client fantôme (reconnexion 1006 abandonnée) : connect_for_user le nettoie et
    # reconnecte → Greg REJOINT le salon, il ne « se déplace » pas.
    vc = FakeVC(SimpleNamespace(id=333, members=[]), connected=False)
    cog, inter, ch, guild, bot = _setup(make_inter, vc=vc)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert bot.player_service.connect_calls == [(guild, ch)]
    assert vc.moves == []
    assert inter.followup.messages[0][0] in _variants("join_voice", channel="Chez moi", user="<@5>")


def test_join_reports_voice_connect_failure(make_inter):
    # Client fantôme / reconnexion 1006 : connect_for_user renvoie VOICE_CONNECT_FAILED → pas de faux succès.
    cog, inter, _, _, bot = _setup(make_inter, ps_kwargs={"connect_ok": False})
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert inter.response.deferred
    assert len(inter.followup.messages) == 1
    assert inter.followup.messages[0][0] in _variants("error_voice_connect", user="<@5>")
    assert bot.player_service.playing_calls == []


def test_join_refuses_when_busy_elsewhere_found_during_reconnect(make_inter):
    # busy_elsewhere() ne voyait rien (client en reconnexion) mais connect_for_user,
    # sous le verrou vocal, découvre que Greg joue ailleurs → refus, pas de déplacement.
    cog, inter, _, _, bot = _setup(make_inter, ps_kwargs={"busy_after_connect": 333})
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert inter.response.deferred
    assert len(inter.followup.messages) == 1
    assert "<#333>" in inter.followup.messages[0][0]
    assert bot.player_service.playing_calls == []


def test_join_player_service_error_is_reported_once(make_inter):
    cog, inter, _, _, bot = _setup(make_inter, ps_kwargs={"connect_raises": RuntimeError("boom")})
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert inter.response.deferred
    assert len(inter.followup.messages) == 1
    assert bot.player_service.playing_calls == []


# ── Repli sans PlayerService : connexion directe (toujours différée) ──

def test_join_defers_before_connecting(make_inter):
    cog, inter, ch, _, _ = _setup(make_inter, with_ps=False)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert ch.connects == 1
    assert ch.response_done_at_connect is True, "connect() lancé avant la réponse initiale (fenêtre 3 s)"
    assert inter.followup.messages, "succès non envoyé via followup"


def test_join_timeout_is_reported_via_followup(make_inter):
    cog, inter, _, _, _ = _setup(make_inter, connect_raises=asyncio.TimeoutError(), with_ps=False)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert inter.response.deferred
    assert len(inter.followup.messages) == 1


def test_join_generic_error_is_reported_once(make_inter):
    cog, inter, _, _, _ = _setup(make_inter, connect_raises=RuntimeError("boom"), with_ps=False)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert inter.response.deferred
    assert len(inter.followup.messages) == 1


def test_join_move_uses_followup(make_inter):
    vc = FakeVC(SimpleNamespace(id=333, members=[]))
    cog, inter, ch, _, _ = _setup(make_inter, vc=vc, with_ps=False)
    asyncio.run(voice.Voice.join.callback(cog, inter))
    assert vc.moves == [ch]
    assert inter.response.deferred and inter.followup.messages


def test_join_refuses_when_greg_plays_elsewhere(make_inter):
    busy = SimpleNamespace(id=333, mention="<#333>")
    vc = FakeVC(SimpleNamespace(id=333, members=[]))
    cog, inter, ch, guild, bot = _setup(make_inter, vc=vc, busy=busy)
    asyncio.run(voice.Voice.join.callback(cog, inter))

    assert vc.moves == [], "Greg arraché du salon où il joue pour d'autres"
    assert ch.connects == 0
    assert bot.player_service.connect_calls == []
    assert bot.player_service.calls == [(guild, ch)]
    texts = inter.all_texts()
    assert texts and "<#333>" in texts[0]


def test_leave_defers_before_disconnecting(make_inter):
    vc = FakeVC(SimpleNamespace(id=222, members=[]))
    cog, inter, _, _, _ = _setup(make_inter, vc=vc)
    asyncio.run(voice.Voice.leave.callback(cog, inter))
    assert vc.disconnected
    assert vc.response_done_at_disconnect is True, "disconnect() lancé avant la réponse initiale"
    assert inter.followup.messages


def test_leave_when_not_connected_answers_immediately(make_inter):
    cog, inter, _, _, _ = _setup(make_inter, vc=None)
    asyncio.run(voice.Voice.leave.callback(cog, inter))
    assert inter.response.messages and not inter.response.deferred
