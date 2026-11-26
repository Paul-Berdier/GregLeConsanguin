"""Magasin Redis de l'appli Overwolf : codes d'appareil (RFC 8628), jetons porteurs et limites de débit
(spec 2026-11-25 §3.4).

Clés :
- `greg:overlay:device:{sha256(device_code)}` → JSON {user_code, status, client_name, created_at, interval,
  last_poll_at, uid?, user?, guild_id?}, EX 600 ; status ∈ pending, approved, denied.
- `greg:overlay:user_code:{CODE}` → empreinte de l'appareil (SET NX, EX 600), puis « used » une fois décidé.
- `greg:overlay:token:{sha256(jeton)}` → JSON {tid, uid, label, created_at, last_used_at, expires_at, user,
  default_guild_id}, EX durée du jeton.
- `greg:overlay:tokens:{uid}` → HASH tid → empreinte du jeton (lister, révoquer).
- `greg:ratelimit:{seau}:{sujet}` → compteur, MULTI · INCR · EXPIRE NX · EXEC.

- Ni jeton ni device_code en clair, ni dans Redis ni dans les journaux : seulement leur sha256.
- Usage unique d'un code : l'index passe à « used » (SET XX KEEPTTL) dans la même transaction que la décision de
  l'appareil, sous WATCH des deux clés ; l'index lu dit s'il avait expiré (CODE_EXPIRED) ou déjà servi
  (ALREADY_USED), ce qu'un GETDEL ne distinguerait pas, et une panne avant l'EXEC ne consomme rien.
- Lecture-modification-écriture d'un appareil sous WATCH / MULTI / EXEC (MAX_TRIES essais) : deux sondages
  simultanés ne frappent qu'un jeton, et un sondage n'écrase jamais une décision prise entre-temps.
- Redis injoignable → OverlayError STORAGE_UNAVAILABLE (503), le détail seulement dans les journaux.
- Horodatages en secondes epoch entières, sauf `last_poll_at` (flottant : la marge de slow_down se compte en
  fractions de seconde).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, cast

import redis
from greg_shared.config import settings
from redis.backoff import NoBackoff
from redis.client import Pipeline
from redis.retry import Retry

logger = logging.getLogger("greg.api.overlay")

DEVICE_TTL_S = 600
POLL_INTERVAL_S = 5
SLOW_DOWN_STEP_S = 5
SLOW_DOWN_GRACE_S = 1
LAST_USED_EVERY_S = 300
DEFAULT_TOKEN_TTL_DAYS = 180
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
USER_CODE_LEN = 8
MAX_CODE_TRIES = 5
MAX_TRIES = 3
TOKEN_PREFIX = "greg_ow_"
CLIENT_NAME_MAX = 40
MSG_STORAGE_UNAVAILABLE = "Impossible de vérifier l'appareil pour le moment, réessayez dans un instant."

DEVICE_KEY = "greg:overlay:device:"
USER_CODE_KEY = "greg:overlay:user_code:"
TOKEN_KEY = "greg:overlay:token:"
TOKENS_KEY = "greg:overlay:tokens:"
RATE_LIMIT_KEY = "greg:ratelimit:"
USED = "used"
_STATUSES = ("pending", "approved", "denied")

# fullmatch : « $ » de re.match accepterait un « \n » final
_USER_CODE_RE = re.compile(f"[{USER_CODE_ALPHABET}]{{{USER_CODE_LEN}}}")


class OverlayError(Exception):
    """Erreur codée du parcours de l'appli : {ok: False, error} (+ message pour STORAGE_UNAVAILABLE)."""

    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"ok": False, "error": self.code}
        if self.code == "STORAGE_UNAVAILABLE":
            body["message"] = MSG_STORAGE_UNAVAILABLE
        return body


@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str  # affiché XXXX-XXXX
    expires_in: int
    interval: int


@dataclass(frozen=True)
class TokenRecord:
    tid: str
    uid: int
    label: str
    created_at: int
    last_used_at: int
    expires_at: int
    user: dict
    default_guild_id: str | None
    token_hash: str

    def public(self) -> dict[str, Any]:
        """Ce que l'utilisateur voit de ses appareils : jamais l'empreinte."""
        return {"id": self.tid, "label": self.label, "created_at": self.created_at,
                "last_used_at": self.last_used_at, "expires_at": self.expires_at}


@dataclass(frozen=True)
class Minted:
    access_token: str
    record: TokenRecord
    expires_in: int


# ─── Redis ───

_client: redis.Redis | None = None


def _build_client() -> redis.Redis:
    """Même client que le chansonnier (library_store._build_client) : timeouts courts, un seul nouvel essai,
    immédiat (Railway coupe les sockets inactives)."""
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
        retry=Retry(NoBackoff(), 1),
        retry_on_error=[redis.ConnectionError, redis.TimeoutError],
    )


def _get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def _now() -> float:
    return time.time()


def _unavailable(e: BaseException) -> OverlayError:
    # Le détail reste dans les journaux : la réponse ne porte que le code et le message FR.
    logger.warning("Overlay : Redis injoignable (%s: %s)", type(e).__name__, e)
    return OverlayError("STORAGE_UNAVAILABLE", 503)


def _redis() -> redis.Redis:
    """Client Redis, ou STORAGE_UNAVAILABLE si même sa construction échoue (REDIS_URL invalide…)."""
    try:
        return _get_redis()
    except (redis.RedisError, OSError, ValueError) as e:
        raise _unavailable(e) from None


def _retry_or_raise(e: redis.WatchError, what: str, attempt: int) -> None:
    """Conflit WATCH : on relit et on rejoue. Mais un WatchError levé par une connexion perdue PENDANT l'EXEC
    (redis-py) laisse l'écriture incertaine : rejouer compterait un sondage deux fois → 503."""
    if isinstance(e.__context__, (redis.ConnectionError, redis.TimeoutError, OSError)):
        raise _unavailable(e.__context__) from None
    logger.info("Overlay : appareil modifié en parallèle pendant %s (essai %d/%d)", what, attempt, MAX_TRIES)


def _busy(what: str) -> OverlayError:
    logger.warning("Overlay : %d conflits d'affilée pendant %s, abandon", MAX_TRIES, what)
    return OverlayError("STORAGE_UNAVAILABLE", 503)


def _dump(data: dict[str, Any]) -> str:
    # ensure_ascii (défaut) : une demi-paire isolée du corps reste échappée, l'encodeur strict de redis-py passe
    return json.dumps(data, separators=(",", ":"))


def _load(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        logger.warning("Overlay : valeur illisible ignorée")
        return None
    return data


def _load_device(raw: Any) -> dict[str, Any] | None:
    dev = _load(raw)
    return dev if dev is not None and dev.get("status") in _STATUSES else None


def _tokens_key(uid: int) -> str:
    return f"{TOKENS_KEY}{int(uid)}"


def _token_json(rec: TokenRecord) -> str:
    data = dataclasses.asdict(rec)
    del data["token_hash"]  # c'est le nom de la clé
    return _dump(data)


def _token_from(raw: Any, token_hash: str) -> TokenRecord | None:
    data = _load(raw)
    if data is None:
        return None
    try:
        return TokenRecord(
            tid=data["tid"],
            uid=int(data["uid"]),
            label=data["label"],
            created_at=int(data["created_at"]),
            last_used_at=int(data["last_used_at"]),
            expires_at=int(data["expires_at"]),
            user=data["user"],
            default_guild_id=data.get("default_guild_id"),
            token_hash=token_hash,
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("Overlay : jeton illisible ignoré")
        return None


# ─── Codes ───

def hash_secret(s: str) -> str:
    """Empreinte sha256 (hexadécimal) d'un jeton ou d'un device_code : seule forme stockée. surrogatepass : une
    demi-paire isolée venue d'un corps JSON donne une empreinte (inconnue) plutôt qu'une erreur."""
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()


def token_ttl_s() -> int:
    """Durée d'un jeton : OVERLAY_TOKEN_TTL_DAYS (entier ≥ 1, sinon 180) jours, en secondes."""
    raw = os.environ.get("OVERLAY_TOKEN_TTL_DAYS")
    try:
        days = DEFAULT_TOKEN_TTL_DAYS if raw is None else int(raw)
    except ValueError:
        days = 0
    if days < 1:
        logger.warning("OVERLAY_TOKEN_TTL_DAYS=%r invalide : %d jours retenus", raw, DEFAULT_TOKEN_TTL_DAYS)
        days = DEFAULT_TOKEN_TTL_DAYS
    return days * 86_400


def normalize_user_code(raw: object) -> str | None:
    """Saisie d'un code (« bcdf-ghjk », « BCDF GHJK »…) → « BCDFGHJK », ou None s'il n'en a pas la forme."""
    if not isinstance(raw, str):
        return None
    code = "".join(ch for ch in raw if ch.isalnum()).upper()
    return code if _USER_CODE_RE.fullmatch(code) else None


def format_user_code(code: str) -> str:
    half = USER_CODE_LEN // 2
    return f"{code[:half]}-{code[half:]}"


def _draw_user_code() -> str:
    return "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LEN))


# ─── Parcours de l'appareil ───

def start_device(client_name: str) -> DeviceStart:
    """Nouvel appareil en attente : un code libre (SET NX, nouveau tirage sur collision), puis l'appareil."""
    r = _redis()
    device_code = secrets.token_urlsafe(32)
    h = hash_secret(device_code)
    try:
        for _ in range(MAX_CODE_TRIES):
            code = _draw_user_code()
            if r.set(USER_CODE_KEY + code, h, ex=DEVICE_TTL_S, nx=True):
                break
        else:
            logger.warning("Overlay : %d codes tirés déjà pris d'affilée, abandon", MAX_CODE_TRIES)
            raise OverlayError("STORAGE_UNAVAILABLE", 503)
        r.set(DEVICE_KEY + h, _dump({
            "user_code": code,
            "status": "pending",
            "client_name": client_name,
            "created_at": int(_now()),
            "interval": POLL_INTERVAL_S,
            "last_poll_at": None,
        }), ex=DEVICE_TTL_S)
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    return DeviceStart(device_code, format_user_code(code), DEVICE_TTL_S, POLL_INTERVAL_S)


def lookup_user_code(code: str) -> dict[str, Any] | None:
    """Ce que /lier montre avant d'autoriser : {client_name, created_at, expires_in} ; None si le code est
    inconnu, a déjà servi ou a expiré."""
    norm = normalize_user_code(code)
    if norm is None:
        return None
    r = _redis()
    try:
        h = cast("str | None", r.get(USER_CODE_KEY + norm))  # decode_responses=True : du texte
        if h is None or h == USED:
            return None
        key = DEVICE_KEY + h
        dev = _load_device(r.get(key))
        if dev is None or dev["status"] != "pending":
            return None
        ttl = r.ttl(key)
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    if ttl <= 0:
        return None
    return {"client_name": dev.get("client_name"), "created_at": dev.get("created_at"), "expires_in": ttl}


def decide(code: str, *, approve: bool, uid: int, user: dict, guild_id: str | None) -> None:
    """Autorise ou refuse l'appareil du code, une seule fois : CODE_EXPIRED (404), ALREADY_USED (409).

    Une seule transaction : WATCH de l'index et de l'appareil, lecture et contrôles, puis MULTI · SET « used » XX
    KEEPTTL de l'index · SET XX KEEPTTL de l'appareil décidé · EXEC. Une panne avant l'EXEC ne consomme pas le code
    (une nouvelle tentative réussit) ; sous WATCH, redis-py ne rejoue jamais l'EXEC ; un clic concurrent qui passe
    avant notre EXEC le fait échouer (WatchError) : on relit, et l'index dit alors ALREADY_USED.
    """
    norm = normalize_user_code(code)
    if norm is None:
        raise OverlayError("CODE_EXPIRED", 404)
    idx = USER_CODE_KEY + norm
    r = _redis()
    try:
        with r.pipeline(transaction=True) as pipe:
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    pipe.watch(idx)
                    h = cast("str | None", pipe.get(idx))  # decode_responses=True : du texte
                    if h is None:
                        raise OverlayError("CODE_EXPIRED", 404)
                    if h == USED:
                        raise OverlayError("ALREADY_USED", 409)
                    key = DEVICE_KEY + h
                    pipe.watch(key)
                    dev = _load_device(pipe.get(key))
                    if dev is None:
                        raise OverlayError("CODE_EXPIRED", 404)
                    if dev["status"] != "pending":
                        raise OverlayError("ALREADY_USED", 409)
                    dev.update(status="approved" if approve else "denied", uid=int(uid), user=user,
                               guild_id=guild_id)
                    pipe.multi()
                    pipe.set(idx, USED, xx=True, keepttl=True)
                    pipe.set(key, _dump(dev), xx=True, keepttl=True)
                    used, written = pipe.execute()
                    if not (used and written):  # échu entre la lecture et l'écriture
                        raise OverlayError("CODE_EXPIRED", 404)
                    return
                except redis.WatchError as e:
                    _retry_or_raise(e, "la décision", attempt)
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    raise _busy("la décision")


def poll(device_code: str) -> Minted | str:
    """Sondage de l'appli : le jeton (Minted) une fois autorisé, sinon une erreur RFC 8628
    (authorization_pending, slow_down, access_denied, expired_token)."""
    if not isinstance(device_code, str):
        return "expired_token"
    key = DEVICE_KEY + hash_secret(device_code)
    r = _redis()
    try:
        with r.pipeline(transaction=True) as pipe:
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    pipe.watch(key)
                    dev = _load_device(pipe.get(key))
                    if dev is None:
                        return "expired_token"
                    if dev["status"] == "approved":
                        return _mint(pipe, key, dev)
                    if dev["status"] == "denied":
                        pipe.multi()
                        pipe.delete(key)
                        pipe.execute()
                        return "access_denied"
                    return _wait(pipe, key, dev)
                except redis.WatchError as e:
                    _retry_or_raise(e, "le sondage", attempt)
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    raise _busy("le sondage")


def _wait(pipe: Pipeline, key: str, dev: dict[str, Any]) -> str:
    """Appareil en attente : slow_down (+5 s) si l'appli sonde plus vite que l'intervalle, moins une seconde de
    marge pour la gigue de ses minuteries ; l'heure du sondage est notée dans les deux cas."""
    now = _now()
    interval = int(dev.get("interval") or POLL_INTERVAL_S)
    last = dev.get("last_poll_at")
    slow = last is not None and now - last < interval - SLOW_DOWN_GRACE_S
    if slow:
        interval += SLOW_DOWN_STEP_S
    dev.update(interval=interval, last_poll_at=now)
    pipe.multi()
    pipe.set(key, _dump(dev), xx=True, keepttl=True)
    if not pipe.execute()[0]:  # échu entre la lecture et l'écriture
        return "expired_token"
    return "slow_down" if slow else "authorization_pending"


def _mint(pipe: Pipeline, key: str, dev: dict[str, Any]) -> Minted:
    """Appareil autorisé : dans un seul MULTI, l'appareil disparaît et le jeton naît (clé et entrée du HASH)."""
    now = int(_now())
    ttl = token_ttl_s()
    uid = int(dev["uid"])
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    rec = TokenRecord(
        tid=secrets.token_hex(8),
        uid=uid,
        label=dev["client_name"],
        created_at=now,
        last_used_at=now,
        expires_at=now + ttl,
        user=dev["user"],
        default_guild_id=dev.get("guild_id"),
        token_hash=hash_secret(token),
    )
    pipe.multi()
    pipe.delete(key)
    pipe.set(TOKEN_KEY + rec.token_hash, _token_json(rec), ex=ttl)
    pipe.hset(_tokens_key(uid), rec.tid, rec.token_hash)
    pipe.execute()
    return Minted(token, rec, ttl)


# ─── Jetons ───

def resolve(token: str) -> TokenRecord | None:
    """Enregistrement du jeton porteur, ou None (préfixe absent, jeton inconnu, expiré ou révoqué).

    last_used_at est réécrit au plus une fois toutes les LAST_USED_EVERY_S secondes, par SET XX KEEPTTL : un
    jeton révoqué entre la lecture et l'écriture n'est jamais recréé, et son échéance ne bouge pas.
    """
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX):
        return None
    th = hash_secret(token)
    key = TOKEN_KEY + th
    r = _redis()
    try:
        rec = _token_from(r.get(key), th)
        if rec is None:
            return None
        now = int(_now())
        if now - rec.last_used_at >= LAST_USED_EVERY_S:
            rec = dataclasses.replace(rec, last_used_at=now)
            if not r.set(key, _token_json(rec), xx=True, keepttl=True):
                return None  # révoqué pendant la requête
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    return rec


def is_live(uid: int, tid: str) -> bool:
    """Le jeton `tid` de `uid` existe encore (ni révoqué, ni expiré)."""
    r = _redis()
    try:
        th = cast("str | None", r.hget(_tokens_key(uid), tid))
        return th is not None and bool(r.exists(TOKEN_KEY + th))
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None


def list_tokens(uid: int) -> list[TokenRecord]:
    """Jetons de `uid`, du plus récent au plus ancien ; ceux qui ont expiré sont retirés du HASH."""
    hkey = _tokens_key(uid)
    r = _redis()
    records: list[TokenRecord] = []
    try:
        gone = []
        for tid, th in cast("dict[str, str]", r.hgetall(hkey)).items():
            raw = r.get(TOKEN_KEY + th)
            if raw is None:
                gone.append(tid)
                continue
            rec = _token_from(raw, th)
            if rec is not None:
                records.append(rec)
        if gone:
            r.hdel(hkey, *gone)
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    records.sort(key=lambda rec: (rec.created_at, rec.tid), reverse=True)
    return records


def revoke(uid: int, tid: str) -> bool:
    """Révoque le jeton `tid` de `uid` (clé et entrée du HASH, un seul MULTI) ; faux s'il n'est pas à lui."""
    hkey = _tokens_key(uid)
    r = _redis()
    try:
        th = cast("str | None", r.hget(hkey, tid))
        if th is None:
            return False
        with r.pipeline(transaction=True) as pipe:
            pipe.delete(TOKEN_KEY + th)
            pipe.hdel(hkey, tid)
            pipe.execute()
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    return True


# ─── Limites de débit ───

def hit_rate_limit(bucket: str, subject: str, limit: int, window_s: int) -> bool:
    """Compte une requête de `subject` dans `bucket` ; vrai si elle dépasse `limit` sur la fenêtre.

    INCR et EXPIRE NX dans un seul MULTI : un compteur a toujours une échéance (une coupure entre deux
    commandes séparées laisserait un 429 permanent), et NX ne prolonge jamais la fenêtre en cours.
    """
    key = f"{RATE_LIMIT_KEY}{bucket}:{subject}"
    r = _redis()
    try:
        with r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s, nx=True)
            count, _ = pipe.execute()
    except (redis.RedisError, OSError) as e:
        raise _unavailable(e) from None
    return int(count) > limit
