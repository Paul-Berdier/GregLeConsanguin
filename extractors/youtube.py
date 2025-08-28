# extractors/youtube.py
#
# YouTube robuste (anti-403)
# - stream: yt-dlp -> stdout -> FFmpeg (pas d'URL googlevideo directe)
# - clients safe: ios → web → web_creator → web_mobile → android
# - formats fallback: bestaudio m4a/opus → best → 140/251/18
# - download: MP3 192 kbps / 48 kHz, chemin fiable
# - cookies: navigateur prioritaire (cookiesfrombrowser), sinon fichier
# - search: ytsearch5 (flat)
from __future__ import annotations

import os
import sys
import shlex
import asyncio
import subprocess
from typing import Optional, Tuple, Dict, Any, List

import discord
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

_YT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("youtube.com/watch" in u) or ("youtu.be/" in u) or ("youtube.com/shorts/" in u)

# ---------- helpers ----------

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
        "http_headers": {"User-Agent": _YT_UA, "Referer": "https://www.youtube.com/"},
        "extractor_args": {"youtube": {"player_client": ["ios", "web", "web_creator", "web_mobile", "android"]}},
        # Formats audio + file d'attente vers 18 si rien d'autre
        "format": "bestaudio[ext=m4a]/bestaudio/best/140/251/18",
    }
    if ratelimit_bps:
        ydl_opts["ratelimit"] = int(ratelimit_bps)
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path
    if search:
        ydl_opts.update({"default_search": "ytsearch5", "extract_flat": True})
    if for_download:
        ydl_opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
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

def _resolve_cli() -> List[str]:
    import shutil
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]

# ---------- public: search ----------

def search(query: str, *, cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> List[dict]:
    if not query or not query.strip():
        return []
    with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser, search=True)) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = (data or {}).get("entries") or []
        return _normalize_search_entries(entries)

# ---------- public: stream (PIPE, anti-403) ----------

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    *,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
) -> Tuple[discord.FFmpegPCMAudio, str]:
    """
    Stream robuste: yt-dlp (stdout) -> FFmpeg (pipe:0) -> PCM 48 kHz.
    On évite toute URL googlevideo directe (source majeure de 403).
    Retourne (source, title). La source porte _ytdlp_proc pour cleanup.
    """
    # 1) Résoudre titre + URL de page
    def _probe(q: str):
        with YoutubeDL(_mk_opts(cookies_file=cookies_file, cookies_from_browser=cookies_from_browser)) as ydl:
            info = ydl.extract_info(q, download=False)
            if info and "entries" in info and info["entries"]:
                info = info["entries"][0]
            return {
                "title": info.get("title", "Musique inconnue"),
                "page_url": info.get("webpage_url") or q
            }
    meta = await asyncio.get_running_loop().run_in_executor(None, _probe, url_or_query)
    title = meta["title"]
    page_url = meta["page_url"]

    # 2) Lancer yt-dlp en PIPE (bestaudio avec fallback)
    ytdlp_cmd = _resolve_cli() + [
        "-f", "bestaudio[ext=m4a]/bestaudio/best/140/251/18",
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--newline",
        "--user-agent", _YT_UA,
        "--extractor-args", "youtube:player_client=ios,web,web_creator,web_mobile,android",
        "-o", "-",   # -> stdout
        page_url,
    ]
    # cookies
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        spec = cfb[0] if len(cfb) == 1 else f"{cfb[0]}:{cfb[1]}"
        ytdlp_cmd.insert(len(_resolve_cli()), "--cookies-from-browser")
        ytdlp_cmd.insert(len(_resolve_cli()) + 1, spec)
    elif cookies_file and os.path.exists(cookies_file):
        ytdlp_cmd.insert(len(_resolve_cli()), "--cookies")
        ytdlp_cmd.insert(len(_resolve_cli()) + 1, cookies_file)
    if ratelimit_bps:
        ytdlp_cmd.extend(["--limit-rate", str(int(ratelimit_bps))])

    try:
        yt_proc = subprocess.Popen(
            ytdlp_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=0,  # Linux/Docker
        )
    except Exception as e:
        raise RuntimeError(f"Impossible de lancer yt-dlp: {e}\nCMD: {shlex.join(ytdlp_cmd)}")

    if yt_proc.stdout is None:
        yt_proc.kill()
        raise RuntimeError("yt-dlp n'a pas ouvert stdout")

    # 3) FFmpeg lit depuis stdin -> PCM
    before_opts = None
    ff_opts = "-vn -ar 48000 -f s16le -ac 2"
    source = discord.FFmpegPCMAudio(
        source=yt_proc.stdout,  # type: ignore[arg-type]
        executable=ffmpeg_path,
        before_options=before_opts,
        options=ff_opts,
        pipe=True,
    )
    setattr(source, "_ytdlp_proc", yt_proc)
    return source, title

# ---------- public: download ----------

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
    Télécharge l'audio et convertit en MP3 (192 kbps, 48 kHz).
    Retourne (filepath_mp3, title, duration_seconds|None).
    """
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
            return filepath, title, duration
    except DownloadError as e:
        if "Requested format is not available" in str(e):
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
                info = ydl2.extract_info(url, download=True)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                req = (info or {}).get("requested_downloads") or []
                filepath = req[0].get("filepath") if req else (os.path.splitext(ydl2.prepare_filename(info))[0] + ".mp3")
                title = (info or {}).get("title", "Musique inconnue")
                duration = (info or {}).get("duration")
                return filepath, title, duration
        raise RuntimeError(f"Échec download YouTube: {e}") from e
