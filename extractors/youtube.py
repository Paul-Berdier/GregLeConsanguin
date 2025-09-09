# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — DEBUG MAX + Contournements 403
# - Clients sûrs (évite TV/SABR): ios → web → web_creator → web_mobile → android
# - STREAM direct: URL + headers → FFmpeg (anti-403) (+ -http_proxy si défini)
# - STREAM (PIPE): yt-dlp → stdout → FFmpeg (avant fallback download)
# - DOWNLOAD: MP3 (192 kbps, 48 kHz) avec fallback propre (itag 18 si besoin)
# - Cookies: navigateur (cookiesfrombrowser) prioritaire, sinon fichier Netscape ;
#            support injection via env/base64 (YTDLP_COOKIES_B64 → youtube.com_cookies.txt)
# - Proxies/VPN: support env YTDLP_HTTP_PROXY / HTTPS_PROXY / ALL_PROXY → yt-dlp & http_probe & FFmpeg
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

def _fmt_epoch(e: str | int | None) -> str:
    try:
        e = int(e)
        t = dt.datetime.utcfromtimestamp(e)
        left = e - int(time.time())
        return f"{t.isoformat()}Z (t-{left}s)"
    except Exception:
        return "?"

# ====== CONFIG via ENV ======
_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
_FORCE_IPV4 = os.getenv("YTDLP_FORCE_IPV4", "1").lower() not in ("0", "false", "")
_HTTP_PROXY = os.getenv("YTDLP_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

_CLIENTS_ORDER = ["ios", "web", "web_creator", "web_mobile", "android"]

# 🔊 Formats orientés AUDIO ; overridable par env YTDLP_FORMAT
_FORMAT_CHAIN = os.getenv(
    "YTDLP_FORMAT",
    "bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/bestaudio/18"
)
_COOKIE_FILE_DEFAULT = "youtube.com_cookies.txt"

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u)

# ------------------------ FFmpeg path helpers ------------------------

def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Résout le binaire FFmpeg à exécuter ET le dossier à donner à yt-dlp (pour ffprobe).
    Retourne (ffmpeg_exec, ffmpeg_location_dir|None).
    - Accepte: chemin exe, dossier bin, simple 'ffmpeg' si dans PATH.
    - Sur Windows: binaire = 'ffmpeg.exe'
    """
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    def _abs(p: str) -> str:
        return os.path.abspath(os.path.expanduser(p))

    # 1) Pas d'indice fourni → chercher dans PATH
    if not ffmpeg_hint:
        which = shutil.which(exe_name) or shutil.which("ffmpeg")
        if which:
            return which, os.path.dirname(which)
        return "ffmpeg", None  # on laisse le système résoudre

    p = _abs(ffmpeg_hint)

    # 2) Si c'est un dossier → joindre le binaire
    if os.path.isdir(p):
        cand = os.path.join(p, exe_name)
        if os.path.isfile(cand):
            return cand, p
        # si on a passé .../ffmpeg (racine) → souvent le binaire est dans ./bin
        cand2 = os.path.join(p, "bin", exe_name)
        if os.path.isfile(cand2):
            return cand2, os.path.dirname(cand2)
        raise FileNotFoundError(f"FFmpeg introuvable dans le dossier: {p} (attendu: {exe_name} ou bin/{exe_name})")

    # 3) Si c'est un fichier → OK
    if os.path.isfile(p):
        return p, os.path.dirname(p)

    # 4) Sinon, essayer le PATH avec ce hint
    which = shutil.which(p)
    if which:
        return which, os.path.dirname(which)

    raise FileNotFoundError(f"FFmpeg introuvable: {ffmpeg_hint}")

# ------------------------ cookies helpers ------------------------

def _ensure_cookiefile_from_b64(target_path: str) -> Optional[str]:
    """
    Si YTDLP_COOKIES_B64 est présent, (ré)écrit un fichier cookies Netscape.
    Retourne le chemin si écrit, sinon None.
    """
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
    allow_playlist: bool = False,   # ★ NEW
    extract_flat: bool = False,     # ★ NEW (utile pour les playlists)
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
        "noplaylist": (not allow_playlist),   # ★
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "source_address": "0.0.0.0" if _FORCE_IPV4 else None,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
        },
        "extractor_args": {
            "youtube": {
                "player_client": list(_CLIENTS_ORDER),
            }
        },
        "youtube_include_dash_manifest": True,
        "format": _FORMAT_CHAIN,
    }

    if extract_flat:
        ydl_opts["extract_flat"] = True  # ★ rapide et suffisant pour lister les entrées

    # ffmpeg_location pour yt-dlp = dossier (pas le .exe)
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

def is_playlist_or_mix_url(url: str) -> bool:
    """
    Détecte les liens YouTube de type playlist/mix.
    Gère:
      - watch?v=...&list=PL..., RD..., RDEM..., OLAK..., etc.
      - /playlist?list=...
      - watch?...&start_radio=1 (radio/mix auto)
    """
    if not isinstance(url, str):
        return False
    try:
        u = _url.urlsplit(url)
        host = (u.hostname or "").lower()
        if "youtube.com" not in host and "youtu.be" not in host and "music.youtube.com" not in host:
            return False
        qs = {k: v[0] for k, v in _url.parse_qs(u.query).items()}
        if "list" in qs and qs["list"]:
            return True
        if qs.get("start_radio") == "1":
            return True
        if (u.path or "").startswith("/playlist"):
            return True
        return False
    except Exception:
        return False


def expand_playlist_or_mix(
    url: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    max_items: int = 10,
) -> List[dict]:
    """
    Retourne jusqu'à `max_items` éléments à partir d'une URL YouTube playlist/mix.
    - Supporte list=PL..., RD..., RDEM..., OLAK..., start_radio=1, etc.
    - Extraction "flat" rapide puis normalisation en:
      {title, url, webpage_url, duration, thumb, uploader, provider='youtube'}.
    - Essaie de commencer à la vidéo courante si identifiable (v=... ou index=...).
    """
    if not url or "youtube" not in url:
        return []

    # Paramètres utiles (pour caler le point de départ)
    u = _url.urlsplit(url)
    q = {k: v[0] for k, v in _url.parse_qs(u.query).items()}
    list_id  = q.get("list")
    video_id = q.get("v")
    start_idx = None
    try:
        if "index" in q:
            start_idx = max(0, int(q["index"]) - 1)
    except Exception:
        start_idx = None
    if (not list_id) and q.get("start_radio") == "1" and video_id:
        list_id = f"RD{video_id}"

    seed_url = f"https://www.youtube.com/playlist?list={list_id}" if list_id else url

    # Extraction flat de la playlist/mix
    opts = _mk_opts(
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        allow_playlist=True,
        extract_flat=True,
    )
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(seed_url, download=False)

    entries = (info or {}).get("entries") or []
    if not entries:
        return []

    # Trouver le point de départ
    if start_idx is not None and 0 <= start_idx < len(entries):
        begin = start_idx
    elif video_id:
        begin = 0
        for i, e in enumerate(entries):
            vid = (e or {}).get("id") or (e or {}).get("url")
            if vid and vid == video_id:
                begin = i
                break
    else:
        begin = 0

    sub = entries[begin:begin + max_items]
    if not sub:
        sub = entries[:max_items]

    out: List[dict] = []
    for e in sub:
        if not isinstance(e, dict):
            continue
        vid = e.get("id") or e.get("url")
        if not vid:
            continue
        watch = f"https://www.youtube.com/watch?v={vid}"
        if list_id:
            watch += f"&list={list_id}"

        # thumb: 'thumbnails' (liste) > 'thumbnail'
        thumb = None
        if isinstance(e.get("thumbnails"), list) and e["thumbnails"]:
            try:
                thumb = (e["thumbnails"][-1] or {}).get("url")
            except Exception:
                thumb = None
        thumb = thumb or e.get("thumbnail")

        out.append({
            "title": e.get("title") or "Titre inconnu",
            "url": watch,
            "webpage_url": watch,
            "duration": e.get("duration"),
            "thumb": thumb,
            "uploader": e.get("uploader"),
            "provider": "youtube",
        })

    return out

def expand_bundle(
    url: str,
    *,
    limit: int = 10,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> List[dict]:
    """Alias attendu par extractors.expand_bundle / music.py (paramètre 'limit')."""
    return expand_playlist_or_mix(
        url,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        max_items=limit,
    )

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
    """Essaye d'extraire info (avec URL directe) en forçant un client précis si fourni."""
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
    """Tente successivement les clients jusqu'à obtenir un info['url'] exploitable."""
    _dbg(f"_best_info_with_fallbacks(query={query})")
    # 1) yt-dlp auto
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

    # 2) forcer clients connus
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
    """Optionnel: interroge en HEAD puis GET Range 0-1 pour voir si 403 côté serveur."""
    if not _YTDBG_HTTP_PROBE:
        return
    _dbg("HTTP_PROBE: start")
    opener = None
    try:
        handlers = []
        if _HTTP_PROXY:
            handlers.append(_ureq.ProxyHandler({"http": _HTTP_PROXY, "https": _HTTP_PROXY}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        # HEAD
        r = _ureq.Request(url, method="HEAD", headers=headers)
        with opener.open(r, timeout=10) as resp:
            _dbg(f"HTTP_PROBE: HEAD {getattr(resp, 'status', resp.getcode())}")
            _dbg(f"HTTP_PROBE: Server={resp.headers.get('Server')} Age={resp.headers.get('Age')} Via={resp.headers.get('Via')}")
            return
    except Exception as e:
        _dbg(f"HTTP_PROBE: HEAD failed: {e}")
    # GET Range
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
    afilter: Optional[str] = None,  # ★ filtre audio optionnel
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Prépare un stream pour Discord via URL directe (yt-dlp choisit un flux audio).
    Passe les http_headers à FFmpeg (anti-403) + DEBUG complet.
    Applique un filtre audio (-af) si fourni et force 48 kHz / stéréo pour Discord.
    """
    import asyncio

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM request: url_or_query={url_or_query!r}")
    _dbg(f"ENV: UA={_YT_UA[:60]}...")
    _dbg(f"ENV: cookies_from_browser={cookies_from_browser or os.getenv('YTDLP_COOKIES_BROWSER')}, cookies_file={cookies_file}, proxy={_HTTP_PROXY or 'none'}, ipv4={_FORCE_IPV4}")
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

    # Log params URL
    qs = _parse_qs(stream_url)
    _dbg(f"yt-dlp client_used={client_used}, title={title!r}")
    _dbg(f"URL host={_url.urlsplit(stream_url).hostname}, itag={qs.get('itag')} mime={qs.get('mime')} dur={qs.get('dur')} clen={qs.get('clen')} ip={qs.get('ip')}")
    _dbg(f"URL expire={_fmt_epoch(qs.get('expire'))}")

    # Headers FFmpeg
    headers = (info.get("http_headers") or {})
    headers.setdefault("User-Agent", _YT_UA)
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    headers.setdefault("Accept-Language", "en-us,en;q=0.5")
    headers.setdefault("Sec-Fetch-Mode", "navigate")
    headers.setdefault("Referer", "https://www.youtube.com/")
    headers.setdefault("Origin", "https://www.youtube.com")
    hdr_blob = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"

    # HTTP probe (optionnel)
    try:
        _http_probe(stream_url, headers)
    except Exception as e:
        _dbg(f"http_probe error: {e}")

    before_opts = (
        "-nostdin "
        f"-user_agent {shlex.quote(headers['User-Agent'])} "
        f"-headers {shlex.quote(hdr_blob)} "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-rw_timeout 15000000 "
        "-probesize 32k -analyzeduration 0 "
        "-fflags nobuffer -flags low_delay "
        "-seekable 0"
    )
    # 🔌 Proxy FFmpeg si défini
    if _HTTP_PROXY:
        before_opts += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"

    _dbg(f"FFMPEG before_options={before_opts}")
    _dbg(f"FFMPEG headers (redacted)={_redact_headers(headers)}")

    # ★ Options de sortie: 48 kHz + stéréo + debug + filtre éventuel
    out_opts = "-vn -ar 48000 -ac 2 -loglevel debug"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options=out_opts,  # ★
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
    afilter: Optional[str] = None,  # ★ filtre audio optionnel
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Fallback streaming robuste: yt-dlp → stdout → FFmpeg (pipe) → Discord.
    Utilisé si FFmpeg direct prend 403 malgré les headers.
    Applique un filtre audio (-af) si fourni et force 48 kHz / stéréo pour Discord.
    """
    import asyncio

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")
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
    title = (info or {}).get("title", "Musique inconnue")

    cmd = _resolve_ytdlp_cli() + [
        "-f", _FORMAT_CHAIN,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", f"youtube:player_client={','.join(_CLIENTS_ORDER)}",
        "-o", "-",  # → stdout
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

    # IMPORTANT: text=False pour que stdout reste binaire (FFmpeg lit des bytes)
    yt = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,   # on capture pour debug
        text=False,
        bufsize=0,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    # Draine stderr dans un thread (décodage best-effort)
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

    # ★ Options de sortie: 48 kHz + stéréo + format PCM + filtre éventuel
    out_opts = "-vn -ar 48000 -ac 2 -f s16le"
    if afilter:
        out_opts += f" -af {shlex.quote(afilter)}"

    # FFmpeg via PIPE (yt-dlp -> stdout)
    src = discord.FFmpegPCMAudio(
        source=yt.stdout,
        executable=ff_exec,
        # -re est une OPTION D'ENTRÉE => doit être AVANT -i, donc ici:
        before_options="-nostdin -re -probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay",
        # ces options s’appliquent APRÈS -i (sortie/filtre/encodage PCM pour Discord)
        options=out_opts,  # ★
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
    """
    Télécharge l'audio et convertit en MP3.
    Retourne (filepath_mp3, title, duration_seconds|None).
    """
    os.makedirs(out_dir, exist_ok=True)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)
    # mêmes règles cookies/proxy/ipv4
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
            # Fallback ultime: itag 18 (mp4) puis conversion audio
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
    print(f"YTDBG: {_YTDBG} YTDBG_HTTP_PROBE: {_YTDBG_HTTP_PROBE}")
    print("====================\n")

def _ffmpeg_pull_test(url: str, headers: Dict[str, str], ffmpeg_path: str, seconds: int = 3) -> int:
    ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_path)
    hdr_blob = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"
    before_opts = [
        "-nostdin",
        "-user_agent", headers.get("User-Agent", _YT_UA),
        "-headers", hdr_blob,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-rw_timeout", "15000000",
        "-probesize", "32k", "-analyzeduration", "0",
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

    ytcmd = _resolve_ytdlp_cli() + [
        "-f", _FORMAT_CHAIN,
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "3",
        "--fragment-retries", "3",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", f"youtube:player_client={','.join(_CLIENTS_ORDER)}",
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
        [ff_exec, "-nostdin", "-probesize", "32k", "-analyzeduration", "0", "-fflags", "nobuffer", "-flags", "low_delay",
         "-i", "pipe:0", "-t", str(seconds), "-f", "null", "-"],
        stdin=yt.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # draine les logs yt-dlp
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

    p_stream = sub.add_parser("stream", help="Tester un pull direct FFmpeg (headers anti-403)")
    p_stream.add_argument("url")
    p_stream.add_argument("--ffmpeg", required=True, help="Chemin vers ffmpeg (exe OU dossier)")
    p_stream.add_argument("--seconds", type=int, default=3)

    p_pipe = sub.add_parser("pipe", help="Tester un pull PIPE yt-dlp → ffmpeg")
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
        # on fait juste l'extraction et un coup de ffmpeg -t N
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
        headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        headers.setdefault("Accept-Language", "en-us,en;q=0.5")
        headers.setdefault("Sec-Fetch-Mode", "navigate")
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
