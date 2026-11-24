"""Chansonnier du Roi — coups de cœur et playlists de chaque utilisateur, dans Redis (spec 2026-11-23 §3).

Une clé par Roi : `greg:library:{discord_id}` → JSON `{"v": 1, "likes": [Track], "playlists": [Playlist]}`.
Le disque du bot est perdu à chaque redéploiement (Railway) ; Redis a son volume, et l'API sait déjà qui est
connecté (SEC-C1) : aucune commande au bot, aucune guild en jeu.

- Track stocké : {url, title, artist, duration, thumb, provider, added_at} (nettoyé par clean_track).
- Playlist : {id, name, tracks, created_at, updated_at} ; id = secrets.token_urlsafe(8).
- Identité d'un titre (doublons) : track_key — `yt:<id>` pour une vidéo YouTube, sinon `url:<url>`.
  Le site calcule la même clé (trackKey, services/web/src/lib/library.ts).
- Modifications en lecture-écriture sous WATCH / MULTI / EXEC (deux onglets du même Roi), MAX_TRIES essais,
  sinon STORAGE_UNAVAILABLE (503). Redis injoignable → STORAGE_UNAVAILABLE, jamais de trace renvoyée.
- Budget de MAX_LIBRARY_BYTES octets par Roi (valeur stockée) : une écriture qui le dépasserait en grossissant
  → LIMIT_REACHED (limit="size") ; retirer reste toujours possible.
- Valeur illisible ou étrangère (JSON cassé, autre version, entrées invalides) : lue comme vide (ou sans les
  entrées invalides) et journalisée ; JAMAIS écrasée à l'aveugle : la première écriture qui la remplace copie
  d'abord la valeur brute sous `greg:library:{discord_id}:corrupt:{epoch}` (même transaction).
"""
from __future__ import annotations

import json
import logging
import math
import re
import secrets
import time
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlsplit

import redis
from greg_shared.config import settings
from redis.backoff import NoBackoff
from redis.retry import Retry

logger = logging.getLogger("greg.api.library")

KEY_PREFIX = "greg:library:"
VERSION = 1
MAX_TRIES = 5

# Plafonds (renvoyés au site dans library.limits)
LIMIT_LIKES = 500
LIMIT_PLAYLISTS = 50
LIMIT_TRACKS = 200
LIMIT_NAME = 60

# Budget d'octets de la valeur stockée (JSON UTF-8). Les plafonds comptent des titres, pas leur poids : 10 500
# titres aux champs pleins (liens de 500, textes en caractères de 4 octets) pèseraient ~25 Mo, relus, réécrits et
# renvoyés en entier à chaque cœur. Un chansonnier plein de vrais titres YouTube en pèse ~3 (test_library_store) ;
# 6 Mio laissent de la marge aux vignettes longues des playlists développées, sans rouvrir la porte aux 25 Mo.
MAX_LIBRARY_BYTES = 6 * 1024 * 1024

MAX_URL = 500
MAX_TITLE = 200
MAX_ARTIST = 120
MAX_DURATION = 86400
# Titres acceptés dans UN corps de requête (create / add) : au-delà, 400 plutôt qu'un travail sans borne.
MAX_INPUT_TRACKS = 500
PROVIDERS = ("youtube", "soundcloud")

# Les 6 clés d'un item de file (mêmes que /player/enqueue) : ce que /queue/add_many transmet au bot.
QUEUE_ITEM_KEYS = ("url", "title", "artist", "duration", "thumb", "provider")

# Messages FR (champ `message`), au Roi : vouvoiement.
MSG_INVALID_TRACK = f"Titre illisible : il lui faut un lien http(s) d'au plus {MAX_URL} caractères."
MSG_INVALID_NAME = f"Le nom d'une playlist compte de 1 à {LIMIT_NAME} caractères."
MSG_INVALID_REQUEST = "Requête invalide."
MSG_BAD_POSITION = "Cette position n'existe pas dans la playlist."
MSG_PLAYLIST_NOT_FOUND = "Cette playlist n'existe pas (ou plus)."
MSG_LIMIT_LIKES = f"Vous avez atteint la limite de {LIMIT_LIKES} coups de cœur."
MSG_LIMIT_PLAYLISTS = f"Vous avez atteint la limite de {LIMIT_PLAYLISTS} playlists."
MSG_LIMIT_SIZE = "Votre chansonnier est plein : retirez des titres ou des playlists avant d'en ajouter."
MSG_STORAGE_UNAVAILABLE = "Le chansonnier est injoignable pour le moment : réessayez dans un instant."
MSG_STORAGE_BUSY = "Le chansonnier est modifié ailleurs en même temps : réessayez dans un instant."
MSG_STALE = "Cette playlist a changé ailleurs entre-temps : rien n'a été déplacé, relisez-la."

# id de playlist : alphabet de token_urlsafe, longueur bornée (jamais de « : » ni de « / » dans une requête).
# Lu par fullmatch : « $ » de re.match accepte un « \n » final, qu'une restauration (id choisi par le site)
# stockerait alors tel quel.
_PLAYLIST_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Mêmes formes que VIDEO_ID / YOUTUBE_HOST du site (services/web/src/lib/format.ts) : ?v=, /shorts/, /live/,
# /embed/ (sauf videoseries), youtu.be/, anciennes formes /v/ /e/ /watch/ ; hôtes youtube.com (www., m.,
# music.…), youtu.be, youtube-nocookie.com.
_YT_ID_RE = re.compile(
    r"(?:[?&]v=|/shorts/|/live/|/embed/(?!videoseries)|youtu\.be/|\.com/(?:v|e|watch)/)([A-Za-z0-9_-]{11})"
)
_YT_HOST_RE = re.compile(r"(?:^|\.)(?:youtube\.com|youtu\.be|youtube-nocookie\.com)$")
_SC_HOST_RE = re.compile(r"(?:^|\.)soundcloud\.com$")
_WS_RE = re.compile(r"\s")
# Caractères de contrôle (catégorie Cc : U+0000..U+001F, U+007F..U+009F) et demi-paires de substitution
# (U+D800..U+DFFF : un « \ud83d » isolé, emoji coupé en deux côté JS, passe json.loads mais pas l'encodeur
# UTF-8 strict de redis-py → UnicodeEncodeError, 500). Regex et non boucle par caractère : chaque lecture
# renettoie toute la bibliothèque (jusqu'à ~10 000 titres).
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
# Ceux qui ne sont pas des blancs (str.isspace) : retirés du texte ; les blancs, eux, sont réduits par split().
_CTRL_NOT_SPACE_RE = re.compile(r"[\x00-\x08\x0e-\x1b\x7f-\x84\x86-\x9f\ud800-\udfff]")


class LibraryError(Exception):
    """Erreur codée d'une route du chansonnier : {ok: False, error, message, …} et son code HTTP."""

    def __init__(self, code: str, message: str, status: int, **extra: Any):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, **self.extra}


def _invalid(message: str = MSG_INVALID_REQUEST, **extra: Any) -> LibraryError:
    return LibraryError("INVALID_REQUEST", message, 400, **extra)


# ─── Redis ───

_client: redis.Redis | None = None


def _build_client() -> redis.Redis:
    """Client à timeouts courts : une route du site ne doit jamais attendre Redis 20 s (cf. bot_bridge).

    Un seul nouvel essai, immédiat : Railway coupe les sockets inactives, la 1re commande après une longue
    pause tombe sur une connexion morte. Sous WATCH, redis-py ne rejoue rien : il lève WatchError.
    """
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


def _reset_redis() -> None:
    """Ferme et jette le client caché : le prochain _get_redis() en recrée un."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except (redis.RedisError, OSError) as e:
            logger.debug("Fermeture du client Redis du chansonnier : %s", e)
    _client = None


def library_key(uid: int) -> str:
    return f"{KEY_PREFIX}{int(uid)}"


def _unavailable(uid: int, e: BaseException) -> LibraryError:
    # Le détail reste dans les journaux : la réponse ne porte que le code et le message FR.
    # Pas de _reset_redis() ici : close() viderait le pool partagé, connexions des autres requêtes en cours comprises
    # (fausses 503 en cascade). Le pool jette seul une connexion cassée ; le client n'est refait que s'il n'a pas pu naître.
    logger.warning("Chansonnier de %s : Redis injoignable (%s: %s)", uid, type(e).__name__, e)
    return LibraryError("STORAGE_UNAVAILABLE", MSG_STORAGE_UNAVAILABLE, 503)


def _client_for(uid: int) -> redis.Redis:
    """Client Redis, ou STORAGE_UNAVAILABLE si même sa construction échoue (REDIS_URL invalide…)."""
    try:
        return _get_redis()
    except (redis.RedisError, OSError, ValueError) as e:
        raise _unavailable(uid, e) from None


# ─── Identité d'un titre ───

def _host(url: str) -> str:
    s = url.strip()
    if "://" not in s:
        s = "https://" + s
    try:
        return (urlsplit(s).hostname or "").lower()
    except ValueError:
        return ""


def youtube_id(url: str) -> str | None:
    """Id (11 caractères) de la vidéo YouTube visée par `url`, sinon None."""
    s = str(url or "")
    m = _YT_ID_RE.search(s)
    return m.group(1) if m and _YT_HOST_RE.search(_host(s)) else None


def track_key(url: str) -> str:
    """Identité d'un titre (doublons) : `yt:<id>` pour une vidéo YouTube, sinon `url:<url>` sans aucun blanc
    ni « / » final. Même règle que trackKey côté site."""
    s = str(url or "")
    vid = youtube_id(s)
    if vid:
        return f"yt:{vid}"
    return "url:" + _WS_RE.sub("", s).rstrip("/")


# ─── Nettoyage des entrées ───

def clean_text(value: str) -> str:
    """Caractères de contrôle et demi-paires isolées retirés, blancs réduits à une espace, bords rognés."""
    return " ".join(_CTRL_NOT_SPACE_RE.sub("", value).split())


def _http_url(value: str, max_len: int) -> str | None:
    """Lien http(s) absolu d'au plus max_len caractères, sans blanc, contrôle, demi-paire isolée ni « \\ »,
    sinon None."""
    s = value.strip()
    # « \ » : urlsplit le garde dans l'hôte (https://a.b\@youtube.com → youtube.com) quand le navigateur le
    # lit comme « / » (→ a.b) ; refusé, sinon l'identité (yt:…) et le fournisseur mentiraient sur la cible.
    if not s or len(s) > max_len or "\\" in s or _WS_RE.search(s) or _CTRL_RE.search(s):
        return None
    try:
        u = urlsplit(s)
        host = u.hostname
    except ValueError:
        return None
    if u.scheme.lower() not in ("http", "https") or not host:
        return None
    return s


def _provider_of(url: str) -> str | None:
    host = _host(url)
    if _YT_HOST_RE.search(host):
        return "youtube"
    if _SC_HOST_RE.search(host):
        return "soundcloud"
    return None


def _finite(n: float) -> bool:
    """Nombre fini et convertible en flottant. Un entier JSON de 400 chiffres est lu tel quel par json.loads :
    math.isfinite lève alors OverflowError (500) ; il est refusé comme 1e400, que json.loads lit inf."""
    try:
        return math.isfinite(n)
    except OverflowError:
        return False


def _opt_str(raw: dict, *names: str) -> str | None:
    """Premier champ présent et non null parmi `names` : str attendu (sinon INVALID_TRACK)."""
    for n in names:
        v = raw.get(n)
        if v is None:
            continue
        if not isinstance(v, str):
            raise LibraryError("INVALID_TRACK", MSG_INVALID_TRACK, 400)
        return v
    return None


def clean_track(raw: Any, added_at: int = 0) -> dict[str, Any]:
    """Track stocké {url, title, artist, duration, thumb, provider, added_at}, ou LibraryError INVALID_TRACK.

    Refusé (400) : pas un objet, url absente / pas http(s) / > 500 caractères / avec des blancs, ou un champ
    du mauvais type JSON (title / artist / thumb / provider : texte ou null ; duration : nombre fini ou null).
    Nettoyé sans refus : title et artist (contrôles retirés, blancs réduits, coupés à 200 / 120 ; title vide →
    l'url), duration hors de 0..86400 → null, thumb qui n'est pas un lien http(s) d'au plus 500 → null,
    provider hors de youtube / soundcloud → déduit de l'hôte. `thumbnail` est accepté pour `thumb`.
    """
    if not isinstance(raw, dict):
        raise LibraryError("INVALID_TRACK", MSG_INVALID_TRACK, 400)
    url = raw.get("url")
    url = _http_url(url, MAX_URL) if isinstance(url, str) else None
    if url is None:
        raise LibraryError("INVALID_TRACK", MSG_INVALID_TRACK, 400)

    title = clean_text(_opt_str(raw, "title") or "")[:MAX_TITLE].rstrip() or url[:MAX_TITLE]
    artist = clean_text(_opt_str(raw, "artist") or "")[:MAX_ARTIST].rstrip() or None

    duration = raw.get("duration")
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not _finite(duration):
            raise LibraryError("INVALID_TRACK", MSG_INVALID_TRACK, 400)
        duration = int(duration)
        if not 0 <= duration <= MAX_DURATION:
            duration = None

    thumb = _opt_str(raw, "thumb", "thumbnail")
    thumb = _http_url(thumb, MAX_URL) if thumb is not None else None

    provider = (_opt_str(raw, "provider") or "").strip().lower()
    if provider not in PROVIDERS:
        provider = _provider_of(url)

    return {
        "url": url,
        "title": title,
        "artist": artist,
        "duration": duration,
        "thumb": thumb,
        "provider": provider,
        "added_at": int(added_at),
    }


def clean_tracks(raw: Any, added_at: int = 0, max_items: int = MAX_INPUT_TRACKS) -> list[dict[str, Any]]:
    """Liste de tracks nettoyés. Pas une liste / trop longue → INVALID_REQUEST ; une entrée invalide →
    INVALID_TRACK avec `index` (rien n'est écrit : le site filtre ses titres sans lien avant d'envoyer)."""
    if not isinstance(raw, list):
        raise _invalid()
    if len(raw) > max_items:
        raise _invalid(f"Trop de titres d'un coup ({max_items} au plus).")
    out = []
    for i, t in enumerate(raw):
        try:
            out.append(clean_track(t, added_at))
        except LibraryError as e:
            raise LibraryError(e.code, e.message, e.status, index=i) from None
    return out


def clean_name(raw: Any) -> str:
    """Nom de playlist : 1 à 60 caractères après nettoyage (sinon INVALID_NAME)."""
    if not isinstance(raw, str):
        raise LibraryError("INVALID_NAME", MSG_INVALID_NAME, 400)
    name = clean_text(raw)
    if not 1 <= len(name) <= LIMIT_NAME:
        raise LibraryError("INVALID_NAME", MSG_INVALID_NAME, 400)
    return name


def clean_label(raw: Any) -> str | None:
    """Libellé facultatif d'un lot (/queue/add_many) : texte nettoyé, coupé à 200, ou None."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _invalid()
    return clean_text(raw)[:MAX_TITLE].rstrip() or None


def clean_playlist_id(raw: Any) -> str:
    if not isinstance(raw, str) or not _PLAYLIST_ID_RE.fullmatch(raw):
        raise _invalid()
    return raw


def clean_url_ref(raw: Any) -> str:
    """Lien désignant un titre à retirer (comparé par track_key) : texte non vide d'au plus 500 caractères."""
    if not isinstance(raw, str):
        raise _invalid()
    s = raw.strip()
    if not s or len(s) > MAX_URL:
        raise _invalid()
    return s


def clean_index(raw: Any) -> int:
    """Position dans une playlist : entier JSON >= 0 (ni booléen, ni texte, ni flottant)."""
    if type(raw) is not int or raw < 0:
        raise _invalid(MSG_BAD_POSITION)
    return raw


def clean_position(raw: Any) -> int | None:
    """Rang facultatif d'une insertion (annulations) : absent ou null → None ; sinon entier JSON (ni booléen, ni
    texte, ni flottant), négatif ou trop grand compris : l'opération le borne à la liste qu'elle trouve."""
    if raw is None:
        return None
    if type(raw) is not int:
        raise _invalid()
    return raw


def _past_epoch(v: Any, now: int) -> int:
    """Date d'origine renvoyée par le site : entier de 0 à now gardé, sinon now (ni futur, ni texte, ni booléen)."""
    return v if type(v) is int and 0 <= v <= now else now


def clean_restored_playlist(raw: Any, now: int) -> dict[str, Any]:
    """Playlist rendue par l'annulation d'une suppression (POST /library/playlists/restore), forme stockée.

    id au format d'un id de playlist (sinon INVALID_REQUEST) ; nom et titres nettoyés comme à la création
    (INVALID_NAME, INVALID_TRACK avec `index`, 500 titres au plus par requête ; doublons écartés, LIMIT_TRACKS
    gardés). Les dates d'origine (playlist et titres) restent quand ce sont des entiers de 0 à now, sinon now.
    """
    if not isinstance(raw, dict):
        raise _invalid()
    pid = clean_playlist_id(raw.get("id"))
    name = clean_name(raw.get("name"))
    raw_tracks = raw.get("tracks")
    tracks = [] if raw_tracks is None else clean_tracks(raw_tracks, now)
    # clean_tracks rend une entrée par titre reçu, dans l'ordre (sinon il lève) : chacune retrouve sa date.
    for t, r in zip(tracks, raw_tracks or []):
        t["added_at"] = _past_epoch(r.get("added_at"), now)
    return {
        "id": pid,
        "name": name,
        "tracks": _unique(tracks)[:LIMIT_TRACKS],
        "created_at": _past_epoch(raw.get("created_at"), now),
        "updated_at": _past_epoch(raw.get("updated_at"), now),
    }


# ─── Lecture de la valeur stockée ───

def _empty() -> dict[str, list]:
    return {"likes": [], "playlists": []}


def _epoch(v: Any) -> int:
    return v if type(v) is int and v >= 0 else 0


def _stored_tracks(raw: Any) -> tuple[list[dict], bool]:
    """Tracks relus (même nettoyage qu'à l'écriture) ; (liste, quelque chose a été écarté ?)."""
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        return [], True
    out: list[dict] = []
    seen = set()
    lossy = False
    for t in raw:
        try:
            tr = clean_track(t, _epoch(t.get("added_at")) if isinstance(t, dict) else 0)
        except LibraryError:
            lossy = True
            continue
        k = track_key(tr["url"])
        if k in seen:
            lossy = True
            continue
        seen.add(k)
        out.append(tr)
    return out, lossy


def _stored_playlist(raw: Any) -> tuple[dict | None, bool]:
    if not isinstance(raw, dict):
        return None, True
    try:
        pid = clean_playlist_id(raw.get("id"))
        name = clean_name(raw.get("name"))
    except LibraryError:
        return None, True
    tracks, lossy = _stored_tracks(raw.get("tracks"))
    return {
        "id": pid,
        "name": name,
        "tracks": tracks,
        "created_at": _epoch(raw.get("created_at")),
        "updated_at": _epoch(raw.get("updated_at")),
    }, lossy


def parse_library(raw: str | None, uid: int = 0) -> tuple[dict[str, list], bool]:
    """Valeur brute de Redis → (état {likes, playlists}, lossy).

    lossy = la valeur existe mais n'a pas pu être relue entière (JSON cassé, autre version, entrées
    invalides ou en double) : l'état est ce qui en a été sauvé, et la prochaine écriture garde une copie
    de la valeur brute avant de la remplacer.
    """
    if raw is None:
        return _empty(), False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Chansonnier de %s illisible (JSON invalide) : lu comme vide", uid)
        return _empty(), True
    if not isinstance(data, dict) or data.get("v") != VERSION:
        version = data.get("v") if isinstance(data, dict) else type(data).__name__
        logger.warning("Chansonnier de %s étranger (v=%r, attendu %d) : lu comme vide", uid, version, VERSION)
        return _empty(), True

    likes, lossy = _stored_tracks(data.get("likes"))
    playlists: list[dict] = []
    ids = set()
    raw_pls = data.get("playlists")
    if raw_pls is not None and not isinstance(raw_pls, list):
        raw_pls, lossy = [], True
    for p in raw_pls or []:
        pl, pl_lossy = _stored_playlist(p)
        lossy = lossy or pl_lossy
        if pl is None or pl["id"] in ids:
            lossy = True
            continue
        ids.add(pl["id"])
        playlists.append(pl)
    if lossy:
        logger.warning("Chansonnier de %s : entrées invalides écartées à la lecture", uid)
    return {"likes": likes, "playlists": playlists}, lossy


def _dump(state: dict[str, list]) -> str:
    return json.dumps({"v": VERSION, "likes": state["likes"], "playlists": state["playlists"]},
                      ensure_ascii=False, separators=(",", ":"))


def limits() -> dict[str, int]:
    return {"likes": LIMIT_LIKES, "playlists": LIMIT_PLAYLISTS, "tracks": LIMIT_TRACKS, "name": LIMIT_NAME}


def public(state: dict[str, list]) -> dict[str, Any]:
    """Forme renvoyée au site : {likes, playlists, limits}."""
    return {"likes": state["likes"], "playlists": state["playlists"], "limits": limits()}


# ─── Accès ───

def read_library(uid: int) -> dict[str, Any]:
    """Bibliothèque du Roi (forme publique) ; Redis injoignable → LibraryError STORAGE_UNAVAILABLE."""
    r = _client_for(uid)
    try:
        raw = r.get(library_key(uid))
    except (redis.RedisError, OSError) as e:
        raise _unavailable(uid, e) from None
    state, _lossy = parse_library(raw, uid)
    return public(state)


# Une opération reçoit l'état relu et le modifie EN PLACE ; elle renvoie (modifié ?, champs propres de la
# réponse) ou lève LibraryError. Elle peut être rejouée (WatchError) : pas d'effet de bord hors de l'état.
Op = Callable[[dict[str, list]], tuple[bool, dict[str, Any]]]


def mutate(uid: int, op: Op) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lecture-modification-écriture atomique (WATCH / MULTI / EXEC), MAX_TRIES essais.

    Renvoie (bibliothèque publique, champs propres de l'opération). Rien n'est écrit si l'opération ne
    change rien. Valeur qui grossirait au-delà de MAX_LIBRARY_BYTES → LibraryError LIMIT_REACHED (409,
    limit="size") ; ce qui la garde ou la réduit passe toujours (retirer, déplacer, supprimer).
    Conflits à chaque essai ou Redis injoignable → LibraryError STORAGE_UNAVAILABLE (503).
    Seul un vrai conflit (WATCH) fait rejouer l'opération : une connexion perdue pendant l'EXEC laisse
    l'écriture incertaine, l'opération (pas toujours idempotente) n'est jamais rejouée → 503.
    """
    key = library_key(uid)
    r = _client_for(uid)
    try:
        with r.pipeline() as pipe:
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    pipe.watch(key)
                    raw = cast("str | None", pipe.get(key))  # decode_responses=True : du texte, ou None
                    state, lossy = parse_library(raw, uid)
                    changed, extra = op(state)
                    if not changed:
                        pipe.unwatch()
                        return public(state), extra
                    data = _dump(state)
                    # Budget d'octets : refusé seulement si la valeur grossit au-delà ; un chansonnier déjà
                    # trop lourd (budget abaissé) peut toujours maigrir. L'erreur sort du `with` (UNWATCH).
                    size = len(data.encode("utf-8"))
                    if size > MAX_LIBRARY_BYTES and size > len((raw or "").encode("utf-8")):
                        logger.warning("Chansonnier de %s : %d octets refusés (budget %d)", uid, size,
                                       MAX_LIBRARY_BYTES)
                        raise LibraryError("LIMIT_REACHED", MSG_LIMIT_SIZE, 409, limit="size")
                    # Jamais d'écrasement à l'aveugle : une valeur illisible est gardée à côté, même transaction.
                    backup = f"{key}:corrupt:{int(time.time())}" if lossy and raw is not None else None
                    pipe.multi()
                    if backup:
                        pipe.set(backup, raw)
                    pipe.set(key, data)
                    try:
                        pipe.execute()
                    except redis.WatchError as e:
                        if isinstance(e.__context__, (redis.ConnectionError, redis.TimeoutError, OSError)):
                            # Connexion perdue PENDANT l'EXEC : redis-py le signale par un WatchError, mais
                            # Redis a peut-être déjà appliqué l'écriture. Rejouer l'opération créerait une
                            # 2e playlist, déplacerait deux fois… : issue inconnue → 503, le site relit.
                            raise _unavailable(uid, e.__context__) from None
                        raise
                    if backup:
                        logger.warning("Chansonnier de %s : valeur illisible gardée sous %s", uid, backup)
                    return public(state), extra
                except redis.WatchError:
                    # Un autre onglet a écrit entre la lecture et l'écriture : on relit et on rejoue.
                    logger.info("Chansonnier de %s modifié en parallèle (essai %d/%d)", uid, attempt, MAX_TRIES)
    except (redis.RedisError, OSError) as e:
        raise _unavailable(uid, e) from None
    logger.warning("Chansonnier de %s : %d conflits d'écriture d'affilée, abandon", uid, MAX_TRIES)
    raise LibraryError("STORAGE_UNAVAILABLE", MSG_STORAGE_BUSY, 503)


# ─── Opérations (pures, sur l'état relu) ───

def _find(state: dict[str, list], pid: str) -> dict:
    for pl in state["playlists"]:
        if pl["id"] == pid:
            return pl
    raise LibraryError("PLAYLIST_NOT_FOUND", MSG_PLAYLIST_NOT_FOUND, 404)


def _without(tracks: list[dict], url: str) -> list[dict]:
    k = track_key(url)
    return [t for t in tracks if track_key(t["url"]) != k]


def _unique(tracks: list[dict]) -> list[dict]:
    """Doublons (même track_key) écartés, premier gardé, ordre conservé."""
    seen = set()
    out = []
    for t in tracks:
        k = track_key(t["url"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _clamp(index: int | None, n: int, default: int) -> int:
    """Rang d'insertion borné à [0, n] ; None → default. (list.insert lit un rang négatif depuis la fin.)"""
    return default if index is None else max(0, min(index, n))


def op_add_like(track: dict, index: int | None = None) -> Op:
    """Idempotent : un titre déjà aimé (même identité) ne bouge pas ; sinon en tête, ou au rang `index` (borné)
    quand l'annulation d'un retrait le remet à sa place."""
    def run(state):
        k = track_key(track["url"])
        if any(track_key(t["url"]) == k for t in state["likes"]):
            return False, {}
        if len(state["likes"]) >= LIMIT_LIKES:
            raise LibraryError("LIMIT_REACHED", MSG_LIMIT_LIKES, 409, limit="likes")
        state["likes"].insert(_clamp(index, len(state["likes"]), 0), track)
        return True, {}
    return run


def op_remove_like(url: str) -> Op:
    """Retrait par identité ; absent → rien à faire (200)."""
    def run(state):
        kept = _without(state["likes"], url)
        changed = len(kept) != len(state["likes"])
        state["likes"] = kept
        return changed, {}
    return run


def op_create_playlist(name: str, tracks: list[dict], now: int,
                       new_id: Callable[[], str] = lambda: secrets.token_urlsafe(8)) -> Op:
    """Nouvelle playlist (en dernier) ; titres en double écartés, plafonnés à LIMIT_TRACKS."""
    def run(state):
        if len(state["playlists"]) >= LIMIT_PLAYLISTS:
            raise LibraryError("LIMIT_REACHED", MSG_LIMIT_PLAYLISTS, 409, limit="playlists")
        ids = {pl["id"] for pl in state["playlists"]}
        pid = new_id()
        while pid in ids:
            pid = new_id()
        state["playlists"].append({
            "id": pid,
            "name": name,
            "tracks": _unique(tracks)[:LIMIT_TRACKS],
            "created_at": now,
            "updated_at": now,
        })
        return True, {"playlist_id": pid}
    return run


def op_restore_playlist(playlist: dict, index: int | None) -> Op:
    """Annulation d'une suppression : la playlist (clean_restored_playlist) revient à son rang `index`, borné à
    [0, nombre de playlists] (None : à la fin). Déjà là (même id : rejouée, autre onglet) → rien à faire (200),
    même au plafond ; sinon le plafond de playlists de la création."""
    def run(state):
        pls = state["playlists"]
        if any(pl["id"] == playlist["id"] for pl in pls):
            return False, {}
        if len(pls) >= LIMIT_PLAYLISTS:
            raise LibraryError("LIMIT_REACHED", MSG_LIMIT_PLAYLISTS, 409, limit="playlists")
        # copie : l'opération peut être rejouée (WatchError) sur un état relu
        pls.insert(_clamp(index, len(pls), len(pls)), {**playlist, "tracks": list(playlist["tracks"])})
        return True, {}
    return run


def op_rename_playlist(pid: str, name: str, now: int) -> Op:
    def run(state):
        pl = _find(state, pid)
        if pl["name"] == name:
            return False, {}
        pl["name"] = name
        pl["updated_at"] = now
        return True, {}
    return run


def op_delete_playlist(pid: str) -> Op:
    def run(state):
        pl = _find(state, pid)
        state["playlists"].remove(pl)
        return True, {}
    return run


def op_add_tracks(pid: str, tracks: list[dict], now: int) -> Op:
    """Ajout en fin de playlist : doublons écartés et ce qui dépasse LIMIT_TRACKS comptés dans `skipped`."""
    def run(state):
        pl = _find(state, pid)
        keys = {track_key(t["url"]) for t in pl["tracks"]}
        added = skipped = 0
        for t in tracks:
            k = track_key(t["url"])
            if k in keys or len(pl["tracks"]) >= LIMIT_TRACKS:
                skipped += 1
                continue
            keys.add(k)
            pl["tracks"].append(t)
            added += 1
        if added:
            pl["updated_at"] = now
        return added > 0, {"added": added, "skipped": skipped}
    return run


def op_remove_track(pid: str, url: str, now: int) -> Op:
    """Retrait par identité ; titre absent → rien à faire (200), playlist absente → 404."""
    def run(state):
        pl = _find(state, pid)
        kept = _without(pl["tracks"], url)
        if len(kept) == len(pl["tracks"]):
            return False, {}
        pl["tracks"] = kept
        pl["updated_at"] = now
        return True, {}
    return run


def op_move_track(pid: str, src: int, dst: int, now: int, url: str | None = None) -> Op:
    """Déplace le titre `src` à la position `dst` (0 ≤ src, dst < nombre de titres, sinon 400).

    `url` donné : le titre au rang `src` doit être celui-là (même track_key), sinon 409 STALE sans rien
    déplacer, rang disparu compris. Les rangs sont comptés sur la copie du site, dépassée quand un autre
    onglet ou appareil a réordonné la playlist : ils viseraient un autre titre.
    """
    def run(state):
        pl = _find(state, pid)
        n = len(pl["tracks"])
        if url is not None and (src >= n or track_key(pl["tracks"][src]["url"]) != track_key(url)):
            raise LibraryError("STALE", MSG_STALE, 409)
        if src >= n or dst >= n:
            raise _invalid(MSG_BAD_POSITION)
        if src == dst:
            return False, {}
        pl["tracks"].insert(dst, pl["tracks"].pop(src))
        pl["updated_at"] = now
        return True, {}
    return run
