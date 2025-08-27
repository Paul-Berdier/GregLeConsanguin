# extractors/soundcloud.py
# Stream SoundCloud fiable :
# 1) si URL SoundCloud -> API v2 + progressive MP3 quand dispo (via client_id)
# 2) sinon -> yt_dlp (download=False) ; on passe les headers à FFmpeg (HLS/opus)
# 3) fallback download() si stream échoue
#
# DEBUG: imprime les choix de transcodings, headers, host, etc.
# Cache: garde les client_id trouvés (env + scraping) et le "dernier bon".
# Probe: teste HLS via ffmpeg -t <SC_PROBE_SECS> avant de lancer réellement.

from __future__ import annotations

import asyncio
import functools
import json
import os
import random
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, List

import requests
from yt_dlp import YoutubeDL
from urllib.parse import urlparse

# ---------- Log helper ----------
def _dbg(msg: str):
    print(f"[SC] {msg}")

UA = os.getenv("SC_UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/134.0.0.0 Safari/537.36")

# ---------- Validation ----------
def is_valid(url: str) -> bool:
    try:
        return isinstance(url, str) and "soundcloud.com" in url
    except Exception:
        return False

# ---------- Cache client_ids ----------
_SC_CLIENT_CACHE_FILE = os.getenv("SC_CLIENT_CACHE_FILE", "/app/.cache/sc_ids.json")
_SC_CLIENT_CACHE: dict = {}  # {"ids": [...], "last_good": "..."}

def _load_sc_cache():
    global _SC_CLIENT_CACHE
    try:
        p = Path(_SC_CLIENT_CACHE_FILE)
        if p.exists():
            _SC_CLIENT_CACHE = json.loads(p.read_text("utf-8") or "{}")
            if not isinstance(_SC_CLIENT_CACHE, dict):
                _SC_CLIENT_CACHE = {}
    except Exception:
        _SC_CLIENT_CACHE = {}

def _save_sc_cache():
    try:
        p = Path(_SC_CLIENT_CACHE_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_SC_CLIENT_CACHE, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        _dbg(f"cache save failed: {e}")

def _cache_set_ids(ids: List[str]):
    _load_sc_cache()
    arr = list(dict.fromkeys([i for i in ids if i]))  # unique, conserve l'ordre
    if not _SC_CLIENT_CACHE.get("ids"):
        _SC_CLIENT_CACHE["ids"] = arr
    else:
        # merge en gardant l'ordre et sans doublons
        have = list(_SC_CLIENT_CACHE["ids"])
        for i in arr:
            if i not in have:
                have.append(i)
        _SC_CLIENT_CACHE["ids"] = have
    _save_sc_cache()

def _cache_mark_good(cid: str):
    if not cid:
        return
    _load_sc_cache()
    _SC_CLIENT_CACHE["last_good"] = cid
    # on met le "bon" en tête dans ids
    ids = list(_SC_CLIENT_CACHE.get("ids") or [])
    if cid in ids:
        ids.remove(cid)
    ids.insert(0, cid)
    _SC_CLIENT_CACHE["ids"] = ids
    _save_sc_cache()

# ---------- Scraping client_id ----------
_CLIENT_ID_RE = re.compile(r'client_id["\']?\s*[:=]\s*["\']([A-Za-z0-9-_]{10,})["\']')

def _scrape_main_and_assets(session: requests.Session) -> List[str]:
    found: List[str] = []
    # 1) GET home
    _dbg("scraping client_id — GET /")
    r = session.get("https://soundcloud.com/", timeout=6)
    r.raise_for_status()
    html = r.text or ""

    # 2) collect js assets (a-v2.sndcdn.com/assets/*)
    assets = re.findall(r'src=["\'](https://a-v2\.sndcdn\.com/assets/[^"\']+\.js)["\']', html)
    assets = list(dict.fromkeys(assets))
    max_js = int(os.getenv("SC_SCRAPE_MAX_JS", "12"))
    assets = assets[:max_js]
    _dbg(f"scanning {len(assets)} JS assets for client_id…")

    for url in assets:
        try:
            js = session.get(url, timeout=6).text
        except Exception:
            continue
        for m in _CLIENT_ID_RE.finditer(js or ""):
            cid = m.group(1)
            if cid and cid not in found:
                found.append(cid)
                _dbg(f"found client_id in {url}: {cid[:3]}…")
    return found

def _sc_scrape_client_ids() -> List[str]:
    try:
        ses = requests.Session()
        ses.headers.update({"User-Agent": UA})
        return _scrape_main_and_assets(ses)
    except Exception as e:
        _dbg(f"scraping exception: {e}")
        return []

# ---------- Client IDs provider (env + cache + scrape) ----------
def _sc_client_ids() -> List[str]:
    _load_sc_cache()

    env_raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    env_ids: List[str] = []
    if env_raw:
        env_ids = [x.strip() for x in env_raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        _dbg(f"client_ids from env: {len(env_ids)}")

    cache_ids = list(_SC_CLIENT_CACHE.get("ids") or [])
    last_good = _SC_CLIENT_CACHE.get("last_good")

    scraped: List[str] = []
    # scrape seulement si pas d'IDs cache ET pas d'IDs env, ou si on veut enrichir
    try:
        scraped = _sc_scrape_client_ids()
    except Exception as e:
        _dbg(f"scrape failed: {e}")
        scraped = []

    # merge : last_good (1er) > env > scraped > cache (restant)
    merged: List[str] = []
    if last_good:
        merged.append(last_good)
    merged.extend(env_ids)
    merged.extend(scraped)
    merged.extend([i for i in cache_ids if i not in merged])

    # unique + shuffle léger après last_good pour varier
    seen = set()
    dedup = []
    for i in merged:
        if i and i not in seen:
            seen.add(i)
            dedup.append(i)

    if last_good and len(dedup) > 1:
        head, tail = dedup[0], dedup[1:]
        random.shuffle(tail)
        dedup = [head] + tail
    else:
        random.shuffle(dedup)

    if scraped:
        _cache_set_ids(scraped)

    return dedup

# ---------- Resolve & pick transcoding ----------
def _sc_resolve_track(url: str, client_id: str, timeout: float = 8.0) -> Optional[dict]:
    ses = requests.Session()
    ses.headers.update({"User-Agent": UA})
    r = ses.get("https://api-v2.soundcloud.com/resolve",
                params={"url": url, "client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    data = r.json()
    if isinstance(data, dict) and (data.get("kind") == "track" or "media" in data):
        return data
    return None

def _pick_transcoding(track_json: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Renvoie (chosen_transcoding, protocol) en préférant progressive > hls.
    Ignore 'ctr-encrypted-hls' / 'cbc-encrypted-hls'.
    """
    media = track_json.get("media") or {}
    trans = list(media.get("transcodings") or [])
    if not trans:
        return None, None

    # filtrer chiffrés
    plain = [t for t in trans if (t.get("format") or {}).get("protocol") in ("progressive", "hls")]
    # préférer progressive
    for t in plain:
        if (t.get("format") or {}).get("protocol") == "progressive":
            return t, "progressive"
    # sinon premier hls
    for t in plain:
        if (t.get("format") or {}).get("protocol") == "hls":
            return t, "hls"
    return None, None

def _resolve_stream_url(transcoding: dict, client_id: str, timeout: float = 8.0) -> Optional[str]:
    """
    Appelle l'URL 'transcoding.url?client_id=...' => { "url": "https://cf-..." }
    """
    u = transcoding.get("url")
    if not u:
        return None
    ses = requests.Session()
    ses.headers.update({"User-Agent": UA})
    r = ses.get(u, params={"client_id": client_id}, timeout=timeout)
    if not r.ok:
        return None
    j = r.json()
    su = j.get("url")
    return su if isinstance(su, str) and su.startswith("http") else None

# ---------- FFmpeg headers builder ----------
def _ffmpeg_headers_str(base_headers: Optional[dict] = None, referer: Optional[str] = None) -> str:
    h = {}
    if isinstance(base_headers, dict):
        for k, v in base_headers.items():
            h[str(k).lower()] = str(v)
    ua = h.get("user-agent") or UA
    ref = referer or h.get("referer") or "https://soundcloud.com"
    org = h.get("origin") or "https://soundcloud.com"
    out = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
    # yt-dlp peut donner Authorization/Cookie, on les propage si présents
    if h.get("authorization"):
        out.append(f"Authorization: {h['authorization']}")
    if h.get("cookie"):
        out.append(f"Cookie: {h['cookie']}")
    return "\r\n".join(out)

# ---------- yt-dlp search ----------
def search(query: str):
    ydl_opts = {
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"scsearch3:{query}", download=False)
        return results.get("entries", []) if results else []

# ---------- Download fallback ----------
async def download(url: str, ffmpeg_path: str, cookies_file: str = None):
    os.makedirs("downloads", exist_ok=True)
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[abr>0]/bestaudio/best",
        "outtmpl": "downloads/greg_audio.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192",
        }],
        "ffmpeg_location": ffmpeg_path,
        "quiet": False,
        "nocheckcertificate": True,
        "ratelimit": 5.0,
        "sleep_interval_requests": 1,
        "prefer_ffmpeg": True,
        "force_generic_extractor": False,
    }
    loop = asyncio.get_event_loop()
    with YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, url, False))
        title = info.get("title", "Son inconnu")
        duration = info.get("duration", 0)
        await loop.run_in_executor(None, functools.partial(ydl.download, [url]))
        original = ydl.prepare_filename(info)
        if original.endswith(".opus"):
            converted = original.replace(".opus", ".mp3")
            subprocess.run([ffmpeg_path, "-y", "-i", original, "-vn",
                            "-ar", "44100", "-ac", "2", "-b:a", "192k", converted])
            try:
                os.remove(original)
            except Exception:
                pass
            filename = converted
        else:
            filename = str(Path(original).with_suffix(".mp3"))
        if not os.path.exists(filename):
            raise FileNotFoundError(f"Fichier manquant après extraction : {filename}")
    return filename, title, duration

# ---------- Internal: ffmpeg probe ----------
def _ffmpeg_probe_hls(ffmpeg_path: str, stream_url: str, headers: str, seconds: int = None) -> bool:
    sec = int(os.getenv("SC_PROBE_SECS", str(seconds or 2)))
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-headers", headers,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
        "-allowed_extensions", "ALL",
        "-t", str(sec), "-i", stream_url, "-f", "null", "-"
    ]
    _dbg(f"[FFMPEG] probe: {shlex.join(cmd)}")
    try:
        rc = subprocess.call(cmd)
        ok = (rc == 0)
        _dbg(f"probe HLS → {'OK' if ok else f'FAIL (rc={rc})'}")
        return ok
    except Exception as e:
        _dbg(f"probe exception: {e}")
        return False

# ---------- Stream ----------
async def stream(url_or_query: str, ffmpeg_path: str):
    import discord

    page_referer = url_or_query if is_valid(url_or_query) else "https://soundcloud.com"

    # 1) Tentative API v2 (progressive > hls) avec rotation client_id
    if is_valid(url_or_query):
        cids = _sc_client_ids()
        _dbg(f"using client_ids: {len(cids)}")
        for cid in cids or [None]:
            if not cid:
                _dbg("no client_id available → skip resolve")
                break
            try:
                tr = _sc_resolve_track(url_or_query, cid)
                if not tr:
                    continue
                trans_all = (tr.get("media", {}) or {}).get("transcodings") or []
                _dbg("resolve → transcodings: " + str([(t.get("format") or {}).get("protocol") for t in trans_all]))

                chosen, proto = _pick_transcoding(tr)
                if not chosen:
                    continue

                stream_url = _resolve_stream_url(chosen, cid)
                if not stream_url:
                    continue

                host = urlparse(stream_url).hostname
                _dbg(f"chosen protocol={proto}, host={host}")

                # Si progressive MP3 → idéal
                if proto == "progressive" and ".mp3" in (stream_url.split("?")[0].lower()):
                    hdr = _ffmpeg_headers_str(None, referer=page_referer)
                    before = f"-headers {shlex.quote(hdr)} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                    source = discord.FFmpegPCMAudio(
                        stream_url,
                        before_options=before,
                        options="-vn",
                        executable=ffmpeg_path
                    )
                    _cache_mark_good(cid)
                    title = tr.get("title") or "Son inconnu"
                    return source, title

                # Sinon HLS → probe court avant de jouer
                hdr = _ffmpeg_headers_str(None, referer=page_referer)
                if _ffmpeg_probe_hls(ffmpeg_path, stream_url, hdr):
                    before = (
                        f"-headers {shlex.quote(hdr)} "
                        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
                        "-protocol_whitelist file,http,https,tcp,tls,crypto "
                        "-allowed_extensions ALL"
                    )
                    source = discord.FFmpegPCMAudio(
                        stream_url,
                        before_options=before,
                        options="-vn",
                        executable=ffmpeg_path
                    )
                    _cache_mark_good(cid)
                    title = tr.get("title") or "Son inconnu"
                    return source, title

                _dbg(f"resolve attempt failed (cid={cid[:4]}…)")
            except Exception as e:
                _dbg(f"resolve attempt failed (cid={cid[:4]}…): {e}")
                continue

    # 2) Fallback: yt_dlp → stream (HLS/opus probable)
    _dbg("fallback: yt_dlp download=False")
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "scsearch3",
        "nocheckcertificate": True,
    }
    loop = asyncio.get_event_loop()
    def extract():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url_or_query, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
        info = data["entries"][0] if "entries" in data else data
        stream_url = info["url"]
        title = info.get("title", "Son inconnu")
        http_headers = info.get("http_headers") or data.get("http_headers") or {}

        hdr = _ffmpeg_headers_str(http_headers, referer=page_referer)
        host = urlparse(stream_url).hostname
        _dbg(f"yt_dlp → stream host: {host} headers: {bool(http_headers)}")

        # Probe HLS court pour éviter un play qui mourra dans 2s
        if stream_url.endswith(".m3u8") or "playlist.m3u8" in stream_url:
            ok = _ffmpeg_probe_hls(ffmpeg_path, stream_url, hdr)
            if not ok:
                raise RuntimeError("ffmpeg HLS probe failed")

        before = (
            f"-headers {shlex.quote(hdr)} "
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-protocol_whitelist file,http,https,tcp,tls,crypto "
            "-allowed_extensions ALL"
        )
        import discord  # noqa: F401 (re-import safe)
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=before,
            options="-vn",
            executable=ffmpeg_path
        )
        return source, title
    except Exception as e:
        # 3) Dernier recours: download
        raise RuntimeError(f"Échec de l'extraction SoundCloud : {e}")

# ---------- CLI self-test ----------
if __name__ == "__main__":
    import sys
    ff = os.getenv("FFMPEG", "/usr/bin/ffmpeg")
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://soundcloud.com/damsoofficial/pa-pa-paw"
    _dbg(f"SELFTEST url={test_url}")
    print("Python:", sys.version)
    try:
        out = subprocess.check_output([ff, "-version"], text=True).splitlines()[0]
        print("ffmpeg:", out)
    except Exception as e:
        print("ffmpeg: not found", e)

    try:
        # simple smoke test (no Discord)
        # Resolve only, show chosen protocol
        ids = _sc_client_ids()
        print(f"client_ids candidates: {len(ids)}")
        ok = False
        for cid in ids or [None]:
            if not cid: break
            tr = _sc_resolve_track(test_url, cid)
            if not tr: continue
            c, proto = _pick_transcoding(tr)
            print("transcodings:", [ (t.get('format') or {}).get('protocol') for t in (tr.get('media',{}) or {}).get('transcodings',[]) ])
            if c:
                u = _resolve_stream_url(c, cid)
                print("chosen:", proto, "url:", bool(u))
                ok = True
                break
        print("resolve_ok:", ok)
    except Exception as e:
        print("resolve failed:", e)
