# Contrat C6 (côté extracteurs) : un seul chemin de cookies, résolu à chaque appel.

from __future__ import annotations

import base64
import gzip
import os

from greg_shared.extractors import token_fetcher, youtube, youtube_policy

NETSCAPE_FILE = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tFROM_FILE\tfile-value\n"
)
NETSCAPE_B64 = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tFROM_B64\tb64-value\n"
)


def _b64(text: str, gz: bool = False) -> str:
    raw = text.encode("utf-8")
    if gz:
        raw = gzip.compress(raw)
    return base64.b64encode(raw).decode("ascii")


def test_upload_path_is_evaluated_per_call(monkeypatch, tmp_path):
    assert youtube.cookies_upload_path() == "youtube.com_cookies.txt"
    monkeypatch.setenv("YOUTUBE_COOKIES_PATH", str(tmp_path / "b.txt"))
    assert youtube.cookies_upload_path() == str(tmp_path / "b.txt")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(tmp_path / "a.txt"))
    assert youtube.cookies_upload_path() == str(tmp_path / "a.txt")


def test_explicit_existing_arg_wins(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit.txt"
    explicit.write_text(NETSCAPE_FILE, encoding="utf-8")
    up = tmp_path / "data" / "yt.txt"
    up.parent.mkdir()
    up.write_text(NETSCAPE_FILE, encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(up))
    assert youtube._pick_cookiefile(str(explicit)) == str(explicit)


def test_uploaded_file_beats_legacy_and_b64(monkeypatch, tmp_path):
    up = tmp_path / "data" / "yt.txt"
    up.parent.mkdir()
    up.write_text(NETSCAPE_FILE, encoding="utf-8")
    (tmp_path / "youtube.com_cookies.txt").write_text("legacy", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(up))
    monkeypatch.setenv("YTDLP_COOKIES_B64", _b64(NETSCAPE_B64))
    assert youtube._pick_cookiefile(None) == str(up)
    assert up.read_text(encoding="utf-8") == NETSCAPE_FILE, "l'upload ne doit jamais être écrasé"


def test_legacy_file_used_when_upload_path_absent(monkeypatch, tmp_path):
    (tmp_path / "youtube.com_cookies.txt").write_text(NETSCAPE_FILE, encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(tmp_path / "data" / "absent.txt"))
    monkeypatch.setenv("YTDLP_COOKIES_B64", _b64(NETSCAPE_B64))
    assert youtube._pick_cookiefile(None) == "youtube.com_cookies.txt"
    assert not (tmp_path / "data" / "absent.txt").exists()


def test_b64_materialised_into_upload_path_only_when_absent(monkeypatch, tmp_path):
    target = tmp_path / "data" / "yt.txt"
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(target))
    monkeypatch.setenv("YTDLP_COOKIES_B64", _b64(NETSCAPE_B64))
    assert youtube._pick_cookiefile(None) == str(target)
    assert target.read_text(encoding="utf-8") == NETSCAPE_B64
    # Un nouvel upload n'est pas écrasé au prochain appel
    target.write_text(NETSCAPE_FILE, encoding="utf-8")
    assert youtube._pick_cookiefile(None) == str(target)
    assert target.read_text(encoding="utf-8") == NETSCAPE_FILE


def test_gzip_b64_is_decoded(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_COOKIES_B64", _b64(NETSCAPE_B64, gz=True))
    picked = youtube._pick_cookiefile(None)
    assert picked == "youtube.com_cookies.txt"
    with open(picked, encoding="utf-8") as f:
        assert f.read() == NETSCAPE_B64


def test_nothing_configured_returns_none():
    assert youtube._pick_cookiefile(None) is None
    assert youtube._pick_cookiefile("does/not/exist.txt") is None


def test_token_fetcher_injects_the_resolved_cookie_file(monkeypatch, tmp_path):
    up = tmp_path / "yt.txt"
    up.write_text(NETSCAPE_FILE, encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(up))
    monkeypatch.setenv("YTDLP_COOKIES_B64", _b64(NETSCAPE_B64))

    class Ctx:
        def __init__(self):
            self.cookies = []

        def add_cookies(self, cookies):
            self.cookies.extend(cookies)

    ctx = Ctx()
    token_fetcher._inject_cookies(ctx)
    names = [c["name"] for c in ctx.cookies]
    assert names == ["FROM_FILE"]


def test_policy_resolution_follows_same_precedence(monkeypatch, tmp_path):
    up = tmp_path / "data" / "yt.txt"
    up.parent.mkdir()
    up.write_text(NETSCAPE_FILE, encoding="utf-8")
    (tmp_path / "youtube.com_cookies.txt").write_text("legacy", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(up))
    cookiefile, browser = youtube_policy.resolve_cookie_inputs(None, None)
    assert cookiefile == str(up)
    assert browser is None
    assert os.path.exists(cookiefile)


# ── yt-dlp réécrit son cookiejar à la fermeture : jamais sur le fichier partagé ──

def test_real_ytdlp_close_does_not_overwrite_a_fresh_upload(monkeypatch, tmp_path):
    shared = tmp_path / "data" / "yt.txt"
    shared.parent.mkdir()
    shared.write_text(NETSCAPE_FILE, encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(shared))
    opts = youtube._mk_opts()
    assert opts["cookiefile"] == str(shared)
    with youtube._open_ydl(opts) as ydl:  # vrai YoutubeDL (aucun accès réseau ici)
        assert ydl.params["cookiefile"] != str(shared)
        assert [c.name for c in ydl.cookiejar] == ["FROM_FILE"]
        # /yt_cookies_update pendant l'extraction
        shared.write_text(NETSCAPE_B64, encoding="utf-8")
        private = ydl.params["cookiefile"]
    assert shared.read_text(encoding="utf-8") == NETSCAPE_B64
    assert not os.path.exists(private)


def test_cookiefile_copy_is_private_and_removed(tmp_path):
    src = tmp_path / "yt.txt"
    src.write_text(NETSCAPE_FILE, encoding="utf-8")
    with youtube.cookiefile_copy(str(src)) as ck:
        assert ck and ck != str(src)
        with open(ck, encoding="utf-8") as f:
            assert f.read() == NETSCAPE_FILE
        with open(ck, "w", encoding="utf-8") as f:
            f.write("réécrit")
    assert not os.path.exists(ck)
    assert src.read_text(encoding="utf-8") == NETSCAPE_FILE


def test_cookiefile_copy_without_file_yields_none(tmp_path):
    with youtube.cookiefile_copy(None) as ck:
        assert ck is None
    with youtube.cookiefile_copy(str(tmp_path / "absent.txt")) as ck:
        assert ck is None
