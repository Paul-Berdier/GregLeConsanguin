"""Faux Redis du magasin de l'overlay (api.services.overlay_tokens) et ses fixtures, partagés par les tests.

FakeOverlayRedis implémente les commandes du magasin : chaînes (GET, SET et ses options EX / NX / XX / GET /
KEEPTTL, INCR), HASH (HGET, HSET, HGETALL, HDEL), DEL, EXISTS, TTL, EXPIRE (NX) et les transactions d'un
pipeline (WATCH / MULTI / EXEC). Les autres fichiers de test l'importent ainsi :
`from overlay_fakes import overlay_redis, issue_token  # noqa: F401`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import api.services.overlay_tokens as ot
import pytest
import redis

T0 = 1_800_000_000.0

_WRONGTYPE = "WRONGTYPE Operation against a key holding the wrong kind of value"


def _text(value: Any) -> str:
    """Valeur telle que redis-py l'envoie : texte, entier ou flottant (un booléen ou un objet est refusé)."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise redis.DataError(f"Invalid input of type: '{type(value).__name__}'")
    return value if isinstance(value, str) else str(value)


class FakeOverlayRedis:
    """Redis en mémoire, à horloge réglable.

    - `now` : heure du faux (secondes epoch, flottant) ; une échéance est évaluée à chaque accès, comme Redis.
    - `kv` : valeurs stockées, du texte (decode_responses=True) ou, pour un HASH, un dict texte → texte.
    - `fail` : exception levée par toute commande qui atteint le serveur (Redis coupé).
    - `interleave` : appels « d'un autre client » joués juste avant les prochains EXEC (un par EXEC), pour
      provoquer un WatchError comme le ferait Redis.
    - `on_get` : appel `(key)` après chaque GET hors transaction (une révocation pendant une requête).
    - `log` : commandes reçues, dans l'ordre.
    """

    def __init__(self) -> None:
        self.now = T0
        self.kv: dict[str, Any] = {}
        self.fail: BaseException | None = None
        self.interleave: list[Callable[[], Any]] = []
        self.on_get: Callable[[str], Any] | None = None
        self.log: list[tuple] = []
        self._exp: dict[str, float] = {}      # échéances absolues (secondes epoch)
        self._version: dict[str, int] = {}    # versions vues par WATCH

    # ─── Mécanique ───

    def _cmd(self, *args: Any) -> None:
        self.log.append(args)
        if self.fail is not None:
            raise self.fail

    def _touch(self, name: str) -> None:
        self._version[name] = self._version.get(name, 0) + 1

    def _drop(self, name: str) -> None:
        self.kv.pop(name, None)
        self._exp.pop(name, None)
        self._touch(name)

    def _alive(self, name: str) -> bool:
        """La clé existe encore ; échue, elle est retirée (ce qui change sa version, comme pour WATCH)."""
        when = self._exp.get(name)
        if when is not None and self.now >= when:
            self._drop(name)
        return name in self.kv

    def _str(self, name: str) -> str | None:
        if not self._alive(name):
            return None
        value = self.kv[name]
        if isinstance(value, dict):
            raise redis.ResponseError(_WRONGTYPE)
        return value

    def _hash(self, name: str, create: bool = False) -> dict[str, str] | None:
        if not self._alive(name):
            if not create:
                return None
            self.kv[name] = {}
        value = self.kv[name]
        if not isinstance(value, dict):
            raise redis.ResponseError(_WRONGTYPE)
        return value

    # ─── Commandes (effet seul : appelées telles quelles par EXEC) ───

    def _get(self, name: str) -> str | None:
        return self._str(name)

    def _set(self, name: str, value: Any, ex: int | None = None, nx: bool = False, xx: bool = False,
             get: bool = False, keepttl: bool = False) -> bool | str | None:
        old = self._str(name) if get else None
        exists = self._alive(name)
        if (nx and exists) or (xx and not exists):
            return old  # rien d'écrit : l'ancienne valeur avec GET, sinon None
        self.kv[name] = _text(value)
        if ex is not None:
            self._exp[name] = self.now + int(ex)
        elif not keepttl:
            self._exp.pop(name, None)
        self._touch(name)
        return old if get else True

    def _delete(self, *names: str) -> int:
        count = 0
        for name in names:
            if self._alive(name):
                self._drop(name)
                count += 1
        return count

    def _exists(self, *names: str) -> int:
        return sum(1 for name in names if self._alive(name))

    def _ttl(self, name: str) -> int:
        if not self._alive(name):
            return -2
        when = self._exp.get(name)
        if when is None:
            return -1
        return int(when - self.now + 0.5)  # Redis arrondit à la seconde la plus proche

    def _hget(self, name: str, key: str) -> str | None:
        h = self._hash(name)
        return None if h is None else h.get(key)

    def _hset(self, name: str, key: str, value: Any) -> int:
        h = self._hash(name, create=True)
        assert h is not None
        field = _text(key)
        added = field not in h
        h[field] = _text(value)
        self._touch(name)
        return int(added)

    def _hgetall(self, name: str) -> dict[str, str]:
        h = self._hash(name)
        return dict(h) if h else {}

    def _hdel(self, name: str, *keys: str) -> int:
        h = self._hash(name)
        if h is None:
            return 0
        count = sum(1 for k in keys if h.pop(k, None) is not None)
        if not h:
            self._drop(name)  # Redis retire un HASH vidé
        elif count:
            self._touch(name)
        return count

    def _incr(self, name: str) -> int:
        current = self._str(name)
        try:
            value = int("0" if current is None else current) + 1
        except ValueError:
            raise redis.ResponseError("value is not an integer or out of range") from None
        self.kv[name] = str(value)  # texte décimal ; INCR garde l'échéance
        self._touch(name)
        return value

    def _expire(self, name: str, time: int, nx: bool = False) -> bool:
        if not self._alive(name) or (nx and name in self._exp):
            return False
        self._exp[name] = self.now + int(time)
        self._touch(name)
        return True

    # ─── Commandes immédiates (client) ───

    def get(self, name):
        self._cmd("GET", name)
        value = self._get(name)
        if self.on_get is not None:
            self.on_get(name)
        return value

    def set(self, name, value, ex=None, nx=False, xx=False, get=False, keepttl=False):
        self._cmd("SET", name)
        return self._set(name, value, ex=ex, nx=nx, xx=xx, get=get, keepttl=keepttl)

    def delete(self, *names):
        self._cmd("DEL", *names)
        return self._delete(*names)

    def exists(self, *names):
        self._cmd("EXISTS", *names)
        return self._exists(*names)

    def ttl(self, name):
        self._cmd("TTL", name)
        return self._ttl(name)

    def hget(self, name, key):
        self._cmd("HGET", name, key)
        return self._hget(name, key)

    def hset(self, name, key, value):
        self._cmd("HSET", name, key)
        return self._hset(name, key, value)

    def hgetall(self, name):
        self._cmd("HGETALL", name)
        return self._hgetall(name)

    def hdel(self, name, *keys):
        self._cmd("HDEL", name, *keys)
        return self._hdel(name, *keys)

    def incr(self, name):
        self._cmd("INCR", name)
        return self._incr(name)

    def expire(self, name, time, nx=False):
        self._cmd("EXPIRE", name, time)
        return self._expire(name, time, nx=nx)

    def pipeline(self, transaction=True):
        assert transaction, "le magasin de l'overlay écrit toujours en transaction"
        return FakeOverlayPipeline(self)

    def close(self):
        pass


class FakeOverlayPipeline:
    """Pipeline transactionnel de redis-py : après WATCH et avant MULTI, chaque commande part tout de suite ;
    sinon elle est mise en file et jouée d'un bloc par execute(), qui rend la liste des résultats (WatchError si
    une clé surveillée a changé) et remet le pipeline à zéro, comme redis-py."""

    def __init__(self, r: FakeOverlayRedis) -> None:
        self.r = r
        self._watched: dict[str, int] = {}
        self._multi = False
        self._queue: list[tuple[str, tuple, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.reset()
        return False

    def _call(self, op: str, *args: Any, **kw: Any):
        if self._watched and not self._multi:
            return getattr(self.r, op)(*args, **kw)
        self.r.log.append((op.upper(), *args))
        self._queue.append((op, args, kw))
        return self

    def watch(self, *names: str) -> None:
        if self._multi:
            raise redis.RedisError("Cannot issue a WATCH after a MULTI")
        self.r._cmd("WATCH", *names)
        for name in names:
            self.r._alive(name)
            self._watched[name] = self.r._version.get(name, 0)

    def multi(self) -> None:
        if self._multi:
            raise redis.RedisError("Cannot issue nested calls to MULTI")
        if self._queue:
            raise redis.RedisError("Commands without an initial WATCH have already been issued")
        self._multi = True

    def get(self, name):
        return self._call("get", name)

    def hget(self, name, key):
        return self._call("hget", name, key)

    def set(self, name, value, ex=None, nx=False, xx=False, get=False, keepttl=False):
        return self._call("set", name, value, ex=ex, nx=nx, xx=xx, get=get, keepttl=keepttl)

    def delete(self, *names):
        return self._call("delete", *names)

    def hset(self, name, key, value):
        return self._call("hset", name, key, value)

    def hdel(self, name, *keys):
        return self._call("hdel", name, *keys)

    def incr(self, name):
        return self._call("incr", name)

    def expire(self, name, time, nx=False):
        return self._call("expire", name, time, nx=nx)

    def execute(self) -> list:
        try:
            self.r._cmd("EXEC")
            if self.r.interleave:
                self.r.interleave.pop(0)()
            for name in self._watched:
                self.r._alive(name)  # une clé surveillée qui échoit fait échouer EXEC (Redis ≥ 6.0.9)
            if any(self.r._version.get(k, 0) != v for k, v in self._watched.items()):
                raise redis.WatchError("Watched variable changed.")
            return [getattr(self.r, "_" + op)(*args, **kw) for op, args, kw in self._queue]
        finally:
            self.reset()

    def reset(self) -> None:
        self._watched = {}
        self._multi = False
        self._queue = []


@pytest.fixture()
def overlay_redis(monkeypatch) -> FakeOverlayRedis:
    """FakeOverlayRedis branché à la place du client et de l'horloge du magasin de l'overlay."""
    fr = FakeOverlayRedis()
    monkeypatch.setattr(ot, "_get_redis", lambda: fr)
    monkeypatch.setattr(ot, "_now", lambda: fr.now)
    return fr


@pytest.fixture()
def issue_token(overlay_redis):
    """issue(uid=777, guild_id="42", label="GregLC") → jeton porteur frappé par le parcours complet."""
    def issue(uid: int = 777, guild_id: str | None = "42", label: str = "GregLC") -> str:
        d = ot.start_device(label)
        ot.decide(d.user_code, approve=True, uid=uid, guild_id=guild_id,
                  user={"id": str(uid), "username": f"user{uid}", "global_name": None, "avatar": None})
        overlay_redis.now += 5
        minted = ot.poll(d.device_code)
        assert isinstance(minted, ot.Minted), minted
        return minted.access_token
    return issue
