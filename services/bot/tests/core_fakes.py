"""Faux objets Discord / extracteurs pour tester PlayerService, RedisBridge et le cog Music
sans réseau, sans Discord et sans yt-dlp.

Le vrai discord.py est importé (types, exceptions) mais aucune connexion n'est faite.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
import types
from typing import Any, Callable, Dict, List, Optional

import discord
import pytest_asyncio

# ─────────────────────────── Faux Discord ───────────────────────────


class FakeMember:
    def __init__(self, uid: int, *, bot: bool = False, admin: bool = False,
                 roles: tuple = (), channel=None):
        self.id = int(uid)
        self.bot = bot
        self.name = f"user{uid}"
        self.display_name = self.name
        self.mention = f"<@{uid}>"
        self.display_avatar = None
        self.avatar = None
        self.roles = [types.SimpleNamespace(name=r) for r in roles]
        self.guild_permissions = types.SimpleNamespace(
            administrator=admin, manage_guild=False, manage_channels=False,
        )
        self.voice = types.SimpleNamespace(channel=channel) if channel is not None else None


class FakeVoiceChannel(discord.VoiceChannel):
    """Vrai sous-type de discord.VoiceChannel (isinstance OK) sans état Discord."""

    def __init__(self, cid: int, guild: "FakeGuild"):
        self.id = int(cid)
        self.name = f"vocal-{cid}"
        self._fake_guild = guild
        self._fake_members: List[FakeMember] = []
        self.connect_calls: List[dict] = []
        self.connect_exc: Optional[BaseException] = None

    @property
    def members(self):  # type: ignore[override]
        return self._fake_members

    async def connect(self, *, timeout: float = 60.0, reconnect: bool = True, **kw):  # type: ignore[override]
        self.connect_calls.append({"timeout": timeout})
        g = self._fake_guild
        if self.connect_exc is not None:
            raise self.connect_exc
        if g.voice_client is not None:
            raise discord.ClientException("Already connected to a voice channel.")
        vc = FakeVC(self, g)
        g.voice_client = vc
        return vc


class FakeVC:
    """Client vocal au comportement proche de discord.VoiceClient.

    `play()` lance un thread qui « lit » la source pendant `source.die_after`
    secondes puis appelle `after(None)` depuis ce thread (comme discord.py).
    """

    def __init__(self, channel: FakeVoiceChannel, guild: "FakeGuild", *, connected: bool = True):
        self.channel = channel
        self.guild = guild
        self.connected = connected
        self._playing = False
        self._paused = False
        self._token: Optional[object] = None
        self._stop_evt: Optional[threading.Event] = None
        self.play_calls: List[Any] = []
        self.moves: List[int] = []
        self.disconnect_calls = 0
        self.play_exc: Optional[BaseException] = None

    def is_connected(self) -> bool:
        return self.connected

    def is_playing(self) -> bool:
        return self._playing and not self._paused

    def is_paused(self) -> bool:
        return self._playing and self._paused

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def play(self, source, *, after=None, **kw):
        if self.play_exc is not None:
            raise self.play_exc
        if not self.connected:
            raise discord.ClientException("Not connected to voice.")
        if self._playing:
            raise discord.ClientException("Already playing audio.")
        self.play_calls.append(source)
        token = object()
        self._token = token
        self._playing = True
        self._paused = False
        ev = threading.Event()
        self._stop_evt = ev
        dur = float(getattr(source, "die_after", 30.0))

        def run():
            ev.wait(dur)
            if self._token is token:
                self._playing = False
                self._paused = False
            if after:
                after(None)

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._playing = False
        self._paused = False
        self._token = None
        if self._stop_evt:
            self._stop_evt.set()

    async def move_to(self, channel):
        self.moves.append(int(channel.id))
        self.channel = channel

    async def disconnect(self, *, force: bool = False):
        self.disconnect_calls += 1
        self.stop()
        self.connected = False
        if self.guild.voice_client is self:
            self.guild.voice_client = None

    def cleanup(self):
        if self.guild.voice_client is self:
            self.guild.voice_client = None


class FakeGuild:
    def __init__(self, gid: int):
        self.id = int(gid)
        self.name = f"guild-{gid}"
        self.voice_client: Optional[FakeVC] = None
        self._members: Dict[int, FakeMember] = {}
        self.channels: Dict[int, FakeVoiceChannel] = {}

    def get_member(self, uid):
        try:
            return self._members.get(int(uid))
        except (TypeError, ValueError):
            return None

    def channel(self, cid: int) -> FakeVoiceChannel:
        if cid not in self.channels:
            self.channels[cid] = FakeVoiceChannel(cid, self)
        return self.channels[cid]

    def add_member(self, uid: int, *, channel_id: Optional[int] = None, **kw) -> FakeMember:
        ch = self.channel(channel_id) if channel_id is not None else None
        m = FakeMember(uid, channel=ch, **kw)
        self._members[int(uid)] = m
        if ch is not None:
            ch._fake_members.append(m)
        return m


class FakeBridge:
    def __init__(self):
        self.progress = 0
        self.ticks: List[tuple] = []  # (args, kwargs) de chaque publish_progress

    async def publish_progress(self, *a, **k):
        self.progress += 1
        self.ticks.append((a, k))


class FakeBot:
    def __init__(self, loop, *guilds: FakeGuild):
        self.loop = loop
        self._guilds = {g.id: g for g in guilds}
        self.redis_bridge = FakeBridge()
        self.emits: List[int] = []
        self.user = types.SimpleNamespace(id=999)
        self.player_service = None

    @property
    def guilds(self):
        return list(self._guilds.values())

    def get_guild(self, gid):
        try:
            return self._guilds.get(int(gid))
        except (TypeError, ValueError):
            return None

    def emit_state_update(self, gid, payload=None):
        self.emits.append(gid)


# ─────────────────────────── Faux extracteurs ───────────────────────────


_KNOWN_HOSTS = re.compile(
    r"^(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be|soundcloud\.com|on\.soundcloud\.com|"
    r"open\.spotify\.com|spotify\.link)/",
    re.I,
)


def fake_normalize_link(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    if _KNOWN_HOSTS.match(s):
        s = "https://" + s
    return s


def fake_is_url(s: str) -> bool:
    return fake_normalize_link(s).lower().startswith(("http://", "https://"))


def fake_is_spotify_url(s: str) -> bool:
    s = fake_normalize_link(s).lower()
    return "open.spotify.com" in s or "spotify.link" in s or s.startswith("spotify:")


def fake_is_bundle_url(u: str) -> bool:
    u = (u or "").lower()
    return "list=" in u or "/playlist" in u or "/sets/" in u


FRAME = b"\x00" * 3840  # une trame PCM de 20 ms (48 kHz stéréo s16le)


class FakeSource:
    """Source ffmpeg factice. `frames` : trames disponibles (None = infini, 0 = ffmpeg ne produit rien) ;
    `read_delay` : chaque read() bloque ce temps (premier octet lent, mode pipe), sauf si la source est
    nettoyée entre-temps (ffmpeg tué : read() rend b'' tout de suite)."""

    def __init__(self, url: str, die_after: float, cleanup_delay: float = 0.0,
                 frames: Optional[int] = None, read_delay: float = 0.0):
        self.url = url
        self.die_after = die_after
        self.cleaned = False
        self._ytdlp_proc = None
        # cleanup() bloquant (comme _PipedFFmpegPCMAudio : join du thread d'écriture)
        self.cleanup_delay = cleanup_delay
        self.frames_left = frames
        self.read_delay = read_delay
        self.reads = 0

    def read(self) -> bytes:
        end = time.monotonic() + self.read_delay
        while not self.cleaned and time.monotonic() < end:
            time.sleep(0.005)
        if self.cleaned:
            return b""
        if self.frames_left is not None:
            if self.frames_left <= 0:
                return b""
            self.frames_left -= 1
        self.reads += 1
        return FRAME

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        if self.cleanup_delay:
            time.sleep(self.cleanup_delay)
        self.cleaned = True


def yt_entry(i: int, **kw) -> dict:
    e = {
        "title": f"Titre {i}",
        "url": f"https://www.youtube.com/watch?v=vid{i:08d}",
        "webpage_url": f"https://www.youtube.com/watch?v=vid{i:08d}",
        "artist": "Artiste",
        "thumb": None,
        "duration": 180,
        "provider": "youtube",
    }
    e.update(kw)
    return e


class FakeExtractor:
    """Extracteur piloté par URL :
    {"fail", "unavailable", "pipe_tried", "delay", "die_after", "cleanup_delay", "title",
     "no_audio" (ffmpeg ne produit aucune trame), "read_delay" (chaque trame lente)}."""

    def __init__(self, ps_module):
        self.ps = ps_module
        self.calls: List[tuple] = []
        self.behaviour: Dict[str, dict] = {}
        self.default_die_after = 30.0
        self.sources: List[FakeSource] = []
        self.expand_calls: List[dict] = []
        self.expand_impl: Optional[Callable[..., list]] = None
        self.search_calls: List[dict] = []
        self.search_results: Dict[str, list] = {}
        self.search_threads: List[str] = []
        self.expand_threads: List[str] = []

    # stream / stream_pipe
    async def stream(self, url, ffmpeg_path, **kw):
        return await self._make("stream", url)

    async def stream_pipe(self, url, ffmpeg_path, **kw):
        return await self._make("stream_pipe", url)

    async def _make(self, method, url):
        self.calls.append((method, url))
        b = self.behaviour.get(url, {})
        if b.get("delay"):
            await asyncio.sleep(b["delay"])
        if b.get("unavailable"):
            raise make_unavailable(self.ps, "Video unavailable")
        if b.get("pipe_tried") and method == "stream":
            # youtube.stream() a déjà basculé sur stream_pipe en interne, qui a échoué aussi.
            err = RuntimeError("Stream YouTube indisponible (403/SABR)")
            err.pipe_tried = True
            raise err
        if b.get("fail"):
            raise RuntimeError("HTTP Error 403: Forbidden")
        src = FakeSource(url, b.get("die_after", self.default_die_after), b.get("cleanup_delay", 0.0),
                         frames=0 if b.get("no_audio") else None, read_delay=b.get("read_delay", 0.0))
        self.sources.append(src)
        return src, b.get("title", f"Titre de {url}")

    # expand_bundle (synchrone, appelé dans un thread)
    def expand_bundle(self, url, *, limit=10, cookies_file=None, cookies_from_browser=None):
        self.expand_calls.append({"url": url, "limit": limit})
        self.expand_threads.append(threading.current_thread().name)
        if self.expand_impl is None:
            raise AssertionError("expand_bundle appelé sans comportement configuré")
        return self.expand_impl(url, limit=limit)

    # youtube.search (synchrone, appelé dans un thread)
    def search(self, query, *, cookies_file=None, cookies_from_browser=None, limit=5):
        self.search_calls.append({"query": query, "limit": limit})
        self.search_threads.append(threading.current_thread().name)
        res = self.search_results.get(query, [])
        if isinstance(res, BaseException):
            raise res
        return list(res)[:limit]


def make_bundle_error(ps_module, code: str, message: str):
    base = ps_module.BundleError

    class _BundleError(base):  # type: ignore[misc, valid-type]
        def __init__(self, c, m):
            Exception.__init__(self, m)
            self.code = c
            self.message = m

    return _BundleError(code, message)


def make_unavailable(ps_module, message: str):
    base = ps_module.TrackUnavailable

    class _Unavailable(base):  # type: ignore[misc, valid-type]
        permanent = True

        def __init__(self, m):
            Exception.__init__(self, m)

    return _Unavailable(message)


# ─────────────────────────── Harnais PlayerService ───────────────────────────


GID = 4242
BOT_CHANNEL = 111
USER_CHANNEL = 111


class Harness:
    def __init__(self, ps, svc, bot, guild, ext, tmp_path):
        self.ps = ps
        self.svc = svc
        self.bot = bot
        self.guild = guild
        self.ext = ext
        self.tmp_path = tmp_path

    @property
    def gid(self) -> int:
        return self.guild.id

    def connect_bot(self, channel_id: int = BOT_CHANNEL) -> FakeVC:
        ch = self.guild.channel(channel_id)
        vc = FakeVC(ch, self.guild)
        self.guild.voice_client = vc
        return vc

    def queue(self) -> List[dict]:
        return self.svc._get_pm(self.gid).get_queue()

    def urls(self) -> List[str]:
        return [it.get("url") for it in self.queue()]

    def seed_queue(self, items: List[dict]):
        pm = self.svc._get_pm(self.gid)
        for it in items:
            pm.add(dict(it))

    async def wait_for(self, cond: Callable[[], bool], timeout: float = 3.0, msg: str = ""):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"condition non atteinte en {timeout}s {msg}")

    async def settle(self, delay: float = 0.05):
        """Laisse tourner les tâches de fond (play_next, retries…)."""
        await asyncio.sleep(delay)


async def loop_max_gap(coro, tick=0.02):
    """Exécute `coro` en mesurant le plus grand trou entre deux ticks de la boucle."""
    gaps = []
    stop = asyncio.Event()

    async def heartbeat():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(tick)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    hb = asyncio.create_task(heartbeat())
    while not gaps:  # le battement doit tourner AVANT d'appeler la coroutine mesurée
        await asyncio.sleep(tick)
    try:
        result = await coro
    finally:
        stop.set()
        await hb
    return result, max(gaps) if gaps else 0.0


@pytest_asyncio.fixture
async def harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLAYLIST_DIR", str(tmp_path / "playlists"))
    for var in ("GREG_OWNER_ID", "PLAYLIST_EXPAND_LIMIT", "QUEUE_PER_USER_CAP",
                "PRIORITY_ROLE_WEIGHTS", "PRIORITY_THRESHOLD"):
        monkeypatch.delenv(var, raising=False)

    import greg_shared.priority as prio
    monkeypatch.setattr(prio, "_overrides", {"weights": {}, "cap": None})
    monkeypatch.setattr(prio, "_initialized", True)

    import bot.services.player_service as ps
    ext = FakeExtractor(ps)
    monkeypatch.setattr(ps, "get_extractor", lambda url: ext)
    monkeypatch.setattr(ps, "normalize_link", fake_normalize_link)
    monkeypatch.setattr(ps, "is_url", fake_is_url)
    monkeypatch.setattr(ps, "is_spotify_url", fake_is_spotify_url)
    monkeypatch.setattr(ps, "is_bundle_url", fake_is_bundle_url)
    monkeypatch.setattr(ps, "expand_bundle", ext.expand_bundle)
    monkeypatch.setattr(ps, "yt_search", ext.search)
    # Délais raccourcis pour les tests
    monkeypatch.setattr(ps, "_RECONNECT_WAIT", 0.02)
    monkeypatch.setattr(ps, "_BACKOFF_MAX", 0.1)
    monkeypatch.setattr(ps, "_VOICE_RECONNECT_WAIT", 0.3, raising=False)

    loop = asyncio.get_running_loop()
    guild = FakeGuild(GID)
    bot = FakeBot(loop, guild)
    svc = ps.PlayerService(bot)
    bot.player_service = svc
    h = Harness(ps, svc, bot, guild, ext, tmp_path)
    yield h
    # Arrêt propre des lectures « en cours » (threads daemon) et des tâches de fond.
    vc = guild.voice_client
    if vc is not None:
        vc.connected = False
        vc.stop()
    for t in list(getattr(svc, "_bg_tasks", ())):
        t.cancel()
    for t in list(getattr(svc, "_progress_task", {}).values()):
        t.cancel()
    await asyncio.sleep(0.05)
