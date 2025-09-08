# extractors/soundcloud.py
# ----------------------------------------------------------------------
#  SoundCloud extractor (Greg le Consanguin) — Parité avec YouTube
#  - STREAM prioritaire via API v2 (progressive MP3 quand dispo), sinon HLS
#  - Fallback yt_dlp (download=False) avec headers → FFmpeg
#  - Client IDs: ENV + cache persistant + scraping a-v2.sndcdn.com/assets/*.js
#  - Tests CLI: env | search | resolve | stream | download
#  - Proxy/IPv4: respecte HTTP(S)_PROXY / ALL_PROXY / SC_FORCE_IPV4
#  - Debug: SC_DEBUG=1 pour traces verbeuses
# ----------------------------------------------------------------------

from __future__ import annotations

import asyncio
import base64
import functools
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL

# ============================== DEBUG / ENV ===============================

_SCDBG = os.getenv("SC_DEBUG", "0").lower() not in ("", "0", "false", "no")
_FORCE_IPV4 = os.getenv("SC_FORCE_IPV4", "1").lower() not in ("", "0", "false", "no")
_HTTP_PROXY = os.getenv("YTDLP_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

def _dbg(*args):
    if _SCDBG:
        print("[SCDBG]", *args)

def is_valid(url: str) -> bool:
    return isinstance(url, str) and ("soundcloud.com" in url or "sndcdn.com" in url)

def _headers_default() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": "https://soundcloud.com",
        "Origin": "https://soundcloud.com",
        "Accept": "*/*",
    }

def _ffmpeg_headers_str(h: dict | None) -> str:
    """Construit les en-têtes CRLF que FFmpeg attend avec -headers."""
    base = _headers_default()
    h = {str(k).lower(): str(v) for k, v in (h or {}).items()}
    ua = h.get("user-agent") or base["User-Agent"]
    ref = h.get("referer") or base["Referer"]
    org = h.get("origin") or base["Origin"]
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    return "\r\n".join(out)

# ------------------------ FFmpeg path helpers ------------------------

def _resolve_ffmpeg_paths(ffmpeg_hint: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Résout le binaire FFmpeg à exécuter ET le dossier à donner à yt-dlp (pour ffprobe).
    Retourne (ffmpeg_exec, ffmpeg_location_dir|None).
    """
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

# ============================ Client IDs ============================

_SC_CACHE_FILE = Path(".sc_client_ids.json")
_SC_CLIENT_CACHE: List[str] = []
_SC_MAX_CACHE = 20

_CLIENT_ID_REGEXES = [
    re.compile(r'client_id\s*[:=]\s*"([A-Za-z0-9-_]{16,64})"'),
    re.compile(r'client_id=([A-Za-z0-9-_]{16,64})'),
]

def _load_sc_cache():
    global _SC_CLIENT_CACHE
    try:
        if _SC_CACHE_FILE.exists():
            data = json.loads(_SC_CACHE_FILE.read_text("utf-8"))
            if isinstance(data, list):
                _SC_CLIENT_CACHE = [str(x) for x in data if x]
                _dbg("cache load:", _SC_CLIENT_CACHE[:3], f"(total {len(_SC_CLIENT_CACHE)})")
    except Exception as e:
        _dbg("cache load failed:", e)

def _save_sc_cache():
    try:
        _SC_CACHE_FILE.write_text(json.dumps(list(dict.fromkeys(_SC_CLIENT_CACHE))[:_SC_MAX_CACHE]), "utf-8")
    except Exception as e:
        _dbg("cache save failed:", e)

def _push_good_client_id(cid: str):
    if not cid:
        return
    if cid in _SC_CLIENT_CACHE:
        _SC_CLIENT_CACHE.remove(cid)
    _SC_CLIENT_CACHE.insert(0, cid)
    while len(_SC_CLIENT_CACHE) > _SC_MAX_CACHE:
        _SC_CLIENT_CACHE.pop()
    _save_sc_cache()
    _dbg(f"mark good client_id: {cid[:4]}… (cache={len(_SC_CLIENT_CACHE)})")

def _requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_headers_default())
    # Requests honore déjà les proxies via env, mais on les force si précisés
    if _HTTP_PROXY:
        s.proxies.update({"http": _HTTP_PROXY, "https": _HTTP_PROXY})
    return s

def _sc_scrape_client_ids(max_assets: int = 12, timeout: float = 8.0) -> List[str]:
    """Scrape des client_id depuis la home + assets JS."""
    ids: List[str] = []
    ses = _requests_session()
    _dbg("scraping client_id — GET /")
    r = ses.get("https://soundcloud.com/", timeout=timeout)
    r.raise_for_status()

    assets = set()
    for m in re.finditer(r'src="(https://[^"]+?/assets/[^"]+?\.js)"', r.text):
        assets.add(m.group(1))
    assets = list(assets)[:max_assets]
    _dbg(f"scanning {len(assets)} JS assets for client_id…")

    for url in assets:
        try:
            js = ses.get(url, timeout=timeout).text
        except Exception:
            continue
        for rx in _CLIENT_ID_REGEXES:
            for m in rx.finditer(js):
                cid = m.group(1)
                if cid and cid not in ids:
                    ids.append(cid)
                    _dbg(f"found client_id in {url}: {cid[:4]}…")
    return ids

def _sc_client_ids() -> List[str]:
    """
    IDs depuis l'env **+** cache **+** scraping.
    - env: SOUNDCLOUD_CLIENT_ID (séparés par , ; espace)
    - cache: .sc_client_ids.json
    - scraping: si rien → tente maintenant
    """
    _load_sc_cache()

    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    env_ids: List[str] = []
    if raw:
        env_ids = [x.strip() for x in raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        _dbg(f"client_ids from env: {len(env_ids)}")

    cache_ids = list(_SC_CLIENT_CACHE)

    scraped_ids: List[str] = []
    if not (env_ids or cache_ids):
        try:
            scraped_ids = _sc_scrape_client_ids()
        except Exception as e:
            _dbg("scraping failed:", e)

    merged = list(dict.fromkeys([*cache_ids, *env_ids, *scraped_ids]))
    random.shuffle(merged)
    for good in reversed(cache_ids):
        if good in merged:
            merged.remove(good)
            merged.insert(0, good)
    return merged

# ======================== API v2 Resolve / Streams ===================

def _sc_resolve_track(page_url: str, client_id: str, timeout: float = 8.0) -> Optional[dict]:
    """Resolve API v2 -> JSON de track (avec media.transcodings)."""
    ses = _requests_session()
    r = ses.get("https://api-v2.soundcloud.com/resolve",
                params={"url": page_url, "client_id": client_id},
                timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None

def _pick_transcodings(track_json: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """Retourne (progressive, hls) s'ils existent."""
    media = (track_json or {}).get("media") or {}
    trans = media.get("transcodings") or []
    progressive = None
    hls = None
    for t in trans:
        proto = ((t.get("format") or {}).get("protocol") or "").lower()
        if proto == "progressive" and not progressive:
            progressive = t
        elif proto == "hls" and not hls:
            hls = t
    return progressive, hls

def _resolve_stream_url(transcoding: dict, client_id: str, timeout: float = 8.0) -> Optional[str]:
    """Appelle l'endpoint de transcoding pour obtenir l'URL signée finale."""
    if not transcoding or not transcoding.get("url"):
        return None
    ses = _requests_session()
    u = transcoding["url"]
    r = ses.get(u, params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    j = r.json()
    url = j.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None

# =========================== Public: search ==========================

def search(query: str):
    """Recherche SoundCloud (flat entries avec webpage_url)."""
    ydl_opts = {
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,
    }
    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []

# =========================== Public: download ========================

async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    """
    Télécharge en .mp3 (postproc FFmpeg 192 kbps / 48 kHz).
    Reste async pour compat avec ton code actuel.
    """
    from pathlib import Path as _Path
    os.makedirs("downloads", exist_ok=True)

    ff_exec, ff_loc = _resolve_ffmpeg_paths(ffmpeg_path)

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best",
        "outtmpl": "downloads/greg_audio.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "postprocessor_args": ["-ar", "48000"],
        "ffmpeg_location": ff_loc or os.path.dirname(ff_exec),
        "quiet": False,
        "nocheckcertificate": True,
        "sleep_interval_requests": 0,
        "prefer_ffmpeg": True,
        "force_generic_extractor": False,
        "retries": 5,
        "fragment_retries": 5,
    }
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY
    if _FORCE_IPV4:
        ydl_opts["source_address"] = "0.0.0.0"

    loop = asyncio.get_event_loop()

    def _extract_and_download():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            ydl.download([url])
            return info, ydl

    info, ydl = await loop.run_in_executor(None, _extract_and_download)
    title = (info or {}).get("title", "Son inconnu")
    duration = (info or {}).get("duration", 0)

    original = ydl.prepare_filename(info)
    filename = Path(original).with_suffix(".mp3")
    if not os.path.exists(filename):
        candidates = list(Path("downloads").glob("greg_audio*.mp3"))
        if candidates:
            filename = candidates[0]
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")

    return str(filename), title, duration

# ============================ Public: stream =========================

async def stream(url_or_query: str, ffmpeg_path: str):
    """
    Stream SoundCloud :
    1) URL SoundCloud → API v2 (progressive prioritaire, sinon HLS) → FFmpeg
    2) Sinon → yt_dlp (download=False) → FFmpeg avec headers
    Retourne (discord.FFmpegPCMAudio, title)
    """
    import discord  # import tardif pour éviter charge côté outils CLI

    ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_path)

    # --- 1) Progressive/HLS via API v2 si URL SoundCloud
    if isinstance(url_or_query, str) and "soundcloud.com" in url_or_query:
        cids = _sc_client_ids()
        _dbg("client_ids available:", len(cids))
        for cid in cids or [None]:
            if not cid:
                _dbg("no client_id available → skip resolve, go yt_dlp fallback")
                break
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if not tr:
                    continue

                title = tr.get("title") or "Son inconnu"
                duration_ms = tr.get("duration") or 0
                if tr.get("access", "").lower() == "blocked":
                    _dbg("access=blocked → cannot stream via API")
                progressive, hls = _pick_transcodings(tr)
                _dbg("resolve → transcodings:",
                     [((t or {}).get("format", {}) or {}).get("protocol") for t in [progressive, hls] if t])

                chosen = progressive or hls
                if chosen:
                    stream_url = _resolve_stream_url(chosen, cid)
                    if stream_url:
                        _push_good_client_id(cid)
                        proto = ((chosen.get("format") or {}).get("protocol") or "").lower()
                        is_hls = proto == "hls" or stream_url.lower().endswith(".m3u8")

                        before = f"-headers {shlex.quote(_ffmpeg_headers_str(None))} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                        if _HTTP_PROXY:
                            before += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
                        if _FORCE_IPV4:
                            before += " -protocol_whitelist file,http,https,tcp,tls,crypto"

                        if is_hls:
                            before += " -protocol_whitelist file,http,https,tcp,tls,crypto -allowed_extensions ALL"

                        source = discord.FFmpegPCMAudio(
                            stream_url,
                            before_options=before,
                            options="-vn -fflags nobuffer -flags low_delay",
                            executable=ff_exec
                        )
                        return source, title

            except Exception as e:
                _dbg(f"resolve attempt failed ({cid[:4]}…): {e}")
                continue

    # --- 2) Fallback: yt_dlp (peut renvoyer HLS)
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "retries": 5,
        "fragment_retries": 5,
    }
    if _HTTP_PROXY:
        ydl_opts["proxy"] = _HTTP_PROXY
    if _FORCE_IPV4:
        ydl_opts["source_address"] = "0.0.0.0"

    loop = asyncio.get_event_loop()

    def _extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    try:
        data = await loop.run_in_executor(None, _extract)
        info = data["entries"][0] if "entries" in data else data
        stream_url = info["url"]
        title = info.get("title", "Son inconnu")
        http_headers = info.get("http_headers") or data.get("http_headers") or {}
        is_hls = ".m3u8" in stream_url.lower()

        before = f"-headers {shlex.quote(_ffmpeg_headers_str(http_headers))} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        if _HTTP_PROXY:
            before += f" -http_proxy {shlex.quote(_HTTP_PROXY)}"
        if is_hls:
            before += " -protocol_whitelist file,http,https,tcp,tls,crypto -allowed_extensions ALL"

        import discord
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=before,
            options="-vn -fflags nobuffer -flags low_delay",
            executable=ff_exec
        )
        return source, title

    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")

# ======================== Helpers de test (CLI) =======================

def _print_env_summary():
    print("\n=== SC ENV SUMMARY ===")
    print(f"FORCE_IPV4: {_FORCE_IPV4}")
    print(f"PROXY: {_HTTP_PROXY or 'none'}")
    print(f"SC_DEBUG: {_SCDBG}")
    raw = (os.getenv("SOUNDCLOUD_CLIENT_ID") or "").strip()
    print(f"SOUNDCLOUD_CLIENT_ID: {'set' if raw else 'unset'}")
    cache_count = 0
    try:
        if _SC_CACHE_FILE.exists():
            cache_count = len(json.loads(_SC_CACHE_FILE.read_text('utf-8')) or [])
    except Exception:
        pass
    print(f"Cache file: {_SC_CACHE_FILE} (ids={cache_count})")
    print("======================\n")

def _ffmpeg_pull_test(url: str, headers_blob: str, ffmpeg_path: str, seconds: int = 3, is_hls: bool = False) -> int:
    ff_exec, _ = _resolve_ffmpeg_paths(ffmpeg_path)
    before = [
        "-nostdin",
        "-headers", headers_blob,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-probesize", "32k", "-analyzeduration", "0",
        "-fflags", "nobuffer", "-flags", "low_delay",
    ]
    if _HTTP_PROXY:
        before += ["-http_proxy", _HTTP_PROXY]
    if is_hls:
        before += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-allowed_extensions", "ALL"]
    cmd = [ff_exec] + before + ["-i", url, "-t", str(seconds), "-f", "null", "-"]
    print("[CLI] ffmpeg test cmd:", " ".join(shlex.quote(c) for c in cmd))
    cp = subprocess.run(cmd, text=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    print("[CLI] ffmpeg exit:", cp.returncode)
    if cp.stdout:
        print(cp.stdout[-1200:])
    return cp.returncode

# =============================== CLI =================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("SoundCloud extractor debug CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="Afficher le résumé d'environnement")

    p_search = sub.add_parser("search", help="Recherche scsearch3")
    p_search.add_argument("query")

    p_res = sub.add_parser("resolve", help="Resolve API v2 (transcodings, stream URL)")
    p_res.add_argument("url")

    p_stream = sub.add_parser("stream", help="Tester un pull FFmpeg (API v2 progressive/HLS sinon yt-dlp)")
    p_stream.add_argument("url")
    p_stream.add_argument("--ffmpeg", required=True, help="Chemin vers ffmpeg (exe OU dossier)")
    p_stream.add_argument("--seconds", type=int, default=3)

    p_dl = sub.add_parser("download", help="Télécharger et convertir (mp3)")
    p_dl.add_argument("url")
    p_dl.add_argument("--ffmpeg", required=False, default=shutil.which("ffmpeg") or "ffmpeg",
                      help="Chemin vers ffmpeg (exe OU dossier)")

    args = parser.parse_args()
    _print_env_summary()

    if args.cmd == "env":
        sys.exit(0)

    elif args.cmd == "search":
        res = search(args.query)
        print(f"Results: {len(res)}")
        for i, e in enumerate(res or [], 1):
            t = e.get("title") or "?"
            u = e.get("webpage_url") or e.get("url") or "?"
            print(f" {i}. {t} — {u}")

    elif args.cmd == "resolve":
        ids = _sc_client_ids()
        print(f"Trying {len(ids)} client_id(s)…")
        for cid in ids or [None]:
            if not cid:
                print("no client_id available.")
                break
            tr = _sc_resolve_track(args.url, cid)
            if not tr:
                continue
            prog, hls = _pick_transcodings(tr)
            print("title:", tr.get("title"))
            print("transcodings:", [((t or {}).get("format", {}) or {}).get("protocol") for t in [prog, hls] if t])
            chosen = prog or hls
            if chosen:
                su = _resolve_stream_url(chosen, cid)
                print("resolved stream host:", urlparse(su).hostname if su else None)
                if su:
                    print("OK (first resolved).")
                    sys.exit(0)
        print("No stream resolved via API v2.")
        sys.exit(2)

    elif args.cmd == "stream":
        # 1) Essai API v2
        ids = _sc_client_ids()
        ok = False
        if "soundcloud.com" in args.url:
            for cid in ids or [None]:
                if not cid:
                    break
                tr = _sc_resolve_track(args.url, cid)
                if not tr:
                    continue
                prog, hls = _pick_transcodings(tr)
                chosen = prog or hls
                if not chosen:
                    continue
                su = _resolve_stream_url(chosen, cid)
                if not su:
                    continue
                proto = ((chosen.get("format") or {}).get("protocol") or "").lower()
                is_hls = proto == "hls" or su.lower().endswith(".m3u8")
                hdr_blob = _ffmpeg_headers_str(None)
                code = _ffmpeg_pull_test(su, hdr_blob, args.ffmpeg, seconds=args.seconds, is_hls=is_hls)
                sys.exit(code)
        # 2) Fallback yt-dlp
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "default_search": "scsearch3",
            "nocheckcertificate": True,
            "retries": 3,
            "fragment_retries": 3,
        }
        if _HTTP_PROXY:
            ydl_opts["proxy"] = _HTTP_PROXY
        if _FORCE_IPV4:
            ydl_opts["source_address"] = "0.0.0.0"
        with YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(args.url, download=False)
        info = data["entries"][0] if "entries" in data else data
        su = info["url"]
        is_hls = ".m3u8" in su.lower()
        hdr_blob = _ffmpeg_headers_str(info.get("http_headers") or data.get("http_headers") or {})
        code = _ffmpeg_pull_test(su, hdr_blob, args.ffmpeg, seconds=args.seconds, is_hls=is_hls)
        sys.exit(code)


    elif args.cmd == "download":
        try:
            path, title, dur = asyncio.run(download(args.url, args.ffmpeg))
            print(f"OK: {path} | {title} | {dur}")
            sys.exit(0)
        except Exception as e:
            print(f"DOWNLOAD ERROR: {e}")
            sys.exit(3)
