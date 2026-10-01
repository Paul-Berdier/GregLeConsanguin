"""CountingSource (spec synchro son/vidéo §4.1) : trames comptées, pré-lecture, callbacks, délégation à ffmpeg."""
from __future__ import annotations

import types

import discord
import discord.player

from bot.services.audio_clock import FRAME_MS, CountingSource

F1, F2, F3 = b"\x01" * 3840, b"\x02" * 3840, b"\x03" * 3840


class Inner:
    """Source ffmpeg scriptée : une trame par élément, b'' (fin de flux) quand la liste est vide."""

    def __init__(self, frames=()):
        self.frames = list(frames)
        self.reads = 0
        self.cleaned = 0
        self._current_error = None
        self._ytdlp_proc = None
        self.url = "https://www.youtube.com/watch?v=vid00000001"

    def read(self):
        self.reads += 1
        return self.frames.pop(0) if self.frames else b""

    def is_opus(self):
        return True  # volontairement faux : l'enveloppe répond False elle-même

    def cleanup(self):
        self.cleaned += 1


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class Loop:
    """Boucle asyncio factice : garde les call_soon_threadsafe."""

    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, cb, *args):
        self.calls.append((cb, args))


def test_counts_only_non_empty_frames():
    src = CountingSource(Inner([F1, F2, F3]))
    assert [src.read() for _ in range(4)] == [F1, F2, F3, b""]
    assert src.frames == 3
    assert src.position_ms() == 3 * FRAME_MS == 60.0


def test_preroll_reads_one_frame_ahead_and_hands_it_out_first():
    inner = Inner([F1, F2])
    src = CountingSource(inner)
    assert src.preroll() is True
    assert src.preroll() is True, "idempotente : pas de 2e lecture"
    assert inner.reads == 1 and src.frames == 0 and src.preroll_ms is not None
    assert src.read() is F1
    assert src.read() is F2
    assert src.frames == 2


def test_preroll_of_an_empty_stream_is_a_start_failure():
    src = CountingSource(Inner([]))
    assert src.preroll() is False
    assert src.read() == b""
    assert src.frames == 0 and src.first_read_at is None


def test_read_times_and_stall_detection():
    clk = Clock(100.0)
    src = CountingSource(Inner([F1, F2]), clock=clk)
    assert src.is_stalled() is False, "rien lu : chargement, pas blocage"
    src.read()
    assert (src.first_read_at, src.last_read_at) == (100.0, 100.0)
    clk.t = 100.2
    assert src.is_stalled() is False
    clk.t = 100.3
    assert src.is_stalled() is True
    src.read()
    assert src.last_read_at == 100.3 and src.is_stalled() is False


def test_callbacks_go_through_call_soon_threadsafe():
    clk, loop = Clock(10.0), Loop()
    first, resumed = [], []
    src = CountingSource(Inner([F1, F2, F3]), loop=loop, clock=clk,
                         on_first_frame=first.append, on_resume_after_stall=resumed.append)
    src.read()
    clk.t = 10.02
    src.read()
    clk.t = 10.5  # 480 ms sans lecture : fin d'un blocage
    src.read()
    assert first == [] and resumed == [], "jamais appelés depuis le thread audio"
    assert loop.calls == [(first.append, (src,)), (resumed.append, (src,))]


def test_note_resume_keeps_a_pause_from_looking_like_a_stall():
    clk, loop = Clock(10.0), Loop()
    src = CountingSource(Inner([F1, F2]), loop=loop, clock=clk, on_resume_after_stall=lambda s: None)
    src.read()
    clk.t = 40.0  # 30 s de pause
    src.note_resume()
    assert src.is_stalled() is False
    src.read()
    assert len(loop.calls) == 0


def test_without_loop_callbacks_are_called_directly():
    seen = []
    src = CountingSource(Inner([F1]), on_first_frame=seen.append)
    src.read()
    assert seen == [src]


def test_closed_loop_is_ignored():
    class Closed:
        def call_soon_threadsafe(self, *a):
            raise RuntimeError("Event loop is closed")

    src = CountingSource(Inner([F1]), loop=Closed(), on_first_frame=lambda s: None)
    assert src.read() == F1


def test_delegation_to_the_ffmpeg_source():
    inner = Inner([F1])
    src = CountingSource(inner)
    assert isinstance(src, discord.AudioSource)
    assert src.is_opus() is False
    assert src.url == inner.url
    assert src._ytdlp_proc is None
    err = RuntimeError("FFmpeg exited with code 1")
    inner._current_error = err
    assert src._current_error is err
    src.preroll()
    src.cleanup()
    assert inner.cleaned == 1
    assert src.read() == b"", "trame d'avance jetée au nettoyage"


def test_mode_pipe_when_a_ytdlp_process_is_attached():
    inner = Inner([F1])
    assert CountingSource(inner).mode == "direct"
    inner._ytdlp_proc = types.SimpleNamespace(poll=lambda: None)
    assert CountingSource(inner).mode == "pipe"


class _Client:
    """VoiceClient minimal pour le vrai discord.player.AudioPlayer (pas de ws : _speak journalise et continue)."""

    def __init__(self):
        self.sent = []

    def is_connected(self):
        return True

    def send_audio_packet(self, data, *, encode=True):
        self.sent.append((data, encode))


def test_real_audio_player_counts_the_frames_it_sends():
    client = _Client()
    src = CountingSource(Inner([F1, F2, F3]))
    assert src.preroll()
    player = discord.player.AudioPlayer(src, client, after=lambda e: None)
    player.run()  # synchrone : 3 trames puis b''
    pcm = [d for d, enc in client.sent if enc]
    assert pcm == [F1, F2, F3]
    assert src.frames == 3


def test_real_audio_player_reports_ffmpeg_error_through_the_wrapper():
    """Rupture d'une montée de discord.py : AudioPlayer lit source._current_error (player.py:806)."""
    inner = Inner([])
    err = RuntimeError("FFmpeg exited with code 1")
    inner._current_error = err
    got = []
    player = discord.player.AudioPlayer(CountingSource(inner), _Client(), after=got.append)
    player.run()
    assert got == [err]
    assert inner.cleaned >= 1
