# extractors/youtube.py
#
# YouTube robuste (Greg le Consanguin) — DEBUG MAX
# - Clients sûrs (évite TV/SABR): ios → web → web_creator → web_mobile → android (overridable)
# - STREAM direct: URL + headers → FFmpeg (anti-403)
# - STREAM (PIPE): yt-dlp → stdout (binaire) → FFmpeg (avant fallback download)
# - DOWNLOAD: MP3 (192 kbps, 48 kHz) avec fallback propre
# - Cookies: navigateur (cookiesfrombrowser) prioritaire, sinon fichier Netscape (+ import auto depuis YTDLP_COOKIES_B64)
# - Recherche: ytsearch5 (flat)
# - DEBUG: traces complètes [YTDBG], HTTP probe optionnelle, hints auto si ça casse
from __future__ import annotations

import os
import sys
import shlex
import shutil
import functools
import subprocess
import threading
import time
import datetime as dt
import base64
import tempfile
import urllib.parse as _url
import urllib.request as _ureq
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# ====== DEBUG TOGGLES ======
_YTDBG = os.getenv("YTDBG", "1") not in ("0", "false", "False", "")
_YTDBG_HTTP_PROBE = os.getenv("YTDBG_HTTP_PROBE", "0") not in ("0", "false", "False", "")

def _dbg(msg: str):
    if _YTDBG:
        print(f"[YTDBG] {msg}")

def _redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = dict(h or {})
    for k in list(out.keys()):
        lk = k.lower()
        if lk in ("cookie", "authorization", "x-youtube-identity-token"):
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

# ====== Versions (une seule fois) ======
_versions_logged = False
def _log_versions_once():
    global _versions_logged
    if _versions_logged:
        return
    _versions_logged = True
    try:
        yt_v = subprocess.check_output([sys.executable, "-m", "yt_dlp", "--version"], text=True).strip()
    except Exception:
        yt_v = "unknown"
    try:
        ff_v = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    except Exception:
        ff_v = "unknown"
    _dbg(f"versions: yt-dlp={yt_v} ; ffmpeg={ff_v}")

# UA par défaut ; peut être surchargé par l'env (recommandé: UA de ton navigateur)
_YT_UA = os.getenv("YTDLP_FORCE_UA") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

# Ordre clients configurable via env YTDLP_FORCE_CLIENTS="ios,web,..."
_DEFAULT_CLIENTS = ["ios", "web", "web_creator", "web_mobile", "android"]
_env_clients = [c.strip() for c in (os.getenv("YTDLP_FORCE_CLIENTS") or "").split(",") if c.strip()]
_CLIENTS_ORDER = _env_clients or _DEFAULT_CLIENTS

_FORMAT_CHAIN = "bestaudio[ext=m4a]/bestaudio/best/140/251/18"

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u)

# ------------------------ cookies helper ------------------------
_COOKIES_TMP_PATH: Optional[str] = None

def _ensure_cookies_file(cookies_file: Optional[str]) -> Optional[str]:
    """
    Si cookies_file n'existe pas mais que YTDLP_COOKIES_B64 est présent, on le matérialise.
    Retourne le chemin à utiliser ou None.
    """
    global _COOKIES_TMP_PATH
    if cookies_file and os.path.exists(cookies_file):
        return cookies_file

    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return cookies_file if cookies_file else None

    try:
        raw = base64.b64decode(b64.encode("utf-8"), validate=True)
        # On écrit soit au chemin demandé, soit dans un tmp dédié
        if cookies_file:
            path = cookies_file
        else:
            if _COOKIES_TMP_PATH and os.path.exists(_COOKIES_TMP_PATH):
                return _COOKIES_TMP_PATH
            fd, path = tempfile.mkstemp(prefix="youtube_cookies_", suffix=".txt")
            os.close(fd)
            _COOKIES_TMP_PATH = path
        with open(path, "wb") as f:
            f.write(raw)
        _dbg(f"cookies materialized from YTDLP_COOKIES_B64 → {path}")
        return path
    except Exception as e:
        _dbg(f"cookies materialization failed: {e}")
        return cookies_file if cookies_file else None

# ------------------------ helpers ------------------------

def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec:
        return None
    parts = spec.split(":", 1)
    browser = parts[0].strip().lower()
    profile = parts[1].strip() if len(parts) > 1 else None
    return (browser,) if profile is None else (browser, profile)

def _mk_opts(
    *,
    ffmpeg_path: Optional[str] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
    search: bool = False,
    for_download: bool = False,
) -> Dict[str, Any]:
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        # important: forcer IPv4 sur certains DC (Railway/IPv6 souvent 403)
        "source_address": "0.0.0.0",
        "http_headers": {
            "User-Agent": _YT_UA,
            "Referer": "https://www.youtube.com/",
        },
        "extractor_args": {
            "youtube": {
                # ordre de clients pour éviter TV/SABR
                "player_client": list(_CLIENTS_ORDER),
            }
        },
        "youtube_include_dash_manifest": True,
        "format": _FORMAT_CHAIN,
    }
    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    # Cookies: navigateur d'abord, sinon fichier
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    cfile = _ensure_cookies_file(cookies_file or os.getenv("YTDLP_COOKIES_FILE") or "youtube.com_cookies.txt")
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
        _dbg(f"cookiesfrombrowser={cfb}")
    elif cfile and os.path.exists(cfile):
        ydl_opts["cookiefile"] = cfile
        _dbg(f"cookiefile={cfile} (exists={os.path.exists(cfile)})")
    else:
        _dbg("cookies: none")

    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

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
            # 48 kHz pour Discord
            "postprocessor_args": ["-ar", "48000"],
        })

    return ydl_opts

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
        opts["extractor_args"]["youtube"]["player_client"] = [client]

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
    # 1) tentative avec chaîne complète (laisser yt-dlp choisir)
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

    # 2) forcer iOS, puis autres clients en séquence
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
    req_h = dict(headers or {})
    try:
        r = _ureq.Request(url, method="HEAD", headers=req_h)
        with _ureq.urlopen(r, timeout=10) as resp:
            _dbg(f"HTTP_PROBE: HEAD {resp.status}")
            _dbg(f"HTTP_PROBE: Server={resp.headers.get('Server')} Age={resp.headers.get('Age')} Via={resp.headers.get('Via')} Alt-Svc={resp.headers.get('Alt-Svc')}")
            return
    except Exception as e:
        _dbg(f"HTTP_PROBE: HEAD failed: {e}")

    try:
        req_h2 = dict(headers or {})
        req_h2["Range"] = "bytes=0-1"
        r2 = _ureq.Request(url, method="GET", headers=req_h2)
        with _ureq.urlopen(r2, timeout=10) as resp:
            _dbg(f"HTTP_PROBE: GET Range→ {resp.status} (len={resp.headers.get('Content-Length')})")
            return
    except Exception as e:
        _dbg(f"HTTP_PROBE: GET Range failed: {e}")

# ------------------------ public: search ------------------------

def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    _log_versions_once()
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        return _normalize_search_entries(entries)

# ------------------------ public: stream ------------------------

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Prépare un stream pour Discord via URL directe (yt-dlp choisit un flux audio).
    Passe les http_headers à FFmpeg (anti-403) + DEBUG complet.
    """
    import asyncio

    _log_versions_once()
    _dbg(f"STREAM request: url_or_query={url_or_query!r}")
    _dbg(f"ENV: UA={_YT_UA[:60]}...")
    _dbg(f"ENV: cookies_from_browser={cookies_from_browser or os.getenv('YTDLP_COOKIES_BROWSER')}, cookies_file={cookies_file or os.getenv('YTDLP_COOKIES_FILE') or 'youtube.com_cookies.txt'}")

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
        ratelimit_bps=ratelimit_bps,
    ))
    if not info:
        raise RuntimeError("Aucun résultat YouTube")

    stream_url = info.get("url")
    title = info.get("title", "Musique inconnue")
    client_used = info.get("_dbg_client_used", "unknown")
    if not stream_url:
        raise RuntimeError("Flux audio indisponible (clients bloqués).")

    # Log des paramètres URL
    qs = _parse_qs(stream_url)
    _dbg(f"yt-dlp client_used={client_used}, title={title!r}")
    _dbg(f"URL host={_url.urlsplit(stream_url).hostname}, itag={qs.get('itag')} mime={qs.get('mime')} dur={qs.get('dur')} clen={qs.get('clen')} ip={qs.get('ip')}")
    _dbg(f"URL expire={_fmt_epoch(qs.get('expire'))}")

    # >>>>>> HEADERS POUR FFMPEG (crucial pour éviter 403) <<<<<<
    headers = (info.get("http_headers") or {})
    headers.setdefault("User-Agent", _YT_UA)
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
    _dbg(f"FFMPEG before_options={before_opts}")
    _dbg(f"FFMPEG headers (redacted)={_redact_headers(headers)}")

    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options=before_opts,
        options="-vn -loglevel debug",
        executable=ffmpeg_path,
    )
    _dbg("FFMPEG source created (direct URL).")

    setattr(source, "_ytdlp_proc", None)
    return source, title

async def stream_pipe(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Fallback streaming robuste: yt-dlp → stdout → FFmpeg (pipe) → Discord.
    Utilisé si FFmpeg en direct prend 403 malgré les headers.
    """
    import asyncio

    _log_versions_once()
    _dbg(f"STREAM_PIPE request: {url_or_query!r}")
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, functools.partial(
        _best_info_with_fallbacks,
        url_or_query,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ffmpeg_path=ffmpeg_path,
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
        url_or_query,
    ]
    # Forcer IPv4 côté yt-dlp aussi (souvent utile sur Railway)
    cmd.insert(1, "--force-ipv4")

    spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER")) or None
    cfile = _ensure_cookies_file(cookies_file or os.getenv("YTDLP_COOKIES_FILE") or "youtube.com_cookies.txt")
    if spec:
        cmd += ["--cookies-from-browser", spec]
    elif cfile and os.path.exists(cfile):
        cmd += ["--cookies", cfile]
    if ratelimit_bps:
        cmd += ["--limit-rate", str(int(ratelimit_bps))]

    _dbg(f"yt-dlp PIPE cmd: {' '.join(shlex.quote(str(c)) for c in cmd)}")

    # PIPE binaire: stdout=None (bytes), stderr capturé en texte (thread séparé)
    yt = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,               # <<< IMPORTANT: flux binaire
        bufsize=0,
        universal_newlines=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    # Draine stderr dans un thread pour diagnostic (décodage utf-8 permissif)
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

    src = discord.FFmpegPCMAudio(
        source=yt.stdout,
        executable=ffmpeg_path,
        before_options="-nostdin -probesize 32k -analyzeduration 0 -fflags nobuffer -flags low_delay",
        options="-re -vn -ar 48000 -ac 2 -f s16le",
        pipe=True,
    )
    _dbg("FFMPEG source created (PIPE).")

    setattr(src, "_ytdlp_proc", yt)
    setattr(src, "_title", title)
    return src, title

# ------------------------ public: download ------------------------

def _print_hints(prefix: str, exc: Exception):
    msg = str(exc)
    _dbg(f"{prefix} — HINTS")
    # Pistes générales et commandes prêtes :
    _dbg("  • Vérifie les cookies: /yt_cookies_update (ou YTDLP_COOKIES_B64 / YTDLP_COOKIES_FILE)")
    _dbg("  • Forcer UA réel: export YTDLP_FORCE_UA='(UA complet de ton navigateur)'")
    _dbg("  • MAJ yt-dlp: pip install -U yt-dlp   (puis)   yt-dlp --rm-cache-dir")
    _dbg("  • MAJ FFmpeg recommandée (>= 5.x)")
    _dbg("  • Railway: préférer IPv4 (déjà forcé), sinon change de région/instance si 403 global.")
    if "Sign in to confirm you're not a bot" in msg or "HTTP Error 429" in msg:
        _dbg("  • Erreur d'auth/anti-bot: cookies récents requis (Firefox conseillé).")
    if "Unsupported URL" in msg:
        _dbg("  • URL non reconnue par yt-dlp → vérifie le lien.")
    if "ERROR: Unable to extract" in msg or "RegexNotFoundError" in msg:
        _dbg("  • yt-dlp trop vieux face aux changements YouTube → mets à jour + --rm-cache-dir.")
    if "403" in msg:
        _dbg("  • 403: essaye d'abord stream_pipe (yt-dlp gère la session), sinon download.")

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
    _log_versions_once()
    os.makedirs(out_dir, exist_ok=True)
    opts = _mk_opts(
        ffmpeg_path=ffmpeg_path,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
        for_download=True,
    )
    opts["paths"] = {"home": out_dir}
    opts["outtmpl"] = "%(title).200B - %(id)s.%(ext)s"

    try:
        _dbg(f"DOWNLOAD start: {url}")
        with YoutubeDL(opts) as ydl:
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
        _print_hints("DOWNLOAD", e)
        if "Requested format is not available" in str(e):
            # Fallback ultime: itag 18 (mp4) puis conversion audio
            opts2 = _mk_opts(
                ffmpeg_path=ffmpeg_path,
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
