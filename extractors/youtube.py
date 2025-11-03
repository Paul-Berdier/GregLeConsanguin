# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — DEBUG MAX + Contournements 403 + PO Token
# - Clients sûrs (évite SABR): ios → android → web_creator → web → web_mobile
# - PO Token: pris depuis l'ENV (brut) et décliné en ios.gvs+/android.gvs+/web.gvs+ automatiquement
# - STREAM direct: URL + headers → FFmpeg (anti-403) (+ -http_proxy si défini)
# - STREAM (PIPE): yt-dlp → stdout → FFmpeg (fallback)
# - DOWNLOAD: MP3 (192 kbps, 48 kHz) avec fallback propre (itag 18 si besoin)
# - Cookies: navigateur (cookiesfrombrowser) prioritaire, sinon fichier Netscape
# - Proxies/VPN: YTDLP_HTTP_PROXY / HTTPS_PROXY / ALL_PROXY → yt-dlp & FFmpeg
# - IPv4: forçage source_address=0.0.0.0 + --force-ipv4 pour le PIPE
# - Recherche: ytsearch5 (flat)
# - DEBUG: traces complètes [YTDBG], HTTP probe optionnelle (HEAD/GET Range)
from __future__ import annotations

import base64
import datetime as dt
import functools
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse as _url
import urllib.request as _ureq
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# ====== DEBUG TOGGLES ======
_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")
_YTDBG_HTTP_PROBE = os.getenv("YTDBG_HTTP_PROBE", "0").lower() not in ("0", "false", "")

def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG] {msg}")

def _redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = dict(h or {})
    for k in list(out.keys()):
        kl = k.lower()
        if kl in ("cookie", "authorization", "x-youtube-identity-token", "x-goog-authuser"):
            v = out.get(k)
            out[k] = f"<redacted:{len(v) if isinstance(v, str) else '?'}>"
    return out

def _parse_qs(url: str) -> Dict[str, str]:
    try:
        q = _url.urlsplit(url).query
        return {k: v[0] for k, v in _url.parse_qs(q).items()}
    except Exception:
        return {}

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u) or ("music.youtube.com/watch" in u)

# ------------------------ CONFIG via ENV ------------------------

_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
_FORCE_IPV4 = os.getenv("YTDLP_FORCE_IPV4", "1").lower() not in ("0", "false", "")
_HTTP_PROXY = os.getenv("YTDLP_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

# Ordre des clients (on met iOS/Android en tête car ce sont ceux qui nécessitent PO token pour HTTPS direct)
_CLIENTS_ORDER = ["ios", "android", "web_creator", "web", "web_mobile"]

# Formats orientés AUDIO ; overridable par env YTDLP_FORMAT
_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/bestaudio/18"
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"

# ------------------------ PO TOKEN handling ------------------------

def _collect_po_tokens() -> List[str]:
    """
    Récupère un token brut depuis l'ENV et construit automatiquement
    des variantes préfixées (ios.gvs+/android.gvs+/web.gvs+).
    Accepte aussi des tokens déjà préfixés (avec '+').
    ENV pris en compte, par ordre:
      - YT_PO_TOKEN         (brut ou déjà préfixé)
      - YTDLP_PO_TOKEN      (alias)
      - YT_PO_TOKEN_IOS     (brut → ios.gvs+)
      - YT_PO_TOKEN_ANDROID (brut → android.gvs+)
      - YT_PO_TOKEN_WEB     (brut → web.gvs+)
      - YT_PO_TOKEN_PREFIXED (déjà préfixé, passe tel quel)
    """
    raw_candidates = []
    prefixed_candidates = []

    # brut ou déjà préfixé
    for k in ("YT_PO_TOKEN", "YTDLP_PO_TOKEN"):
        v = (os.getenv(k) or "").strip()
        if not v:
            continue
        if "+" in v:
            prefixed_candidates.append(v)
        else:
            raw_candidates.append(v)

    # spécifiques bruts
    ios = (os.getenv("YT_PO_TOKEN_IOS") or "").strip()
    if ios:
        raw_candidates.append(("ios.gvs", ios))
    android = (os.getenv("YT_PO_TOKEN_ANDROID") or "").strip()
    if android:
        raw_candidates.append(("android.gvs", android))
    web = (os.getenv("YT_PO_TOKEN_WEB") or "").strip()
    if web:
        raw_candidates.append(("web.gvs", web))

    # déjà préfixé explicite
    v_pref = (os.getenv("YT_PO_TOKEN_PREFIXED") or "").strip()
    if v_pref:
        prefixed_candidates.append(v_pref)

    tokens: List[str] = []

    # si on a un brut “simple” (sans préciser le préfixe), on crée plusieurs variantes
    for raw in raw_candidates:
        if isinstance(raw, tuple):
            # (prefix, token)
            prefix, tok = raw
            if tok:
                tokens.append(f"{prefix}+{tok}")
        else:
            # pas de prefix connu → on tente plusieurs clients
            tok = raw
            if tok:
                tokens.append(f"ios.gvs+{tok}")
                tokens.append(f"android.gvs+{tok}")
                tokens.append(f"web.gvs+{tok}")

    # + tokens déjà préfixés
    for p in prefixed_candidates:
        if p:
            tokens.append(p)

    # dédup
    out = []
    seen = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)

    if out:
        _dbg(f"PO tokens detected → using: {', '.join(p.split('+',1)[0] for p in out)}")
    else:
        _dbg("PO tokens: none")
    return out

_PO_TOKENS = _collect_po_tokens()

# ------------------------ FFmpeg path helpers ------------------------

def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    def _abs(p: str) -> str:
        return os.path.abspath(os.path.expanduser(p))

    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        if which:
            return which, os.path.dirname(which)
        return "ffmpeg", None

    p = _abs(ffmpeg_hint)

    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand):
            return cand, p
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2):
            return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans le dossier: {p}")

    if os.path.isfile(p):
        return p, os.path.dirname(p)

    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)

    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")

# ------------------------ cookies helpers ------------------------

def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
        text = raw.decode("utf-8", errors="replace")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(text)
        _dbg(f"cookies: written from env to {target_path} ({len(text)} chars)")
        return target_path
    except Exception as e:
        _dbg(f"cookies: failed to write from env: {e}")
        return None

def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec:
        return None
    parts = spec.split(":", 1)
    browser = parts[0].strip().lower()
    profile = parts[1].strip() if len(parts) > 1 else None
    return (browser,) if profile is None else (browser, profile)

# ------------------------ yt-dlp opts ------------------------

def _mk_opts(
    *,
    ffmpeg_path: Optional[str] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    search: bool = False,
    for_download: bool = False,
    allow_playlist: bool = False,
    extract_flat: bool = False,
) -> Dict[str, Any]:
    # cookies via env/base64 si besoin
    if (not cookies_file) and os.path.exists(_COOKIE_FILE_DEFAULT):
        cookies_file = _COOKIE_FILE_DEFAULT
    if (not cookies_file) and os.getenv("YTDLP_COOKIES_B64"):
        _ensure_cookiefile_from_b64(_COOKIE_FILE_DEFAULT)
        if os.path.exists(_COOKIE_FILE_DEFAULT):
            cookies_file = _COOKIE_FILE_DEFAULT

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": (not allow_playlist),
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "source_address": "0.0.0.0" if _FORCE_IPV4 else None,
        # 🔑 En-têtes exigés par YT (erreur 153 si Referer absent côté "client")
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": {
            "youtube": {
                "player_client": list(_CLIENTS_ORDER),
            }
        },
        "youtube_include_dash_manifest": True,
        "format": _FORMAT_CHAIN,
    }

    if _PO_TOKENS:
        ydl_opts["extractor_args"]["youtube"]["po_token"] = ",".join(_PO_TOKENS)

    if extract_flat:
        ydl_opts["extract_flat"] = True

    if ffmpeg_path:
        if os.path.isfile(ffmpeg_path):
            ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path)
        else:
            ydl_opts["ffmpeg_location"] = ffmpeg_path

    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY

    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
        _dbg(f"cookiesfrombrowser={cfb}")
    elif cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file
        _dbg(f"cookiefile={cookies_file} (exists=True)")
    else:
        _dbg("cookies: none")

    if search:
        ydl_opts.update({
            "default_search": "ytsearch5",
            "extract_flat": True,
        })

    if for_download:
        ydl_opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "postprocessor_args": ["-ar", "48000"],
        })

    for k in list(ydl_opts.keys()):
        if ydl_opts[k] is None:
            del ydl_opts[k]
    return ydl_opts

# ------------------------ search ------------------------

def _normalize_search_entries(entries: List[dict]) -> List[dict]:
    out = []
    for e in entries or []:
        title = e.get("title") or "Titre inconnu"
        url = e.get("webpage_url") or e.get("url") or ""
        if not (url.startswith("http://") or url.startswith("https://")):
            vid = e.get("id")
            if vid:
                url = f"https://www.youtube.com/watch?v={vid}"
        out.append({
            "title": title,
            "url": url,
            "webpage_url": url,
            "duration": e.get("duration"),
            "thumb": e.get("thumbnail"),
            "provider": "youtube",
            "uploader": e.get("uploader"),
        })
    return out

def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        return _normalize_search_entries(entries)

# ------------------------ playlist / mix expansion ------------------------
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional

def is_playlist_or_mix_url(url: str) -> bool:
    try:
        u = urlparse(url)
        if not u.netloc:
            return False
        if "youtube.com" not in u.netloc and "youtu.be" not in u.netloc and "music.youtube.com" not in u.netloc:
            return False
        q = parse_qs(u.query)
        lst = (q.get("list") or [None])[0]
        if lst:
            return True
        if u.path.strip("/").lower() == "playlist" and lst:
            return True
        return False
    except Exception:
        return False

def is_playlist_like(url: str) -> bool:
    return is_playlist_or_mix_url(url)

def _yt_watch_url(video_id: str, list_id: Optional[str] = None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return f"{base}&list={list_id}" if list_id else base

def expand_bundle(
    page_url: str,
    limit_total: Optional[int] = None,
    limit: Optional[int] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> List[Dict]:
    """
    Déplie une URL YouTube playlist/mix en N=10 éléments *consécutifs*.
    - Si ?index=K est présent (1-based côté YouTube), on prend K..K+9.
    - Sinon, on commence sur la vidéo v=... si fournie, puis on prend 10 au total.
    """
    import yt_dlp

    N = int(limit_total or limit or 10)

    # --- Paramètres playlist: list & index (YouTube: index est 1-based)
    parsed = urlparse(page_url)
    q = parse_qs(parsed.query)
    list_id = (q.get("list") or [None])[0]
    start_idx: Optional[int] = None
    try:
        raw_idx = (q.get("index") or [None])[0]
        if raw_idx is not None:
            start_idx = max(1, int(raw_idx))
    except Exception:
        start_idx = None

    # --- Options yt-dlp dédiées "bundle"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": False,
        "playlistend": N,
        "http_headers": {  # 👈 assure Referer/Origin pendant l’expansion
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        },
        "extractor_args": {
            "youtube": {
                "player_client": list(_CLIENTS_ORDER),
            }
        }
    }
    if start_idx:
        # on récupère exactement index..index+N-1
        ydl_opts["playliststart"] = start_idx
        ydl_opts["playlistend"]   = start_idx + N - 1
    else:
        # sinon: les N premières
        ydl_opts["playlistend"] = N

    # PO token + cookies si dispo
    if _PO_TOKENS:
        ydl_opts["extractor_args"]["youtube"]["po_token"] = ",".join(_PO_TOKENS)

    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = tuple(
            cookies_from_browser.split(":", 1)
        ) if ":" in cookies_from_browser else (cookies_from_browser,)

    def _extract(u):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(u, download=False)

    # 1) tentative directe sur l'URL donnée
    info = _extract(page_url)

    # 2) fallback explicite /playlist?list=...
    if (not info or not info.get("entries")) and list_id:
        playlist_url = f"https://www.youtube.com/playlist?list={list_id}"
        info2 = _extract(playlist_url)
        if info2 and info2.get("entries"):
            info = info2

    # 3) certains watch-pages redirigent vers une autre URL de type playlist
    if (not info or not info.get("entries")) and info and info.get("_type") == "url":
        try:
            info3 = _extract(info["url"])
            if info3 and info3.get("entries"):
                info = info3
        except Exception:
            pass

    entries = (info or {}).get("entries") or []
    if not entries:
        return []

    # Si aucun index explicite, on aligne la 1ʳᵉ sur v=...
    v_id = None
    try:
        v_id = (parse_qs(urlparse(page_url).query).get("v") or [None])[0]
    except Exception:
        v_id = None

    if v_id and not start_idx:
        try:
            idx = next((i for i, e in enumerate(entries)
                        if (e.get("id") or e.get("url")) == v_id), None)
            if idx is not None:
                entries = entries[idx:] + entries[:idx]
        except Exception:
            pass

    out: List[Dict] = []
    for e in entries:
        vid = e.get("id") or e.get("url")
        if not vid:
            continue
        title = e.get("title") or ""
        artist = e.get("uploader") or e.get("channel") or e.get("uploader_id")
        thumb = (
            e.get("thumbnail")
            or (e.get("thumbnails") or [{}])[-1].get("url")
            or None
        )
        dur = e.get("duration")
        url = f"https://www.youtube.com/watch?v={vid}"
        if list_id:
            url += f"&list={list_id}"

        out.append({
            "title": title or url,
            "url": url,
            "webpage_url": url,
            "artist": artist,
            "thumb": thumb,
            "duration": dur,
            "provider": "youtube",
        })
        if len(out) >= N:
            break

    return out

# ------------------------ internal probe helpers ------------------------

def _probe_with_client(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
    client: Optional[str] = None,
) -> Optional[dict]:
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
    )
    if client:
        opts.setdefault("extractor_args", {}).setdefault("youtube", {})["player_client"] = [client]

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info and info["entries"]:
            info = info["entries"][0]
        if info is not None:
            info["_dbg_client_used"] = client or "auto"
        return info or None

def _best_info_with_fallbacks(
    query: str,
    *,
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    ffmpeg_path: Optional[str],
    ratelimit_bps: Optional[int],
) -> Optional[dict]:
    _dbg(f"_best_info_with_fallbacks(query={query})")
    info = _probe_with_client(
        query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
        client=None,
    )
    if info and info.get("url"):
        _dbg(f"yt-dlp chose client={info.get('_dbg_client_used')}, title={info.get('title')!r}")
        return info

    for c in _CLIENTS_ORDER:
        info = _probe_with_client(
            query,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ffmpeg_path,
            ratelimit_bps=ratelimit_bps,
            client=c,
        )
        if info and info.get("url"):
            _dbg(f"fallback client={c} worked, title={info.get('title')!r}")
            return info
        else:
            _dbg(f"client={c} → no direct url")
    return None

def _resolve_ytdlp_cli() -> List[str]:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]

def _http_probe(url: str, headers: Dict[str, str]) -> None:
    if not _YTDBG_HTTP_PROBE:
        return
    _dbg("HTTP_PROBE: start")
    opener = None
    try:
        handlers = []
        if _HTTP_PROXY:
            handlers.append(_ureq.ProxyHandler({"http": _HTTP_PROXY, "https": _HTTP_PROXY}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        r = _ureq.Request(url, method="HEAD", headers=headers)
        with opener.open(r, timeout=10) as resp:
            _dbg(f"HTTP_PROBE: HEAD {getattr(resp, 'status', resp.getcode())}")
            _dbg(f"HTTP_PROBE: Server={resp.headers.get('Server')} Age={resp.headers.get('Age')} Via={resp.headers.get('Via')}")
            return
    except Exception as e:
        _dbg(f"HTTP_PROBE: HEAD failed: {e}")
    try:
        req_h2 = dict(headers or {})
        req_h2["Range"] = "bytes=0-1"
        r2 = _ureq.Request(url, method="GET", headers=req_h2)
        resp2 = (opener or _ureq.build_opener()).open(r2, timeout=10)
        with resp2 as resp:
            _dbg(f"HTTP_PROBE: GET Range→ {getattr(resp, 'status', resp.getcode())} (len={resp.headers.get('Content-Length')})")
    except Exception as e:
        _dbg(f"HTTP_PROBE: GET Range failed: {e}")

# ------------------------ public: stream (direct) ------------------------

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Résout un flux bestaudio stable (clients web/android) puis lance FFmpeg
    avec les *mêmes headers* que yt-dlp (anti-403/googlevideo).
    """
    import asyncio

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM request: url_or_query={url_or_query!r}")
    _dbg(f"ENV: UA={_YT_UA[:60]}...")
    _dbg(f"ENV: cookies_from_browser={cookies_from_browser or os.getenv('YTDLP_COOKIES_BROWSER')}, "
         f"cookies_file={cookies_file}, proxy={_HTTP_PROXY or 'none'}, ipv4={_FORCE_IPV4}")
    _dbg(f"FFmpeg exec resolved: {ff_exec}")
    _dbg(f"yt-dlp ffmpeg_location: {ff_loc or '-'}")

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec,
        ratelimit_bps=ratelimit_bps,
    ))
    if not info:
        raise RuntimeError("Aucun résultat YouTube (aucun client n’a fourni d’URL).")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    client_used = info.get("_dbg_client_used", "unknown")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible (clients bloqués).")

    qs = _parse_qs(stream_url)
    _dbg(f"yt-dlp client_used={client_used}, title={title!r}")
    _dbg(f"URL host={_url.urlsplit(stream_url).hostname}, itag={qs.get('itag')} "
         f"mime={qs.get('mime')} dur={qs.get('dur')} clen={qs.get('clen')} ip={qs.get('ip')}")
    _dbg(f"URL expire={qs.get('expire')}")

    # Headers exacts retournés par yt-dlp (incluant cookies si besoin)
    headers = (info.get("http_headers") or {})
    headers.setdefault("User-Agent", _YT_UA)
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    headers.setdefault("Accept-Language", "en-us,en;q=0.5")
    headers.setdefault("Sec-Fetch-Mode", "navigate")
    # 🔑 indispensables contre l’erreur 153 côté “client”
    headers.setdefault("Referer", "https://www.youtube.com/")
    headers.setdefault("Origin", "https://www.youtube.com")
    hdr_blob = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"

    # Optionnel: sonde HTTP (HEAD/GET range) pour debug
    try:
        _http_probe(stream_url, headers)
    except Exception as e:
        _dbg(f"http_probe error: {e}")

    before_opts = (
        "-nostdin "
        f"-user_agent {shlex.quote(headers['User-Agent'])} "
        f"-headers {shlex.quote(hdr_blob)} "
        f"-referer {shlex.quote('https://www.youtube.com/') } "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-rw_timeout 15000000 "
        "-probesize 64k -analyzeduration 0 "
        "-fflags nobuffer -flags low_delay "
        "-seekable 0"
    )
    if _HTTP_PROXY:
        before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"

    _dbg(f"FFMPEG before_options={before_opts}")
    _dbg(f"FFMPEG headers (redacted)={_redact_headers(headers)}")

    out_opts = "-vn -ar 48000 -ac 2 -loglevel error"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options=out_opts,
        executable=ff_exec,
    )
    _dbg("FFMPEG source created (direct URL).")

    setattr(source, "_ytdlp_proc", None)
    return source, title

# ------------------------ public: stream_pipe (yt-dlp → ffmpeg) ------------------------

async def stream_pipe(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    afilter: Optional[str] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Fallback "pipe" : yt-dlp télécharge/concatène en stdout, FFmpeg lit sur pipe.
    Utile quand les URLs directes retournent 403 ou expirent agressivement.
    """
    import asyncio

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")
    _dbg(f"FFmpeg exec resolved: {ff_exec}")
    _dbg(f"yt-dlp ffmpeg_location: {ff_loc or '-'}")

    loop = asyncio.get_running_loop()
    # on résout quand même info pour le titre (non bloquant si None)
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ff_loc or ff_exec,
        ratelimit_bps=ratelimit_bps,
    ))
    title = (info or {}).get("title", "Musique inconnue")

    # --extractor-args : player_client + po_token (si dispo)
    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if _PO_TOKENS:
        ea_parts.append(f"po_token={','.join(_PO_TOKENS)}")
    ea = "youtube:" + ";".join(ea_parts)

    cmd = _resolve_ytdlp_cli() + [
        "-f", _FORMAT_CHAIN,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", ea,
        # 🔑 anti-153: injecter Referer/Origin côté yt-dlp aussi
        "--add-header", "Referer:https://www.youtube.com/",
        "--add-header", "Origin:https://www.youtube.com",
        "-o", "-",
    ]
    if _FORCE_IPV4:
        cmd += ["--force-ipv4"]
    if _HTTP_PROXY:
        cmd += ["--proxy", _HTTP_PROXY]
    spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
    if spec:
        cmd += ["--cookies-from-browser", spec]
    elif cookies_file and os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]
    elif os.path.exists(_COOKIE_FILE_DEFAULT):
        cmd += ["--cookies", _COOKIE_FILE_DEFAULT]
    if ratelimit_bps:
        cmd += ["--limit-rate", str(int(ratelimit_bps))]
    cmd += [url_or_query]

    _dbg(f"yt-dlp PIPE cmd: {' '.join(shlex.quote(c) for c in cmd)}")

    yt = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    def _drain_stderr():
        try:
            while True:
                chunk = yt.stderr.readline()
                if not chunk:
                    break
                try:
                    line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                except Exception:
                    line = repr(chunk)
                if line:
                    print(f"[YTDBG][yt-dlp] {line}")
        except Exception as e:
            print(f"[YTDBG][yt-dlp] <stderr reader died: {e}>")

    threading.Thread(target=_drain_stderr, daemon=True).start()

    out_opts = "-vn -ar 48000 -ac 2 -f s16le"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    src = discord.FFmpegPCMAudio(
        source=yt.stdout,
        executable=ff_exec,
        before_options="-nostdin -re -probesize 64k -analyzeduration 0 -fflags nobuffer -flags low_delay",
        options=out_opts,
        pipe=True,
    )

    _dbg("FFMPEG source created (PIPE).")

    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title

# ------------------------ public: download ------------------------

def download(
    url: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    out_dir: str = "downloads",
    ratelimit_bps: Optional[int] = 2_500_000,
) -> Tuple[str, str, Optional[int]]:
    os.makedirs(out_dir, exist_ok=True)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    opts = _mk_opts(
        ffmpeg_path=ff_loc or ff_exec,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        for_download=True,
    )
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"

    try:
        with YoutubeDL(opts) as ydl:
            _dbg(f"DOWNLOAD start: {url}")
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]

            req = (info or {}).get("requested_downloads") or []
            if req:
                filepath = req[0].get("filepath")
            else:
                base = ydl.prepare_filename(info)
                filepath = os.path.splitext(base)[0] + ".mp3"

            title = (info or {}).get("title", "Musique inconnue")
            duration = (info or {}).get("duration")
            _dbg(f"DOWNLOAD ok: path={filepath}, title={title!r}, dur={duration}")
            return filepath, title, duration
    except DownloadError as e:
        _dbg(f"DOWNLOAD failed: {e}")
        if "Requested format is not available" in str(e):
            opts2 = _mk_opts(
                ffmpeg_path=ff_loc or ff_exec,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                ratelimit_bps=ratelimit_bps,
                for_download=True,
            )
            opts2["format"] = "18"
            opts2["paths"] = {"home": out_dir}
            opts2["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"
            with YoutubeDL(opts2) as ydl2:
                _dbg("DOWNLOAD fallback: itag=18")
                info = ydl2.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = req[0].get("filepath") if req else (os.path.splitext(ydl2.prepare_filename(info))[0] + ".mp3")
                title = (info or {}).get("title", "Musique inconnue")
                duration = (info or {}).get("duration")
                _dbg(f"DOWNLOAD fallback ok: path={filepath}, title={title!r}, dur={duration}")
                return filepath, title, duration
        raise RuntimeError(f"Échec download YouTube: {e}") from e

# ======================== CLI de test local ========================

def _print_env_summary():
    print("\n=== ENV SUMMARY ===")
    print(f"UA: {_YT_UA[:80]}...")
    print(f"FORCE_IPV4: {_FORCE_IPV4}")
    print(f"PROXY: {_HTTP_PROXY or 'none'}")
    print(f"YTDLP_COOKIES_BROWSER: {os.getenv('YTDLP_COOKIES_BROWSER') or 'none'}")
    print(f"YTDLP_COOKIES_B64: {'set' if os.getenv('YTDLP_COOKIES_B64') else 'unset'}")
    cf = os.path.exists(_COOKIE_FILE_DEFAULT)
    print(f"cookie file present: {cf} -> {_COOKIE_FILE_DEFAULT if cf else '-'}")
    print(f"PO tokens: {', '.join(_PO_TOKENS) if _PO_TOKENS else 'none'}")
    print(f"YTDBG: {_YTDBG} YTDBG_HTTP_PROBE: {_YTDBG_HTTP_PROBE}")
    print("====================\n")

def _ffmpeg_pull_test(url: str, headers: Dict[str, str], ffmpeg_path: str, seconds: int = 3) -> int:
    ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_path)
    hdr_blob = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"
    before_opts = [
        "-nostdin",
        "-user_agent", headers.get("User-Agent", _YT_UA),
        "-headers", hdr_blob,
        "-referer", "https://www.youtube.com/",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-rw_timeout", "15000000",
        "-probesize", "64k", "-analyzeduration", "0",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-seekable", "0",
    ]
    if _HTTP_PROXY:
        before_opts += ["-http_proxy", _HTTP_PROXY]
    cmd = [ff_exec] + before_opts + ["-i", url, "-t", str(seconds), "-f", "null", "-"]
    print("[CLI] ffmpeg test cmd:", " ".join(shlex.quote(c) for c in cmd))
    cp = subprocess.run(cmd, text=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    print("[CLI] ffmpeg exit:", cp.returncode)
    if cp.stdout:
        print(cp.stdout[-1200:])
    return cp.returncode

def _ytdlp_pipe_pull_test(url: str, ffmpeg_path: str, seconds: int = 3) -> int:
    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)

    ea_parts = [f"player_client={','.join(_CLIENTS_ORDER)}"]
    if _PO_TOKENS:
        ea_parts.append(f"po_token={','.join(_PO_TOKENS)}")
    ea = "youtube:" + ";".join(ea_parts)

    ytcmd = _resolve_ytdlp_cli() + [
        "-f", _FORMAT_CHAIN,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "3",
        "--fragment-retries", "3",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", ea,
        "--add-header", "Referer:https://www.youtube.com/",
        "--add-header", "Origin:https://www.youtube.com",
        "-o", "-",
    ]

    if _FORCE_IPV4:
        ytcmd += ["--force-ipv4"]
    if _HTTP_PROXY:
        ytcmd += ["--proxy", _HTTP_PROXY]
    if os.path.exists(_COOKIE_FILE_DEFAULT):
        ytcmd += ["--cookies", _COOKIE_FILE_DEFAULT]
    ytcmd += [url]

    print("[CLI] yt-dlp pipe cmd:", " ".join(shlex.quote(c) for c in ytcmd))

    yt = subprocess.Popen(
        ytcmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    ff = subprocess.Popen(
        [ff_exec, "-nostdin", "-probesize", "64k", "-analyzeduration", "0", "-fflags", "nobuffer", "-flags", "low_delay",
         "-i", "pipe:0", "-t", str(seconds), "-f", "null", "-"],
        stdin=yt.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def _drain_stderr():
        try:
            while True:
                chunk = yt.stderr.readline()
                if not chunk:
                    break
                try:
                    line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                except Exception:
                    line = repr(chunk)
                if line:
                    print(f"[YTDBG][yt-dlp] {line}")
        except Exception as e:
            print(f"[YTDBG][yt-dlp] <stderr reader died: {e}>")

    threading.Thread(target=_drain_stderr, daemon=True).start()

    out = ff.communicate()[0] or ""
    rc = ff.returncode
    print("[CLI] ffmpeg (pipe) exit:", rc)
    if out:
        print(out[-1200:])

    try:
        yt.kill()
    except Exception:
        pass
    return rc

def _cli_env():
    _print_env_summary()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("YouTube extractor debug CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="Afficher le résumé d'environnement")

    p_search = sub.add_parser("search", help="Recherche ytsearch5")
    p_search.add_argument("query")

    p_stream = sub.add_parser("stream", help="Tester un pull direct FFmpeg (headers anti-403/153)")
    p_stream.add_argument("url")
    p_stream.add_argument("--ffmpeg", required=True, help="Chemin vers ffmpeg (exe OU dossier)")
    p_stream.add_argument("--seconds", type=int, default=3)

    p_pipe = sub.add_parser("pipe", help="Tester un pull PIPE yt-dlp → ffmpeg (headers côté yt-dlp)")
    p_pipe.add_argument("url")
    p_pipe.add_argument("--ffmpeg", required=True, help="Chemin vers ffmpeg (exe OU dossier)")
    p_pipe.add_argument("--seconds", type=int, default=3)

    p_dl = sub.add_parser("download", help="Télécharger et convertir (mp3)")
    p_dl.add_argument("url")
    p_dl.add_argument("--ffmpeg", required=False, default=shutil.which("ffmpeg") or "ffmpeg",
                      help="Chemin vers ffmpeg (exe OU dossier)")
    p_dl.add_argument("--out", default="downloads")

    p_probe = sub.add_parser("probe", help="Faire un HTTP probe (HEAD/GET Range) sur une URL googlevideo")
    p_probe.add_argument("url")

    args = parser.parse_args()
    _print_env_summary()

    if args.cmd == "env":
        _cli_env()
    elif args.cmd == "search":
        res = search(args.query)
        print(f"Results: {len(res)}")
        for i, r in enumerate(res, 1):
            print(f" {i}. {r['title']} — {r['url']}")
    elif args.cmd == "stream":
        ff_exec, ff_loc = _resolve_ffmpeg_paths(args.ffmpeg)
        info = _best_info_with_fallbacks(
            args.url,
            cookies_file=_COOKIE_FILE_DEFAULT if os.path.exists(_COOKIE_FILE_DEFAULT) else None,
            cookies_from_browser=os.getenv("YTDLP_COOKIES_BROWSER"),
            ffmpeg_path=ff_loc or ff_exec,
            ratelimit_bps=None,
        )
        if not info or not info.get("url"):
            print("AUCUNE URL DIRECTE OBTENUE")
            sys.exit(2)
        headers = (info.get("http_headers") or {})
        headers.setdefault("User-Agent", _YT_UA)
        headers.setdefault("Referer", "https://www.youtube.com/")
        headers.setdefault("Origin", "https://www.youtube.com")
        code = _ffmpeg_pull_test(info["url"], headers, ff_exec, seconds=args.seconds)
        sys.exit(code)
    elif args.cmd == "pipe":
        code = _ytdlp_pipe_pull_test(args.url, args.ffmpeg, seconds=args.seconds)
        sys.exit(code)
    elif args.cmd == "download":
        try:
            path, title, dur = download(
                args.url,
                args.ffmpeg,
                cookies_file=_COOKIE_FILE_DEFAULT if os.path.exists(_COOKIE_FILE_DEFAULT) else None,
                cookies_from_browser=os.getenv("YTDLP_COOKIES_BROWSER"),
                out_dir=args.out,
            )
            print(f"OK: {path} | {title} | {dur}")
            sys.exit(0)
        except Exception as e:
            print(f"DOWNLOAD ERROR: {e}")
            sys.exit(3)
    elif args.cmd == "probe":
        headers = {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        }
        try:
            _http_probe(args.url, headers)
        except Exception as e:
            print("probe failed:", e)
