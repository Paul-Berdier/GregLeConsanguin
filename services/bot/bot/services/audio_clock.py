"""Horloge audio du bot : les trames que discord.py lit vraiment (spec synchro son/vidéo §4.1).

discord.py appelle read() une fois par trame de 20 ms, juste avant de l'envoyer, et ne l'appelle ni pendant une
pause ni pendant l'attente d'une reconnexion vocale : frames × 20 ms est la position réellement envoyée.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

import discord

FRAME_MS = 20.0   # une trame : 3840 octets de PCM 48 kHz stéréo (OpusEncoder.FRAME_SIZE)
STALL_S = 0.25    # plus de 250 ms sans lecture hors pause : flux bloqué

Callback = Callable[["CountingSource"], Any]


class CountingSource(discord.AudioSource):
    """Enveloppe d'une source ffmpeg (FFmpegPCMAudio, pipe ou direct) qui compte les trames lues.

    Les callbacks partent du thread audio : jamais d'asyncio direct, toujours loop.call_soon_threadsafe(cb, source).
    Tout attribut inconnu est délégué à la source interne : _current_error (lu par AudioPlayer), _ytdlp_proc
    (_cleanup_source), url, die_after (faux des tests)…
    """

    def __init__(self, inner: Any, *, loop: Any = None, on_first_frame: Optional[Callback] = None,
                 on_resume_after_stall: Optional[Callback] = None,
                 clock: Callable[[], float] = time.monotonic, stall_s: float = STALL_S):
        self._inner = inner
        self._loop = loop
        self._on_first_frame = on_first_frame
        self._on_resume_after_stall = on_resume_after_stall
        self._clock = clock
        self._stall_s = stall_s
        self._pre: Optional[bytes] = None
        self.frames = 0
        self.first_read_at: Optional[float] = None
        self.last_read_at: Optional[float] = None
        self.preroll_ms: Optional[float] = None
        # yt-dlp attaché (youtube.stream_pipe) : mode pipe ; youtube.stream pose _ytdlp_proc = None
        self.mode = "pipe" if getattr(inner, "_ytdlp_proc", None) is not None else "direct"

    def __getattr__(self, name: str) -> Any:
        if name == "_inner":  # __init__ avorté (puis __del__) : pas de récursion
            raise AttributeError(name)
        return getattr(self._inner, name)

    def preroll(self) -> bool:
        """Lit une trame d'avance (dans un thread, avant vc.play) ; False : ffmpeg n'a rien produit (b'')."""
        if self._pre is not None:
            return True
        t0 = self._clock()
        data = self._inner.read()
        self.preroll_ms = (self._clock() - t0) * 1000.0
        if not data:
            return False
        self._pre = data
        return True

    def read(self) -> bytes:
        if self._pre is not None:
            data, self._pre = self._pre, None
        else:
            data = self._inner.read()
        if not data:
            return b""
        now = self._clock()
        prev = self.last_read_at
        self.frames += 1
        self.last_read_at = now
        if self.first_read_at is None:
            self.first_read_at = now
            self._fire(self._on_first_frame)
        elif prev is not None and now - prev > self._stall_s:
            self._fire(self._on_resume_after_stall)
        return data

    def note_resume(self) -> None:
        """Juste AVANT vc.resume() : le temps passé en pause n'est pas un blocage."""
        if self.last_read_at is not None:
            self.last_read_at = self._clock()

    def position_ms(self) -> float:
        return self.frames * FRAME_MS

    def is_stalled(self) -> bool:
        return self.last_read_at is not None and self._clock() - self.last_read_at > self._stall_s

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self._pre = None
        inner = self.__dict__.get("_inner")
        if inner is not None and hasattr(inner, "cleanup"):
            inner.cleanup()

    def _fire(self, cb: Optional[Callback]) -> None:
        if cb is None:
            return
        try:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(cb, self)
            else:
                cb(self)
        except RuntimeError:  # boucle fermée (arrêt du bot) : rien à prévenir
            pass
