"""Tests du cog Announcer (cogs/cookie_guardian.py).

Couvre : announce-commands-no-permission, cookie-guardian-leaks-password,
cookie-guardian-sync-ytdlp, cookie-path-precedence-uploaded-ignored (côté guardian).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from types import SimpleNamespace

import bot.cogs.cookie_guardian as cg
import discord
import pytest
from discord import app_commands

GUILD_A = SimpleNamespace(id=1001)
GUILD_B = SimpleNamespace(id=2002)


class FakeMessage:
    def __init__(self, mid: int):
        self.id = mid
        self.pinned = False
        self.deleted = False
        self.delete_delay = "unset"

    async def pin(self, reason=None):
        self.pinned = True

    async def unpin(self, reason=None):
        self.pinned = False

    async def delete(self, *, delay=None):
        self.delete_delay = delay
        if delay:
            # Imite discord.py : suppression différée en arrière-plan
            return
        self.deleted = True


class FakeTextChannel(discord.TextChannel):
    """Passe le isinstance(TextChannel) de _send_announcement sans état Discord."""

    def __init__(self, cid: int, guild):
        self.id = cid
        self.guild = guild
        self.sent = []          # [(content, kwargs)]
        self.messages = {}
        self._next = 500

    async def send(self, content=None, **kwargs):
        self._next += 1
        msg = FakeMessage(self._next)
        self.sent.append((content, kwargs))
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, mid):
        return self.messages[int(mid)]


class FakeBot:
    def __init__(self, channels=()):
        self.channels = {c.id: c for c in channels}

    def get_channel(self, cid):
        return self.channels.get(int(cid))

    async def wait_until_ready(self):
        await asyncio.Event().wait()   # le scheduler ne tourne jamais pendant les tests


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(cg, "ANNOUNCE_STORE", str(tmp_path / "announcements.json"))
    monkeypatch.setattr(cg, "OWNER_ID", 0)
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES_B64", raising=False)


def _run(coro_fn):
    """Construit le cog dans une boucle active (tasks.loop.start en a besoin)."""
    async def _main():
        return await coro_fn()
    return asyncio.run(_main())


def _new_cog(bot):
    cog = cg.Announcer(bot)
    return cog


# ─────────────────────── announce-commands-no-permission ───────────────────────

SUBCOMMANDS = ["add", "list", "remove", "toggle", "edit", "send", "cookie_guardian"]


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_announce_subcommands_carry_app_command_checks(name, make_inter):
    cmd = cg.Announcer.announce.get_command(name)
    assert cmd is not None
    assert cmd.checks, f"/announce {name} n'a aucun check app_commands"

    plain = make_inter(user_id=5, manage_guild=False, guild=GUILD_A)

    async def _go():
        for check in cmd.checks:
            await check(plain)
    with pytest.raises(app_commands.CheckFailure):
        asyncio.run(_go())


@pytest.mark.parametrize("name", ["add", "list", "remove", "toggle", "edit", "send"])
def test_announce_manage_guild_member_passes(name, make_inter):
    cmd = cg.Announcer.announce.get_command(name)
    admin = make_inter(user_id=6, manage_guild=True, guild=GUILD_A)

    async def _go():
        return [await check(admin) for check in cmd.checks]
    assert all(asyncio.run(_go()))


def test_cookie_guardian_config_is_owner_only(make_inter):
    cmd = cg.Announcer.announce.get_command("cookie_guardian")
    admin = make_inter(user_id=6, manage_guild=True, guild=GUILD_A, app_owner_id=42)
    owner = make_inter(user_id=42, manage_guild=False, guild=GUILD_A, app_owner_id=42)

    async def _go(inter):
        return [await check(inter) for check in cmd.checks]

    with pytest.raises(app_commands.CheckFailure):
        asyncio.run(_go(admin))
    assert all(asyncio.run(_go(owner)))


def test_announce_group_is_guild_only_and_hidden_by_default():
    grp = cg.Announcer.announce
    assert grp.guild_only is True
    assert grp.default_permissions is not None and grp.default_permissions.manage_guild


def test_announcement_send_blocks_mass_mentions():
    ch = FakeTextChannel(10, GUILD_A)
    bot = FakeBot([ch])

    async def _go():
        cog = _new_cog(bot)
        try:
            a = cg.Announcement(id=1, channel_id=10, message="@everyone <@&55> go", every_seconds=0,
                                next_run_ts=0)
            await cog._send_announcement(a)
        finally:
            cog._scheduler.cancel()
    _run(_go)

    assert ch.sent, "annonce non envoyée"
    _, kwargs = ch.sent[0]
    am = kwargs.get("allowed_mentions")
    assert am is not None, "allowed_mentions absent → @everyone / rôles pingés"
    assert am.everyone is False
    assert am.roles is False


def test_announcement_delete_after_does_not_block_scheduler():
    ch = FakeTextChannel(10, GUILD_A)
    bot = FakeBot([ch])

    async def _go():
        cog = _new_cog(bot)
        try:
            a = cg.Announcement(id=1, channel_id=10, message="hello", every_seconds=0,
                                next_run_ts=0, delete_after=3600)
            await asyncio.wait_for(cog._send_announcement(a), timeout=2)
        finally:
            cog._scheduler.cancel()
    _run(_go)
    msg = next(iter(ch.messages.values()))
    assert msg.delete_delay == 3600


def test_add_enforces_minimum_interval(make_inter):
    ch = FakeTextChannel(10, GUILD_A)
    bot = FakeBot([ch])
    inter = make_inter(user_id=6, manage_guild=True, guild=GUILD_A)

    async def _go():
        cog = _new_cog(bot)
        try:
            cmd = cog.announce.get_command("add")
            await cmd.callback(cog, inter, channel=ch, message="spam", every="1s")
            return list(cog.announcements.values())
        finally:
            cog._scheduler.cancel()
    anns = _run(_go)
    assert len(anns) == 1
    assert anns[0].every_seconds >= cg.MIN_EVERY_SECONDS >= 60


def test_announcements_are_scoped_to_the_invoking_guild(make_inter):
    ch_a = FakeTextChannel(10, GUILD_A)
    ch_b = FakeTextChannel(20, GUILD_B)
    bot = FakeBot([ch_a, ch_b])
    list_inter, rm_inter, send_inter = (make_inter(user_id=6, manage_guild=True, guild=GUILD_A)
                                        for _ in range(3))

    async def _go():
        cog = _new_cog(bot)
        try:
            cog.announcements[1] = cg.Announcement(id=1, channel_id=10, message="A", every_seconds=0,
                                                   next_run_ts=0)
            cog.announcements[2] = cg.Announcement(id=2, channel_id=20, message="B", every_seconds=0,
                                                   next_run_ts=0)
            await cog.announce.get_command("list").callback(cog, list_inter)
            await cog.announce.get_command("remove").callback(cog, rm_inter, ann_id=2)
            await cog.announce.get_command("send").callback(cog, send_inter, ann_id=2)
            return dict(cog.announcements)
        finally:
            cog._scheduler.cancel()
    anns = _run(_go)

    listing = list_inter.followup.messages[0][0]
    assert "#1" in listing and "#2" not in listing
    assert 2 in anns, "un admin de A a supprimé l'annonce de B"
    assert ch_b.sent == [], "un admin de A a posté dans le salon de B"


# ──────────── Annonces orphelines (salon supprimé / inaccessible) ────────────

def test_add_stores_the_guild_of_the_announcement(make_inter):
    ch = FakeTextChannel(10, GUILD_A)
    bot = FakeBot([ch])
    inter = make_inter(user_id=6, manage_guild=True, guild=GUILD_A)

    async def _go():
        cog = _new_cog(bot)
        try:
            await cog.announce.get_command("add").callback(cog, inter, channel=ch, message="hello")
            return list(cog.announcements.values())
        finally:
            cog._scheduler.cancel()
    anns = _run(_go)
    assert anns[0].guild_id == GUILD_A.id


def test_admin_can_remove_announcement_whose_channel_was_deleted(make_inter):
    bot = FakeBot([])      # #annonces supprimé : le salon n'est plus résolu
    list_b = make_inter(user_id=7, manage_guild=True, guild=GUILD_B)
    rm_b = make_inter(user_id=7, manage_guild=True, guild=GUILD_B)
    list_a = make_inter(user_id=6, manage_guild=True, guild=GUILD_A)
    rm_a = make_inter(user_id=6, manage_guild=True, guild=GUILD_A)

    async def _go():
        cog = _new_cog(bot)
        try:
            cog.announcements[3] = cg.Announcement(id=3, channel_id=10, message="A", every_seconds=3600,
                                                   next_run_ts=0, guild_id=GUILD_A.id)
            await cog.announce.get_command("list").callback(cog, list_b)
            await cog.announce.get_command("remove").callback(cog, rm_b, ann_id=3)
            still_there = 3 in cog.announcements
            await cog.announce.get_command("list").callback(cog, list_a)
            await cog.announce.get_command("remove").callback(cog, rm_a, ann_id=3)
            return still_there, dict(cog.announcements)
        finally:
            cog._scheduler.cancel()
    still_there, anns = _run(_go)
    assert still_there, "un admin de B a supprimé l'annonce de A"
    assert "#3" not in list_b.followup.messages[0][0]
    assert "#3" in list_a.followup.messages[0][0]
    assert 3 not in anns, "annonce orpheline impossible à supprimer par l'admin de sa guild"


def test_legacy_announcement_guild_is_backfilled_before_channel_deletion(make_inter):
    ch = FakeTextChannel(10, GUILD_A)
    bot = FakeBot([ch])
    rm_a = make_inter(user_id=6, manage_guild=True, guild=GUILD_A)

    async def _go():
        cog = _new_cog(bot)
        try:
            # Entrée héritée (stockée avant l'ajout de guild_id)
            cog.announcements[4] = cg.Announcement(id=4, channel_id=10, message="A", every_seconds=3600,
                                                   next_run_ts=0)
            changed = cog._backfill_guild_ids()
            bot.channels.clear()            # puis le salon est supprimé
            await cog.announce.get_command("remove").callback(cog, rm_a, ann_id=4)
            return changed, dict(cog.announcements)
        finally:
            cog._scheduler.cancel()
    changed, anns = _run(_go)
    assert changed
    assert 4 not in anns


def test_orphan_legacy_announcement_is_manageable_by_owner_only(make_inter):
    bot = FakeBot([])
    admin = make_inter(user_id=6, manage_guild=True, guild=GUILD_A, app_owner_id=42)
    owner_list = make_inter(user_id=42, manage_guild=False, guild=GUILD_A, app_owner_id=42)
    owner_rm = make_inter(user_id=42, manage_guild=False, guild=GUILD_A, app_owner_id=42)

    async def _go():
        cog = _new_cog(bot)
        try:
            cog.announcements[5] = cg.Announcement(id=5, channel_id=10, message="?", every_seconds=3600,
                                                   next_run_ts=0)
            await cog.announce.get_command("remove").callback(cog, admin, ann_id=5)
            after_admin = 5 in cog.announcements
            await cog.announce.get_command("list").callback(cog, owner_list)
            await cog.announce.get_command("remove").callback(cog, owner_rm, ann_id=5)
            return after_admin, dict(cog.announcements)
        finally:
            cog._scheduler.cancel()
    after_admin, anns = _run(_go)
    assert after_admin, "guild inconnue : un admin quelconque ne doit pas pouvoir la supprimer"
    assert "#5" in owner_list.followup.messages[0][0]
    assert 5 not in anns, "annonce orpheline héritée ingérable même pour l'owner"


def test_legacy_store_entries_without_guild_id_still_load(tmp_path):
    import json
    store = {"announcements": [{"id": 1, "channel_id": 10, "message": "x", "every_seconds": 0,
                                "next_run_ts": 0, "enabled": True, "pin": False,
                                "delete_after": None, "last_message_id": None}],
             "cookie_guardian": {"enabled": False}}
    with open(cg.ANNOUNCE_STORE, "w", encoding="utf-8") as f:
        json.dump(store, f)

    async def _go():
        cog = _new_cog(FakeBot([]))
        try:
            return dict(cog.announcements)
        finally:
            cog._scheduler.cancel()
    anns = _run(_go)
    assert 1 in anns and anns[1].guild_id is None


# ─────────────────────── cookie-guardian-leaks-password ───────────────────────

def test_guardian_alert_never_contains_credentials(monkeypatch, fake_youtube):
    monkeypatch.setattr(cg, "YT_USER", "greg.bot@gmail.com", raising=False)
    monkeypatch.setattr(cg, "YT_PASS", "hunter2-S3cret", raising=False)
    monkeypatch.setenv("YTBOT_USER", "greg.bot@gmail.com")
    monkeypatch.setenv("YTBOT_PASS", "hunter2-S3cret")
    ch = FakeTextChannel(77, GUILD_A)
    bot = FakeBot([ch])

    async def _go():
        cog = _new_cog(bot)
        try:
            async def _invalid(_path):
                return False, "auth_required"
            cog._yt_cookies_valid = _invalid
            await cog._run_cookie_guardian_once({"channel_id": 77, "pin": True})
        finally:
            cog._scheduler.cancel()
    _run(_go)

    assert ch.sent, "aucune alerte envoyée"
    text, kwargs = ch.sent[0]
    assert "hunter2-S3cret" not in text
    assert "greg.bot@gmail.com" not in text
    am = kwargs.get("allowed_mentions")
    assert am is not None and am.everyone is False and am.roles is False


def test_guardian_deletes_superseded_alert(fake_youtube):
    ch = FakeTextChannel(77, GUILD_A)
    old = FakeMessage(12)
    old.pinned = True
    ch.messages[12] = old
    bot = FakeBot([ch])

    async def _go():
        cog = _new_cog(bot)
        try:
            async def _invalid(_path):
                return False, "missing_cookiefile"
            cog._yt_cookies_valid = _invalid
            cgc = {"channel_id": 77, "pin": True, "last_message_id": 12}
            await cog._run_cookie_guardian_once(cgc)
            return cgc
        finally:
            cog._scheduler.cancel()
    cgc = _run(_go)
    assert old.deleted, "l'ancienne alerte (qui contenait les identifiants) reste dans le salon"
    assert cgc["last_message_id"] != 12


# ─────────────── cookie-path-precedence-uploaded-ignored (guardian) ───────────────

def test_guardian_resolves_cookiefile_each_run_without_touching_environ(fake_youtube, tmp_path):
    first = str(tmp_path / "b64.txt")
    second = str(tmp_path / "uploaded.txt")
    seq = iter([first, second])
    fake_youtube.picked = lambda: next(seq)
    ch = FakeTextChannel(77, GUILD_A)
    bot = FakeBot([ch])
    seen = []
    env_before = dict(os.environ)

    async def _go():
        cog = _new_cog(bot)
        try:
            async def _valid(path):
                seen.append(path)
                return True, "ok"
            cog._yt_cookies_valid = _valid
            await cog._run_cookie_guardian_once({"channel_id": 77})
            await cog._run_cookie_guardian_once({"channel_id": 77})
        finally:
            cog._scheduler.cancel()
    _run(_go)

    assert fake_youtube.pick_calls == [None, None]
    assert seen == [first, second]
    assert dict(os.environ) == env_before, "le guardian a modifié os.environ"


# ─────────────────────── cookie-guardian-sync-ytdlp ───────────────────────

def test_yt_cookies_valid_runs_off_the_event_loop(monkeypatch, tmp_path):
    cookie = tmp_path / "c.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False, **kw):
            time.sleep(0.4)            # I/O bloquante simulée (réseau + Deno)
            return {"id": "x"}

    # Le vrai extracteur (cookiefile_copy) doit être importé AVANT de remplacer yt_dlp,
    # sinon son `from yt_dlp.utils import …` casse quand ce test tourne seul.
    import greg_shared.extractors.youtube  # noqa: F401

    fake_mod = types.ModuleType("yt_dlp")
    fake_mod.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_mod)
    bot = FakeBot()

    async def _go():
        cog = _new_cog(bot)
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1
        t = asyncio.create_task(_ticker())
        try:
            ok, err = await cog._yt_cookies_valid(str(cookie))
        finally:
            t.cancel()
            cog._scheduler.cancel()
        return ok, err, ticks
    ok, err, ticks = _run(_go)
    assert ok, err
    assert ticks >= 3, f"event loop bloquée pendant extract_info (ticks={ticks})"
    assert captured["opts"].get("socket_timeout"), "pas de socket_timeout : un hang réseau bloque le check"
