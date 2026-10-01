# Synchro du son Discord et de la vidéo du site : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** la vidéo YouTube muette du site reste à ±60 à 80 ms du son que le Roi entend dans Discord. Le bot publie la position réellement lue, l'API l'horodate sur sa propre horloge, et le site s'y cale en vitesse plutôt que par sauts.

**Architecture:** un contrat additif (spec §3), porté par trois chaînes indépendantes, une par service.
- **Bot (B1 à B4).** `CountingSource` enveloppe la source ffmpeg et compte les trames que discord.py lit vraiment. Une trame est lue d'avance avant `vc.play`. `get_state` et les ticks portent un bloc `clock` (`play_id`, `status`, `position_ms`, `sampled_at_ms`). Le ticker échantillonne à 4 Hz pour voir les blocages.
- **API (A1 à A3).** `relay_at_ms` est posé sur chaque état et chaque tick (Redis et réponses RPC), et `clock` passe dans le tick reconstruit. L'événement socket `time_sync` répond par un accusé `{t0, ts}`.
- **Site (W1 à W6).** Trois modules purs : `timesync`, `refclock` et `controller`. Ils sont branchés dans `socket.ts` et `usePlayer.ts` (le store reçoit `clock`, et la barre lit `refclock`), puis dans `Portal.tsx` : régulateur à 4 Hz et démarrage gardé. Enfin, « Synchro vidéo » passe au pas de 50 ms.

**Tech Stack:**
- Bot : discord.py 2.7.1, asyncio, pytest et pytest-asyncio.
- API : Flask-SocketIO en mode threading, redis-py.
- Site : Next.js 14.2, React 18, TypeScript 5, zustand 4 et `node:test`.
- Socket : socket.io-client 4.8.4, avec `socket.timeout(ms).emit(ev, data, (err, res) => …)` (vérifié sur Context7).
- Vidéo : API IFrame YouTube (`setPlaybackRate`, `getPlaybackRate`).

**Spec:** `docs/superpowers/specs/2026-10-01-synchro-son-video-design.md` : §3 contrat, §4 bot, §5 API, §6 site, §7 tests. La carte du code et les mesures sont dans `S\sync-understand.json`.

## Global Constraints

- **Contrat** (spec §3). Utiliser exactement ces noms partout :
  - `clock.play_id` : 8 caractères hexadécimaux, ou `null` ;
  - `clock.status` : `idle | loading | playing | paused | stalled` ;
  - `clock.position_ms` : float, ou `null` en `idle` / `loading` ;
  - `clock.sampled_at_ms` : entier, horloge murale du bot en ms epoch ;
  - `relay_at_ms` : entier, horloge murale de l'API en ms epoch, posé à côté de `clock` ;
  - l'événement socket `time_sync` : requête `{t0}`, accusé `{t0, ts}`.
- **Additif.**
  - `position` et `progress.elapsed` restent publiés en secondes entières : ils valent `int(position_ms / 1000)`.
  - Le site fonctionne sans `clock` : c'est le mode compatibilité.
  - Les anciens champs du tick ne changent pas.
- **Chaînes.** B ne touche que `services/bot`, A que `services/api`, W que `services/web`. `packages/shared` n'est pas modifié (décision 1). Les trois chaînes tournent en parallèle ; dans une chaîne, les tâches suivent l'ordre.
- **Git : règles dures.**
  - **Aucune signature d'assistant** : ni trailer `Co-Authored-By`, ni ligne « Generated with … », ni mention de l'outil, que ce soit dans les messages, les commentaires ou la doc.
  - Messages de commit en français, au style du dépôt (`feat(bot): …`, `test(api): …`).
  - Jamais commités : `services/web/tsconfig.json`, `services/web/next-env.d.ts`, `.claude/`, `.serena/`, `.playwright-mcp/`, `CHANGELOG.md`, `assets.zip`, `services/GREG.zip`.
  - Jamais de `git stash`, `reset`, `rebase`, `push --force`, ni de `checkout` d'une autre branche. Pas de push.
  - D'autres agents travaillent dans le **même arbre**. Faire `git add <nouveaux fichiers>`, puis `git commit -m "…" -- <chaque fichier créé ou modifié>`. Sur un `index.lock`, attendre quelques secondes puis réessayer.
- **Commandes.** Git Bash, depuis la racine du dépôt.
  - `PYBOT` = `"C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad\venv-bot\Scripts\python.exe"`.
  - `PYAPI` = le même chemin avec `venv-api` à la place de `venv-bot`.
  - Dans les étapes, `PYBOT` et `PYAPI` désignent ces chemins **écrits en entier, entre guillemets** : l'état du shell ne persiste pas d'un appel à l'autre.
  - Tests du site : `cd services/web && npm test`, puis `GREG_TEST_TRANSPILE=1 npm test` (le Node 20 de l'image Docker), puis `npx tsc --noEmit`.
  - Aucun serveur de développement. `next build` est lancé par l'orchestrateur seulement, une fois, à la fin.
- **Compteurs.**
  - Bases : bot 197, API 372, site 368.
  - Chaque tâche annonce son ajout (« +N ») : vérifier « avant + N ». D'autres agents peuvent ajouter leurs propres tests.
- **Fins de ligne.** `core.autocrlf=true`, et Git normalise en LF au commit. Garder la fin de ligne de chaque fichier. Sont en CRLF dans l'arbre :
  - `services/web/src/lib/types.ts` ;
  - `services/web/src/lib/playerUtils.ts` ;
  - `services/web/tests/playerUtils.test.mjs` (mixte) ;
  - `services/api/api/services/redis_listener.py`.
- **Modules purs du site.**
  - Aucun import à l'exécution (`import type` seulement).
  - TypeScript effaçable : ni `enum`, ni `namespace`.
  - Les tests doivent passer en natif (Node 24) et en transpilation.
- **Textes.**
  - Français ; Greg vouvoie le Roi.
  - Le deck `copy.v2.json` ne s'édite pas à la main : tout nouveau texte va dans `copy.extra.ts`.
  - Typographie : U+00A0 avant « : », U+202F avant ; ! ?, apostrophe courbe.
- **Style et TDD.**
  - Commentaires en français, brefs, comme le code autour.
  - Test d'abord ; le voir échouer ; implémenter ; le voir passer ; commit.
- **Prototype.** Le code et les tests de ce plan ont été prototypés sur une copie du dépôt (`S\syncplan`).
  - Bot : 219 passés, stables sur 5 passes.
  - API : 392 passés.
  - Site : 399 passés en natif et en transpilation, `tsc` sans erreur.

## Décisions et précisions (spec → code)

1. **Enveloppe dans `PlayerService.play_next`**, juste après `stream` ou `stream_pipe`. Ce seul point couvre les deux créations de source, directe (`youtube.py:1099`) et pipe (`youtube.py:1381`). Le mode se lit sur `_ytdlp_proc` : non `None` veut dire pipe. `packages/shared` ne change pas, et l'intro n'est pas enveloppée.
2. **`source[gid]` de la spec** est le `current_source[gid]` existant, qui contient désormais le `CountingSource`.
3. **`play_id`** vaut `null` pendant la fenêtre de chargement. Un nouveau `secrets.token_hex(4)` est tiré juste avant chaque `vc.play`.
4. **Fenêtre de chargement.** Un état complet part dès le choix du titre : nouveau `current`, `loading`, position `null`. Avant, rien ne partait avant `vc.play`.
5. **Ticker.** Il échantillonne toutes les 0,25 s (un blocage est vu en 0,5 s au plus) et publie toutes les 1 s, comme avant.
6. **`note_resume()` avant `vc.resume()`.** Sinon, la première lecture après une pause passerait pour la fin d'un blocage.
7. **API.**
   - `relay_at_ms` est posé dans l'objet état, à côté de `clock`. En REST, il va dans `state`, ou à la racine s'il n'y a pas de `state`.
   - Il est aussi posé sur l'état envoyé à l'abonnement socket (`_subscribe`, réponse RPC).
   - Le `ts` de `time_sync` est un float, en ms.
8. **Store `clock: ClockView = {playId, status, compat, url}`.** Les états complets associent l'URL du titre au `play_id`. Le démarrage gardé compare la vidéo de cette URL à `videoId` : le saut optimiste montre le nouveau titre alors que le bot joue encore l'ancien.
9. **Barre et minutages.**
   - `withClock` pose l'ancre de l'instantané sur la lecture de `refclock`.
   - `TickBase.frozen` fige l'horloge hors lecture.
   - `crown` pose `{pos: 0, frozen: true}` : plus de position qui court dès le clic.
10. **Blocage.** La vidéo se met en pause (`still = paused || status === 'stalled'`), repart avec le son, puis attend 3 s.
11. **Régulateur.**
    - Pendant l'attente, vitesse ×1 et aucun saut.
    - Ancien bot (mode compat) : sauts seuls à 1,2 s, 15 s entre deux sauts (l'ancien régime).
    - `LOAD_COMP_S` est gardé : la spec ne remplace que `DRIFT_*` et `SEEK_COMP_S`, et l'alignement qui en dépendait.
12. **`time_sync`.** Les mesures sont oubliées à chaque connexion (ce peut être une autre instance de l'API). Avant la première mesure, `serverNow` vaut `performance.timeOrigin + now`.

## File Structure

| Fichier | Tâches | Rôle |
|---|---|---|
| `services/bot/bot/services/audio_clock.py` *(créé)* | B1 | `CountingSource` : comptage, pré-lecture, callbacks thread-safe, délégation |
| `services/bot/tests/test_audio_clock.py` *(créé)* | B1 | unitaires + vrai `discord.player.AudioPlayer` |
| `services/bot/bot/services/player_service.py` | B2, B3, B4 | enveloppe et pré-lecture ; `clock` et `play_id` ; ticker |
| `services/bot/tests/core_fakes.py` | B2, B4 | `FakeSource.read()` ; `FakeBridge.ticks` |
| `services/bot/tests/test_sync_clock.py` *(créé en B2)* | B2, B3, B4 | PlayerService côté synchro |
| `services/bot/bot/services/redis_bridge.py`, `services/bot/tests/test_redis_bridge.py` | B4 | `publish_progress(..., clock=)` |
| `services/api/api/services/relay_clock.py` *(créé)* | A1 | `now_ms()`, `with_relay_at()` |
| `services/api/api/services/redis_listener.py` | A1 | horodatage des deux canaux, `clock` dans le tick |
| `services/api/tests/test_sync_relay.py` *(créé en A1)* | A1, A2, A3 | tests de la synchro côté API |
| `services/api/tests/test_socketio.py` | A1, A2 | `_strip` (relay_at_ms présent et entier) |
| `services/api/api/routes/player.py` | A2 | REST horodaté |
| `services/api/api/websocket/events.py` | A2, A3 | abonnement horodaté ; `time_sync` |
| `services/web/src/lib/sync/timesync.ts` *(créé)* + `tests/timesync.test.mjs` | W1 | mesure d'horloge |
| `services/web/src/lib/sync/refclock.ts` *(créé)* + `tests/refclock.test.mjs` | W2 | horloge de référence, mode compatibilité, `ClockView` |
| `services/web/src/lib/sync/controller.ts` *(créé)* + `tests/controller.test.mjs` | W3 | `decide`, attente, repli, `gateLoad` |
| `services/web/src/lib/sync/live.ts` *(créé)* | W4 | instances `timeSync`, `refClock`, `serverNow` |
| `src/lib/types.ts`, `src/lib/playerUtils.ts`, `src/lib/queue/optimistic.ts`, `src/lib/socket.ts`, `src/hooks/usePlayer.ts` | W4 | `frozen`, `withClock`, `time_sync`, store `clock` |
| `tests/playerUtils.test.mjs`, `tests/optimistic.test.mjs`, `tests/player-contract.test.mjs` | W4 | |
| `src/hooks/useYouTubePlayer.ts`, `src/components/Stage/Portal.tsx`, `tests/stage-motion.test.mjs` | W5 | régulateur à 4 Hz, démarrage gardé |
| `src/lib/stage/cover.ts`, `tests/cover.test.mjs` | W5, W6 | anciens seuils retirés ; pas de 50 ms |
| `src/hooks/useVideoOffset.ts`, `src/components/Stage/SyncOffset.tsx`, `src/theme/copy.extra.ts`, `tests/copy-extra.test.mjs` | W6 | « Synchro vidéo » |

Les chemins `src/` et `tests/` du site sont relatifs à `services/web/`.

---

# Chaîne bot

### Task B1 : `CountingSource`, l'horloge des trames réellement lues

**Files:**
- Create: `services/bot/bot/services/audio_clock.py`
- Test: `services/bot/tests/test_audio_clock.py`

**Interfaces:**
- Consumes: `discord.AudioSource`, `discord.player.AudioPlayer` (discord.py 2.7.1).
- Produces (`bot.services.audio_clock`, signatures exactes à l'étape 3) :
  - `FRAME_MS`, `STALL_S` ;
  - `CountingSource(inner, *, loop, on_first_frame, on_resume_after_stall, clock, stall_s)`, dont les callbacks reçoivent `cb(source)` ;
  - attributs `frames`, `first_read_at`, `last_read_at`, `preroll_ms`, `mode` ;
  - méthodes `preroll() -> bool`, `read()`, `note_resume()`, `position_ms() -> float`, `is_stalled() -> bool`, `is_opus()`, `cleanup()` ;
  - délégation de tout autre attribut (`_current_error`, `_ytdlp_proc`).

- [ ] **Step 1: Écrire le test qui échoue** — créer `services/bot/tests/test_audio_clock.py` :

```python
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
```

- [ ] **Step 2: Le voir échouer**

Run: `PYBOT -m pytest services/bot/tests/test_audio_clock.py -q -p no:cacheprovider`
Expected: erreur de collecte, `ModuleNotFoundError: No module named 'bot.services.audio_clock'`.

- [ ] **Step 3: Implémenter** — créer `services/bot/bot/services/audio_clock.py` :

```python
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
```

- [ ] **Step 4: Le voir passer**

Run: `PYBOT -m pytest services/bot/tests/test_audio_clock.py -q -p no:cacheprovider` → `12 passed`.
Puis toute la suite : `PYBOT -m pytest services/bot/tests -q -p no:cacheprovider` → base + 12 (209), aucun échec.

- [ ] **Step 5: Commit**

```bash
git add services/bot/bot/services/audio_clock.py services/bot/tests/test_audio_clock.py
git commit -m "feat(bot): CountingSource, horloge des trames reellement lues par discord.py" -- services/bot/bot/services/audio_clock.py services/bot/tests/test_audio_clock.py
```

---

### Task B2 : pré-lecture avant `vc.play`, source comptée, log `[SYNC]`

**Files:**
- Modify: `services/bot/bot/services/player_service.py` (imports l.35-41 et 78 ; `__init__` l.281 ; `play_next` l.898 et 943-944 ; nouvelles méthodes avant `_handle_track_end`, l.1084)
- Modify: `services/bot/tests/core_fakes.py` (`FakeSource` l.241-253, docstring et `_make` de `FakeExtractor` l.271-308)
- Create: `services/bot/tests/test_sync_clock.py`

**Interfaces:**
- Consumes: `CountingSource` (B1) : constructeur avec `loop`, `on_first_frame`, `on_resume_after_stall` ; `preroll()`, `mode`, `preroll_ms`, `first_read_at`.
- Produces :
  - `PlayerService._chosen_at: Dict[int, float]` : instant (`time.monotonic`) du choix du titre.
  - `PlayerService._on_first_frame(gid: int, src: CountingSource) -> None` : log `[SYNC]` et `self._emit(gid)`.
  - `PlayerService._on_stall_end(gid: int, src: CountingSource) -> None` : `self._emit(gid)`.
  - Les deux handlers ne font rien si `src` n'est plus `current_source[gid]`.
  - Toute source musicale passée à `vc.play` est un `CountingSource` déjà pré-lu, rangé dans `current_source[gid]`.
  - Dans `core_fakes`, `FakeSource` reçoit `read()`, `is_opus()`, `reads`, `frames_left` et `read_delay`. `FakeExtractor` comprend les comportements `"no_audio"` et `"read_delay"`.

- [ ] **Step 1: Faux objets et tests qui échouent**

Dans `services/bot/tests/core_fakes.py`, remplacer la classe `FakeSource` (l.241-253) par :

```python
FRAME = b"\x00" * 3840  # une trame PCM de 20 ms (48 kHz stéréo s16le)


class FakeSource:
    """Source ffmpeg factice. `frames` : trames disponibles (None = infini, 0 = ffmpeg ne produit rien) ;
    `read_delay` : chaque read() bloque ce temps (premier octet lent, mode pipe)."""

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
        if self.read_delay:
            time.sleep(self.read_delay)
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
```

Toujours dans `core_fakes.py`, faire deux remplacements dans `FakeExtractor`.

La docstring (l.271-272) :

```python
    """Extracteur piloté par URL :
    {"fail", "unavailable", "pipe_tried", "delay", "die_after", "cleanup_delay", "title",
     "no_audio" (ffmpeg ne produit aucune trame), "read_delay" (chaque trame lente)}."""
```

Et, dans `_make`, la ligne `src = FakeSource(url, b.get("die_after", self.default_die_after), b.get("cleanup_delay", 0.0))` :

```python
        src = FakeSource(url, b.get("die_after", self.default_die_after), b.get("cleanup_delay", 0.0),
                         frames=0 if b.get("no_audio") else None, read_delay=b.get("read_delay", 0.0))
```

Créer `services/bot/tests/test_sync_clock.py` :

```python
"""Synchro son/vidéo côté bot (spec §4.2) : source comptée, pré-lecture, log [SYNC], bloc clock, ticker."""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from bot.services.audio_clock import CountingSource
from core_fakes import harness, yt_entry  # noqa: F401  (fixture importée)

pytestmark = pytest.mark.asyncio

A = yt_entry(1, title="A")
B = yt_entry(2, title="B")


def _plays(vc, url):
    return sum(1 for s in vc.play_calls if s.url == url)


async def _playing(h, vc, url, n=1):
    await h.wait_for(lambda: _plays(vc, url) >= n, timeout=3, msg=f"{url} jamais joué")
    return [s for s in vc.play_calls if s.url == url][n - 1]


# ─────────────────────────── Pré-lecture (B2) ───────────────────────────


async def test_music_source_is_counted_and_primed_before_vc_play(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"read_delay": 0.2}  # 1er octet lent (mode pipe, yt-dlp qui démarre)
    h.seed_queue([A])
    t0 = time.monotonic()
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    assert isinstance(src, CountingSource)
    assert src.url == A["url"] and src.mode == "direct"
    assert h.ext.sources[0].reads == 1, "une trame lue d'avance, avant vc.play"
    assert src.frames == 0, "pas encore envoyée"
    assert h.svc.play_start[h.gid] - t0 >= 0.2, "play_start posé APRÈS la pré-lecture"


async def test_stream_without_audio_never_reaches_vc_play(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"no_audio": True}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    await _playing(h, vc, B["url"])
    assert _plays(vc, A["url"]) == 0
    a_calls = [c for c in h.ext.calls if c[1] == A["url"] and c[0] == "stream"]
    assert len(a_calls) == h.ps._MAX_FAILURES_PER_TRACK, "même politique d'abandon qu'un extracteur KO"
    assert all(s.cleaned for s in h.ext.sources if s.url == A["url"])
    assert A["url"] not in h.urls()


async def test_skip_during_preroll_drops_the_source(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[A["url"]] = {"read_delay": 0.3}
    h.seed_queue([A, B])
    task = asyncio.create_task(h.svc.play_next(h.guild))
    await h.wait_for(lambda: h.ext.sources and h.ext.sources[0].url == A["url"], msg="A pas extrait")
    await h.svc.skip(h.gid)
    await task
    await _playing(h, vc, B["url"])
    assert _plays(vc, A["url"]) == 0
    await h.wait_for(lambda: h.ext.sources[0].cleaned, msg="source de A jamais nettoyée")


async def test_first_frame_logs_sync_and_emits(harness, caplog):
    caplog.set_level(logging.INFO, logger="greg.player")
    h = harness
    vc = h.connect_bot()
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    before = len(h.bot.emits)
    src.read()  # le thread audio de discord.py envoie la 1re trame
    await h.wait_for(lambda: len(h.bot.emits) > before, msg="pas d'état à la 1re trame")
    sync = [r.getMessage() for r in caplog.records if "[SYNC]" in r.getMessage()]
    assert len(sync) == 1 and "mode=direct" in sync[0], sync
```

- [ ] **Step 2: Les voir échouer**

Run: `PYBOT -m pytest services/bot/tests/test_sync_clock.py -q -p no:cacheprovider`
Expected : `4 failed`.
- `assert isinstance(src, CountingSource)` échoue.
- `_plays(vc, A["url"]) == 0` échoue, puisque A est joué sans pré-lecture.
- Aucun `[SYNC]` n'est journalisé.

Le reste de la suite reste vert : les faux objets gardent leur comportement par défaut.

- [ ] **Step 3: Implémenter** dans `services/bot/bot/services/player_service.py`

Faire les modifications suivantes, dans l'ordre :

1. **Imports.** Ajouter `import functools` après `import asyncio`, et `import math` après `import logging`. Puis, juste avant `from bot.services.ffmpeg import detect_ffmpeg` :

```python
from bot.services.audio_clock import CountingSource
```

2. **`__init__`.** Après `self.current_source: Dict[int, Any] = {}` :

```python
        # Synchro son/vidéo : instant du choix du titre (log [SYNC] : délai jusqu'à la 1re trame).
        self._chosen_at: Dict[int, float] = {}
```

3. **`play_next`, choix du titre.** Après `self.current_meta[gid] = {"duration": dur, "thumbnail": item.get("thumb")}` :

```python
            self._chosen_at[gid] = time.monotonic()
```

4. **`play_next`, avant la lecture.** Remplacer les deux lignes

```python
            if srcp is not None:
                if title and isinstance(title, str):
```

par :

```python
            if srcp is not None:
                # Horloge audio (spec synchro §4.2) : trames réellement lues ; une trame lue d'avance, AVANT
                # vc.play, pour que play_start et la 1re trame coïncident (plus d'avance en mode pipe).
                srcp = CountingSource(
                    srcp, loop=loop,
                    on_first_frame=functools.partial(self._on_first_frame, gid),
                    on_resume_after_stall=functools.partial(self._on_stall_end, gid),
                )
                pre_err: Optional[Exception] = None
                try:
                    primed = await asyncio.to_thread(srcp.preroll)
                except Exception as e:
                    primed, pre_err = False, e
                if self._is_stale(gid, gen):
                    # stop/skip/play_at/restart pendant la pré-lecture : même abandon que pendant l'extraction.
                    _cleanup_source_off_loop(srcp)
                    logger.info("[Chargement annulé] guild=%s url=%s", gid, url)
                    self._spawn(self.play_next(guild))
                    return
                if not primed:
                    # ffmpeg n'a produit aucune trame (b'') : échec de démarrage, même politique qu'un extracteur KO.
                    logger.warning("[pré-lecture KO] guild=%s url=%s: %s", gid, url, pre_err or "aucune trame")
                    _cleanup_source_off_loop(srcp)
                    srcp = None
                    last_err = pre_err or RuntimeError("ffmpeg n'a produit aucune trame")

            if srcp is not None:
                if title and isinstance(title, str):
```

La suite ne change pas : le bloc `try: await self._play_source(...)` reçoit le `CountingSource`. `srcp = None` fait tomber dans le chemin d'échec existant de l'extracteur : compteur `_track_failures`, abandon au bout de `_MAX_FAILURES_PER_TRACK`, sinon remise en tête et attente.

5. **Nouvelles méthodes.** Les placer juste avant `async def _handle_track_end(` :

```python
    def _on_first_frame(self, gid: int, src: CountingSource) -> None:
        """1re trame lue par discord.py (sur la boucle, via call_soon_threadsafe) : log [SYNC] et état tout de suite."""
        if self.current_source.get(gid) is not src:
            return
        chosen = self._chosen_at.get(gid)
        g = self.bot.get_guild(gid)
        lat = getattr(g.voice_client if g else None, "average_latency", None)
        logger.info(
            "[SYNC] guild=%s mode=%s choix_1re_trame_ms=%s prelecture_ms=%.0f latence_vocale_ms=%s",
            gid, src.mode,
            f"{(src.first_read_at - chosen) * 1000:.0f}" if chosen and src.first_read_at else "?",
            src.preroll_ms or 0.0,
            f"{lat * 1000:.0f}" if isinstance(lat, (int, float)) and math.isfinite(lat) else "?",
        )
        self._emit(gid)

    def _on_stall_end(self, gid: int, src: CountingSource) -> None:
        """Le flux repart après un blocage (sur la boucle, via call_soon_threadsafe) : état complet tout de suite."""
        if self.current_source.get(gid) is src:
            self._emit(gid)
```

- [ ] **Step 4: Les voir passer**

Run: `PYBOT -m pytest services/bot/tests -q -p no:cacheprovider` → base + 4 (213), aucun échec. Les tests existants (échecs, coupures, retries, `_plays`) passent sans changement : l'enveloppe délègue `url`, `die_after` et `cleanup`.

- [ ] **Step 5: Commit**

```bash
git add services/bot/tests/test_sync_clock.py
git commit -m "feat(bot): pre-lecture avant vc.play, source comptee et log [SYNC] par titre" -- services/bot/bot/services/player_service.py services/bot/tests/core_fakes.py services/bot/tests/test_sync_clock.py
```

---

### Task B3 : bloc `clock` dans l'état, `play_id`, fenêtre de chargement

**Files:**
- Modify: `services/bot/bot/services/player_service.py`
  - imports ;
  - `__init__` ;
  - `_clear_now_playing` (l.393-398) ;
  - `get_state` (l.538-606) ;
  - `play_next`, juste après le `_chosen_at` de B2 ;
  - `_play_source` (l.1063-1064) ;
  - `resume` (l.1235-1236).
- Test: `services/bot/tests/test_sync_clock.py` (ajout)

**Interfaces:**
- Consumes: `CountingSource.frames`, `.position_ms()`, `.is_stalled()`, `.note_resume()` (B1) ; `current_source[gid]` contient le `CountingSource` (B2).
- Produces :
  - `PlayerService.play_id: Dict[int, str]`.
  - `PlayerService._clock(gid: int, vc) -> dict` rend `{"play_id": Optional[str], "status": str, "position_ms": Optional[float], "sampled_at_ms": int}`.
  - `get_state(gid)["clock"]` porte ce bloc. `position` et `progress.elapsed` valent `int(position_ms // 1000)`, ou 0.
  - Un état complet est émis dès le choix d'un titre.

- [ ] **Step 1: Tests qui échouent** — ajouter à la fin de `services/bot/tests/test_sync_clock.py` :

```python


# ─────────────────────────── Bloc clock de get_state (B3) ───────────────────────────


def _clock(h):
    st = h.svc.get_state(h.gid)
    return st, st["clock"]


async def test_clock_status_follows_the_audio(harness):
    """loading → playing → paused → playing → stalled → playing (spec §7)."""
    h = harness
    vc = h.connect_bot()
    st, c = _clock(h)
    assert c["status"] == "idle" and c["play_id"] is None and c["position_ms"] is None
    h.ext.behaviour[A["url"]] = {"delay": 0.3}
    h.seed_queue([A])
    task = asyncio.create_task(h.svc.play_next(h.guild))
    await h.wait_for(lambda: h.ext.calls, msg="extraction jamais lancée")
    st, c = _clock(h)
    assert st["current"]["url"] == A["url"]
    assert (c["status"], c["position_ms"], st["position"], st["progress"]["elapsed"]) == ("loading", None, 0, 0)
    await task
    src = await _playing(h, vc, A["url"])
    st, c = _clock(h)
    assert c["status"] == "loading", "vc.play fait, aucune trame envoyée"
    assert isinstance(c["play_id"], str) and len(c["play_id"]) == 8
    int(c["play_id"], 16)
    for _ in range(60):
        src.read()  # 60 trames : 1,2 s
    st, c = _clock(h)
    assert (c["status"], c["position_ms"], st["position"], st["progress"]["elapsed"]) == ("playing", 1200.0, 1, 1)
    assert abs(c["sampled_at_ms"] - time.time() * 1000) < 1000
    assert await h.svc.pause(h.gid)
    await asyncio.sleep(0.3)  # pause plus longue que le seuil de blocage
    st, c = _clock(h)
    assert (c["status"], c["position_ms"]) == ("paused", 1200.0)
    assert await h.svc.resume(h.gid)
    assert _clock(h)[1]["status"] == "playing", "la pause n'est pas un blocage"
    src.last_read_at -= 1.0  # plus rien lu depuis 1 s : flux bloqué
    assert _clock(h)[1]["status"] == "stalled"
    src.read()
    st, c = _clock(h)
    assert (c["status"], c["position_ms"]) == ("playing", 1220.0)


async def test_play_id_changes_on_restart(harness):
    h = harness
    vc = h.connect_bot()
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    first = await _playing(h, vc, A["url"])
    first.read()
    pid = _clock(h)[1]["play_id"]
    assert await h.svc.restart(h.gid)
    again = await _playing(h, vc, A["url"], n=2)
    again.read()
    c = _clock(h)[1]
    assert c["status"] == "playing" and c["play_id"] != pid
    assert c["position_ms"] == 20.0, "repart de zéro"


async def test_loading_window_does_not_inherit_the_previous_position(harness):
    h = harness
    vc = h.connect_bot()
    h.ext.behaviour[B["url"]] = {"delay": 0.5}
    h.seed_queue([A, B])
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    for _ in range(150):
        src.read()  # 3 s de A
    assert h.svc.get_state(h.gid)["position"] == 3
    emits = len(h.bot.emits)
    await h.svc.skip(h.gid)
    await h.wait_for(lambda: (h.svc.now_playing.get(h.gid) or {}).get("url") == B["url"], msg="B jamais choisi")
    st, c = _clock(h)
    assert st["current"]["url"] == B["url"]
    assert (c["status"], c["play_id"], c["position_ms"], st["position"]) == ("loading", None, None, 0)
    assert len(h.bot.emits) > emits, "l'état « loading » part tout de suite"
```

- [ ] **Step 2: Les voir échouer**

Run: `PYBOT -m pytest services/bot/tests/test_sync_clock.py -q -p no:cacheprovider`
Expected : les 3 nouveaux tests échouent.
- Les deux premiers échouent sur `KeyError: 'clock'`.
- Le troisième échoue dès `position == 3` : sans B3, la position vient encore de `play_start`.

- [ ] **Step 3: Implémenter** dans `player_service.py`

1. **Import.** Ajouter `import secrets` après `import re`.

2. **`__init__`.** Après le `self._chosen_at` de B2 :

```python
        # play_id : 8 hex, nouveau à chaque vc.play (titre, « Depuis le début », boucle, reprise après coupure).
        self.play_id: Dict[int, str] = {}
```

3. **`_clear_now_playing`.** Le tuple devient :

```python
        for d in (self.current_song, self.play_start, self.paused_since,
                  self.paused_total, self.current_meta, self.now_playing, self.play_id):
```

4. **`get_state`.** Remplacer le début de la méthode, de `def get_state` jusqu'au bloc `elapsed = 0 / if start: …` inclus (l.538-551) :

```python
    def _clock(self, gid: int, vc) -> dict:
        """Bloc `clock` (spec synchro §3) : position réellement lue par discord.py, horodatée (epoch ms du bot)."""
        sampled_at_ms = int(time.time() * 1000)
        pid = self.play_id.get(gid)
        src = self.current_source.get(gid)
        pos: Optional[float] = None
        if not (self.now_playing.get(gid) or self.current_song.get(gid)):
            status = "idle"
        elif pid is None or not isinstance(src, CountingSource) or src.frames == 0:
            status = "loading"   # titre choisi, aucune trame encore envoyée
        else:
            pos = src.position_ms()
            if vc is not None and vc.is_paused():
                status = "paused"
            elif src.is_stalled():
                status = "stalled"
            else:
                status = "playing"
        return {"play_id": pid, "status": status, "position_ms": pos, "sampled_at_ms": sampled_at_ms}

    def get_state(self, guild_id: int) -> dict:
        gid = int(guild_id)
        g = self.bot.get_guild(gid)
        vc = g.voice_client if g else None
        is_paused = bool(vc and vc.is_paused())

        clock = self._clock(gid, vc)
        elapsed = int(clock["position_ms"] // 1000) if clock["position_ms"] else 0
```

Dans le `return` final de `get_state`, ajouter après `"queue_users": queue_users,` :

```python
            "clock": clock,
```

5. **`play_next`, fenêtre de chargement.** Juste après la ligne `self._chosen_at[gid] = time.monotonic()` de B2 :

```python
            # Fenêtre de chargement : clock « loading », plus aucune position héritée du titre précédent.
            self.play_id.pop(gid, None)
            self.play_start.pop(gid, None)
            self.paused_since.pop(gid, None)
            self.paused_total[gid] = 0.0
            self._emit(gid)
```

6. **`_play_source`.** Remplacer

```python
        # play_start AVANT vc.play : un _after immédiat ne doit pas lire l'ancien départ.
        self.play_start[gid] = time.monotonic()
```

par :

```python
        # play_start AVANT vc.play : un _after immédiat ne doit pas lire l'ancien départ.
        # (Après la pré-lecture de play_next : il coïncide avec la 1re trame.)
        self.play_id[gid] = secrets.token_hex(4)
        self.play_start[gid] = time.monotonic()
```

7. **`resume`.** Remplacer

```python
        if vc and vc.is_paused():
            vc.resume()
```

par :

```python
        if vc and vc.is_paused():
            src = self.current_source.get(gid)
            if isinstance(src, CountingSource):
                src.note_resume()  # AVANT vc.resume : le thread audio relit aussitôt, la pause n'est pas un blocage
            vc.resume()
```

`play_start`, `paused_since` et `paused_total` restent : `_after` les utilise pour décider d'une relance après coupure.

- [ ] **Step 4: Les voir passer**

Run: `PYBOT -m pytest services/bot/tests -q -p no:cacheprovider` → base + 3 (216), aucun échec.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(bot): bloc clock dans l'etat (play_id, statut, position_ms) et fenetre de chargement" -- services/bot/bot/services/player_service.py services/bot/tests/test_sync_clock.py
```

---

### Task B4 : ticker à 4 Hz, blocages publiés tout de suite, `clock` dans les ticks

**Files:**
- Modify: `services/bot/bot/services/player_service.py` (constantes après `_YT_ID_RE` l.133 ; `_ensure_ticker._run` l.1615-1641)
- Modify: `services/bot/bot/services/redis_bridge.py` (`publish_progress`, l.501-508)
- Modify: `services/bot/tests/core_fakes.py` (`FakeBridge`, l.177-182)
- Test: `services/bot/tests/test_sync_clock.py` (ajout), `services/bot/tests/test_redis_bridge.py` (ajout)

**Interfaces:**
- Consumes: `PlayerService._clock(gid, vc)` (B3) et `_on_stall_end` (B2).
- Produces :
  - Constantes de module `_TICK_S = 0.25` et `_PROGRESS_EVERY_S = 1.0`.
  - `RedisBridge.publish_progress(guild_id, position, duration, paused, clock: Optional[dict] = None)`. Le payload Redis garde `{guild_id, position, duration, paused}` et gagne `"clock"` s'il est fourni.
  - `FakeBridge.ticks: List[tuple]`, la liste des `(args, kwargs)`.

- [ ] **Step 1: Tests qui échouent**

Dans `core_fakes.py`, remplacer `FakeBridge` par :

```python
class FakeBridge:
    def __init__(self):
        self.progress = 0
        self.ticks: List[tuple] = []  # (args, kwargs) de chaque publish_progress

    async def publish_progress(self, *a, **k):
        self.progress += 1
        self.ticks.append((a, k))
```

Ajouter à la fin de `test_sync_clock.py` :

```python


# ─────────────────────────── Ticker et envois immédiats (B4) ───────────────────────────


@pytest.fixture
def fast_ticker(harness, monkeypatch):
    monkeypatch.setattr(harness.ps, "_TICK_S", 0.02)
    monkeypatch.setattr(harness.ps, "_PROGRESS_EVERY_S", 0.05)
    return harness


async def test_ticker_publishes_the_clock_with_integer_positions(fast_ticker):
    h = fast_ticker
    vc = h.connect_bot()
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    for _ in range(75):
        src.read()  # 1,5 s
    n = len(h.bot.redis_bridge.ticks)
    await h.wait_for(lambda: len(h.bot.redis_bridge.ticks) > n, msg="aucun tick")
    (gid, position, duration, paused), kw = h.bot.redis_bridge.ticks[-1]
    assert (gid, position, duration, paused) == (h.gid, 1, 180, False)
    c = kw["clock"]
    assert (c["status"], c["position_ms"], c["play_id"]) == ("playing", 1500.0, h.svc.play_id[h.gid])


async def test_stall_start_and_end_are_pushed_at_once(fast_ticker):
    h = fast_ticker
    vc = h.connect_bot()
    h.seed_queue([A])
    await h.svc.play_next(h.guild)
    src = await _playing(h, vc, A["url"])
    src.read()
    await h.settle(0.1)
    emits = len(h.bot.emits)
    src.last_read_at -= 1.0  # ffmpeg ne rend plus rien
    await h.wait_for(lambda: len(h.bot.emits) > emits, msg="début du blocage non publié")
    assert h.svc.get_state(h.gid)["clock"]["status"] == "stalled"
    emits = len(h.bot.emits)
    src.read()  # le flux repart
    await h.wait_for(lambda: len(h.bot.emits) > emits, msg="fin du blocage non publiée")
    assert h.svc.get_state(h.gid)["clock"]["status"] == "playing"
```

Ajouter à la fin de `services/bot/tests/test_redis_bridge.py` :

```python


# ─────────────────────────── Synchro son/vidéo : tick + clock ───────────────────────────


async def test_publish_progress_carries_the_clock_and_keeps_its_fields(bridge):
    clock = {"play_id": "a1b2c3d4", "status": "playing", "position_ms": 83460.0, "sampled_at_ms": 1790846494123}
    await bridge.publish_progress(1, 83, 200, False, clock=clock)
    await bridge.publish_progress(1, 84, 200, True)
    (ch1, d1), (ch2, d2) = bridge.published
    assert ch1 == ch2 == rb.CHANNEL_PROGRESS
    assert d1 == {"guild_id": 1, "position": 83, "duration": 200, "paused": False, "clock": clock}
    assert d2 == {"guild_id": 1, "position": 84, "duration": 200, "paused": True}, "sans clock : payload d'avant"
```

- [ ] **Step 2: Les voir échouer**

Run: `PYBOT -m pytest services/bot/tests/test_sync_clock.py services/bot/tests/test_redis_bridge.py -q -p no:cacheprovider`
Expected : `3 failed`.
- Le test du ticker échoue sur `KeyError: 'clock'` dans les kwargs du tick.
- Le test de blocage échoue sur « début du blocage non publié ».
- Le test du pont échoue sur `TypeError: … unexpected keyword argument 'clock'`.

- [ ] **Step 3: Implémenter**

1. **Constantes** (`player_service.py`), juste après `_YT_ID_RE = re.compile(...)` :

```python

# ── Ticker de progression (synchro son/vidéo) ──
# Échantillon toutes les _TICK_S : un blocage du flux (> 250 ms sans trame) est vu vite ;
# un tick publié toutes les _PROGRESS_EVERY_S, comme avant.
_TICK_S = 0.25
_PROGRESS_EVERY_S = 1.0
```

2. **Corps de `_run`** dans `_ensure_ticker`. Remplacer tout ce qui précède `except asyncio.CancelledError:`, de `async def _run():` à `await asyncio.sleep(1.0)` inclus, par :

```python
        async def _run():
            last_pub: Optional[float] = None
            was_stalled = False
            try:
                while True:
                    g = self.bot.get_guild(gid)
                    vc = g.voice_client if g else None
                    if not vc or (not vc.is_playing() and not vc.is_paused()):
                        break

                    clock = self._clock(gid, vc)
                    stalled = clock["status"] == "stalled"
                    if stalled and not was_stalled:
                        self._emit(gid)  # début d'un blocage : le site fige sa référence tout de suite
                    was_stalled = stalled

                    now = time.monotonic()
                    if last_pub is None or now - last_pub >= _PROGRESS_EVERY_S:
                        last_pub = now
                        elapsed = int(clock["position_ms"] // 1000) if clock["position_ms"] else 0
                        meta = self.current_meta.get(gid, {})
                        dur = meta.get("duration")
                        if dur is None:
                            cs = self.current_song.get(gid, {})
                            dur = int(cs["duration"]) if isinstance(cs.get("duration"), (int, float)) else None
                        try:
                            await self.bot.redis_bridge.publish_progress(
                                gid, elapsed, dur, bool(vc.is_paused()), clock=clock,
                            )
                        except Exception:
                            pass

                    await asyncio.sleep(_TICK_S)
```

Les blocs `except asyncio.CancelledError` et `finally` qui suivent ne changent pas. La fin d'un blocage part déjà par `_on_stall_end` (B2), via `call_soon_threadsafe`.

3. **`redis_bridge.py`.** Remplacer `publish_progress` par :

```python
    async def publish_progress(self, guild_id: int, position: int, duration: Optional[int], paused: bool,
                               clock: Optional[dict] = None):
        """Publie un tick de progression (+ bloc `clock` de la synchro son/vidéo, si fourni)."""
        data = {
            "guild_id": guild_id,
            "position": position,
            "duration": duration,
            "paused": paused,
        }
        if clock is not None:
            data["clock"] = clock
        await self._publish(CHANNEL_PROGRESS, data)
```

- [ ] **Step 4: Les voir passer**

Run: `PYBOT -m pytest services/bot/tests -q -p no:cacheprovider` → base + 3 (219), aucun échec. Relancer 3 fois `PYBOT -m pytest services/bot/tests/test_sync_clock.py services/bot/tests/test_audio_clock.py -q -p no:cacheprovider` : 21 passés à chaque passe, donc pas de test instable.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(bot): ticker a 4 Hz, blocages publies tout de suite, clock dans les ticks" -- services/bot/bot/services/player_service.py services/bot/bot/services/redis_bridge.py services/bot/tests/core_fakes.py services/bot/tests/test_sync_clock.py services/bot/tests/test_redis_bridge.py
```

---

# Chaîne API

### Task A1 : `relay_at_ms` et `clock` relayés depuis Redis

**Files:**
- Create: `services/api/api/services/relay_clock.py`
- Modify: `services/api/api/services/redis_listener.py` (CRLF ; import l.17, `_handle_message` l.67-90)
- Create: `services/api/tests/test_sync_relay.py`
- Modify: `services/api/tests/test_socketio.py` (`_got_relay` l.92-94, assertion l.249)

**Interfaces:**
- Produces (module `api.services.relay_clock`) :
  - `now_ms() -> int` : horloge murale de l'API, en ms epoch.
  - `with_relay_at(state: dict, at_ms: int) -> dict` : copie de l'état avec `relay_at_ms`.
- Produces, côté socket (`playlist_update`) :
  - un état du canal state porte en plus `relay_at_ms` ;
  - un tick porte `relay_at_ms`, et `clock` quand le bot l'envoie sous forme d'objet.
- Produces (`test_socketio.py`) : `_strip(state) -> dict`, qui vérifie que `relay_at_ms` est présent et entier puis le retire.

- [ ] **Step 1: Tests qui échouent** — créer `services/api/tests/test_sync_relay.py` :

```python
"""Synchro son/vidéo côté API (spec §5) : relay_at_ms sur les états et les ticks, clock relayé, time_sync."""
from __future__ import annotations

import time

import pytest

from api import socketio
from api.services import redis_listener as rl
from api.services.relay_clock import now_ms, with_relay_at

CLOCK = {"play_id": "a1b2c3d4", "status": "playing", "position_ms": 83460.0, "sampled_at_ms": 1790846494123}


class FakeSio:
    def __init__(self):
        self.emits = []

    def emit(self, event, data, room=None):
        self.emits.append((event, data, room))


def _between(v, t0, t1):
    return isinstance(v, int) and not isinstance(v, bool) and t0 <= v <= t1


# ── A1 : relais Redis ──

def test_now_ms_is_the_api_wall_clock_in_ms():
    t0 = int(time.time() * 1000)
    assert _between(now_ms(), t0, int(time.time() * 1000))


def test_with_relay_at_returns_a_copy():
    st = {"queue": []}
    assert with_relay_at(st, 5) == {"queue": [], "relay_at_ms": 5}
    assert st == {"queue": []}


def test_state_channel_is_stamped_and_keeps_the_clock():
    sio = FakeSio()
    state = {"current": {"title": "A"}, "position": 83, "clock": CLOCK}
    t0 = now_ms()
    rl._handle_message(sio, rl.CHANNEL_STATE, {"guild_id": 42, "state": state})
    t1 = now_ms()
    (event, data, room), = sio.emits
    assert (event, room) == ("playlist_update", "guild:42")
    assert _between(data.pop("relay_at_ms"), t0, t1)
    assert data == state
    assert "relay_at_ms" not in state, "l'état reçu n'est pas modifié"


def test_progress_channel_relays_the_clock_and_the_relay_time():
    sio = FakeSio()
    t0 = now_ms()
    rl._handle_message(sio, rl.CHANNEL_PROGRESS,
                       {"guild_id": 42, "position": 83, "duration": 200, "paused": False, "clock": CLOCK})
    t1 = now_ms()
    (event, data, room), = sio.emits
    assert (event, room) == ("playlist_update", "guild:42")
    assert _between(data.pop("relay_at_ms"), t0, t1)
    assert data == {"only_elapsed": True, "paused": False, "is_paused": False, "position": 83, "duration": 200,
                    "progress": {"elapsed": 83, "duration": 200}, "clock": CLOCK}


@pytest.mark.parametrize("clock", [None, "playing", 42, ["a"]])
def test_progress_without_a_clock_object_keeps_the_old_payload(clock):
    sio = FakeSio()
    data = {"guild_id": 42, "position": 7, "duration": 100}
    if clock is not None:
        data["clock"] = clock
    rl._handle_message(sio, rl.CHANNEL_PROGRESS, data)
    (_, out, _), = sio.emits
    assert "clock" not in out and isinstance(out["relay_at_ms"], int)
    assert out["position"] == 7 and out["progress"] == {"elapsed": 7, "duration": 100}
```

L'import de `socketio` ne sert qu'à A3 : le garder dès maintenant, l'en-tête du fichier ne change plus ensuite.

Dans `services/api/tests/test_socketio.py`, remplacer `_got_relay` par :

```python
def _strip(state):
    """État émis sans relay_at_ms (horodatage de l'API, synchro son/vidéo), présent et entier."""
    st = dict(state)
    stamp = st.pop("relay_at_ms", None)
    assert isinstance(stamp, int) and not isinstance(stamp, bool), state
    return st


def _got_relay(client):
    return [u for u in _events(client.get_received(), "playlist_update")
            if _strip(u["args"][0]) == {"queue": ["relay"]}]
```

Dans `test_redis_listener_relay_from_native_thread_reaches_room`, la ligne `assert updates[0]["args"][0] == {"queue": [1, 2]}` devient :

```python
    assert _strip(updates[0]["args"][0]) == {"queue": [1, 2]}
```

- [ ] **Step 2: Les voir échouer**

Run: `PYAPI -m pytest services/api/tests -q -p no:cacheprovider`
Expected :
- `test_sync_relay.py` ne se collecte pas : `ModuleNotFoundError: No module named 'api.services.relay_clock'` ;
- dans `test_socketio.py`, les tests qui relaient un état échouent sur l'assertion de `_strip`.

- [ ] **Step 3: Implémenter**

Créer `services/api/api/services/relay_clock.py` :

```python
"""Horloge de l'API pour la synchro son/vidéo (spec §3, §5) : le site se cale sur elle.

relay_at_ms : heure murale de l'API (ms epoch) à la réception d'un état ou d'un tick du bot (Redis ou réponse RPC).
time_sync renvoie la même horloge : aucun écart d'horloge entre les conteneurs du bot et de l'API.
"""
from __future__ import annotations

import time


def now_ms() -> int:
    """Horloge murale de l'API, en millisecondes epoch."""
    return int(time.time() * 1000)


def with_relay_at(state: dict, at_ms: int) -> dict:
    """Copie de `state` avec relay_at_ms : l'état reçu n'est jamais modifié."""
    return {**state, "relay_at_ms": at_ms}
```

Dans `redis_listener.py` (CRLF), faire trois modifications :

1. Après `from api.services.authz import ROOM_AUTHENTICATED` :

```python
from api.services.relay_clock import now_ms, with_relay_at
```

2. Dans `_handle_message`, remplacer

```python
    room = f"guild:{guild_id}" if guild_id else None

    if channel == CHANNEL_STATE:
        state = data.get("state", data)
```

par :

```python
    room = f"guild:{guild_id}" if guild_id else None
    relay_at_ms = now_ms()  # réception : le site se cale sur l'horloge de l'API (synchro son/vidéo)

    if channel == CHANNEL_STATE:
        state = data.get("state", data)
        if isinstance(state, dict):
            state = with_relay_at(state, relay_at_ms)
```

3. Dans la branche `CHANNEL_PROGRESS`, terminer le dict `payload` ainsi :

```python
            "progress": {
                "elapsed": data.get("position", 0),
                "duration": data.get("duration"),
            },
            "relay_at_ms": relay_at_ms,
        }
        if isinstance(data.get("clock"), dict):
            payload["clock"] = data["clock"]  # position réellement lue par le bot, horodatée
```

- [ ] **Step 4: Les voir passer**

Run: `PYAPI -m pytest services/api/tests -q -p no:cacheprovider` → base + 8 (380), aucun échec.

- [ ] **Step 5: Commit**

```bash
git add services/api/api/services/relay_clock.py services/api/tests/test_sync_relay.py
git commit -m "feat(api): relay_at_ms et clock relayes depuis Redis (synchro son/video)" -- services/api/api/services/relay_clock.py services/api/api/services/redis_listener.py services/api/tests/test_sync_relay.py services/api/tests/test_socketio.py
```

---

### Task A2 : `relay_at_ms` sur les états lus par RPC (REST et abonnement socket)

**Files:**
- Modify: `services/api/api/routes/player.py` (imports l.9 ; nouveau `_stamped` avant `play_for_user_response` l.70 ; `get_state` l.85-94)
- Modify: `services/api/api/websocket/events.py` (import l.20 ; `_subscribe` l.62-82)
- Test: `services/api/tests/test_sync_relay.py` (ajout), `services/api/tests/test_socketio.py` (l.149 et l.309)

**Interfaces:**
- Consumes: `now_ms`, `with_relay_at` (A1).
- Produces :
  - `GET /api/v1/player/state` et `/api/v1/playlist` répondent `{ok, state: {…, "relay_at_ms": int}}`, ou `{…, "relay_at_ms"}` à la racine s'il n'y a pas de `state`.
  - L'heure est prise à la réception de la réponse du bot.
  - Un échec reste `{ok: false, stale: true, …}`, sans horodatage.
  - Le `playlist_update` d'un abonnement porte `relay_at_ms`.

- [ ] **Step 1: Tests qui échouent**

Ajouter à la fin de `test_sync_relay.py` :

```python


# ── A2 : états lus par RPC (REST) ──

@pytest.mark.parametrize("path", ["/player/state", "/playlist"])
def test_rest_state_is_stamped_at_the_bot_reply(logged_client, fake_send, path):
    state = {"current": {"title": "a"}, "queue": [], "position": 83, "clock": CLOCK}
    fake_send.result = {"ok": True, "state": state}
    t0 = now_ms()
    body = logged_client.get(f"/api/v1{path}?guild_id=42").get_json()
    t1 = now_ms()
    assert body["ok"] is True
    assert _between(body["state"].pop("relay_at_ms"), t0, t1)
    assert body["state"] == state, "clock et champs du bot intacts"
    assert "relay_at_ms" not in body


def test_rest_reply_without_state_is_stamped_at_its_root(logged_client, fake_send):
    fake_send.result = {"ok": True, "current": None, "queue": []}
    body = logged_client.get("/api/v1/player/state?guild_id=42").get_json()
    assert isinstance(body["relay_at_ms"], int)


def test_rest_failure_is_not_stamped(logged_client, fake_send):
    fake_send.result = {"ok": False, "error": "TIMEOUT"}
    body = logged_client.get("/api/v1/player/state?guild_id=42").get_json()
    assert body["stale"] is True and "relay_at_ms" not in body
```

Dans `test_socketio.py`, faire deux remplacements.

Dans `test_member_joins_room_and_gets_state`, `assert ups and ups[0]["args"][0] == STATE` devient :

```python
    assert ups and _strip(ups[0]["args"][0]) == STATE
```

Dans `test_request_state_emits_state`, l'assertion devient :

```python
    assert ups and _strip(ups[0]["args"][0]) == {"current": None, "queue": []}
```

- [ ] **Step 2: Les voir échouer**

Run: `PYAPI -m pytest services/api/tests -q -p no:cacheprovider`
Expected :
- `KeyError: 'relay_at_ms'` dans les deux tests REST horodatés (`/player/state` et `/playlist`) et dans `test_rest_reply_without_state_is_stamped_at_its_root` ;
- dans les tests d'abonnement de `test_socketio.py`, l'assertion de `_strip` échoue.

- [ ] **Step 3: Implémenter**

**`routes/player.py`.**

1. Après `from api.services.bot_bridge import send_command` :

```python
from api.services.relay_clock import now_ms, with_relay_at
```

2. Juste avant `def play_for_user_response(` :

```python
def _stamped(res: dict[str, Any], at_ms: int) -> dict[str, Any]:
    """relay_at_ms (synchro son/vidéo) là où le site lit `clock` : dans `state`, sinon à la racine."""
    st = res.get("state")
    return {**res, "state": with_relay_at(st, at_ms)} if isinstance(st, dict) else with_relay_at(res, at_ms)


```

3. Dans `get_state`, remplacer

```python
    res = send_command("get_state", gid, _uid(), timeout=8)

    if res.get("ok"):
        return jsonify(res), 200
```

par :

```python
    res = send_command("get_state", gid, _uid(), timeout=8)
    at_ms = now_ms()  # réception de la réponse du bot

    if res.get("ok"):
        return jsonify(_stamped(res, at_ms)), 200
```

**`websocket/events.py`.**

1. Après `from api.services.authz import MSG_NOT_AUTHENTICATED, ROOM_AUTHENTICATED, session_user_id` :

```python
from api.services.relay_clock import now_ms, with_relay_at
```

2. Dans `_subscribe`, remplacer

```python
        _deny(gid, "REDIS_UNAVAILABLE", _MSG_BRIDGE_ERROR, True)
        return False
    if not isinstance(res, dict) or not res.get("ok"):
```

par :

```python
        _deny(gid, "REDIS_UNAVAILABLE", _MSG_BRIDGE_ERROR, True)
        return False
    at_ms = now_ms()  # réception de la réponse du bot (synchro son/vidéo)
    if not isinstance(res, dict) or not res.get("ok"):
```

3. À la fin de `_subscribe`, remplacer

```python
    emit("playlist_update", res.get("state", res))
    return True
```

par :

```python
    state = res.get("state", res)
    emit("playlist_update", with_relay_at(state, at_ms) if isinstance(state, dict) else state)
    return True
```

- [ ] **Step 4: Les voir passer**

Run: `PYAPI -m pytest services/api/tests -q -p no:cacheprovider` → base + 4 (384), aucun échec.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(api): relay_at_ms sur les etats lus par RPC (REST et abonnement)" -- services/api/api/routes/player.py services/api/api/websocket/events.py services/api/tests/test_sync_relay.py services/api/tests/test_socketio.py
```

---

### Task A3 : événement `time_sync` (accusé `{t0, ts}`)

**Files:**
- Modify: `services/api/api/websocket/events.py` (import `time` ; nouveau gestionnaire avant `# ── State request ──`)
- Test: `services/api/tests/test_sync_relay.py` (ajout)

**Interfaces:**
- Produces : l'événement socket `time_sync`.
  - Requête `{t0}`, accusé (valeur de retour du gestionnaire) `{"t0": <t0 tel quel>, "ts": float}`, où `ts` vaut `time.time() * 1000`, l'horloge murale de l'API en ms.
  - Une charge utile non-dict, ou un `t0` non numérique : `t0` est renvoyé tel quel (`None` pour un non-dict).
  - Aucune authentification.

- [ ] **Step 1: Tests qui échouent** — ajouter à la fin de `test_sync_relay.py` :

```python


# ── A3 : time_sync ──

def test_time_sync_acks_with_the_api_clock(app):
    c = socketio.test_client(app)
    try:
        t0 = time.time() * 1000
        ack = c.emit("time_sync", {"t0": 1234.5}, callback=True)
        t1 = time.time() * 1000
        assert ack["t0"] == 1234.5
        assert isinstance(ack["ts"], float) and t0 <= ack["ts"] <= t1
    finally:
        c.disconnect()


@pytest.mark.parametrize("payload", [{"t0": "abc"}, {"t0": None}, {}, "str", [1, 2], 5, None])
def test_time_sync_tolerates_bad_input(app, payload):
    c = socketio.test_client(app)
    try:
        ack = c.emit("time_sync", callback=True) if payload is None else c.emit("time_sync", payload, callback=True)
        assert ack["t0"] == (payload.get("t0") if isinstance(payload, dict) else None), "t0 renvoyé tel quel"
        assert isinstance(ack["ts"], float)
        assert c.is_connected()
    finally:
        c.disconnect()
```

`emit(..., callback=True)` du client de test Flask-SocketIO renvoie les arguments de l'accusé : vérifié avec l'app réelle.

- [ ] **Step 2: Les voir échouer**

Run: `PYAPI -m pytest services/api/tests/test_sync_relay.py -q -p no:cacheprovider`
Expected : `8 failed`, avec `TypeError: 'NoneType' object is not subscriptable` (aucun accusé).

- [ ] **Step 3: Implémenter** dans `events.py`

1. Ajouter `import time` après `import re`.

2. Juste avant le commentaire `# ── State request ──` :

```python
@socketio.on("time_sync")
def on_time_sync(data=None):
    """Synchro d'horloge du site (spec synchro §3) : {t0} → accusé {t0, ts}, ts = horloge murale de l'API (ms).

    Aucune donnée sensible, aucune autorisation au-delà du socket ; t0 renvoyé tel quel, même non numérique.
    """
    return {"t0": _payload(data).get("t0"), "ts": time.time() * 1000}


```

- [ ] **Step 4: Les voir passer**

Run: `PYAPI -m pytest services/api/tests -q -p no:cacheprovider` → base + 8 (392), aucun échec.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(api): evenement time_sync (accuse {t0, ts}) pour la synchro d'horloge" -- services/api/api/websocket/events.py services/api/tests/test_sync_relay.py
```

---

# Chaîne web

Les commandes se lancent depuis `services/web/`. Les chemins sont relatifs à ce dossier, sauf dans `git commit -- …`, qui part de la racine.

### Task W1 : `lib/sync/timesync.ts`, la mesure de l'horloge de l'API

**Files:**
- Create: `services/web/src/lib/sync/timesync.ts`
- Test: `services/web/tests/timesync.test.mjs`

**Interfaces:**
- Produces (signatures exactes à l'étape 3) : `SyncSample`, `TS_KEEP`, `TS_MAX_RTT_MS`, `sampleOf(t0, ts, t1)`, `TimeSync` (`add`, `best`, `serverNow(perfNow)`, `reset`) et `createTimeSync()`. `t0` et `t1` viennent de `performance.now()` ; `ts` est en ms epoch de l'API.

- [ ] **Step 1: Test qui échoue** — créer `tests/timesync.test.mjs` :

```js
// Mesure de l'horloge de l'API (spec synchro son/vidéo §6.1) : filtre au plus court aller-retour, rejet des aberrations.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const { createTimeSync, sampleOf, TS_KEEP, TS_MAX_RTT_MS } = await loadTs('../src/lib/sync/timesync.ts');

test('un échantillon : offset = ts − (t0 + t1) / 2, rtt = t1 − t0', () => {
  assert.deepEqual(sampleOf(1000, 1_790_000_000_050, 1100), { offset: 1_790_000_000_050 - 1050, rtt: 100 });
});

test('échantillons aberrants rejetés : aller-retour négatif, > 2 s, valeurs illisibles', () => {
  assert.equal(TS_MAX_RTT_MS, 2000);
  assert.equal(sampleOf(1000, 5, 900), null);
  assert.equal(sampleOf(0, 5, 2001), null);
  assert.notEqual(sampleOf(0, 5, 2000), null);
  for (const bad of [Number.NaN, Infinity, undefined, '12', null]) assert.equal(sampleOf(0, bad, 10), null, String(bad));
});

test('retient l’aller-retour le plus court ; serverNow suit son offset', () => {
  const ts = createTimeSync();
  assert.equal(ts.best(), null);
  assert.equal(ts.serverNow(5000), null);
  assert.equal(ts.add(0, 10_050, 100), true);    // rtt 100, offset 10 000
  assert.equal(ts.add(200, 10_230, 220), true);  // rtt 20, offset 10 020
  assert.equal(ts.add(300, 10_400, 500), true);  // rtt 200
  assert.deepEqual(ts.best(), { offset: 10_020, rtt: 20 });
  assert.equal(ts.serverNow(5000), 15_020);
  assert.equal(ts.add(0, 1, 5000), false, 'rejeté : rien ne change');
  assert.deepEqual(ts.best(), { offset: 10_020, rtt: 20 });
});

test('fenêtre des TS_KEEP dernières mesures : le meilleur ancien finit par sortir', () => {
  const ts = createTimeSync();
  assert.equal(TS_KEEP, 8);
  ts.add(0, 1000, 10);                                         // rtt 10, offset 995
  for (let i = 1; i <= 7; i++) ts.add(i * 100, 5000 + i * 100, i * 100 + 50);   // rtt 50
  assert.equal(ts.best().rtt, 10);
  ts.add(900, 6000, 950);                                      // 9e mesure : la première sort
  assert.equal(ts.best().rtt, 50);
  ts.reset();
  assert.equal(ts.best(), null);
});
```

- [ ] **Step 2: Le voir échouer**

Run: `node --test tests/timesync.test.mjs`
Expected : échec au chargement du module, `ERR_MODULE_NOT_FOUND` ou `ENOENT` sur `src/lib/sync/timesync.ts`.

- [ ] **Step 3: Implémenter** — créer `src/lib/sync/timesync.ts` :

```ts
/**
 * Mesure de l'horloge de l'API (spec synchro son/vidéo §3, §6.1) : socket time_sync {t0} → {t0, ts}.
 * t0 et t1 : horloge du client (performance.now(), ms) ; ts : horloge murale de l'API (ms epoch).
 * Un échantillon donne offset = ts − (t0 + t1) / 2 et rtt = t1 − t0 ; on garde les TS_KEEP derniers et on retient
 * celui dont l'aller-retour est le plus court (le moins bruité). Pur, sans import runtime (tests/timesync.test.mjs).
 */

export type SyncSample = { offset: number; rtt: number };

export const TS_KEEP = 8;
export const TS_MAX_RTT_MS = 2000;   // au-delà : rejeté (aberrant)

/** Échantillon (t0, ts, t1), ou null s'il est illisible ou aberrant (aller-retour négatif ou > TS_MAX_RTT_MS). */
export function sampleOf(t0: number, ts: number, t1: number): SyncSample | null {
  if (![t0, ts, t1].every((v) => typeof v === 'number' && Number.isFinite(v))) return null;
  const rtt = t1 - t0;
  if (rtt < 0 || rtt > TS_MAX_RTT_MS) return null;
  return { offset: ts - (t0 + t1) / 2, rtt };
}

export interface TimeSync {
  /** Ajoute une mesure ; false si elle est rejetée. */
  add(t0: number, ts: number, t1: number): boolean;
  /** Échantillon retenu (aller-retour le plus court des TS_KEEP derniers), null sans mesure. */
  best(): SyncSample | null;
  /** Heure de l'API vue d'ici (ms epoch) pour un performance.now() donné ; null sans mesure. */
  serverNow(perfNow: number): number | null;
  reset(): void;
}

export function createTimeSync(): TimeSync {
  let samples: SyncSample[] = [];
  const best = (): SyncSample | null => samples.reduce<SyncSample | null>((b, s) => (!b || s.rtt < b.rtt ? s : b), null);
  return {
    add(t0, ts, t1) {
      const s = sampleOf(t0, ts, t1);
      if (!s) return false;
      samples = [...samples, s].slice(-TS_KEEP);
      return true;
    },
    best,
    serverNow(perfNow) {
      const b = best();
      return b ? perfNow + b.offset : null;
    },
    reset() { samples = []; },
  };
}
```

- [ ] **Step 4: Le voir passer**

Run: `node --test tests/timesync.test.mjs` → 4 passés.
Puis `npm test`, `GREG_TEST_TRANSPILE=1 npm test` et `npx tsc --noEmit` : base + 4 (372), sans erreur.

- [ ] **Step 5: Commit**

```bash
git add services/web/src/lib/sync/timesync.ts services/web/tests/timesync.test.mjs
git commit -m "feat(web): timesync, mesure de l'horloge de l'API au plus court aller-retour" -- services/web/src/lib/sync/timesync.ts services/web/tests/timesync.test.mjs
```

---

### Task W2 : `lib/sync/refclock.ts`, l'horloge de référence du son

**Files:**
- Create: `services/web/src/lib/sync/refclock.ts`
- Test: `services/web/tests/refclock.test.mjs`

**Interfaces:**
- Produces (signatures exactes à l'étape 3) :
  - les types `ClockStatus`, `ClockSample`, `Anchor`, `Ingest` et `ClockView` (`{playId, status, compat, url}`) ;
  - `REANCHOR_MS`, `NO_CLOCK` ;
  - `clockSampleOf(payload, recvNow)`, `predict(a, t)` ;
  - `createRefClock()`, qui rend un `RefClock` (`ingest`, `positionAt(serverNow)`, `anchor`, `reset`) ;
  - `clockViewOf(prev, a, url?)`.

- [ ] **Step 1: Test qui échoue** — créer `tests/refclock.test.mjs` :

```js
// Horloge de référence du son (spec synchro son/vidéo §6.1) : ordre des échantillons, recalages, mode compatibilité.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const { createRefClock, clockSampleOf, clockViewOf, predict, NO_CLOCK, REANCHOR_MS } = await loadTs('../src/lib/sync/refclock.ts');

const T = 1_790_846_494_000;
const S = (o = {}) => ({ play_id: 'p1', status: 'playing', position_ms: 10_000, at: T, compat: false, ...o });
const state = (clock, extra = {}) => ({ current: { url: 'https://youtu.be/aaaaaaaaaaa' }, position: 10, clock, ...extra });

test('échantillon d’un état : clock, relay_at_ms d’abord, sampled_at_ms en repli', () => {
  const clock = { play_id: 'a1b2c3d4', status: 'playing', position_ms: 83_460, sampled_at_ms: T };
  assert.deepEqual(clockSampleOf(state(clock, { relay_at_ms: T + 3 }), 0),
    { play_id: 'a1b2c3d4', status: 'playing', position_ms: 83_460, at: T + 3, compat: false });
  assert.equal(clockSampleOf(state(clock), 0).at, T);
  // REST : { ok, state: {…} } ; tick : only_elapsed
  assert.equal(clockSampleOf({ ok: true, state: state(clock, { relay_at_ms: T + 9 }) }, 0).at, T + 9);
  assert.equal(clockSampleOf({ only_elapsed: true, position: 83, clock, relay_at_ms: T + 1 }, 0).position_ms, 83_460);
  // chargement : position null
  assert.equal(clockSampleOf(state({ ...clock, status: 'loading', position_ms: null, play_id: null }), 0).position_ms, null);
});

test('échantillon : état périmé ou illisible → null ; sans clock → compatibilité, ancré à la réception', () => {
  assert.equal(clockSampleOf({ ok: false, stale: true, backend_error: 'TIMEOUT' }, 5), null);
  assert.equal(clockSampleOf(null, 5), null);
  assert.equal(clockSampleOf({ position: 'abc' }, 5), null);
  assert.deepEqual(clockSampleOf({ current: { title: 'A' }, position: 83, is_paused: false }, 5000),
    { play_id: null, status: 'playing', position_ms: 83_000, at: 5000, compat: true });
  assert.equal(clockSampleOf({ only_elapsed: true, position: 7, paused: true }, 1).status, 'paused');
  assert.equal(clockSampleOf({ current: null, queue: [], position: 0 }, 1).status, 'idle');
  // un statut inconnu : traité comme un ancien bot
  assert.equal(clockSampleOf(state({ status: 'bogus', sampled_at_ms: T }), 1).compat, true);
});

test('positionAt : avance en lecture, figée en pause, en blocage, en chargement', () => {
  const rc = createRefClock();
  assert.equal(rc.positionAt(T), null);
  assert.equal(rc.ingest(S()), 'anchored');
  assert.equal(rc.positionAt(T + 1500), 11_500);
  for (const status of ['paused', 'stalled']) {
    rc.ingest(S({ status, at: T + 2000, position_ms: 12_000 }));
    assert.equal(rc.positionAt(T + 60_000), 12_000, status);
  }
  rc.ingest(S({ play_id: 'p2', status: 'loading', position_ms: null, at: T + 3000 }));
  assert.equal(rc.positionAt(T + 9000), null);
  assert.equal(predict(S({ position_ms: 0, at: T }), T - 500), 0, 'jamais négative');
});

test('ticks conformes à la prédiction : l’ancre ne bouge pas (zone de 40 ms)', () => {
  const rc = createRefClock();
  rc.ingest(S());
  assert.equal(REANCHOR_MS, 40);
  assert.equal(rc.ingest(S({ at: T + 1000, position_ms: 11_020 })), 'kept');
  assert.equal(rc.ingest(S({ at: T + 2000, position_ms: 11_960 })), 'kept');
  assert.equal(rc.anchor().at, T, 'ancre d’origine');
  assert.equal(rc.ingest(S({ at: T + 3000, position_ms: 13_041 })), 'anchored', 'écart > 40 ms : recalée');
  assert.equal(rc.positionAt(T + 3000), 13_041);
});

test('recalage sur un changement de play_id ou de statut, même à position égale', () => {
  const rc = createRefClock();
  rc.ingest(S());
  assert.equal(rc.ingest(S({ at: T + 1000, position_ms: 11_000, status: 'paused' })), 'anchored');
  assert.equal(rc.ingest(S({ at: T + 5000, position_ms: 11_000, status: 'paused' })), 'kept');
  assert.equal(rc.ingest(S({ at: T + 6000, position_ms: 11_000 })), 'anchored', 'reprise');
  assert.equal(rc.ingest(S({ at: T + 7000, position_ms: 0, play_id: 'p2' })), 'anchored');
  assert.equal(rc.anchor().play_id, 'p2');
});

test('un échantillon plus ancien que l’ancre est ignoré (REST lente après un tick)', () => {
  const rc = createRefClock();
  rc.ingest(S({ at: T + 5000, position_ms: 15_000 }));
  assert.equal(rc.ingest(S({ at: T + 4000, position_ms: 10_000, play_id: 'old' })), 'stale');
  assert.equal(rc.anchor().play_id, 'p1');
  assert.equal(rc.positionAt(T + 6000), 16_000);
});

test('mode compatibilité : recalée à chaque état, comme avant ; passage au bot neuf sans blocage', () => {
  const rc = createRefClock();
  assert.equal(rc.ingest({ play_id: null, status: 'playing', position_ms: 83_000, at: 5000, compat: true }), 'anchored');
  assert.equal(rc.ingest({ play_id: null, status: 'playing', position_ms: 84_000, at: 6000, compat: true }), 'anchored');
  assert.equal(rc.positionAt(6500), 84_500);
  assert.equal(rc.ingest(S({ at: 10 })), 'anchored', 'un bloc clock, même daté « avant » l’ancre de réception');
  rc.reset();
  assert.equal(rc.anchor(), null);
});

test('vue de l’horloge : lien du play_id gardé par les ticks, même objet si rien ne change', () => {
  const a1 = S({ status: 'loading', position_ms: null });
  const v1 = clockViewOf(NO_CLOCK, a1, 'https://youtu.be/aaaaaaaaaaa');
  assert.deepEqual(v1, { playId: 'p1', status: 'loading', compat: false, url: 'https://youtu.be/aaaaaaaaaaa' });
  const v2 = clockViewOf(v1, S(), undefined);                     // tick : même play_id, lien gardé
  assert.deepEqual(v2, { ...v1, status: 'playing' });
  assert.equal(clockViewOf(v2, S(), undefined), v2, 'même objet');
  assert.equal(clockViewOf(v2, S({ play_id: 'p2' }), undefined).url, null, 'autre play_id : lien inconnu');
  assert.equal(clockViewOf(v2, null), NO_CLOCK);
});
```

- [ ] **Step 2: Le voir échouer**

Run: `node --test tests/refclock.test.mjs` → échec au chargement du module : `src/lib/sync/refclock.ts` est introuvable.

- [ ] **Step 3: Implémenter** — créer `src/lib/sync/refclock.ts` :

```ts
/**
 * Horloge de référence du son (spec synchro son/vidéo §3, §6.1). Une ancre {play_id, status, position_ms, at} :
 * `at` est l'heure de l'API (ms epoch) de l'échantillon, relay_at_ms sinon sampled_at_ms. Elle n'est recalée que sur
 * un changement de play_id ou de statut, ou quand un échantillon s'écarte de plus de REANCHOR_MS de la prédiction :
 * les ticks et les relectures REST ne la font plus sauter. Un échantillon plus ancien que l'ancre est ignoré.
 * Sans bloc `clock` (ancien bot) : mode compatibilité, ancre à la réception (`at` = heure de l'API à la réception),
 * recalée à chaque état, comme avant. Pur, sans import runtime (tests/refclock.test.mjs).
 */

export type ClockStatus = 'idle' | 'loading' | 'playing' | 'paused' | 'stalled';
/** Un échantillon, et l'ancre qu'il devient. position_ms null : aucun son encore (idle, loading). */
export type ClockSample = { play_id: string | null; status: ClockStatus; position_ms: number | null; at: number; compat: boolean };
export type Anchor = ClockSample;
/** stale : plus ancien que l'ancre, ignoré ; kept : conforme à la prédiction ; anchored : nouvelle ancre. */
export type Ingest = 'stale' | 'kept' | 'anchored';

export const REANCHOR_MS = 40;
const STATUSES: readonly string[] = ['idle', 'loading', 'playing', 'paused', 'stalled'];

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const truthy = (v: unknown): boolean => v === true || v === 1 || v === '1' || v === 'true';

/**
 * Échantillon d'un état reçu (REST /playlist, socket playlist_update, tick `only_elapsed`). `recvNow` : heure de l'API
 * à la réception (mode compatibilité). null : état périmé (contrat C3) ou rien de lisible.
 */
export function clockSampleOf(payload: any, recvNow: number): ClockSample | null {
  const root = payload && typeof payload === 'object' ? payload : null;
  if (!root || root.ok === false || root.stale === true) return null;
  const p = root.state || root.pm || root.data || root;
  if (!p || typeof p !== 'object') return null;
  const c = p.clock;
  if (c && typeof c === 'object' && STATUSES.includes(c.status)) {
    const at = num(p.relay_at_ms) ?? num(c.sampled_at_ms);
    if (at != null) {
      return {
        play_id: typeof c.play_id === 'string' ? c.play_id : null,
        status: c.status as ClockStatus,
        position_ms: num(c.position_ms),
        at,
        compat: false,
      };
    }
  }
  // compatibilité : secondes entières, ancrées à la réception
  const sec = num(Number(p.progress?.elapsed ?? p.position ?? p.elapsed ?? 0));
  if (sec == null) return null;
  const idle = !p.only_elapsed && !(p.current || p.now_playing);
  const paused = truthy(p.is_paused ?? p.paused);
  return { play_id: null, status: idle ? 'idle' : paused ? 'paused' : 'playing', position_ms: Math.max(0, sec) * 1000, at: recvNow, compat: true };
}

/** Position (ms) prédite par l'ancre à l'heure `t` de l'API : avance en lecture, figée sinon ; null sans son. */
export function predict(a: Anchor, t: number): number | null {
  if (a.position_ms == null) return null;
  return a.status === 'playing' ? Math.max(0, a.position_ms + (t - a.at)) : a.position_ms;
}

export interface RefClock {
  ingest(s: ClockSample): Ingest;
  /** Position du son (ms) à l'heure `serverNow` de l'API ; null sans ancre ou sans son. */
  positionAt(serverNow: number): number | null;
  anchor(): Anchor | null;
  reset(): void;
}

export function createRefClock(): RefClock {
  let a: Anchor | null = null;
  return {
    ingest(s) {
      const both = a !== null && !a.compat && !s.compat;
      if (both && s.at < (a as Anchor).at) return 'stale';
      if (both && s.play_id === (a as Anchor).play_id && s.status === (a as Anchor).status) {
        const p = predict(a as Anchor, s.at);
        if (s.position_ms == null ? p == null : p != null && Math.abs(s.position_ms - p) <= REANCHOR_MS) return 'kept';
      }
      a = { ...s };
      return 'anchored';
    },
    positionAt: (t) => (a ? predict(a, t) : null),
    anchor: () => a,
    reset() { a = null; },
  };
}

/** Ce que la page suit de l'horloge (store) : play_id, statut, mode, et le lien du titre joué sous ce play_id. */
export type ClockView = { playId: string | null; status: ClockStatus | null; compat: boolean; url: string | null };
export const NO_CLOCK: ClockView = { playId: null, status: null, compat: false, url: null };

/**
 * Vue après un échantillon accepté. `url` : lien du titre d'un état complet (null : aucun titre) ; undefined pour un
 * tick (sans titre) : le lien reste celui du même play_id, inconnu pour un autre. Même objet si rien ne change.
 */
export function clockViewOf(prev: ClockView, a: Anchor | null, url?: string | null): ClockView {
  if (!a) return NO_CLOCK;
  const u = url !== undefined ? url : a.play_id === prev.playId ? prev.url : null;
  if (prev.playId === a.play_id && prev.status === a.status && prev.compat === a.compat && prev.url === u) return prev;
  return { playId: a.play_id, status: a.status, compat: a.compat, url: u };
}
```

- [ ] **Step 4: Le voir passer**

Run: `node --test tests/refclock.test.mjs` → 8 passés.
Puis `npm test`, `GREG_TEST_TRANSPILE=1 npm test` et `npx tsc --noEmit` : base + 8 (380).

- [ ] **Step 5: Commit**

```bash
git add services/web/src/lib/sync/refclock.ts services/web/tests/refclock.test.mjs
git commit -m "feat(web): refclock, horloge de reference du son avec mode compatibilite" -- services/web/src/lib/sync/refclock.ts services/web/tests/refclock.test.mjs
```

---

### Task W3 : `lib/sync/controller.ts`, le régulateur

**Files:**
- Create: `services/web/src/lib/sync/controller.ts`
- Test: `services/web/tests/controller.test.mjs`

**Interfaces:**
- Produces (signatures exactes à l'étape 3) :
  - les seuils `CTL_TICK_MS`, `DEAD_S`, `HYST_S`, `NUDGE_MAX_S`, `SEEK_S`, `SEEK_SETTLE_MS`, `HOLD_MS`, `NORATE_*`, `COMPAT_*` et `RATE_CONFIRM_MS` ;
  - `CtlState` et `CTL_INIT` ;
  - `Decision` ;
  - `decide({target, current, state, rateOk, holdUntil, now, compat?})` : `target` et `current` en secondes, `now` et `holdUntil` en `performance.now()` ;
  - `afterDecision`, `nextHold`, `rateCheck` et `gateLoad`.

- [ ] **Step 1: Test qui échoue** — créer `tests/controller.test.mjs` :

```js
// Régulateur de la vidéo (spec synchro son/vidéo §6.1) : seuils, hystérésis, attente, repli en sauts, démarrage gardé.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const {
  decide, afterDecision, nextHold, rateCheck, gateLoad, CTL_INIT, CTL_TICK_MS, HOLD_MS, SEEK_SETTLE_MS,
  NORATE_GAP_MS, COMPAT_GAP_MS, RATE_CONFIRM_MS,
} = await loadTs('../src/lib/sync/controller.ts');

const NOW = 100_000;
// cible 0 : écarts exacts en flottants (60 + 0.04 − 60 < 0.04)
const d = (err, o = {}) => decide({ target: 0, current: err, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW, ...o });

test('4 Hz', () => { assert.equal(CTL_TICK_MS, 250); });

test('seuils : zone morte < 40 ms, ×0,95 / ×1,05 jusqu’à 300 ms, ×0,90 / ×1,10 jusqu’à 2 s, saut au-delà', () => {
  assert.equal(d(0), null);
  assert.equal(d(0.039), null);
  assert.equal(d(-0.039), null);
  assert.deepEqual(d(0.04), { rate: 0.95 }, 'en avance : ralentit');
  assert.deepEqual(d(-0.04), { rate: 1.05 }, 'en retard : accélère');
  assert.deepEqual(d(0.3), { rate: 0.95 });
  assert.deepEqual(d(-0.31), { rate: 1.1 });
  assert.deepEqual(d(2), { rate: 0.9 });
  assert.deepEqual(d(2.01), { seek: 0 });
  assert.deepEqual(d(-5), { seek: 0 });
  assert.deepEqual(decide({ target: 60, current: 65, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), { seek: 60 }, 'saut à la cible');
  assert.deepEqual(decide({ target: -0.2, current: 5, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), { seek: 0 }, 'jamais négatif');
});

test('hystérésis : un recalage en cours continue jusqu’à 15 ms, puis ×1', () => {
  const nudging = { ...CTL_INIT, rate: 0.95 };
  assert.equal(d(0.02, { state: nudging }), null, 'garde ×0,95 dans la zone morte');
  assert.deepEqual(d(-0.02, { state: nudging }), { rate: 1.05 }, 'dépassé : sens inverse');
  assert.deepEqual(d(0.014, { state: nudging }), { rate: 1 });
  assert.deepEqual(d(0.1, { state: { ...CTL_INIT, rate: 0.9 } }), { rate: 0.95 }, 'sous 300 ms : petit pas');
  assert.equal(d(0.5, { state: { ...CTL_INIT, rate: 0.9 } }), null, 'déjà à la bonne vitesse');
});

test('attente : ×1 et rien d’autre pendant HOLD_MS (reprise, blocage, nouveau play_id)', () => {
  assert.equal(HOLD_MS, 3000);
  assert.equal(d(1, { holdUntil: NOW + 1 }), null);
  assert.equal(d(5, { holdUntil: NOW + 1 }), null, 'pas même un saut');
  assert.deepEqual(d(1, { holdUntil: NOW + 1, state: { ...CTL_INIT, rate: 1.1 } }), { rate: 1 });
  assert.deepEqual(d(1, { holdUntil: NOW }), { rate: 0.9 }, 'échue');
});

test('un saut à la fois : SEEK_SETTLE_MS entre deux sauts', () => {
  const justSeeked = { ...CTL_INIT, lastSeekAt: NOW - SEEK_SETTLE_MS + 1 };
  assert.equal(d(3, { state: justSeeked }), null);
  assert.deepEqual(d(3, { state: { ...CTL_INIT, lastSeekAt: NOW - SEEK_SETTLE_MS } }), { seek: 0 });
});

test('sans vitesse confirmée : sauts seuls, seuil 250 ms, 10 s entre deux sauts', () => {
  assert.equal(d(0.25, { rateOk: false }), null);
  assert.deepEqual(d(0.26, { rateOk: false }), { seek: 0 });
  assert.equal(d(0.5, { rateOk: false, state: { ...CTL_INIT, lastSeekAt: NOW - NORATE_GAP_MS + 1 } }), null);
  assert.deepEqual(d(0.5, { rateOk: false, state: { ...CTL_INIT, rate: 1.05 } }), { rate: 1 }, 'retour à ×1 d’abord');
});

test('ancien bot (sans clock) : l’ancien régime, 1,2 s et 15 s entre deux sauts', () => {
  assert.equal(d(1.2, { compat: true }), null);
  assert.deepEqual(d(-1.3, { compat: true }), { seek: 0 });
  assert.equal(d(3, { compat: true, state: { ...CTL_INIT, lastSeekAt: NOW - COMPAT_GAP_MS + 1 } }), null);
});

test('valeurs illisibles : rien', () => {
  assert.equal(decide({ target: Number.NaN, current: 1, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), null);
  assert.equal(decide({ target: 1, current: undefined, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), null);
});

test('afterDecision : vitesse retenue, instant du saut noté', () => {
  assert.equal(afterDecision(CTL_INIT, null, NOW), CTL_INIT);
  assert.deepEqual(afterDecision(CTL_INIT, { rate: 1.05 }, NOW), { rate: 1.05, lastSeekAt: -Infinity });
  assert.deepEqual(afterDecision({ rate: 1.05, lastSeekAt: 0 }, { seek: 12 }, NOW), { rate: 1.05, lastSeekAt: NOW });
});

test('nextHold : à chaque entrée en lecture et à chaque nouveau play_id', () => {
  const P = (status, playId = 'p1') => ({ playId, status });
  assert.equal(nextHold(null, P('playing'), NOW, 0), NOW + HOLD_MS, 'premier état');
  assert.equal(nextHold(P('paused'), P('playing'), NOW, 0), NOW + HOLD_MS, 'reprise');
  assert.equal(nextHold(P('stalled'), P('playing'), NOW, 0), NOW + HOLD_MS, 'fin de blocage');
  assert.equal(nextHold(P('playing'), P('playing', 'p2'), NOW, 0), NOW + HOLD_MS, 'nouveau play_id');
  assert.equal(nextHold(P('playing'), P('playing'), NOW, 7), 7, 'rien de neuf');
  assert.equal(nextHold(P('playing'), P('stalled'), NOW, 7), 7, 'en blocage : la vidéo attend déjà');
});

test('rateCheck : attend RATE_CONFIRM_MS, puis compare à getPlaybackRate()', () => {
  const asked = { rate: 1.05, at: NOW };
  assert.equal(rateCheck(null, 1, NOW), 'ok');
  assert.equal(rateCheck(asked, 1, NOW + RATE_CONFIRM_MS - 1), 'wait');
  assert.equal(rateCheck(asked, 1.05, NOW + RATE_CONFIRM_MS), 'ok');
  assert.equal(rateCheck(asked, 1, NOW + RATE_CONFIRM_MS), 'failed', 'YouTube a arrondi à 1');
  assert.equal(rateCheck(asked, undefined, NOW + RATE_CONFIRM_MS), 'failed');
});

test('démarrage gardé : la vidéo attend que le bot joue ce titre sous un nouveau play_id', () => {
  const V = 'aaaaaaaaaaa', none = { id: null, playId: null };
  const C = (status, playId = 'p1') => ({ playId, status, compat: false });
  assert.equal(gateLoad(C('loading'), V, V, none), false, 'chargement : le poster reste');
  assert.equal(gateLoad(C('playing'), 'bbbbbbbbbbb', V, none), false, 'le bot joue encore l’ancien titre (saut optimiste)');
  assert.equal(gateLoad(C('playing'), null, V, none), false, 'lien du play_id inconnu');
  assert.equal(gateLoad(C('playing'), V, V, none), true);
  assert.equal(gateLoad(C('playing'), V, V, { id: V, playId: 'p1' }), false, 'déjà chargée');
  assert.equal(gateLoad(C('playing', 'p2'), V, V, { id: V, playId: 'p1' }), true, '« Depuis le début », boucle');
  assert.equal(gateLoad(C('playing'), V, null, none), false);
});

test('démarrage gardé, ancien bot ou aucun état : dès que le titre change, comme avant', () => {
  const V = 'aaaaaaaaaaa';
  assert.equal(gateLoad({ playId: null, status: 'playing', compat: true }, null, V, { id: null, playId: null }), true);
  assert.equal(gateLoad({ playId: null, status: 'playing', compat: true }, null, V, { id: V, playId: null }), false);
  assert.equal(gateLoad({ playId: null, status: null, compat: false }, null, V, { id: null, playId: null }), true);
});
```

- [ ] **Step 2: Le voir échouer**

Run: `node --test tests/controller.test.mjs` → échec au chargement du module : `src/lib/sync/controller.ts` est introuvable.

- [ ] **Step 3: Implémenter** — créer `src/lib/sync/controller.ts` :

```ts
/**
 * Régulateur de la vidéo muette (spec synchro son/vidéo §6.1, §6.2). Écart = position vidéo − cible (s) : en avance,
 * la vidéo ralentit ; en retard, elle accélère. YouTube applique 0,90 / 0,95 / 1,05 / 1,10 sans voile ni mise en
 * tampon (sondé) ; au-delà de SEEK_S, saut sous le poster, sans surcompensation fixe. Pur, sans import runtime
 * (tests/controller.test.mjs).
 */

export const CTL_TICK_MS = 250;            // boucle à 4 Hz
export const DEAD_S = 0.04;                // zone morte : vitesse ×1
export const HYST_S = 0.015;               // un recalage en cours finit sous 15 ms
export const NUDGE_MAX_S = 0.3;            // jusqu'ici ×0,95 / ×1,05, puis ×0,90 / ×1,10
export const SEEK_S = 2;                   // au-delà : saut
export const SEEK_SETTLE_MS = 1000;        // un saut à la fois : le temps que YouTube reparte
export const HOLD_MS = 3000;               // après une reprise, un blocage, un nouveau play_id : le client Discord se recale
export const NORATE_SEEK_S = 0.25, NORATE_GAP_MS = 10_000;   // vitesse non confirmée par YouTube : sauts seuls
export const COMPAT_SEEK_S = 1.2, COMPAT_GAP_MS = 15_000;    // ancien bot (positions à la seconde) : l'ancien régime
export const RATE_CONFIRM_MS = 600;        // délai avant de lire getPlaybackRate()
const SLOW = 0.95, SLOWER = 0.9, FAST = 1.05, FASTER = 1.1;

export type CtlState = { rate: number; lastSeekAt: number };
export const CTL_INIT: CtlState = { rate: 1, lastSeekAt: -Infinity };
export type Decision = { rate: number } | { seek: number };
/**
 * target, current : secondes (cible = son + réglage ; current = getCurrentTime()) ; now, holdUntil : performance.now().
 * rateOk : YouTube a confirmé les vitesses ; compat : pas de bloc clock (ancien bot).
 */
export type DecideInput = {
  target: number; current: number; state: CtlState; rateOk: boolean; holdUntil: number; now: number; compat?: boolean;
};

/** Décision du régulateur : { rate }, { seek } ou null (rien à faire). */
export function decide(i: DecideInput): Decision | null {
  const { target, current, state, now } = i;
  if (!Number.isFinite(target) || !Number.isFinite(current)) return null;
  if (now < i.holdUntil) return state.rate !== 1 ? { rate: 1 } : null;
  const err = current - target;
  const a = Math.abs(err);
  if (i.compat || !i.rateOk) {
    if (state.rate !== 1) return { rate: 1 };
    const thr = i.compat ? COMPAT_SEEK_S : NORATE_SEEK_S;
    const gap = i.compat ? COMPAT_GAP_MS : NORATE_GAP_MS;
    return a > thr && now - state.lastSeekAt >= gap ? { seek: Math.max(0, target) } : null;
  }
  if (a > SEEK_S) return now - state.lastSeekAt >= SEEK_SETTLE_MS ? { seek: Math.max(0, target) } : null;
  let want = 1;
  if (a > NUDGE_MAX_S) want = err > 0 ? SLOWER : FASTER;
  else if (a >= DEAD_S || (state.rate !== 1 && a >= HYST_S)) want = err > 0 ? SLOW : FAST;
  return want === state.rate ? null : { rate: want };
}

/** État du régulateur après une décision appliquée. */
export function afterDecision(s: CtlState, d: Decision | null, now: number): CtlState {
  if (!d) return s;
  return 'seek' in d ? { ...s, lastSeekAt: now } : { ...s, rate: d.rate };
}

type HoldKey = { playId: string | null; status: string | null };
/** Fin de l'attente : HOLD_MS à chaque entrée en lecture (reprise, fin de blocage, départ) ou nouveau play_id. */
export function nextHold(prev: HoldKey | null, next: HoldKey, now: number, hold: number): number {
  if (next.status !== 'playing') return hold;
  if (prev && prev.status === 'playing' && prev.playId === next.playId) return hold;
  return now + HOLD_MS;
}

/** Vitesse demandée confirmée par getPlaybackRate() ? 'wait' avant RATE_CONFIRM_MS ; 'ok' sans demande en cours. */
export function rateCheck(asked: { rate: number; at: number } | null, reported: number | undefined, now: number): 'wait' | 'ok' | 'failed' {
  if (!asked) return 'ok';
  if (now - asked.at < RATE_CONFIRM_MS) return 'wait';
  return typeof reported === 'number' && Math.abs(reported - asked.rate) < 0.001 ? 'ok' : 'failed';
}

type GateClock = { playId: string | null; status: string | null; compat: boolean };
/**
 * Démarrage gardé : charger `videoId` maintenant ? Avec bloc clock, seulement quand le bot joue vraiment ce titre
 * (statut playing, `clockVideo` = vidéo du lien de ce play_id) sous un play_id pas encore chargé. Sans bloc clock
 * (ancien bot, ou aucun état reçu), dès que le titre change, comme avant.
 */
export function gateLoad(c: GateClock, clockVideo: string | null, videoId: string | null,
  loaded: { id: string | null; playId: string | null }): boolean {
  if (!videoId) return false;
  if (c.compat || c.status === null) return loaded.id !== videoId;
  return c.status === 'playing' && clockVideo === videoId && (loaded.id !== videoId || loaded.playId !== c.playId);
}
```

- [ ] **Step 4: Le voir passer**

Run: `node --test tests/controller.test.mjs` → 13 passés.
Puis `npm test`, `GREG_TEST_TRANSPILE=1 npm test` et `npx tsc --noEmit` : base + 13 (393).

- [ ] **Step 5: Commit**

```bash
git add services/web/src/lib/sync/controller.ts services/web/tests/controller.test.mjs
git commit -m "feat(web): regulateur de la video (vitesse, sauts, attente, demarrage garde)" -- services/web/src/lib/sync/controller.ts services/web/tests/controller.test.mjs
```

---

### Task W4 : `time_sync` au socket ; états reçus calés sur l'horloge de référence

**Files:**
- Create: `services/web/src/lib/sync/live.ts`
- Modify: `src/lib/types.ts` (CRLF, `TickBase` l.36-41)
- Modify: `src/lib/playerUtils.ts` (CRLF ; `livePosition` l.397-401 ; nouveau `withClock` avant `emptySnapshot` l.192)
- Modify: `src/lib/queue/optimistic.ts` (`live` l.33-38, `crown` l.50-57)
- Modify: `src/lib/socket.ts` (import ; nouveau bloc `time_sync` avant `stopPing`)
- Modify: `src/hooks/usePlayer.ts` (imports l.5-10 ; store l.44-77 ; `receive` l.138-143 ; `resetPlayer` l.151-153 ; `startTimeSync` après `startPing()` l.238)
- Test: `tests/optimistic.test.mjs` (l.50 + ajout), `tests/playerUtils.test.mjs` (ajout, CRLF/LF mixte), `tests/player-contract.test.mjs` (ajout)

**Interfaces:**
- Consumes:
  - `createTimeSync` (W1) ;
  - `createRefClock`, `clockSampleOf`, `clockViewOf`, `NO_CLOCK` et `ClockView` (W2).
- Produces, dans `lib/sync/live.ts` :
  - `timeSync: TimeSync` et `refClock: RefClock` ;
  - `serverNow(perfNow: number): number`.
- Produces, dans les autres fichiers :
  - `TickBase.frozen?: boolean`.
  - `playerUtils` : `type ClockReading = { pos: number; at: number; frozen: boolean }` et `withClock(snap: Snapshot, r: ClockReading | null): Snapshot`. `livePosition` reste figée si `tb.frozen`.
  - Store zustand : `clock: ClockView`. Il est mis à jour à chaque échantillon accepté, sans attendre le tampon des actions.
  - `socket.ts` : `startTimeSync(): void`.

- [ ] **Step 1: Tests qui échouent**

Dans `tests/optimistic.test.mjs`, la ligne `assert.deepEqual(played.tickBase, { pos: 0, at: 5000, dur: 180 });` devient :

```js
  assert.deepEqual(played.tickBase, { pos: 0, at: 5000, dur: 180, frozen: true }, 'figée jusqu’à ce que le bot le joue');
```

Puis ajouter à la fin du fichier :

```js

test('synchro son/vidéo : le saut optimiste fige l’horloge à 0, une pause ne la fait pas avancer', () => {
  const cur = T('cur', 100), n1 = T('n1', 180);
  const s0 = { player: { ...snap([n1], { current: cur }).player, paused: false }, tickBase: { pos: 10, at: 0, dur: 100 } };
  const skipped = applyMutation(s0, mut({ kind: 'skip', fromKey: 'cur', at: 5000 }));
  assert.equal(skipped.player.paused, false, 'pas en pause : seulement en attente du bot');
  const p = applyMutation(skipped, { id: 9, at: 9000, status: 'queued', kind: 'setPaused', paused: true });
  assert.equal(p.tickBase.pos, 0, 'figée : 4 s plus tard, toujours 0');
});
```

Ajouter à la fin de `tests/playerUtils.test.mjs` :

```js

// ── Synchro son/vidéo : horloge de référence dans l'instantané ──
const { withClock } = await loadTs('../src/lib/playerUtils.ts');

test('livePosition : horloge figée (chargement, blocage) même hors pause', () => {
  assert.equal(livePosition({ pos: 12, at: 1000, dur: 200, frozen: true }, false, 61000), 12);
  assert.equal(livePosition({ pos: 12, at: 1000, dur: 200, frozen: false }, false, 2000), 13);
});

test('withClock : position et ancre lues sur l’horloge de référence, durée gardée ; null : instantané tel quel', () => {
  const snap = { player: { current: null, queue: [], paused: false, repeat: false, position: 83, duration: 200 }, tickBase: { pos: 83, at: 10, dur: 200 } };
  assert.equal(withClock(snap, null), snap);
  const out = withClock(snap, { pos: 83.46, at: 20, frozen: false });
  assert.deepEqual(out.tickBase, { pos: 83.46, at: 20, dur: 200, frozen: false });
  assert.equal(out.player.position, 83.46);
  assert.equal(out.player.duration, 200);
  assert.equal(withClock(snap, { pos: -1, at: 20, frozen: true }).tickBase.pos, 0);
});
```

Ajouter à la fin de `tests/player-contract.test.mjs` :

```js

test('synchro son/vidéo : chaque état reçu nourrit l’horloge de référence avant le tampon ; time_sync à la connexion', () => {
  const src = read('src/hooks/usePlayer.ts');
  const recv = body(src, 'function receive(');
  assert.ok(recv.includes('withClock(raw, feedClock(payload, now,'), 'la barre lit l’horloge de référence');
  assert.ok(recv.indexOf('feedClock(') < recv.indexOf('engine.receive('), 'avant le tampon des actions');
  assert.ok(body(src, 'function feedClock(').includes('refClock.ingest('));
  assert.ok(body(src, 'function resetPlayer(').includes('refClock.reset();'), 'autre serveur : horloge oubliée');
  assert.ok(src.includes('startTimeSync();'));
  const sock = read('src/lib/socket.ts');
  assert.ok(sock.includes(".emit('time_sync', { t0 }"), 'accusé {t0, ts}');
  assert.ok(sock.includes('TIME_SYNC_BURST = 5, TIME_SYNC_GAP_MS = 1000, TIME_SYNC_EVERY_MS = 30_000'));
});
```

- [ ] **Step 2: Les voir échouer**

Run: `npm test`
Expected : 5 échecs.
- `deepEqual` sur `played.tickBase` : `frozen` manque.
- « le saut optimiste fige l'horloge » : la position vaut 4.
- `livePosition` figée : elle rend 72.
- `withClock is not a function`.
- Le contrat de `player-contract` échoue.

- [ ] **Step 3: Implémenter**

**1. Créer `src/lib/sync/live.ts`.** Seul fichier de `lib/sync` à avoir des imports à l'exécution ; il n'est pas chargé par les tests.

```ts
/**
 * Les instances de la synchro son/vidéo pour la page : mesure de l'horloge de l'API (socket time_sync, lib/socket.ts)
 * et horloge de référence du son, nourrie par chaque état reçu (hooks/usePlayer.ts) et lue par le régulateur
 * (components/Stage/Portal.tsx).
 */
import { createRefClock } from './refclock';
import { createTimeSync } from './timesync';

export const timeSync = createTimeSync();
export const refClock = createRefClock();

/** Heure de l'API vue d'ici (ms epoch) ; avant la première mesure, l'horloge murale du navigateur. */
export const serverNow = (perfNow: number): number => timeSync.serverNow(perfNow) ?? performance.timeOrigin + perfNow;
```

**2. `src/lib/types.ts` (CRLF).** Remplacer le bloc `TickBase` (sa doc et l'interface) par :

```ts
/**
 * Ancre de l'horloge : position `pos` (s) à l'instant `at` (performance.now(), ms), durée `dur` (s).
 * `frozen` : le son n'avance pas même hors pause (titre en chargement, flux du bot bloqué : synchro son/vidéo).
 */
export interface TickBase {
  pos: number;
  at: number;
  dur: number;
  frozen?: boolean;
}
```

**3. `src/lib/playerUtils.ts` (CRLF).**

Remplacer la doc, la signature et la première ligne de `livePosition` par :

```ts
/** Position courante (s) déduite de tickBase, bornée à la durée (horloge de la scène, useStageClock, file). Figée si `frozen`. */
export function livePosition(tb: { pos: number; at: number; dur: number; frozen?: boolean }, paused: boolean, now: number): number {
  const pos = (tb.pos || 0) + (paused || tb.frozen ? 0 : (now - tb.at) / 1000);
```

Puis insérer, juste avant `/** État vide (déconnecté, changement de serveur). */` :

```ts
/** Lecture de l'horloge de référence du son (lib/sync/refclock.ts) à la réception d'un état : `pos` (s) à `at` (performance.now()). */
export type ClockReading = { pos: number; at: number; frozen: boolean };

/**
 * Instantané calé sur l'horloge de référence (synchro son/vidéo) : la barre et les minutages la lisent, sans les
 * secondes entières ni le temps de transport du bot. null (pas encore d'horloge) : l'instantané tel quel.
 */
export function withClock(snap: Snapshot, r: ClockReading | null): Snapshot {
  if (!r) return snap;
  const pos = Math.max(0, r.pos);
  return { player: { ...snap.player, position: pos }, tickBase: { pos, at: r.at, dur: snap.tickBase.dur, frozen: r.frozen } };
}

```

**4. `src/lib/queue/optimistic.ts`.**

Dans `live()`, remplacer les deux premières lignes du corps par :

```ts
  const { pos, at, dur, frozen } = s.tickBase;
  const p = pos + (s.player.paused || frozen ? 0 : (now - at) / 1000);
```

Remplacer `crown` (avec son commentaire) par :

```ts
// Le titre `next` prend la scène : horloge à zéro, figée jusqu'à ce que le bot le joue vraiment (synchro son/vidéo :
// plus de position qui court dès le clic, la vidéo attend sous le poster).
function crown(s: Snapshot, next: Track | null, queue: Track[], at: number): Snapshot {
  const dur = next?.duration || 0;
  return {
    player: { ...s.player, current: next, queue, paused: !next, position: 0, duration: dur },
    tickBase: { pos: 0, at, dur, frozen: true },
  };
}
```

**5. `src/lib/socket.ts`.**

Après `import { getApiOrigin, isBrowserReachable } from './api';` :

```ts
import { timeSync } from './sync/live';
```

Juste avant `export function stopPing() {` :

```ts
// ── Synchro d'horloge (spec synchro son/vidéo §3, §6.2) ──
const TIME_SYNC_BURST = 5, TIME_SYNC_GAP_MS = 1000, TIME_SYNC_EVERY_MS = 30_000, TIME_SYNC_TIMEOUT_MS = 2000;
let timeSyncInterval: ReturnType<typeof setInterval> | null = null;
let timeSyncBurst: ReturnType<typeof setTimeout>[] = [];

/** Une mesure : {t0} → accusé {t0, ts} (ts : horloge de l'API, ms) ; sans réponse sous 2 s, ignorée. */
function measureClock(s: Socket) {
  if (!s.connected) return;
  const t0 = performance.now();
  try {
    s.timeout(TIME_SYNC_TIMEOUT_MS).emit('time_sync', { t0 }, (err: unknown, res: any) => {
      if (err || !res || res.t0 !== t0) return;
      timeSync.add(t0, Number(res.ts), performance.now());
    });
  } catch {}
}

/** 5 mesures à chaque connexion (1 s d'écart), puis une toutes les 30 s. Nouvelle connexion : mesures oubliées. */
export function startTimeSync() {
  if (timeSyncInterval) return;
  const s = getSocket();
  const burst = () => {
    timeSyncBurst.forEach(clearTimeout);
    timeSync.reset();
    timeSyncBurst = Array.from({ length: TIME_SYNC_BURST }, (_, i) => setTimeout(() => measureClock(s), i * TIME_SYNC_GAP_MS));
  };
  s.on('connect', burst);
  if (s.connected) burst();
  timeSyncInterval = setInterval(() => measureClock(s), TIME_SYNC_EVERY_MS);
}

```

**6. `src/hooks/usePlayer.ts`.**

1. Imports. Remplacer l'import de `@/lib/socket` par

```ts
import { getSocket, overlayRegister, subscribeGuild, unsubscribeGuild, startPing, startTimeSync, resetSocket } from '@/lib/socket';
```

Puis la fin de l'import de `@/lib/playerUtils` par :

```ts
  snapshotFromPayload, emptySnapshot, addedCopy, stateKind, withClock,
} from '@/lib/playerUtils';
import type { ClockReading } from '@/lib/playerUtils';
import { refClock, serverNow } from '@/lib/sync/live';
import { NO_CLOCK, clockSampleOf, clockViewOf } from '@/lib/sync/refclock';
import type { ClockView } from '@/lib/sync/refclock';
```

2. Store. Dans `interface GregStore`, après `tickBase: TickBase;` :

```ts
  /** Horloge de référence du son (synchro son/vidéo) : play_id, statut, lien du titre joué. Jamais retenue en tampon. */
  clock: ClockView;
```

Dans `create<GregStore>(…)`, après `tickBase: EMPTY.tickBase,` :

```ts
  clock: NO_CLOCK,
```

3. `receive`. Remplacer la doc et la tête de `receive`, jusqu'à `if (!snap) return false;` inclus, par :

```ts
/**
 * Horloge de référence du son nourrie par chaque état reçu, AVANT le tampon des actions (la vidéo n'attend pas une
 * action en vol). `url` : lien du titre d'un état complet, undefined pour un tick. Rend sa lecture à `now`.
 */
function feedClock(payload: any, now: number, url: string | null | undefined): ClockReading | null {
  const sNow = serverNow(now);
  const sample = clockSampleOf(payload, sNow);
  if (sample && refClock.ingest(sample) !== 'stale') {
    const prev = useStore.getState().clock;
    const next = clockViewOf(prev, refClock.anchor(), url);
    if (next !== prev) useStore.setState({ clock: next });
  }
  const a = refClock.anchor();
  return a ? { pos: (refClock.positionAt(sNow) ?? 0) / 1000, at: now, frozen: a.status !== 'playing' } : null;
}

/** État reçu (REST ou socket) : clés, partage structurel, tampon pendant une action ou un glisser. */
function receive(payload: any, from: 'socket' | 'rest' = 'socket'): boolean {
  const kind = stateKind(payload, useStore.getState().guildId);
  if (from === 'socket' && kind === 'other') return false;   // l'ancien serveur, sa room pas encore quittée : ni daté ni affiché
  const now = performance.now();
  const raw = snapshotFromPayload(payload, engine.latest(), performance.now());   // l'état gardé compris : un tick ne l'efface pas
  if (!raw) return false;
  // la barre et les minutages lisent l'horloge de référence (positions au ms près, sans transport ni secondes entières)
  const snap = withClock(raw, feedClock(payload, now, kind === 'full' ? raw.player.current?.url ?? null : undefined));
```

La suite de `receive` (`if (from === 'socket' && kind === 'full') _order.socket(); engine.receive(snap); …`) ne change pas. Le contrat existant, qui cherche `snapshotFromPayload(payload, engine.latest(), performance.now())`, reste vrai.

4. `resetPlayer`. Juste après `_queueOf = '';` :

```ts
  refClock.reset();
  useStore.setState({ clock: NO_CLOCK });
```

5. `startTimeSync`. Dans l'effet du socket de `usePlayerInit`, juste après `startPing();` :

```ts
    startTimeSync();
```

- [ ] **Step 4: Les voir passer**

Run: `npm test`, puis `GREG_TEST_TRANSPILE=1 npm test` : base + 4 (397), aucun échec.
Puis `npx tsc --noEmit` : aucune erreur.

- [ ] **Step 5: Commit**

```bash
git add services/web/src/lib/sync/live.ts
git commit -m "feat(web): time_sync au socket, etats recus cales sur l'horloge de reference" -- services/web/src/lib/sync/live.ts services/web/src/lib/types.ts services/web/src/lib/playerUtils.ts services/web/src/lib/queue/optimistic.ts services/web/src/lib/socket.ts services/web/src/hooks/usePlayer.ts services/web/tests/optimistic.test.mjs services/web/tests/playerUtils.test.mjs services/web/tests/player-contract.test.mjs
```

---

### Task W5 : Portal régule la vidéo à 4 Hz et attend que le bot joue (démarrage gardé)

**Files:**
- Modify: `src/hooks/useYouTubePlayer.ts` (type `YTPlayer`, l.15-25)
- Modify: `src/lib/stage/cover.ts` (constantes l.30-36 ; `alignDue` et `driftSeek`, l.73-82)
- Modify: `src/components/Stage/Portal.tsx` (imports l.8-14 ; `clockPos` l.38-42 ; l.75-111 ; l.118-135 ; l.141-181 ; `data-covered` l.222)
- Test: `tests/stage-motion.test.mjs` (ajout), `tests/cover.test.mjs` (l.5, 79-91, 98-107)

**Interfaces:**
- Consumes:
  - `refClock`, `serverNow` (W4) ;
  - store `clock: ClockView` (W4) ;
  - `CTL_INIT`, `CTL_TICK_MS`, `decide`, `afterDecision`, `nextHold`, `rateCheck`, `gateLoad` et `CtlState` (W3) ;
  - `ClockView` (W2) ;
  - `extractVideoId` (`lib/format.ts`).
- Produces :
  - `YTPlayer.setPlaybackRate(rate: number): void` et `YTPlayer.getPlaybackRate(): number`.
  - `cover.ts` perd `ALIGN_AFTER_PLAYING_MS`, `ALIGN_THRESHOLD_S`, `DRIFT_CHECK_MS`, `MIN_SEEK_GAP_MS`, `RUN_THRESHOLD_S`, `SEEK_COMP_S`, `alignDue` et `driftSeek`. `LOAD_COMP_S` et `loadStart` restent.

- [ ] **Step 1: Tests qui échouent**

Ajouter à la fin de `tests/stage-motion.test.mjs`. Son `code()` retire les commentaires ; garder les regex telles quelles.

```js

// ─── Synchro son/vidéo (spec §6.2) : régulateur, démarrage gardé, plus de sauts à seuils fixes ───
test('Portal : régulateur à 4 Hz, démarrage gardé par play_id, attente, plus d’ancien correcteur', () => {
  const portal = code('src/components/Stage/Portal.tsx');
  assert.match(portal, /const id = setInterval\(tick, CTL_TICK_MS\);/);
  assert.match(portal, /if \(awaiting\.current \|\| document\.visibilityState !== 'visible' \|\| ytState\.current !== YT_STATE\.PLAYING\) return;/);
  assert.match(portal, /if \(!gateLoad\(clock, extractVideoId\(clock\.url\), videoId, loaded\.current\)\) return;/);
  assert.match(portal, /hold\.current = nextHold\(prevClock\.current, clock, performance\.now\(\), hold\.current\);/);
  assert.match(portal, /const still = paused \|\| clock\.status === 'stalled';/);
  assert.match(portal, /ctl\.current = \{ \.\.\.ctl\.current, rate: 1 \};/, 'vitesse réappliquée après loadVideoById');
  assert.doesNotMatch(portal, /driftSeek|alignDue|RUN_THRESHOLD_S|MIN_SEEK_GAP_MS|DRIFT_CHECK_MS|SEEK_COMP_S|clockPos\(/);
  const cover = code('src/lib/stage/cover.ts');
  assert.doesNotMatch(cover, /DRIFT_CHECK_MS|SEEK_COMP_S|RUN_THRESHOLD_S|ALIGN_THRESHOLD_S|MIN_SEEK_GAP_MS/);
  assert.match(code('src/hooks/useYouTubePlayer.ts'), /setPlaybackRate\(rate: number\): void;\s*getPlaybackRate\(\): number;/);
});
```

Dans `tests/cover.test.mjs`, retirer `alignDue` et `driftSeek` des imports (l.5). Les trois remplacements suivants concernent tous ce fichier :

1. Le test « un saut de correction réarme (YouTube remontre son habillage), sans réalignement » devient :

```js
test('poster : un saut de correction réarme (YouTube remontre son habillage)', () => {
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false, playing: true };
  const reArmed = coverNext(shown, { type: 'seek', now: 20000 });
  assert.deepEqual(reArmed, { phase: 'armed', armedAt: 20000, bySeek: true, playing: true });
  assert.equal(coverNext(COVERED, { type: 'seek', now: 5 }), COVERED);        // couvert : rien à réarmer
});
```

2. Le test « pause puis reprise après un saut, nouvel alignement dû (tech.md §5.4) » devient :

```js
test('poster : pause puis reprise après un saut, réarmé par le vrai départ', () => {
  const back = run([yt(YT_STATE.PLAYING, 0), { type: 'seek', now: 10 }, { type: 'pause' }, yt(YT_STATE.PLAYING, 20)]);
  assert.deepEqual(back, { phase: 'armed', armedAt: 20, bySeek: false, playing: true });
});
```

3. Dans le test « dérive : saut seulement au-delà du seuil, compensé de 0,45 s », supprimer les six assertions `driftSeek` et le renommer, en gardant les deux assertions `loadStart` :

```js
test('chargement : compensé du temps de loadVideoById, jamais négatif', () => {
  assert.equal(loadStart(42, 1.5), 43.9);
  assert.equal(loadStart(0, -3), 0);
});
```

- [ ] **Step 2: Le voir échouer**

Run: `npm test`
Expected : le nouveau test de `stage-motion` échoue, car `setInterval(tick, CTL_TICK_MS)` est absent. `cover.test.mjs` passe déjà.

- [ ] **Step 3: Implémenter**

**1. `src/hooks/useYouTubePlayer.ts`.** Dans le type `YTPlayer`, après `getCurrentTime(): number;` :

```ts
  /** Vitesse suggérée (synchro son/vidéo) : YouTube peut l'arrondir, getPlaybackRate() dit ce qu'il applique. */
  setPlaybackRate(rate: number): void;
  getPlaybackRate(): number;
```

**2. `src/lib/stage/cover.ts`.**

Remplacer les lignes `ALIGN_AFTER_PLAYING_MS` à `LOAD_COMP_S` par :

```ts
// La dérive est corrigée par le régulateur (lib/sync/controller.ts) : vitesse, ou saut sans surcompensation.
export const LOAD_COMP_S = 0.4;                // loadVideoById met ~404 ms à jouer
```

Supprimer ensuite `alignDue` et `driftSeek`, avec leurs commentaires : de `/** Alignement initial dû : …` jusqu'à la fin de `driftSeek`. La ligne vide reste avant `/** Position de départ d'un loadVideoById …`.

**3. `src/components/Stage/Portal.tsx`.**

a. **Imports.** Remplacer les imports de `@/lib/playerUtils` et de `@/lib/stage/cover`, et leur `import type`, par :

```tsx
import { COVERED, YT_STATE, coverNext, coverVisible, isPlaceholderThumb, loadStart, posterUrl, revealIn, rewound } from '@/lib/stage/cover';
import type { Cover, CoverEvent } from '@/lib/stage/cover';
import { CTL_INIT, CTL_TICK_MS, afterDecision, decide, gateLoad, nextHold, rateCheck } from '@/lib/sync/controller';
import type { CtlState } from '@/lib/sync/controller';
import { refClock, serverNow } from '@/lib/sync/live';
import type { ClockView } from '@/lib/sync/refclock';
```

L'import de `extractVideoId` (`@/lib/format`) reste.

b. **`clockPos`.** Remplacer la fonction et sa doc par :

```tsx
/** Cible de la vidéo (s) : la position du son selon l'horloge de référence (refclock), plus le réglage. null : aucun son. */
function targetPos(offset: number): number | null {
  const ms = refClock.positionAt(serverNow(performance.now()));
  return ms == null ? null : Math.max(0, ms / 1000 + offset);
}
```

c. **Refs et lecteur.** Dans le composant, remplacer le bloc qui va de `const crownRef = useRef(crown);` jusqu'à la fermeture de `onState` (le `},` qui précède `onError`). Ce bloc comprend `pausedRef`, `lastSeek`, `seek` et `correct`. Le remplacer par :

```tsx
  const clock = useStore((s) => s.clock);   // horloge de référence : play_id, statut, lien du titre joué
  const still = paused || clock.status === 'stalled';   // pause, ou flux du bot bloqué : la vidéo attend
  const crownRef = useRef(crown);
  crownRef.current = crown;
  const stillRef = useRef(still);
  stillRef.current = still;
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const videoRef = useRef(videoId);
  videoRef.current = videoId;
  const playerRef = useRef<YTPlayer | null>(null);
  const ytState = useRef<number>(YT_STATE.UNSTARTED);
  const loaded = useRef<{ id: string | null; playId: string | null }>({ id: null, playId: null });   // vidéo chargée, pour quel play_id
  const awaiting = useRef(false);   // titre choisi, le bot ne le joue pas encore : vidéo arrêtée sous le poster
  const ctl = useRef<CtlState>(CTL_INIT);
  const hold = useRef(0);           // pas de correction avant (performance.now)
  const rateOk = useRef(true);      // YouTube applique les vitesses demandées (sinon : sauts seuls)
  const asked = useRef<{ rate: number; at: number } | null>(null);   // vitesse demandée, à confirmer

  const dispatch = useCallback((ev: CoverEvent) => setCover((c) => coverNext(c, ev)), []);

  const player = useYouTubePlayer(wrapRef, {
    onState: (s) => {
      ytState.current = s;
      dispatch({ type: 'yt', state: s, now: performance.now() });
      // l'iframe ne suit que le son : relancée si elle s'arrête seule, arrêtée si elle part pendant la pause ou un
      // blocage ; rien tant que le bot n'a pas commencé ce titre
      if (awaiting.current) return;
      if (s === YT_STATE.PAUSED && !stillRef.current) playerRef.current?.playVideo();
      if (s === YT_STATE.PLAYING && stillRef.current) playerRef.current?.pauseVideo();
    },
```

La ligne `onError`, l'appel `useYouTubePlayer(…, !!(videoId || nextId))`, `playerRef.current = player;` et l'effet `useEffect(() => { if (player) setNoApi(false); }, [player]);` ne changent pas : des tests de contrat les lisent.

d. **Changement de titre et recul.** Remplacer l'effet « Changement de titre » (l.118-127), puis le commentaire et la première ligne du `useStore.subscribe` du recul (l.129-135), par le bloc ci-dessous.

```tsx
  /** Charge la vidéo à la position du son, sous le poster. loadVideoById remet la vitesse à 1 : le régulateur la réappliquera. */
  const load = useCallback((p: YTPlayer, id: string, playId: string | null) => {
    loaded.current = { id, playId };
    awaiting.current = false;
    ctl.current = { ...ctl.current, rate: 1 };
    asked.current = null;
    try { p.loadVideoById({ videoId: id, startSeconds: loadStart(targetPos(0) ?? 0, offsetRef.current) }); } catch {}
  }, []);

  // Changement de titre : le poster couvre tout de suite, la vidéo précédente s'arrête dessous.
  useEffect(() => {
    setUnavailable(false);
    dispatch({ type: videoId ? 'track' : 'stop' });
    loaded.current = { id: null, playId: null };
    awaiting.current = !!videoId;
    if (!player) return;
    try { player.stopVideo(); } catch {}
  }, [videoId, player, dispatch]);

  // Démarrage gardé (gateLoad) : la vidéo part quand le bot joue vraiment ce titre (statut playing, nouveau play_id) ;
  // un ancien bot (sans clock) : tout de suite, comme avant. Le bot recharge la même vidéo (« Depuis le début »,
  // boucle, reprise après coupure) : elle attend sous le poster. Les ids comptent, pas les liens : le bot garde le
  // lien tel que donné, la même vidéo peut revenir sous un autre (youtu.be/X?si=… puis watch?v=X).
  useEffect(() => {
    if (!player || !videoId) return;
    if (!clock.compat && clock.status === 'loading' && loaded.current.id === videoId && !awaiting.current) {
      awaiting.current = true;
      dispatch({ type: 'track' });
      try { player.stopVideo(); } catch {}
      return;
    }
    if (!gateLoad(clock, extractVideoId(clock.url), videoId, loaded.current)) return;
    if (loaded.current.id === videoId) dispatch({ type: 'track' });   // même vidéo, nouvelle lecture
    load(player, videoId, clock.playId);
  }, [videoId, player, clock, dispatch, load]);

  // Ancien bot (sans clock) : le son recule sur la même vidéo → rechargée sous le poster (tech.md §5.4). Avec clock,
  // le nouveau play_id s'en charge (démarrage gardé). videoRef tient encore l'id rendu.
  useEffect(() => useStore.subscribe((s, prev) => {
    const p = playerRef.current, id = videoRef.current;
    if (!s.clock.compat || !p || !id || s.tickBase === prev.tickBase || extractVideoId(s.player.current?.url) !== id) return;
```

Le reste de cet abonnement (`rewound`, `dispatch`, `loadVideoById`, `}), [dispatch]);`) ne change pas.

e. **Pause, alignement, dérive, décalage.** Remplacer les l.141-181 : l'effet « Pause et reprise », l'effet « Armé » avec son alignement, l'effet « Révélé : dérive », et `firstOffset` avec l'effet du décalage. Le remplacement :

```tsx
  // Pause, ou flux du bot bloqué : la vidéo attend sous le poster, puis repart avec le son.
  useEffect(() => {
    if (!player || !videoId || awaiting.current) return;
    try { if (still) player.pauseVideo(); else player.playVideo(); } catch {}
    if (still) dispatch({ type: 'pause' });
  }, [still, player, videoId, dispatch]);

  // Armé : révélation à armedAt + REVEAL_AFTER_PLAYING_MS ; un calage (BUFFERING puis PLAYING) change `cover` et relance
  // l'effet sans la repousser.
  useEffect(() => {
    if (cover.phase !== 'armed') return;
    const reveal = setTimeout(() => dispatch({ type: 'reveal', now: performance.now() }), revealIn(cover, performance.now()));
    return () => clearTimeout(reveal);
  }, [cover, dispatch]);   // coverNext rend le même objet tant que rien ne change

  // Attente après une reprise, un blocage ou un nouveau play_id : le client Discord se recale (nextHold).
  const prevClock = useRef<ClockView | null>(null);
  useEffect(() => {
    hold.current = nextHold(prevClock.current, clock, performance.now(), hold.current);
    prevClock.current = clock;
  }, [clock]);

  // Régulateur à 4 Hz tant que YouTube joue et que l'onglet est visible (decide) : vitesse ×0,90 à ×1,10, ou saut au-delà
  // de 2 s (le poster revient le temps que l'habillage YouTube parte). Le réglage « Synchro vidéo » passe par lui aussi.
  useEffect(() => {
    if (!player || !videoId || still) return;
    const tick = (): void => {
      if (awaiting.current || document.visibilityState !== 'visible' || ytState.current !== YT_STATE.PLAYING) return;
      const now = performance.now();
      let reported: number | undefined;
      try { reported = player.getPlaybackRate(); } catch {}
      const check = rateCheck(asked.current, reported, now);
      if (check !== 'wait') asked.current = null;
      if (check === 'failed') rateOk.current = false;   // vitesse non confirmée : sauts seuls
      const target = targetPos(offsetRef.current);
      if (target == null) return;
      const d = decide({ target, current: player.getCurrentTime(), state: ctl.current, rateOk: rateOk.current,
        holdUntil: hold.current, now, compat: useStore.getState().clock.compat });
      if (!d) return;
      if ('seek' in d) {
        try { player.seekTo(d.seek, true); } catch {}
        dispatch({ type: 'seek', now });
      } else {
        try { player.setPlaybackRate(d.rate); } catch {}
        asked.current = { rate: d.rate, at: now };
      }
      ctl.current = afterDecision(ctl.current, d, now);
    };
    const id = setInterval(tick, CTL_TICK_MS);
    // retour sur l'onglet : recalage tout de suite, sans attente
    const back = (): void => { if (document.visibilityState === 'visible') { hold.current = 0; tick(); } };
    document.addEventListener('visibilitychange', back);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', back); };
  }, [player, videoId, still, dispatch]);
```

f. **Poster.** Dans le rendu, `data-covered={coverVisible(cover, paused)}` devient `data-covered={coverVisible(cover, still)}`.

Les effets des posters (le relais, le préchargement de `nextId`) et le reste du rendu ne changent pas.

- [ ] **Step 4: Le voir passer**

Run: `npm test`, puis `GREG_TEST_TRANSPILE=1 npm test` : base + 1 (398), aucun échec. Les contrats existants sur `Portal.tsx` et `useYouTubePlayer.ts` restent verts.
Puis `npx tsc --noEmit` : aucune erreur, en particulier aucun import inutilisé de `@/lib/playerUtils`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): Portal regule la video a 4 Hz et attend que le bot joue (demarrage garde)" -- services/web/src/hooks/useYouTubePlayer.ts services/web/src/lib/stage/cover.ts services/web/src/components/Stage/Portal.tsx services/web/tests/cover.test.mjs services/web/tests/stage-motion.test.mjs
```

---

### Task W6 : « Synchro vidéo » au pas de 50 ms sur ±3 s

**Files:**
- Modify: `src/lib/stage/cover.ts` (bloc « Décalage de la vidéo » : `OFFSET_*`, `parseOffset`, `fmtOffset`)
- Modify: `src/hooks/useVideoOffset.ts` (lecture du réglage stocké)
- Modify: `src/components/Stage/SyncOffset.tsx` (import `tx`, docstring, texte d'aide)
- Modify: `src/theme/copy.extra.ts` (nouvelle section `sync`)
- Test: `tests/cover.test.mjs` (import l.6 ; trois tests du décalage), `tests/copy-extra.test.mjs` (ajout)

**Interfaces:**
- Consumes : rien de W5 ; l'aperçu passe déjà par le régulateur depuis W5, sans saut brut.
- Produces :
  - `OFFSET_MIN = -3`, `OFFSET_MAX = 3`, `OFFSET_STEP = 0.05`.
  - `parseOffset(raw)` borne le réglage, l'arrondit au pas de 50 ms (le demi-pas s'éloigne de 0) et rend 0 si la valeur est illisible.
  - `fmtOffset(v)` rend par exemple « +0,15 s », avec U+00A0 avant l'unité.
  - `tx('sync.help')`.
  - `useVideoOffset` réécrit un ancien réglage stocké, borné et arrondi.

- [ ] **Step 1: Tests qui échouent**

`tests/cover.test.mjs`.

1. Ajouter `OFFSET_MIN, OFFSET_MAX, OFFSET_STEP` à la ligne d'import `COVERED, YT_STATE, REVEAL_AFTER_PLAYING_MS, REWIND_S,`.
2. Remplacer les trois tests du décalage, de « décalage : borné à ±10 s… » à « décalage affiché à la française » inclus, par le bloc ci-dessous. Les attendus du fichier actuel contiennent un U+00A0 littéral ; ici, il est écrit `\u00a0`.

```js
test('décalage : borné à ±3 s, pas de 50 ms, 0 si illisible ; un ancien réglage est ramené', () => {
  assert.deepEqual([OFFSET_MIN, OFFSET_MAX, OFFSET_STEP], [-3, 3, 0.05]);
  assert.equal(parseOffset('0.15'), 0.15);
  assert.equal(parseOffset('1.3'), 1.3);
  assert.equal(parseOffset('0.123'), 0.1);
  assert.equal(parseOffset('-0.27'), -0.25);
  assert.equal(parseOffset('7.5'), 3, 'ancien réglage (±10 s) : borné');
  assert.equal(parseOffset('-11'), -3);
  assert.equal(parseOffset('abc'), 0);
  assert.equal(parseOffset(null), 0);
  assert.equal(parseOffset(''), 0);
  assert.ok(Object.is(parseOffset('-0.01'), 0));
});

test('décalage : arrondi au pas symétrique autour de 0, sans reste flottant', () => {
  assert.equal(parseOffset('0.025'), 0.05);                  // demi-pas : loin de 0, des deux côtés
  assert.equal(parseOffset('-0.025'), -0.05);
  assert.equal(parseOffset('0.075'), 0.1);
  assert.equal(parseOffset('-0.075'), -0.1);
  assert.equal(parseOffset(1.15), 1.15);
  assert.equal(parseOffset(2.95), 2.95);
});

test('décalage affiché à la française', () => {
  assert.equal(fmtOffset(0), '0\u00a0s');
  assert.equal(fmtOffset(1.5), '+1,5\u00a0s');
  assert.equal(fmtOffset(-2), '−2\u00a0s');
  assert.equal(fmtOffset(0.15), '+0,15\u00a0s');
  assert.equal(fmtOffset(-0.05), '−0,05\u00a0s');
  assert.equal(fmtOffset(3), '+3\u00a0s');
});
```

Ajouter à la fin de `tests/copy-extra.test.mjs` :

```js

test('Synchro vidéo : l’aide dit le sens du réglage', () => {
  const help = tx('sync.help');
  assert.match(help, /avance[^.]*−/);
  assert.match(help, /retard[^.]*\+/);
  assert.match(readFileSync(new URL('../src/components/Stage/SyncOffset.tsx', import.meta.url), 'utf8'), /\{tx\('sync\.help'\)\}/);
});
```

- [ ] **Step 2: Les voir échouer**

Run: `npm test` → 4 échecs.
- `OFFSET_*` vaut `[-10, 10, 0.5]`.
- `parseOffset('0.025')` rend 0.
- `fmtOffset(0.15)` rend « +0 s ».
- `tx('sync.help')` rend le chemin `sync.help`.

- [ ] **Step 3: Implémenter**

**1. `src/lib/stage/cover.ts`.** Remplacer le bloc qui va de `// ── Décalage de la vidéo (réglage du Roi, gardé dans localStorage) ──` jusqu'à la fin de `fmtOffset` par :

```ts
// ── Décalage de la vidéo (réglage du Roi, gardé dans localStorage, par appareil) ──
// Synchro son/vidéo : le bot publie la position réellement lue ; reste le retard propre à Discord (serveur vocal,
// tampon du client, casque : 80 à 250 ms filaire, jusqu'à 500 ms en Bluetooth). Pas de 50 ms, ±3 s.
export const OFFSET_KEY = 'greg.webplayer.video_offset';
export const OFFSET_MIN = -3, OFFSET_MAX = 3, OFFSET_STEP = 0.05;
const PER_S = 20;   // 1 / OFFSET_STEP, entier : arrondi sans reste flottant (1,15 et non 1,1500000000000001)

/** Réglage lu (localStorage, curseur) : borné, arrondi au pas de 50 ms (demi-pas loin de 0), 0 si illisible. */
export function parseOffset(raw: string | number | null | undefined): number {
  const v = typeof raw === 'number' ? raw : raw == null || String(raw).trim() === '' ? NaN : Number(raw);
  if (!Number.isFinite(v)) return 0;
  const c = Math.min(OFFSET_MAX, Math.max(OFFSET_MIN, v));
  const stepped = (Math.sign(c) * Math.round(Math.abs(c) * PER_S)) / PER_S;   // demi-pas loin de 0, des deux côtés
  return stepped + 0;   // pas de −0
}

/** « 0 s », « +0,15 s », « −2 s » : virgule décimale, signe moins U+2212, espace insécable avant l'unité. */
export function fmtOffset(v: number): string {
  const x = parseOffset(v);
  const n = Math.abs(x).toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
  return `${x > 0 ? '+' : x < 0 ? '−' : ''}${n}\u00a0s`;
}
```

**2. `src/hooks/useVideoOffset.ts`.** Remplacer la doc et le premier `useEffect` par :

```ts
/** Décalage vidéo ↔ son du Roi, gardé dans localStorage, par appareil (tech.md §5.4). 0 par défaut. */
export function useVideoOffset(): [number, (v: number) => void] {
  const [offset, setOffsetState] = useState(0);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(OFFSET_KEY);
      const x = parseOffset(raw);
      setOffsetState(x);
      // ancien réglage (±10 s, pas de 0,5 s) : réécrit borné et arrondi
      if (raw != null && String(x) !== raw) { if (x) localStorage.setItem(OFFSET_KEY, String(x)); else localStorage.removeItem(OFFSET_KEY); }
    } catch {}
  }, []);
```

`setOffset` ne change pas.

**3. `src/components/Stage/SyncOffset.tsx`.** Après `import { t } from '@/theme/copy';`, ajouter `import { tx } from '@/theme/copy.extra';`. Puis remplacer la docstring du composant par :

```tsx
/**
 * Réglage « Synchro vidéo » : le retard propre à Discord sur cet appareil (−3 à +3 s, pas de 50 ms). La vidéo y va
 * par le régulateur (vitesse, pas de saut brut). Popover plaque hors de la vidéo (tech.md §5.4 : jamais de flou
 * d'arrière-plan sur l'iframe).
 */
```

Enfin, `<p className="sync-help" id={helpId}>{t('now.sync.help')}</p>` devient :

```tsx
        <p className="sync-help" id={helpId}>{tx('sync.help')}</p>
```

Le curseur lit toujours `OFFSET_MIN`, `OFFSET_MAX` et `OFFSET_STEP` : il passe tout seul au pas de 50 ms.

**4. `src/theme/copy.extra.ts`.** Après la ligne `transport: { … },`, ajouter :

```ts
  sync: {
    help: 'Compense le retard de Discord sur cet appareil. Image en avance sur le son\u00a0: glissez vers −. Image en retard\u00a0: vers +.',
  },
```

La clé `sync.help` n'existe pas dans le deck : `now.sync.help` est une autre clé, laissée en place.

- [ ] **Step 4: Les voir passer**

Run: `npm test`, puis `GREG_TEST_TRANSPILE=1 npm test` : base + 1 (399), aucun échec. La typographie de `copy-extra` passe.
Puis `npx tsc --noEmit` : aucune erreur.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): Synchro video au pas de 50 ms sur +/-3 s, aide sur le sens du reglage" -- services/web/src/lib/stage/cover.ts services/web/src/hooks/useVideoOffset.ts services/web/src/components/Stage/SyncOffset.tsx services/web/src/theme/copy.extra.ts services/web/tests/cover.test.mjs services/web/tests/copy-extra.test.mjs
```

---

## Vérification finale (orchestrateur, après les trois chaînes)

1. **Suites complètes.**
   - Bot : 219 attendus.
   - API : 392.
   - Site : 399, en natif et en transpilation.
   - `npx tsc --noEmit`, puis **un seul** `npx next build`.
2. **Navigateur** (spec §7).
   - La fausse API du scratchpad doit :
     - émettre `clock` et `relay_at_ms` sur `playlist_update`, dans les états comme dans les ticks ;
     - répondre à `time_sync` par l'accusé `{t0, ts}` ;
     - savoir jouer : `loading`, puis `playing` sous un nouveau `play_id`, puis `paused`, puis `stalled`.
   - Avec Playwright (Chrome) et le vrai lecteur YouTube, servi par `next start`, mesurer l'écart entre `getCurrentTime()` et la cible (`refClock.positionAt(serverNow(now)) / 1000 + réglage`) :
     - en régime établi : moins de 40 ms après la phase d'attente ;
     - après une pause et une reprise ;
     - après un saut de plus de 2 s ;
     - pendant un blocage simulé : vidéo en pause, puis reprise.
   - Vérifier aussi qu'un saut optimiste ne lance pas la vidéo avant `playing`.
   - Arrêter tous les serveurs lancés.
3. **Après déploiement.**
   - Lire les logs `[SYNC]` du bot sur Railway : le mode (`direct` ou `pipe`) et `choix_1re_trame_ms`.
   - Le Roi règle une fois « Synchro vidéo » sur son appareil.

## Auto-revue : couverture de la spec

| Spec | Tâche |
|---|---|
| §3 bloc `clock` sur l'état et le tick ; `position` et `progress.elapsed` dérivés | B3, B4 |
| §3 `relay_at_ms` (Redis et RPC) | A1, A2 |
| §3 `time_sync` `{t0}` → `{t0, ts}` | A3 (serveur), W4 (client) |
| §4.1 comptage, `preroll`, callbacks par `call_soon_threadsafe`, délégation de `is_opus`, `cleanup`, `_current_error` et `_ytdlp_proc`, `position_ms` | B1 |
| §4.2 enveloppe dans les deux modes ; pré-lecture ; contrôles de génération ; échec sur `b''` ; `play_start` posé après | B2 |
| §4.2 `play_id`, statuts, fenêtre de chargement | B3 |
| §4.2 envois immédiats : 1re trame (B2), pause et reprise (existant, plus `note_resume` en B3), début de blocage (B4), fin de blocage (B2/B4) | B2–B4 |
| §4.2 log `[SYNC]` : mode, délai entre choix et 1re trame, pré-lecture, `average_latency` | B2 |
| §4.3 `publish_progress` transmet `clock` | B4 |
| §5 `redis_listener`, `routes/player.py`, `events.py` | A1, A2, A3 |
| §6.1 timesync : 8 échantillons, plus court aller-retour, rejet au-delà de 2 s, `serverNow` | W1 |
| §6.1 refclock : ordre, recalages (`play_id`, statut, 40 ms), `positionAt`, mode compatibilité | W2 |
| §6.1 controller : seuils, hystérésis, saut sans surcompensation, attente de 3 s, repli à 250 ms / 10 s | W3 |
| §6.2 `time_sync` 5 × 1 s puis toutes les 30 s ; `refclock` nourri par chaque état ; barre sur `refclock` | W4 |
| §6.2 boucle à 4 Hz (PLAYING, onglet visible), vitesse réappliquée après `loadVideoById`, recalage au retour de l'onglet, anciens seuils retirés | W5 |
| §6.2 démarrage gardé ; `crown` sans position qui court ; poster pendant `loading` | W3 (`gateLoad`), W4 (`crown`), W5 |
| §6.2 « Synchro vidéo » : 50 ms, ±3 s, valeur stockée ramenée, aide, aperçu par le régulateur, par appareil | W6 (aperçu : W5) |
| §7 tests : bot, API, site (dont le démarrage gardé) ; navigateur | toutes ; vérification finale |
| §2 compatibilité : site sans `clock`, ancien site face au nouveau bot | W2 et W3 (compat), contrat additif (B, A) |
