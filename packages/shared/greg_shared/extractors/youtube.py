# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — PO_TOKEN + cookies + anti-403/429/SABR
#
# Différences clés vs version précédente :
# - Ordre par défaut des clients : `tv` (no PO, no cookies) en premier,
#   puis `mweb` + PO, puis ios/android/web en fallback.
# - PO tokens en cache *par video_id* (TTL court), invalidé sur 403.
# - `stream_pipe._preflight_pipe_sync` LÈVE une exception si tous les
#   formats échouent (avant on retournait silencieusement "18" → ffmpeg
#   se prenait un 403 et discord.py interprétait ça comme une coupure
#   réseau, bouclant à l'infini).
# - `_AUTO_PIPE_ON_403` enfin câblé : invalidation du PO + bascule explicite.
# - Logs lisibles, sans bruit.
# - `expand_bundle` = listing FLAT uniquement (aucun PO token, aucun Playwright,
#   jamais d'extraction complète) → BundleError en cas d'échec.
# - Auto-fetch Playwright des PO tokens : opt-in (YT_PO_AUTOFETCH=1).
# - Erreurs définitives (vidéo supprimée/privée/géo-bloquée/membres/DRM…) →
#   TrackUnavailable (permanent) : pas de boucle de clients, pas de retry.
# - yt-dlp ne reçoit jamais le fichier cookies partagé mais une COPIE privée
#   (il réécrit son cookiejar en sortant et écraserait un upload récent).

from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import gzip
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from . import BundleError, TrackUnavailable, is_spotify_url, is_url, normalize_link

__all__ = [
    "is_valid",
    "search",
    "is_playlist_like",
    "is_playlist_or_mix_url",
    "expand_bundle",
    "stream",
    "stream_pipe",
    "download",
    "safe_cleanup",
    "invalidate_po_cache",
    "cookies_upload_path",
    "cookiefile_copy",
]

_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")


def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}", flush=True)


# ─── Reconnaissance d'URLs YouTube ───
# (+ anciennes formes /v/<id>, /e/<id>, /watch/<id>, juste après l'hôte)
_YTID_RE = re.compile(
    r"(?:[?&]v=|/shorts/|/live/|/embed/(?!videoseries)|youtu\.be/|\.com/(?:v|e|watch)/)"
    r"([A-Za-z0-9_\-]{11})"
)


def _extract_video_id(s: str) -> Optional[str]:
    m = _YTID_RE.search(s or "")
    return m.group(1) if m else None


def _yt_parse(url: str):
    """urlparse tolérant (lien sans schéma) → (parsed, host en minuscules)."""
    s = (url or "").strip()
    if s and "://" not in s:
        s = "https://" + s
    u = urlparse(s)
    return u, (u.hostname or "").lower()


def _is_youtube_host(host: str) -> bool:
    return any(
        host == d or host.endswith("." + d)
        for d in ("youtube.com", "youtu.be", "youtube-nocookie.com")
    )


def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return (
        ("youtube.com/watch" in u)
        or ("youtu.be/" in u)
        or ("youtube.com/shorts/" in u)
        or ("music.youtube.com/watch" in u)
    )


# ─── Config réseau ───
_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
_FORCE_IPV4 = os.getenv("YTDLP_FORCE_IPV4", "1").lower() not in ("0", "false", "")
_HTTP_PROXY = (
    os.getenv("YTDLP_HTTP_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("HTTP_PROXY")
    or os.getenv("ALL_PROXY")
)

# Ordre des clients yt-dlp.
#
# `tv` et `tv_simply` ne nécessitent PAS de PO token (YouTube laisse passer
# les TVs/consoles). C'est notre voie royale en 2025/2026.
# `mweb` reste nécessaire pour certains contenus (Music, age-gate) mais
# nécessite un PO token → on l'utilise en second.
# Les anciens `ios`, `android`, `web` sont en dernier (ils ramassent
# fréquemment des 403 sans PO token).
_DEFAULT_CLIENTS = ["tv", "tv_simply", "mweb", "web_safari", "ios", "android", "web"]
_clients_env = os.getenv("YTDLP_CLIENTS")
if _clients_env:
    _CLIENTS_ORDER = [c.strip() for c in _clients_env.split(",") if c.strip()]
else:
    _CLIENTS_ORDER = list(_DEFAULT_CLIENTS)

_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]"
    "/251/140/18/best[protocol^=m3u8]/best",
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"
_AUTO_PIPE_ON_403 = os.getenv("YTDLP_AUTO_PIPE_ON_403", "1").lower() not in ("0", "false", "")


# ══════════════════════════════════════════
# PO Tokens — cache par video_id, TTL court
# ══════════════════════════════════════════
_PO_TTL = float(os.getenv("PO_CACHE_TTL_SEC", "1800"))  # 30 min
_PO_CACHE: Dict[str, Tuple[float, List[str]]] = {}  # video_id → (expires_at, tokens)
_PO_LOCK = threading.Lock()


def _po_cache_get(video_id: Optional[str]) -> Optional[List[str]]:
    if not video_id:
        return None
    with _PO_LOCK:
        entry = _PO_CACHE.get(video_id)
        if not entry:
            return None
        exp, toks = entry
        if time.monotonic() > exp:
            _PO_CACHE.pop(video_id, None)
            return None
        return list(toks)


def _po_cache_set(video_id: Optional[str], tokens: List[str]) -> None:
    if not video_id:
        return
    with _PO_LOCK:
        _PO_CACHE[video_id] = (time.monotonic() + _PO_TTL, list(tokens))


def invalidate_po_cache(video_id: Optional[str] = None) -> None:
    """Vide le cache PO. Si video_id fourni, uniquement cette entrée.

    Pour une vidéo donnée, un résultat négatif ([]) est conservé : sur un 403
    on ne relance pas Playwright pour une vidéo où il n'a rien trouvé.
    """
    with _PO_LOCK:
        if video_id is None:
            _PO_CACHE.clear()
        else:
            entry = _PO_CACHE.get(video_id)
            if entry and entry[1]:
                _PO_CACHE.pop(video_id, None)


def _po_autofetch_enabled() -> bool:
    """Auto-fetch Playwright : opt-in (le scraping ytcfg ne trouve plus de token)."""
    return os.getenv("YT_PO_AUTOFETCH", "0").strip().lower() in ("1", "true", "yes", "on")


def _collect_po_tokens_from_env() -> List[str]:
    raw = (os.getenv("YT_PO_TOKEN") or os.getenv("YTDLP_PO_TOKEN") or "").strip()
    prefixed = (os.getenv("YT_PO_TOKEN_PREFIXED") or "").strip()
    out: List[str] = []
    if raw and "+" not in raw:
        out += [f"mweb.gvs+{raw}", f"web.gvs+{raw}", f"ios.gvs+{raw}", f"android.gvs+{raw}"]
    if raw and "+" in raw:
        out.append(raw)
    if prefixed:
        out.append(prefixed)
    seen = set()
    return [t for t in out if t and not (t in seen or seen.add(t))]


def _resolve_po_tokens_for(query_or_url: str) -> List[str]:
    """Renvoie la liste de PO tokens à passer à yt-dlp pour cette vidéo.

    Ordre de résolution :
    1. Cache (par video_id).
    2. Tokens fournis via env (YT_PO_TOKEN / YT_PO_TOKEN_PREFIXED).
    3. Auto-fetch via Playwright (token_fetcher), seulement si YT_PO_AUTOFETCH=1.

    Toujours instantané sans id vidéo (playlist, recherche…) : jamais
    d'extraction yt-dlp ici.
    """
    vid = _extract_video_id(query_or_url)

    cached = _po_cache_get(vid)
    if cached is not None:
        return cached

    # 1) Env d'abord (déterministe, pas de network)
    env_tokens = _collect_po_tokens_from_env()
    if env_tokens:
        _po_cache_set(vid, env_tokens)
        _dbg(f"PO tokens from env: {len(env_tokens)}")
        return env_tokens

    # 2) Sinon, auto-fetch Playwright (opt-in) pour une vidéo précise
    if not vid or not _po_autofetch_enabled():
        return []

    try:
        from .token_fetcher import fetch_po_token_ex  # type: ignore
    except Exception:
        fetch_po_token_ex = None

    if not fetch_po_token_ex:
        _po_cache_set(vid, [])
        return []

    try:
        _dbg(f"PO: auto-fetch for video {vid}")
        auto, why = fetch_po_token_ex(vid, timeout_ms=15000)
    except Exception as e:
        _dbg(f"PO: auto-fetch failed: {e}")
        auto, why = None, "error"

    if not auto and (why == "busy" or str(why).startswith("negative_cache")):
        # Rien n'a été tenté pour CETTE vidéo (Chromium occupé / cache négatif
        # global) : pas de [] en cache, sinon plus aucun essai pendant _PO_TTL.
        _dbg(f"PO: auto-fetch non tenté ({why})")
        return []

    tokens: List[str] = []
    if auto and isinstance(auto, str) and len(auto) > 10:
        # Préfixe pour tous les clients courants (yt-dlp dédup en interne)
        tokens = [
            f"mweb.gvs+{auto}",
            f"web.gvs+{auto}",
            f"ios.gvs+{auto}",
            f"android.gvs+{auto}",
        ]
        _dbg(f"PO: auto-fetch OK (len={len(auto)})")
    else:
        _dbg("PO: auto-fetch returned none")

    _po_cache_set(vid, tokens)
    return tokens


# ── Cookies ──
def cookies_upload_path() -> str:
    """LE chemin des cookies uploadés/matérialisés (évalué à chaque appel)."""
    return (
        os.getenv("YTDLP_COOKIES_FILE")
        or os.getenv("YOUTUBE_COOKIES_PATH")
        or _COOKIE_FILE_DEFAULT
    )


def _decode_cookies_b64(b64: Optional[str]) -> Optional[str]:
    """YTDLP_COOKIES_B64 → texte Netscape (base64 brut ou gzip, comme le guardian)."""
    if not b64:
        return None
    try:
        blob = base64.b64decode(b64.strip())
        if blob[:2] == b"\x1f\x8b":
            blob = gzip.decompress(blob)
        return blob.decode("utf-8", errors="replace")
    except Exception:
        return None


def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    """Écrit YTDLP_COOKIES_B64 dans target_path, SEULEMENT s'il n'existe pas."""
    if os.path.exists(target_path):
        return target_path
    raw = _decode_cookies_b64(os.getenv("YTDLP_COOKIES_B64"))
    if not raw:
        return None
    try:
        parent = os.path.dirname(os.path.abspath(target_path))
        os.makedirs(parent, exist_ok=True)
        tmp = f"{target_path}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(raw)
        if os.path.exists(target_path):  # un upload est arrivé entre-temps
            os.remove(tmp)
        else:
            os.replace(tmp, target_path)
        return target_path
    except Exception as e:
        _dbg(f"cookies B64 → {target_path} impossible: {e}")
        return None


def _pick_cookiefile(cookies_file: Optional[str]) -> Optional[str]:
    """Résolution À CHAQUE APPEL : arg explicite existant → fichier uploadé
    (cookies_upload_path) → ancien ./youtube.com_cookies.txt → YTDLP_COOKIES_B64
    matérialisé dans cookies_upload_path() (jamais par-dessus un upload)."""
    if cookies_file and os.path.exists(cookies_file):
        return cookies_file
    target = cookies_upload_path()
    if os.path.exists(target):
        return target
    if os.path.exists(_COOKIE_FILE_DEFAULT):
        return _COOKIE_FILE_DEFAULT
    if os.getenv("YTDLP_COOKIES_B64"):
        return _ensure_cookiefile_from_b64(target)
    return None


def _make_cookie_copy(path: Optional[str]) -> Optional[str]:
    """Copie privée (fichier temporaire 0600) du fichier cookies, ou None."""
    if not path or not os.path.isfile(path):
        return None
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="greg-ytcookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(path, tmp)
        return tmp
    except Exception as e:
        _dbg(f"copie des cookies impossible ({path}): {e}")
        _remove_quiet(tmp)
        return None


def _remove_quiet(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as e:
        _dbg(f"suppression de {path} impossible: {e}")


@contextlib.contextmanager
def cookiefile_copy(path: Optional[str]):
    """Copie privée d'un fichier cookies, supprimée à la sortie (None si absent).

    yt-dlp réécrit son cookiejar à la fermeture (YoutubeDL.close → save_cookies,
    CLI `--cookies`) : sur le fichier partagé, il écraserait un upload fait
    pendant l'extraction par les anciens cookies.
    """
    tmp = _make_cookie_copy(path)
    try:
        yield tmp
    finally:
        _remove_quiet(tmp)


@contextlib.contextmanager
def _open_ydl(opts: Dict[str, Any]):
    """`with YoutubeDL(opts)` sur une copie privée de opts['cookiefile']."""
    with cookiefile_copy(opts.get("cookiefile")) as ck:
        o = dict(opts)
        if ck:
            o["cookiefile"] = ck
        else:
            # Fichier disparu : sans cookies plutôt que de le recréer à la fermeture
            o.pop("cookiefile", None)
        with YoutubeDL(o) as ydl:
            yield ydl


def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec:
        return None
    parts = spec.split(":", 1)
    return (
        (parts[0].strip().lower(),)
        if len(parts) == 1
        else (parts[0].strip().lower(), parts[1].strip())
    )


# ── FFmpeg ──
def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        return (which or "ffmpeg", os.path.dirname(which) if which else None)
    if not os.path.dirname(ffmpeg_hint):
        # Nom nu ("ffmpeg") : c'est le PATH qui fait foi, pas le CWD
        which = shutil.which(ffmpeg_hint)
        if which:
            return which, os.path.dirname(which)
    p = os.path.abspath(os.path.expanduser(ffmpeg_hint))
    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand):
            return cand, p
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2):
            return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans: {p}")
    if os.path.isfile(p):
        return p, os.path.dirname(p)
    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)
    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")


def _ff_reconnect_flags() -> List[str]:
    return [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_on_network_error", "1",
        "-reconnect_delay_max", "5",
        "-rw_timeout", "60000000",
        "-timeout", "60000000",
    ]


def _kill_proc(p) -> None:
    try:
        if p and getattr(p, "poll", lambda: None)() is None:
            p.kill()
    except Exception:
        pass


def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


# ── yt-dlp opts ──
def _mk_opts(
    *,
    ffmpeg_path=None,
    cookies_file=None,
    cookies_from_browser=None,
    ratelimit_bps=None,
    search=False,
    for_download=False,
    allow_playlist=False,
    extract_flat=False,
    po_tokens: Optional[List[str]] = None,
) -> Dict[str, Any]:
    cookies_file = _pick_cookiefile(cookies_file)
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": not allow_playlist,
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 20,
        "source_address": "0.0.0.0" if _FORCE_IPV4 else None,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": {"youtube": {"player_client": list(_CLIENTS_ORDER)}},
        "hls_prefer_native": True,
        "format": _FORMAT_CHAIN,
    }
    if po_tokens:
        # API Python : une LISTE (une chaîne serait découpée caractère par caractère)
        opts["extractor_args"]["youtube"]["po_token"] = list(po_tokens)
    if extract_flat:
        opts["extract_flat"] = extract_flat  # True ou "in_playlist"
    if not allow_playlist and not search:
        # Garde-fou : une URL "liste" arrivée ici ne résout que son 1er élément
        opts["playlist_items"] = "1"
    if ffmpeg_path:
        opts["ffmpeg_location"] = (
            os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ffmpeg_path
        )
    if _HTTP_PROXY:
        opts["proxy"] = _HTTP_PROXY
    if ratelimit_bps:
        opts["ratelimit"] = int(ratelimit_bps)

    cfb = _parse_cookies_from_browser_spec(
        cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")
    )
    if cfb:
        opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file

    if search:
        opts.update({"default_search": "ytsearch5", "extract_flat": True})
    if for_download:
        opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "postprocessor_args": ["-ar", "48000"],
        })
    for k in list(opts):
        if opts[k] is None:
            del opts[k]
    return opts


# ── Search ──
def _normalize_search_entries(entries):
    out = []
    for e in entries or []:
        title = e.get("title") or "Titre inconnu"
        url = e.get("webpage_url") or e.get("url") or ""
        if not url.startswith("http"):
            vid = e.get("id")
            if vid:
                url = f"https://www.youtube.com/watch?v={vid}"
        out.append({
            "title": title,
            "url": url,
            "webpage_url": url,
            "duration": e.get("duration"),
            "thumb": e.get("thumbnail"),
            "thumbnail": e.get("thumbnail"),
            "provider": "youtube",
            "uploader": e.get("uploader"),
        })
    return out


def search(query: str, *, cookies_file=None, cookies_from_browser=None,
           limit: int = 5) -> List[dict]:
    if not query or not query.strip():
        return []
    opts = _mk_opts(
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        search=True,
    )
    with _open_ydl(opts) as ydl:
        data = ydl.extract_info(f"ytsearch{max(1, limit)}:{query}", download=False)
        return _normalize_search_entries((data or {}).get("entries") or [])


# ── Playlist ──
# Onglets de chaîne listables à plat : /@x, /@x/videos, /channel/UC…/streams…
_YT_TAB_PATH_RE = re.compile(
    r"^/(?:@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(?:/(?:videos|shorts|streams))?/?$",
    re.IGNORECASE,
)
# Album YouTube Music (music.youtube.com/browse/MPREb_…) : yt-dlp le résout
# vers sa playlist OLAK5uy_…
_YT_MUSIC_ALBUM_RE = re.compile(r"^/browse/MPREb_[\w-]+/?$")
_MIX_PREFIXES = ("RD", "UL", "PU")
_MIX_VIDEO_RE = re.compile(r"^RD(?:AMVM|MM)?([A-Za-z0-9_-]{11})$")
_BUNDLE_MARGIN = 5  # marge pour compenser les entrées indisponibles filtrées
# YouTube sert les playlists par pages de 100 : une fenêtre de 100 coûte une
# seule requête et laisse de la marge si des entrées sont filtrées.
_BUNDLE_PAGE = 100
_BUNDLE_LOCATE_WINDOW = int(os.getenv("YT_BUNDLE_LOCATE_WINDOW", "200"))
_UNAVAILABLE_TITLES = {"[private video]", "[deleted video]", "[unavailable video]"}
_UNAVAILABLE_AVAILABILITY = {"private", "needs_auth", "subscriber_only", "premium_only"}


def _bundle_list_id(u, host: str) -> Optional[str]:
    q = parse_qs(u.query)
    list_id = (q.get("list") or [None])[0]
    if not list_id and host == "music.youtube.com":
        m = re.match(r"^/browse/VL([\w-]+)", u.path or "")
        if m:
            list_id = m.group(1)
    return list_id


def is_playlist_or_mix_url(url: str) -> bool:
    try:
        u, host = _yt_parse(url)
        if not _is_youtube_host(host):
            return False
        q = parse_qs(u.query)
        path = u.path or ""
        return (
            bool(_bundle_list_id(u, host))
            or (
                (q.get("start_radio") or ["0"])[0] in ("1", "true")
                and bool(_extract_video_id(url))
            )
            or path.strip("/").lower() == "playlist"
            or (host != "youtu.be" and bool(_YT_TAB_PATH_RE.match(path)))
            or (host == "music.youtube.com" and bool(_YT_MUSIC_ALBUM_RE.match(path)))
        )
    except Exception:
        return False


def is_playlist_like(url: str) -> bool:
    return is_playlist_or_mix_url(url)


def _flat_bundle_opts(cookies_file, cookies_from_browser, *, end: int, start: int = 1) -> Dict[str, Any]:
    """Options du listing FLAT : base commune (_mk_opts : proxy, IPv4, cookies,
    UA) sans format ni PO token — un listing n'interroge jamais le player."""
    opts = _mk_opts(
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        allow_playlist=True,
        extract_flat="in_playlist",
    )
    opts.pop("format", None)
    opts.pop("hls_prefer_native", None)
    opts.get("extractor_args", {}).get("youtube", {}).pop("po_token", None)
    opts.update({
        "skip_download": True,
        "ignoreerrors": False,  # une erreur de listing doit remonter (BundleError)
        "socket_timeout": 10,
        "playlistend": int(end),
        # YouTube masque lui-même privées/supprimées/bloquées pour notre IP
        "compat_opts": {"no-youtube-unavailable-videos"},
    })
    if start and start > 1:
        opts["playliststart"] = int(start)
    return opts


def _flat_entries(url: str, opts: Dict[str, Any]) -> List[dict]:
    with _open_ydl(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    out: List[dict] = []

    def _walk(entries, depth: int) -> None:
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            if e.get("_type") == "playlist" and depth < 2:
                # Chaîne sans onglet (/@x, /channel/UC…) : yt-dlp renvoie une
                # playlist PAR onglet (Vidéos, Live, Shorts) → aplaties, dans l'ordre
                _walk(e.get("entries"), depth + 1)
            else:
                out.append(e)

    _walk((info or {}).get("entries"), 0)
    return out


def _flat_entry_item(e: dict) -> Optional[Tuple[str, dict]]:
    """Entrée flat → (video_id, item canonique) ; None si illisible/indisponible."""
    if e.get("ie_key") not in (None, "Youtube"):
        return None  # ex. onglet "playlists" d'une chaîne
    vid = str(e.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        vid = _extract_video_id(str(e.get("url") or "")) or ""
    if not vid:
        return None
    title = (e.get("title") or "").strip()
    if title.lower() in _UNAVAILABLE_TITLES:
        return None
    if (e.get("availability") or "") in _UNAVAILABLE_AVAILABILITY:
        return None
    if e.get("live_status") == "is_upcoming":
        return None
    url = f"https://www.youtube.com/watch?v={vid}"
    thumbs = e.get("thumbnails") or []
    thumb = e.get("thumbnail") or (
        thumbs[-1].get("url") if thumbs and isinstance(thumbs[-1], dict) else None
    )
    dur = e.get("duration")
    return vid, {
        "title": title or url,
        "url": url,
        "webpage_url": url,
        "artist": e.get("uploader") or e.get("channel"),
        "thumb": thumb,
        "duration": int(dur) if isinstance(dur, (int, float)) and dur > 0 else None,
        "provider": "youtube",
    }


def _flat_items(url: str, opts: Dict[str, Any]) -> List[Tuple[str, dict]]:
    out: List[Tuple[str, dict]] = []
    for e in _flat_entries(url, opts):
        it = _flat_entry_item(e)
        if it:
            out.append(it)
    return out


def _bare_item(vid: str) -> Tuple[str, dict]:
    url = f"https://www.youtube.com/watch?v={vid}"
    return vid, {
        "title": url, "url": url, "webpage_url": url,
        "artist": None, "thumb": None, "duration": None, "provider": "youtube",
    }


def _x_first(items: List[Tuple[str, dict]], vid: str) -> List[Tuple[str, dict]]:
    head = next((it for it in items if it[0] == vid), None) or _bare_item(vid)
    return [head] + [it for it in items if it[0] != vid]


def _bundle_error_message(err: Exception) -> str:
    s = str(err).lower()
    if "unviewable" in s:
        return "Ce type de playlist (mix) ne peut pas être lu directement."
    if "not a bot" in s or "confirm you" in s:
        return "YouTube bloque temporairement l'accès à cette playlist (vérification anti-bot)."
    if "private" in s:
        return "Cette playlist est privée."
    if "does not exist" in s or "http error 400" in s or "http error 404" in s:
        return "Cette playlist n'existe pas ou n'est plus disponible."
    return "Impossible de lire cette playlist YouTube (privée, supprimée ou indisponible)."


def expand_bundle(page_url, limit_total=None, limit=None,
                  cookies_file=None, cookies_from_browser=None):
    """Liste RAPIDE (flat) d'une playlist / mix / onglet de chaîne YouTube.

    - Jamais de PO token, de Playwright ni d'extraction complète.
    - Entrées canoniques `https://www.youtube.com/watch?v=<id>` (sans list=).
    - watch?v=X&list=PL… : X en tête puis les titres qui le SUIVENT.
    - Mix (list=RD…) : extraits en ligne depuis la page watch (X en tête).
    - Lève BundleError (PLAYLIST_UNAVAILABLE / PLAYLIST_EMPTY / UNSUPPORTED_SOURCE).
    """
    N = max(1, int(limit_total or limit or 10))
    page_url = normalize_link(page_url)
    u, host = _yt_parse(page_url)
    if not _is_youtube_host(host):
        raise BundleError("UNSUPPORTED_SOURCE", "Ce lien n'est pas une playlist YouTube.")

    q = parse_qs(u.query)
    list_id = _bundle_list_id(u, host)
    vid = _extract_video_id(page_url)
    if not list_id and vid and (q.get("start_radio") or ["0"])[0] in ("1", "true"):
        list_id = f"RD{vid}"
    try:
        index = int((q.get("index") or ["0"])[0])
    except ValueError:
        index = 0

    def _opts(end: int, start: int = 1) -> Dict[str, Any]:
        return _flat_bundle_opts(cookies_file, cookies_from_browser, end=end, start=start)

    t0 = time.monotonic()
    try:
        if not list_id:
            if host == "music.youtube.com" and _YT_MUSIC_ALBUM_RE.match(u.path or ""):
                # Album YouTube Music : yt-dlp suit la redirection vers sa playlist
                items = _flat_items(f"https://music.youtube.com{u.path}", _opts(N + _BUNDLE_MARGIN))
            elif host == "youtu.be" or not _YT_TAB_PATH_RE.match(u.path or ""):
                raise BundleError("UNSUPPORTED_SOURCE", "Ce lien YouTube n'est pas une playlist.")
            else:
                # Onglet de chaîne (@x/videos…) ou chaîne entière (/@x : un onglet
                # par playlist imbriquée, aplatis) : derniers titres, à plat
                tab_url = f"https://www.youtube.com{u.path}"
                items = _flat_items(tab_url, _opts(N + _BUNDLE_MARGIN))

        elif list_id.startswith(_MIX_PREFIXES):
            m = _MIX_VIDEO_RE.match(list_id)
            seed = vid or (m.group(1) if m else None)
            if seed:
                # Un mix n'a pas de page /playlist : on le lit depuis la page watch
                items = _x_first(_flat_items(
                    f"https://www.youtube.com/watch?v={seed}&list={list_id}",
                    _opts(N + _BUNDLE_MARGIN),
                ), seed)
            else:
                items = _flat_items(
                    f"https://www.youtube.com/playlist?list={list_id}", _opts(N + _BUNDLE_MARGIN)
                )

        else:
            pl_url = f"https://www.youtube.com/playlist?list={list_id}"
            window = max(N + _BUNDLE_MARGIN, _BUNDLE_PAGE)
            items = []
            if not vid:
                items = _flat_items(pl_url, _opts(window))
            else:
                located = False
                # 1) index= (1-based) : fenêtre qui démarre sur X (vérifiée)
                if index >= 1:
                    win = _flat_items(pl_url, _opts(index + window - 1, start=index))
                    pos = next((i for i, it in enumerate(win) if it[0] == vid), None)
                    if pos is not None and len(win) - pos >= min(N, len(win)):
                        items, located = win[pos:], True
                    else:
                        _dbg(f"expand: index={index} périmé pour {vid} → recherche dans la liste")
                # 2) Sinon on cherche X dans les ~200 premiers titres
                if not located:
                    win = _flat_items(pl_url, _opts(_BUNDLE_LOCATE_WINDOW + N + _BUNDLE_MARGIN))
                    pos = next((i for i, it in enumerate(win) if it[0] == vid), None)
                    # X introuvable : X en tête puis la liste depuis le début
                    items = win[pos:] if pos is not None else _x_first(win, vid)
    except BundleError:
        raise
    except Exception as e:
        _dbg(f"expand_bundle KO {page_url}: {e}")
        raise BundleError("PLAYLIST_UNAVAILABLE", _bundle_error_message(e)) from e

    seen = set()
    out = []
    for v, item in items:
        if v in seen:
            continue
        seen.add(v)
        out.append(item)
        if len(out) >= N:
            break
    _dbg(f"expand_bundle: {len(out)} titre(s) en {time.monotonic() - t0:.2f}s ({page_url})")
    if not out:
        raise BundleError("PLAYLIST_EMPTY", "Cette playlist est vide ou ne contient aucun titre lisible.")
    return out


# ── Erreurs yt-dlp : définitives vs transitoires ──
# Transitoires (IP / réseau / PO / SABR) : jamais classées définitives.
_TRANSIENT_ERROR_RE = re.compile(
    r"not a bot|try again later|http error (?:403|429|5\d\d)|forbidden|too many requests"
    r"|timed out|requested format is not available|connection|temporar",
    re.IGNORECASE,
)
_PERMANENT_ERRORS: List[Tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), reason) for p, reason in (
        (r"private video", "Vidéo privée"),
        (r"members-only|join this channel|channel's members", "Vidéo réservée aux membres de la chaîne"),
        ((r"not made this video available in your country|blocked it in your country"
          r"|geo[- ]?restrict|not available in your country"), "Vidéo bloquée dans ce pays"),
        (r"account associated with this video has been terminated", "Vidéo supprimée (compte fermé)"),
        (r"has been removed|no longer available", "Vidéo supprimée"),
        (r"video unavailable|video is unavailable|video is not available", "Vidéo indisponible"),
        (r"copyright", "Vidéo bloquée pour droits d'auteur"),
        (r"\bdrm\b", "Contenu protégé par DRM (illisible)"),
        (r"confirm your age|age[- ]restricted", "Vidéo soumise à une restriction d'âge"),
        (r"premieres in|live event will begin", "Vidéo pas encore disponible"),
        (r"unsupported url|is not a valid url", "Lien non pris en charge"),
    )
]


def _classify_ytdlp_error(msg: Optional[str]) -> Optional[str]:
    """Raison FR si l'erreur est DÉFINITIVE pour ce titre, sinon None."""
    s = str(msg or "")
    if not s or _TRANSIENT_ERROR_RE.search(s):
        return None
    for rx, reason in _PERMANENT_ERRORS:
        if rx.search(s):
            return reason
    return None


def _short_ytdlp_error(err) -> str:
    """Dernière ligne ERROR utile, sans le préfixe `ERROR: [youtube] <id>:`."""
    lines = [ln.strip() for ln in str(err or "").splitlines() if ln.strip()]
    errs = [ln for ln in lines if "ERROR:" in ln]
    s = (errs[-1] if errs else (lines[0] if lines else ""))
    s = re.sub(r"^.*?ERROR:\s*", "", s)
    s = re.sub(r"^\[[^\]]+\]\s*(?:[\w-]+:\s)?", "", s)
    return s[:200]


def _last_ytdlp_error_line(text: str) -> str:
    errs = [ln.strip() for ln in (text or "").splitlines() if "ERROR:" in ln]
    return errs[-1] if errs else ""


def _stream_target(url_or_query: str) -> str:
    """Cible yt-dlp d'un titre, ou TrackUnavailable immédiat (sans extraction).

    - lien Spotify → refusé (non pris en charge) ;
    - lien YouTube de liste SANS vidéo précise (playlist, mix sans v=, chaîne,
      album) → refusé ; toute autre forme (clip/, v/, e/…) passe telle quelle
      (garde-fou playlist_items=1 dans _mk_opts) ;
    - texte libre → `ytsearch1:<texte>` (jamais passé tel quel comme « URL »).
    """
    raw = (url_or_query or "").strip()
    if re.match(r"^(?:yt|sc)search\d*:", raw, re.IGNORECASE):
        return raw
    s = normalize_link(raw)
    if is_spotify_url(s):
        raise TrackUnavailable(
            "Les liens Spotify ne sont pas pris en charge : colle un lien YouTube ou le titre du morceau."
        )
    if not is_url(s):
        if not s:
            raise TrackUnavailable("Requête vide.")
        return f"ytsearch1:{s}"
    if is_playlist_or_mix_url(s) and not _extract_video_id(s):
        raise TrackUnavailable(
            "Lien de playlist ou de chaîne YouTube : il doit être ajouté comme playlist, pas comme un titre."
        )
    return s


# ── Info fallbacks ──
def _probe_with_client(
    query, *, cookies_file, cookies_from_browser, ffmpeg_path,
    ratelimit_bps, client=None, po_tokens: Optional[List[str]] = None
):
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        po_tokens=po_tokens,
    )
    # Probe mono-vidéo : l'erreur réelle doit remonter (classification)
    opts["ignoreerrors"] = False
    if client:
        opts.setdefault("extractor_args", {}).setdefault("youtube", {})["player_client"] = [client]
    with _open_ydl(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    if info and "entries" in info:
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise TrackUnavailable("Aucun résultat YouTube pour cette recherche.")
        info = entries[0]
    return info or None


def _best_info_with_fallbacks(
    query, *, cookies_file, cookies_from_browser, ffmpeg_path, ratelimit_bps,
    po_tokens: Optional[List[str]] = None,
):
    if po_tokens is None:
        po_tokens = _resolve_po_tokens_for(query)
    common = {
        "cookies_file": cookies_file,
        "cookies_from_browser": cookies_from_browser,
        "ffmpeg_path": ffmpeg_path,
        "ratelimit_bps": ratelimit_bps,
        "po_tokens": po_tokens,
    }

    # 1) Tentative avec l'ordre complet de clients (laisse yt-dlp choisir)
    try:
        info = _probe_with_client(query, client=None, **common)
    except DownloadError as e:
        short = _short_ytdlp_error(e)
        reason = _classify_ytdlp_error(str(e))
        if reason:
            _dbg(f"erreur définitive ({reason}): {short}")
            raise TrackUnavailable(f"{reason} — {short}") from e
        raise RuntimeError(f"Extraction YouTube impossible : {short}") from e
    if not info:
        return None
    if info.get("url"):
        return info

    # 2) Fallback : un client à la fois — seulement si l'info est venue SANS
    #    URL directe (raté de sélection de format), jamais sur une erreur.
    for c in _CLIENTS_ORDER:
        try:
            info = _probe_with_client(query, client=c, **common)
        except DownloadError as e:
            _dbg(f"client={c} → {_short_ytdlp_error(e)}")
            continue
        if info and info.get("url"):
            _dbg(f"fallback client={c} worked")
            return info
        _dbg(f"client={c} → no direct url")
    return None


# ══════════════════════════════════════════
# STREAM direct (avec PREFLIGHT obligatoire)
# ══════════════════════════════════════════
async def stream(
    url_or_query, ffmpeg_path,
    *, cookies_file=None, cookies_from_browser=None,
    ratelimit_bps=None, afilter=None,
):
    # Rejets immédiats (Spotify, playlist sans v=…) : TrackUnavailable, sans extraction
    query = _stream_target(url_or_query)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM request: {query!r}")

    po_tokens = await asyncio.to_thread(_resolve_po_tokens_for, query)
    info = await asyncio.get_running_loop().run_in_executor(
        None,
        functools.partial(
            _best_info_with_fallbacks, query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ff_loc or ff_exec,
            ratelimit_bps=ratelimit_bps,
            po_tokens=po_tokens,
        ),
    )

    if not info:
        raise RuntimeError("Aucun résultat YouTube.")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible.")

    headers = dict(info.get("http_headers") or {})
    ua = headers.pop("User-Agent", _YT_UA)
    hdr_blob = "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"

    # ─── Preflight FFmpeg 2s — bloque tôt sur les 403/429 ───
    def _preflight_direct_sync() -> Tuple[bool, str]:
        try:
            cmd = [
                ff_exec, "-nostdin", "-hide_banner", "-loglevel", "warning",
                *_ff_reconnect_flags(),
                "-protocol_whitelist", "file,https,tcp,tls,crypto",
                "-user_agent", ua, "-headers", hdr_blob,
                "-probesize", "32k", "-analyzeduration", "0",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-i", stream_url, "-t", "2", "-f", "null", "-",
            ]
            if _HTTP_PROXY:
                cmd = cmd[:1] + ["-http_proxy", _HTTP_PROXY] + cmd[1:]
            cp = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=25,
            )
            tail = (cp.stdout or "")[-400:]
            if cp.returncode != 0:
                _dbg(f"preflight direct FAILED rc={cp.returncode} tail={tail}")
            return cp.returncode == 0, tail
        except Exception as e:
            _dbg(f"preflight direct exception: {e}")
            return False, str(e)

    ok_direct, tail = await asyncio.to_thread(_preflight_direct_sync)

    # ─── 403 → invalide le cache PO et tente PIPE ───
    if not ok_direct:
        if _AUTO_PIPE_ON_403 and ("403" in tail or "Forbidden" in tail or "429" in tail):
            vid = _extract_video_id(query) or info.get("id")
            _dbg(f"403/429 détecté → invalidation cache PO pour {vid}, bascule PIPE")
            invalidate_po_cache(vid)
        _dbg("STREAM: direct preflight FAILED → fallback to PIPE")
        try:
            return await stream_pipe(
                query, ffmpeg_path,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                ratelimit_bps=ratelimit_bps,
                afilter=afilter,
                known_info=info,  # pas de ré-extraction juste pour le titre
            )
        except TrackUnavailable:
            raise
        except Exception as e:
            # Le pipe vient d'être tenté : l'appelant peut éviter de le relancer.
            try:
                e.pipe_tried = True
            except Exception:
                pass
            raise

    _dbg("STREAM: preflight OK → direct mode")

    before_opts = (
        f"-nostdin -hide_banner -loglevel warning "
        f"-user_agent {shlex.quote(ua)} -headers {shlex.quote(hdr_blob)} "
        f"-probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay "
        f"-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 "
        f"-reconnect_on_network_error 1 -reconnect_delay_max 5 "
        f"-rw_timeout 60000000 -timeout 60000000 "
        f"-protocol_whitelist file,https,tcp,tls,crypto"
    )
    if _HTTP_PROXY:
        before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
    out_opts = "-vn"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options=out_opts,
        executable=ff_exec,
    )
    setattr(src, "_ytdlp_proc", None)
    return src, title


# ══════════════════════════════════════════
# STREAM PIPE (yt-dlp stdout → FFmpeg)
# ══════════════════════════════════════════
_PIPE_PREFLIGHT_SOFT_S = 12.0
_PIPE_PREFLIGHT_HARD_S = float(os.getenv("YTDLP_PIPE_PREFLIGHT_MAX_S", "30"))
_PROGRESS_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


def _progress_out_time_us(text: Optional[str]) -> int:
    """Durée d'audio décodée d'après `ffmpeg -progress` (0 si rien reçu)."""
    vals = [int(v) for v in _PROGRESS_RE.findall(text or "")]
    return max(vals) if vals else 0


def _drain_lines(pipe, sink: List[str], echo: bool = False) -> None:
    """Vide le stderr de yt-dlp (évite qu'il bloque) en gardant la fin."""
    try:
        while True:
            chunk = pipe.readline()
            if not chunk:
                break
            line = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                sink.append(line)
                del sink[:-40]
                if echo:
                    print(f"[YTDBG][yt-dlp] {line}", flush=True)
    except Exception:
        pass


def _stop_ytdlp_proc(proc, writer: Optional[threading.Thread] = None) -> None:
    """Tue yt-dlp, attend sa fin et ferme ses pipes (idempotent)."""
    if not proc:
        return
    _kill_proc(proc)
    try:
        proc.wait(timeout=2)
    except Exception:
        pass
    if writer is not None and writer is not threading.current_thread():
        try:
            writer.join(timeout=1)
        except Exception:
            pass
    for f in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
        try:
            if f:
                f.close()
        except Exception:
            pass


class _PipedFFmpegPCMAudio(discord.FFmpegPCMAudio):
    """FFmpegPCMAudio alimenté par le stdout de yt-dlp : cleanup() tue aussi
    le producteur (skip/stop/fin anticipée), sinon yt-dlp reste bloqué à vie,
    et supprime la copie privée des cookies donnée à ce yt-dlp."""

    def __init__(self, ytdlp_proc, *args, cookie_copy: Optional[str] = None, **kwargs):
        self._ytdlp_proc = ytdlp_proc
        self._cookie_copy = cookie_copy
        super().__init__(*args, **kwargs)

    def cleanup(self) -> None:
        proc, self._ytdlp_proc = getattr(self, "_ytdlp_proc", None), None
        ck, self._cookie_copy = getattr(self, "_cookie_copy", None), None
        writer = getattr(self, "_pipe_writer_thread", None)
        _kill_proc(proc)  # plus rien n'entre dans le pipe
        try:
            # ffmpeg tué AVANT d'attendre le writer discord.py : après un skip
            # il est bloqué sur le stdin de ffmpeg (~1 s de silence sinon)
            super().cleanup()
        finally:
            _stop_ytdlp_proc(proc, writer)
            _remove_quiet(ck)


async def stream_pipe(
    url_or_query, ffmpeg_path,
    *, cookies_file=None, cookies_from_browser=None,
    ratelimit_bps=None, afilter=None, known_info: Optional[dict] = None,
):
    query = _stream_target(url_or_query)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {query!r}")

    po_tokens = await asyncio.to_thread(_resolve_po_tokens_for, query)

    info = known_info
    if info is None:
        try:
            info = await asyncio.get_running_loop().run_in_executor(
                None,
                functools.partial(
                    _best_info_with_fallbacks, query,
                    cookies_file=cookies_file,
                    cookies_from_browser=cookies_from_browser,
                    ffmpeg_path=ff_loc or ff_exec,
                    ratelimit_bps=ratelimit_bps,
                    po_tokens=po_tokens,
                ),
            )
        except TrackUnavailable:
            raise
        except Exception as e:
            _dbg(f"STREAM_PIPE: extraction préalable KO ({e}) → tentative pipe quand même")
            info = None
    title = (info or {}).get("title", "Musique inconnue")

    # Cible CLI : la vidéo résolue si on la connaît (pas de nouvelle recherche)
    cli_target = query
    page = str((info or {}).get("webpage_url") or "")
    page_vid = _extract_video_id(page)
    if page_vid and _is_youtube_host(_yt_parse(page)[1]):
        cli_target = f"https://www.youtube.com/watch?v={page_vid}"

    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if po_tokens:
        ea_parts.append(f"po_token={','.join(po_tokens)}")
    ea = "youtube:" + ";".join(ea_parts)

    browser_spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
    picked_cookies = None if browser_spec else _pick_cookiefile(cookies_file)

    def _build_cmd(fmt: str, cookie_copy: Optional[str] = None) -> List[str]:
        cmd = _resolve_ytdlp_cli() + [
            "-f", fmt,
            "--no-playlist", "--no-check-certificates",
            "--retries", "5", "--fragment-retries", "5",
            "--concurrent-fragments", "1",
            "--newline",
            "--user-agent", _YT_UA,
            "--extractor-args", ea,
            "--add-header", "Referer:https://www.youtube.com/",
            "--add-header", "Origin:https://www.youtube.com",
            "-o", "-",
        ]
        if _FORCE_IPV4:
            cmd += ["--force-ipv4"]
        if _HTTP_PROXY:
            cmd += ["--proxy", _HTTP_PROXY]
        if browser_spec:
            cmd += ["--cookies-from-browser", browser_spec]
        elif cookie_copy:
            # Copie privée : la CLI réécrit aussi le fichier --cookies en sortant
            cmd += ["--cookies", cookie_copy]
        if ratelimit_bps:
            cmd += ["--limit-rate", str(int(ratelimit_bps))]
        # "--" : la cible ne peut jamais être lue comme une option yt-dlp
        cmd += ["--", cli_target]
        return cmd

    def _preflight_pipe_sync() -> Tuple[Optional[str], str]:
        """Renvoie (format gagnant, "") ou (None, fin du stderr yt-dlp) si
        TOUS les essais échouent.

        ⚠️ FIX MAJEUR : l'ancienne version retournait "18" même en échec,
        ce qui faisait démarrer FFmpeg sur un flux mort et déclenchait la
        boucle de "reconnect réseau" dans le PlayerService.
        Timeout : succès seulement si de l'audio a réellement circulé
        (`-progress`) ; sinon on patiente jusqu'à _PIPE_PREFLIGHT_HARD_S.
        """
        last_rc = None
        err_tail = ""
        for fmt in [_FORMAT_CHAIN, "18"]:
            yt = ff = drain = None
            errs: List[str] = []
            stalled = False
            ck = _make_cookie_copy(picked_cookies)  # une copie par essai
            try:
                yt = subprocess.Popen(
                    _build_cmd(fmt, ck),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=False, bufsize=0, close_fds=True,
                )
                if not yt.stdout:
                    _kill_proc(yt)
                    continue
                if yt.stderr:
                    drain = threading.Thread(target=_drain_lines, args=(yt.stderr, errs), daemon=True)
                    drain.start()
                ff = subprocess.Popen(
                    [
                        ff_exec, "-nostdin", "-hide_banner", "-loglevel", "warning",
                        "-nostats", "-progress", "pipe:1",
                        "-probesize", "32k", "-analyzeduration", "0",
                        "-fflags", "nobuffer", "-flags", "low_delay",
                        "-i", "pipe:0", "-t", "2", "-f", "null", "-",
                    ],
                    stdin=yt.stdout,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    ff.communicate(timeout=_PIPE_PREFLIGHT_SOFT_S)
                except subprocess.TimeoutExpired:
                    # Pas encore 2 s d'audio : yt-dlp lent (extraction, throttling) ou bloqué
                    try:
                        ff.communicate(timeout=max(1.0, _PIPE_PREFLIGHT_HARD_S - _PIPE_PREFLIGHT_SOFT_S))
                    except subprocess.TimeoutExpired:
                        _kill_proc(ff)
                        out, _ = ff.communicate()
                        if _progress_out_time_us(out) > 0:
                            _dbg(f"pipe preflight fmt={fmt}: audio lent mais présent → OK")
                            return fmt, ""
                        stalled = True
                if not stalled:
                    last_rc = ff.returncode
                    if ff.returncode == 0:
                        return fmt, ""
                    _dbg(f"pipe preflight fmt={fmt} rc={ff.returncode}")
            finally:
                _kill_proc(ff)
                _stop_ytdlp_proc(yt, drain)
                _remove_quiet(ck)
            err_tail = "\n".join(errs[-8:])
            if stalled:
                # Extraction bloquée : inutile de retenter un autre format
                _dbg(f"pipe preflight fmt={fmt}: aucun audio après {_PIPE_PREFLIGHT_HARD_S:.0f}s")
                err_tail = err_tail or "aucune donnée audio reçue de yt-dlp"
                break
        _dbg(f"pipe preflight: TOUS les formats ont échoué (last rc={last_rc})")
        return None, err_tail

    chosen_fmt, err_tail = await asyncio.to_thread(_preflight_pipe_sync)

    if chosen_fmt is None:
        err_line = _last_ytdlp_error_line(err_tail)
        reason = _classify_ytdlp_error(err_line)
        if reason:
            raise TrackUnavailable(f"{reason} — {_short_ytdlp_error(err_line)}")
        if any(m in err_tail for m in ("403", "429", "Forbidden")):
            # On n'invalide le PO que sur un vrai 403/429 (PO périmé possible)
            invalidate_po_cache(_extract_video_id(cli_target) or (info or {}).get("id"))
            raise RuntimeError(
                "Stream YouTube indisponible (403/SABR). Vérifie les cookies YT "
                "et le PO token."
            )
        raise RuntimeError(
            f"Stream YouTube indisponible (pipe) : {_short_ytdlp_error(err_tail) or 'aucun flux audio'}"
        )

    _dbg(f"PIPE chosen format: {chosen_fmt}")

    # Copie des cookies propre au producteur : supprimée par src.cleanup()
    ck = _make_cookie_copy(picked_cookies)
    try:
        yt = subprocess.Popen(
            _build_cmd(chosen_fmt, ck),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, bufsize=0, close_fds=True,
        )
    except Exception:
        _remove_quiet(ck)
        raise
    if not yt.stdout:
        _stop_ytdlp_proc(yt)
        _remove_quiet(ck)
        raise RuntimeError("yt-dlp pipe unavailable")

    if yt.stderr:
        threading.Thread(target=_drain_lines, args=(yt.stderr, [], True), daemon=True).start()

    before_opts = (
        "-nostdin -re -hide_banner -loglevel warning "
        "-probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay"
    )
    out_opts = "-vn"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    try:
        src = _PipedFFmpegPCMAudio(
            yt,
            source=yt.stdout, executable=ff_exec,
            before_options=before_opts, options=out_opts, pipe=True,
            cookie_copy=ck,
        )
    except Exception:
        _stop_ytdlp_proc(yt)
        _remove_quiet(ck)
        raise
    setattr(src, "_title", title)
    return src, title


# ── Download ──
def download(
    url, ffmpeg_path,
    *, cookies_file=None, cookies_from_browser=None,
    out_dir="downloads", ratelimit_bps=2_500_000,
):
    os.makedirs(out_dir, exist_ok=True)
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    po_tokens = _resolve_po_tokens_for(url)
    opts = _mk_opts(
        ffmpeg_path=ff_loc or ff_exec,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        for_download=True,
        po_tokens=po_tokens,
    )
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"
    try:
        with _open_ydl(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            req = (info or {}).get("requested_downloads") or []
            filepath = (
                req[0].get("filepath")
                if req
                else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
            )
            return (
                filepath,
                (info or {}).get("title", "Musique inconnue"),
                (info or {}).get("duration"),
            )
    except DownloadError as e:
        if "Requested format is not available" in str(e):
            opts["format"] = "18"
            with _open_ydl(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = (
                    req[0].get("filepath")
                    if req
                    else (os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3")
                )
                return (
                    filepath,
                    (info or {}).get("title", "Musique inconnue"),
                    (info or {}).get("duration"),
                )
        raise RuntimeError(f"Échec download YouTube: {e}") from e


def safe_cleanup(src) -> None:
    try:
        _stop_ytdlp_proc(getattr(src, "_ytdlp_proc", None))
    except Exception:
        pass
    try:
        src.cleanup()
    except Exception:
        pass
