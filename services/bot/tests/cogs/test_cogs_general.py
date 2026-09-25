"""Tests du cog General (cogs/general.py).

Couvre : yt-cookies-update-no-owner-check (+ yt_cookies_check),
cookie-path-precedence-uploaded-ignored (côté upload/check), restart-reexec-crash.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from bot.cogs import general
from discord import app_commands

COOKIE_LINE = ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc"
HTTPONLY_LINE = "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\t__Secure-3PSID\txyz"


class FakeAttachment:
    def __init__(self, data: bytes):
        self._data = data
        self.size = len(data)

    async def read(self):
        return self._data


@pytest.fixture(autouse=True)
def _no_owner_env(monkeypatch, tmp_path):
    monkeypatch.setattr(general, "OWNER_ID", 0)
    # Jamais d'écriture de cookies dans le dépôt, même si le code se trompe de chemin.
    sandbox = tmp_path / "sandbox_cwd"
    sandbox.mkdir()
    monkeypatch.chdir(sandbox)


def _cog():
    return general.General(SimpleNamespace())


# ─────────────────────── yt-cookies-update-no-owner-check ───────────────────────

@pytest.mark.parametrize("attr", ["yt_cookies_update", "yt_cookies_check"])
def test_cookie_commands_are_owner_only(attr, make_inter):
    cmd = getattr(general.General, attr)
    assert cmd.checks, f"/{cmd.name} n'a aucun check"
    member = make_inter(user_id=5, app_owner_id=42)
    owner = make_inter(user_id=42, app_owner_id=42)

    async def _go(inter):
        return [await c(inter) for c in cmd.checks]

    with pytest.raises(app_commands.CheckFailure):
        asyncio.run(_go(member))
    assert all(asyncio.run(_go(owner)))


# ─────────────── cookie-path-precedence-uploaded-ignored (upload/check) ───────────────

def test_upload_writes_to_cookies_upload_path(fake_youtube, make_inter, tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    env_before = dict(os.environ)
    data = ("# Netscape HTTP Cookie File\n" + COOKIE_LINE + "\n" + HTTPONLY_LINE + "\n").encode()
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    target = fake_youtube.upload_path
    assert os.path.exists(target), "cookies non écrits dans cookies_upload_path()"
    content = Path(target).read_text(encoding="utf-8")
    assert COOKIE_LINE in content and HTTPONLY_LINE in content
    assert not (cwd / "youtube.com_cookies.txt").exists(), "écriture dans le cwd au lieu du chemin canonique"
    assert dict(os.environ) == env_before
    assert fake_youtube.po_invalidations == 1


def test_upload_without_any_valid_cookie_keeps_current_file(fake_youtube, make_inter):
    target = fake_youtube.upload_path
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n" + COOKIE_LINE + "\n")
    # Header Netscape + JSON : accepté par _is_netscape, mais yt-dlp lève
    # "Cookies file must be Netscape formatted, not JSON" sur TOUTES les extractions.
    data = b'# Netscape HTTP Cookie File\n{"a": 1}\n'
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    kept = Path(target).read_text(encoding="utf-8")
    assert kept.count(COOKIE_LINE) == 1
    assert '{"a": 1}' not in kept
    assert inter.followup.messages and "❌" in (inter.followup.messages[-1][0] or "")


def test_upload_drops_lines_ytdlp_cannot_parse(fake_youtube, make_inter):
    data = ("# Netscape HTTP Cookie File\n" + COOKIE_LINE + '\n{"json": true}\n').encode()
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    content = Path(fake_youtube.upload_path).read_text(encoding="utf-8")
    assert COOKIE_LINE in content
    assert not any(line.lstrip().startswith(("{", "[")) for line in content.splitlines())


def _load_like_ytdlp(path) -> int:
    """Charge le fichier comme le fait YoutubeDL(cookiefile=…) ; lève si illisible."""
    try:
        from yt_dlp.cookies import YoutubeDLCookieJar as Jar
    except ImportError:  # yt-dlp absent : même _really_load stdlib (en-tête exigé)
        from http.cookiejar import MozillaCookieJar as Jar
    jar = Jar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return len(jar)


COOKIE_LINE_2 = ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tHSID\tdef"


def test_upload_without_header_is_loadable_by_ytdlp(fake_youtube, make_inter):
    # cookies.txt sans en-tête (accepté par _is_netscape via les tabulations) :
    # MozillaCookieJar exige « # Netscape HTTP Cookie File » en 1re ligne.
    data = (COOKIE_LINE + "\n" + COOKIE_LINE_2 + "\n").encode()
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    target = Path(fake_youtube.upload_path)
    assert target.read_text(encoding="utf-8").splitlines()[0] == "# Netscape HTTP Cookie File"
    assert _load_like_ytdlp(target) == 2


def test_upload_with_utf8_bom_keeps_header(fake_youtube, make_inter):
    # Fichier enregistré depuis le Bloc-notes : BOM UTF-8 devant l'en-tête.
    data = b"\xef\xbb\xbf# Netscape HTTP Cookie File\r\n" + (COOKIE_LINE + "\r\n").encode()
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    target = Path(fake_youtube.upload_path)
    content = target.read_text(encoding="utf-8")
    assert "﻿" not in content
    assert content.splitlines()[0] == "# Netscape HTTP Cookie File"
    assert _load_like_ytdlp(target) == 1


def test_upload_drops_entries_that_would_break_the_whole_jar(fake_youtube, make_inter):
    # MozillaCookieJar : `assert domain_specified == initial_dot` → UNE ligne incohérente
    # (flag TRUE sans point initial) rend TOUT le fichier illisible.
    bad = "youtube.com\tTRUE\t/\tTRUE\t1893456000\tBAD\tzzz"
    data = ("# Netscape HTTP Cookie File\n" + COOKIE_LINE + "\n" + bad + "\n").encode()
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    target = Path(fake_youtube.upload_path)
    assert "BAD" not in target.read_text(encoding="utf-8")
    assert _load_like_ytdlp(target) == 1


def test_upload_rejected_by_loader_keeps_current_file(fake_youtube, make_inter, monkeypatch):
    from http.cookiejar import LoadError

    target = Path(fake_youtube.upload_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Netscape HTTP Cookie File\n" + COOKIE_LINE + "\n", encoding="utf-8")

    def _refuse(path):
        raise LoadError(f"{path!r} does not look like a Netscape format cookies file")
    monkeypatch.setattr(general, "_load_cookiefile", _refuse, raising=False)
    data = ("# Netscape HTTP Cookie File\n" + COOKIE_LINE_2 + "\n").encode()
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_update.callback(_cog(), inter, FakeAttachment(data)))

    kept = target.read_text(encoding="utf-8")
    assert COOKIE_LINE in kept and "HSID" not in kept, "fichier actif remplacé malgré le refus du chargeur"
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name], "fichier temporaire laissé"
    assert "❌" in (inter.followup.messages[-1][0] or "")
    assert fake_youtube.po_invalidations == 0


def test_check_reports_the_file_playback_really_uses(fake_youtube, make_inter, tmp_path):
    used = tmp_path / "somewhere" / "cookies.txt"
    used.parent.mkdir()
    used.write_text("# Netscape HTTP Cookie File\n" + (COOKIE_LINE + "\n") * 6 + HTTPONLY_LINE + "\n",
                    encoding="utf-8")
    fake_youtube.picked = str(used)
    inter = make_inter(user_id=42, app_owner_id=42)

    asyncio.run(general.General.yt_cookies_check.callback(_cog(), inter))

    assert fake_youtube.pick_calls == [None]
    embed = inter.followup.messages[-1][1].get("embed")
    assert embed is not None
    assert "**7** cookies" in embed.description
    assert "cookies.txt" in embed.description


def test_check_without_cookies(fake_youtube, make_inter):
    fake_youtube.picked = None
    inter = make_inter(user_id=42, app_owner_id=42)
    asyncio.run(general.General.yt_cookies_check.callback(_cog(), inter))
    assert "Aucun cookies" in inter.followup.messages[-1][0]


# ─────────────────────── restart-reexec-crash ───────────────────────

def test_restart_reexecs_as_module(monkeypatch, make_inter):
    calls = []
    monkeypatch.setattr(general.os, "execv", lambda exe, argv: calls.append((exe, list(argv))))
    monkeypatch.setattr(sys, "argv", ["/app/bot/main.py"])   # ce que donne `python -m bot.main`

    closed = []

    class Bot:
        def __init__(self):
            self.voice_clients = []

        async def close(self):
            closed.append(True)

    inter = make_inter(user_id=42, app_owner_id=42)
    asyncio.run(general.General.restart.callback(general.General(Bot()), inter))

    assert closed == [True]
    assert calls == [(sys.executable, [sys.executable, "-m", "bot.main"])]
