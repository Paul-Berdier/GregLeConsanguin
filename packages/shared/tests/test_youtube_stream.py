# Contrat C1 (flux) : TrackUnavailable permanent, pas de probes inutiles,
# texte libre → ytsearch1:, "--" avant l'URL dans la CLI, yt-dlp tué au cleanup.

from __future__ import annotations

import asyncio
import io
import os
import subprocess

import discord
import pytest
from greg_shared.extractors import TrackUnavailable, youtube
from yt_dlp.utils import DownloadError

VID = "abcdefghijk"
WATCH = f"https://www.youtube.com/watch?v={VID}"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def no_popen(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("aucun sous-processus ne doit être lancé")

    monkeypatch.setattr(youtube.subprocess, "Popen", boom)
    monkeypatch.setattr(youtube.subprocess, "run", boom)


# ── Rejets immédiats (aucune extraction) ──

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PLlaN88a7y2_plecYoJxvRFTLHVbIVAOoc",
    "www.youtube.com/playlist?list=PLlaN88a7y2_plecYoJxvRFTLHVbIVAOoc",
    "https://www.youtube.com/@RickAstleyYT/videos",
    "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
    "https://music.youtube.com/browse/VLPLabcdef",
    "https://music.youtube.com/browse/MPREb_gTAcphH99wE",
    "https://www.youtube.com/@RickAstleyYT",
    "https://www.youtube-nocookie.com/embed/videoseries?list=PLabc",
    "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
])
@pytest.mark.parametrize("method", ["stream", "stream_pipe"])
def test_bundle_or_spotify_rejected_immediately(url, method, fake_ydl, no_popen):
    def responder(u, opts):
        raise AssertionError("aucune extraction attendue")

    fake_ydl.responder = responder
    with pytest.raises(TrackUnavailable) as ei:
        _run(getattr(youtube, method)(url, None))
    assert ei.value.permanent is True
    assert fake_ydl.calls == []


# Formes « une seule vidéo » que yt-dlp sait lire : jamais refusées d'office
@pytest.mark.parametrize("url", [
    "https://www.youtube.com/clip/UgkxU2HSeGL_NvmDJ-nQJrlLwllwMDBdGZFs",
    "https://www.youtube.com/v/dQw4w9WgXcQ",
    "https://www.youtube.com/e/dQw4w9WgXcQ",
    "https://www.youtube.com/watch/dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
])
def test_single_video_url_forms_are_passed_through(url):
    assert youtube._stream_target(url) == url


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/v/dQw4w9WgXcQ",
    "https://www.youtube.com/e/dQw4w9WgXcQ?version=3",
    "https://www.youtube.com/watch/dQw4w9WgXcQ",
])
def test_extract_video_id_legacy_forms(url):
    assert youtube._extract_video_id(url) == "dQw4w9WgXcQ"


# ── Classification des erreurs yt-dlp ──

@pytest.mark.parametrize("msg", [
    f"ERROR: [youtube] {VID}: Video unavailable",
    (f"ERROR: [youtube] {VID}: Video unavailable. This video is no longer available because the YouTube "
     "account associated with this video has been terminated."),
    f"ERROR: [youtube] {VID}: This video is not available",
    f"ERROR: [youtube] {VID}: Private video. Sign in if you've been granted access to this video",
    f"ERROR: [youtube] {VID}: This video has been removed by the uploader",
    f"ERROR: [youtube] {VID}: The uploader has not made this video available in your country",
    f"ERROR: [youtube] {VID}: Join this channel to get access to members-only content like this video",
    f"ERROR: [youtube] {VID}: This video is DRM protected",
    "ERROR: [DRM] The requested site is known to use DRM protection. It will NOT be supported.",
    f"ERROR: [youtube] {VID}: Sign in to confirm your age. This video may be inappropriate for some users.",
])
def test_permanent_errors_raise_track_unavailable_without_retry_loop(msg, fake_ydl, no_popen):
    def responder(u, opts):
        assert opts.get("ignoreerrors") is False, "les probes mono-vidéo doivent laisser remonter l'erreur"
        raise DownloadError(msg)

    fake_ydl.responder = responder
    with pytest.raises(TrackUnavailable) as ei:
        _run(youtube.stream(WATCH, None))
    assert ei.value.permanent is True
    assert len(fake_ydl.calls) == 1, "pas de boucle par client sur une erreur définitive"


@pytest.mark.parametrize("msg", [
    f"ERROR: [youtube] {VID}: Sign in to confirm you’re not a bot. Use --cookies-from-browser",
    f"ERROR: [youtube] {VID}: Sign in to confirm you're not a bot.",
    f"ERROR: [youtube] {VID}: Requested format is not available. Use --list-formats",
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    f"ERROR: [youtube] {VID}: This content isn't available, try again later.",
])
def test_transient_errors_are_not_permanent_and_not_looped(msg, fake_ydl, no_popen):
    def responder(u, opts):
        raise DownloadError(msg)

    fake_ydl.responder = responder
    with pytest.raises(RuntimeError) as ei:
        _run(youtube.stream(WATCH, None))
    assert not isinstance(ei.value, TrackUnavailable)
    assert not getattr(ei.value, "permanent", False)
    assert len(fake_ydl.calls) == 1


def test_format_miss_still_uses_per_client_fallback(fake_ydl, monkeypatch):
    seen_clients = []

    def responder(u, opts):
        seen_clients.append(opts["extractor_args"]["youtube"]["player_client"])
        return {"id": VID, "title": "T"}  # pas d'URL directe

    fake_ydl.responder = responder
    info = youtube._best_info_with_fallbacks(
        WATCH, cookies_file=None, cookies_from_browser=None, ffmpeg_path=None, ratelimit_bps=None,
    )
    assert info is None
    assert len(seen_clients) == 1 + len(youtube._CLIENTS_ORDER)


def test_free_text_becomes_ytsearch1(fake_ydl, no_popen):
    def responder(u, opts):
        return {"_type": "playlist", "entries": []}

    fake_ydl.responder = responder
    with pytest.raises(TrackUnavailable):
        _run(youtube.stream("daft punk around the world", None))
    assert fake_ydl.calls[0][0] == "ytsearch1:daft punk around the world"


def test_free_text_search_picks_first_entry(fake_ydl):
    def responder(u, opts):
        return {"_type": "playlist", "entries": [None, {"id": VID, "title": "One More Time", "url": "https://cdn/x"}]}

    fake_ydl.responder = responder
    info = youtube._best_info_with_fallbacks(
        "ytsearch1:daft punk", cookies_file=None, cookies_from_browser=None,
        ffmpeg_path=None, ratelimit_bps=None,
    )
    assert info["id"] == VID


def test_probe_opts_limit_playlists_to_one_item():
    opts = youtube._mk_opts()
    assert opts["noplaylist"] is True
    assert opts["playlist_items"] == "1"
    # search() et expand_bundle gardent leurs listes
    assert "playlist_items" not in youtube._mk_opts(search=True)
    assert "playlist_items" not in youtube._mk_opts(allow_playlist=True)


# ── stream_pipe : CLI & nettoyage ──

class _FakeProc:
    def __init__(self, args, rc=1, out="", stdout_bytes=b"", stderr_bytes=b""):
        self.args = args
        self.returncode = None
        self._rc = rc
        self._out = out
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self.killed = 0
        self.waited = 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed += 1
        if self.returncode is None:
            self.returncode = -9

    def wait(self, timeout=None):
        self.waited += 1
        if self.returncode is None:
            self.returncode = self._rc
        return self.returncode

    def communicate(self, timeout=None):
        self.returncode = self._rc
        return self._out, None


def _is_ytdlp_cmd(args):
    return "-o" in args and "--extractor-args" in args


def test_stream_pipe_puts_double_dash_before_target(fake_ydl, monkeypatch):
    fake_ydl.responder = lambda u, o: {"id": VID, "title": "T", "url": "https://cdn/x", "webpage_url": WATCH}
    launched = []

    def fake_popen(args, **kw):
        p = _FakeProc(args, rc=1, stderr_bytes=b"ERROR: unable to download video data: HTTP Error 403: Forbidden\n")
        launched.append(p)
        return p

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError) as ei:
        _run(youtube.stream_pipe("--batch-file=/proc/self/environ " + WATCH, None))
    assert not isinstance(ei.value, TrackUnavailable)
    # (le texte ci-dessus n'est pas une URL → recherche, jamais une option CLI)
    yt_cmds = [p.args for p in launched if _is_ytdlp_cmd(p.args)]
    assert yt_cmds, "le preflight pipe doit lancer yt-dlp"
    for cmd in yt_cmds:
        assert cmd[-2] == "--"
        assert not cmd[-1].startswith("-")


def test_stream_pipe_uses_resolved_watch_url_for_cli(fake_ydl, monkeypatch):
    fake_ydl.responder = lambda u, o: {"_type": "playlist", "entries": [
        {"id": VID, "title": "T", "url": "https://cdn/x", "webpage_url": WATCH}]}
    launched = []

    def fake_popen(args, **kw):
        p = _FakeProc(args, rc=1)
        launched.append(p)
        return p

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError):
        _run(youtube.stream_pipe("daft punk one more time", None))
    yt_cmds = [p.args for p in launched if _is_ytdlp_cmd(p.args)]
    assert yt_cmds[0][-2:] == ["--", WATCH]


def test_stream_pipe_permanent_error_from_cli_is_track_unavailable(fake_ydl, monkeypatch):
    def responder(u, o):
        raise DownloadError(f"ERROR: [youtube] {VID}: Sign in to confirm you're not a bot.")

    fake_ydl.responder = responder

    def fake_popen(args, **kw):
        return _FakeProc(args, rc=1, stderr_bytes=f"ERROR: [youtube] {VID}: Video unavailable\n".encode())

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    with pytest.raises(TrackUnavailable):
        _run(youtube.stream_pipe(WATCH, None))


def test_stream_pipe_permanent_error_skips_cli(fake_ydl, no_popen):
    def responder(u, o):
        raise DownloadError(f"ERROR: [youtube] {VID}: Private video. Sign in if you've been granted access")

    fake_ydl.responder = responder
    with pytest.raises(TrackUnavailable):
        _run(youtube.stream_pipe(WATCH, None))


def test_pipe_preflight_timeout_without_audio_is_a_failure(fake_ydl, monkeypatch):
    fake_ydl.responder = lambda u, o: {"id": VID, "title": "T", "url": "https://cdn/x", "webpage_url": WATCH}
    launched = []

    class _HangingFF(_FakeProc):
        def communicate(self, timeout=None):
            if timeout is not None and self.returncode is None:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return "", None  # tué : aucune progression reçue

    def fake_popen(args, **kw):
        p = _FakeProc(args) if _is_ytdlp_cmd(args) else _HangingFF(args)
        launched.append(p)
        return p

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError):
        _run(youtube.stream_pipe(WATCH, None))
    # extraction bloquée : inutile de retenter un autre format
    assert len([p for p in launched if _is_ytdlp_cmd(p.args)]) == 1


def test_pipe_preflight_timeout_with_audio_flowing_is_ok(fake_ydl, monkeypatch):
    fake_ydl.responder = lambda u, o: {"id": VID, "title": "Titre", "url": "https://cdn/x", "webpage_url": WATCH}
    launched = []

    class _SlowFF(_FakeProc):
        def communicate(self, timeout=None):
            if timeout is not None and self.returncode is None:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return "progress=continue\nout_time_us=850000\n", None

    def fake_popen(args, **kw):
        p = _FakeProc(args) if _is_ytdlp_cmd(args) else _SlowFF(args)
        launched.append(p)
        return p

    created = {}

    def fake_init(self, *a, **k):
        self._process = discord.utils.MISSING
        created["kwargs"] = k

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(discord.FFmpegPCMAudio, "__init__", fake_init)
    monkeypatch.setattr(discord.FFmpegPCMAudio, "cleanup", lambda self: None)
    _src, title = _run(youtube.stream_pipe(WATCH, None))
    assert title == "Titre"
    assert created["kwargs"]["pipe"] is True


def test_stream_pipe_source_cleanup_kills_ytdlp(fake_ydl, monkeypatch):
    fake_ydl.responder = lambda u, o: {"id": VID, "title": "Titre", "url": "https://cdn/x", "webpage_url": WATCH}
    launched = []

    def fake_popen(args, **kw):
        if _is_ytdlp_cmd(args):
            p = _FakeProc(args)
        else:
            p = _FakeProc(args, rc=0, out="out_time_us=2000000\nprogress=end\n")
        launched.append(p)
        return p

    parent_cleanups = []
    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    def fake_init(self, *a, **k):
        self._process = discord.utils.MISSING

    monkeypatch.setattr(discord.FFmpegPCMAudio, "__init__", fake_init)
    monkeypatch.setattr(discord.FFmpegPCMAudio, "cleanup", lambda self: parent_cleanups.append(1))

    src, _title = _run(youtube.stream_pipe(WATCH, None))
    producer = launched[-1]
    assert _is_ytdlp_cmd(producer.args)
    assert getattr(src, "_ytdlp_proc", None) is producer
    assert producer.killed == 0

    src.cleanup()
    assert producer.killed == 1
    assert producer.stdout.closed and producer.stderr.closed
    assert parent_cleanups == [1]

    src.cleanup()  # idempotent (discord.py appelle cleanup deux fois)
    assert producer.killed == 1


def test_safe_cleanup_closes_pipes():
    p = _FakeProc(["yt-dlp"])

    class _Src:
        _ytdlp_proc = p
        cleaned = False

        def cleanup(self):
            self.cleaned = True

    s = _Src()
    youtube.safe_cleanup(s)
    assert p.killed == 1 and p.stdout.closed and p.stderr.closed
    assert s.cleaned


def test_pipe_cleanup_kills_ffmpeg_before_joining_writer(monkeypatch):
    """Après un skip, le writer discord.py est bloqué sur le stdin de ffmpeg :
    joindre le thread AVANT de tuer ffmpeg coûtait ~1 s de silence."""
    order = []
    producer = _FakeProc(["yt-dlp"])
    orig_kill = producer.kill

    def kill():
        order.append("kill-ytdlp")
        orig_kill()

    producer.kill = kill

    class _Writer:
        def is_alive(self):
            return "kill-ffmpeg" not in order

        def join(self, timeout=None):
            order.append("join-writer" if "kill-ffmpeg" in order else "join-writer-BLOQUÉ")

    def fake_init(self, *a, **k):
        self._process = discord.utils.MISSING

    monkeypatch.setattr(discord.FFmpegPCMAudio, "__init__", fake_init)
    monkeypatch.setattr(discord.FFmpegPCMAudio, "cleanup", lambda self: order.append("kill-ffmpeg"))
    src = youtube._PipedFFmpegPCMAudio(producer, source=producer.stdout, pipe=True)
    src._pipe_writer_thread = _Writer()

    src.cleanup()
    assert "join-writer-BLOQUÉ" not in order
    assert order.index("kill-ffmpeg") < order.index("join-writer")
    assert producer.killed == 1 and producer.stdout.closed and producer.stderr.closed

    src.cleanup()  # idempotent
    assert producer.killed == 1


def _cookies_arg(args):
    return args[args.index("--cookies") + 1] if "--cookies" in args else None


def test_stream_pipe_cli_gets_private_cookie_copies(fake_ydl, monkeypatch, tmp_path):
    shared = tmp_path / "yt.txt"
    shared.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(shared))
    fake_ydl.responder = lambda u, o: {"id": VID, "title": "T", "url": "https://cdn/x", "webpage_url": WATCH}
    launched = []

    def fake_popen(args, **kw):
        if _is_ytdlp_cmd(args):
            ck = _cookies_arg(args)
            assert ck and ck != str(shared) and os.path.exists(ck)
            p = _FakeProc(args, rc=1, stderr_bytes=b"ERROR: unable to download video data: HTTP Error 403: Forbidden\n")
        else:
            p = _FakeProc(args, rc=1)
        launched.append(p)
        return p

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError):
        _run(youtube.stream_pipe(WATCH, None))
    copies = [_cookies_arg(p.args) for p in launched if _is_ytdlp_cmd(p.args)]
    assert len(copies) == 2 and len(set(copies)) == 2
    assert not any(os.path.exists(c) for c in copies), "copies supprimées après chaque essai"
    assert shared.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\n"


def test_stream_pipe_producer_cookie_copy_removed_on_cleanup(fake_ydl, monkeypatch, tmp_path):
    shared = tmp_path / "yt.txt"
    shared.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(shared))
    fake_ydl.responder = lambda u, o: {"id": VID, "title": "T", "url": "https://cdn/x", "webpage_url": WATCH}
    launched = []

    def fake_popen(args, **kw):
        p = _FakeProc(args) if _is_ytdlp_cmd(args) else _FakeProc(args, rc=0, out="out_time_us=2000000\n")
        launched.append(p)
        return p

    def fake_init(self, *a, **k):
        self._process = discord.utils.MISSING

    monkeypatch.setattr(youtube.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(discord.FFmpegPCMAudio, "__init__", fake_init)
    monkeypatch.setattr(discord.FFmpegPCMAudio, "cleanup", lambda self: None)
    src, _t = _run(youtube.stream_pipe(WATCH, None))
    producer_ck = _cookies_arg(launched[-1].args)
    assert producer_ck and os.path.exists(producer_ck), "la copie vit tant que yt-dlp tourne"
    src.cleanup()
    assert not os.path.exists(producer_ck)
