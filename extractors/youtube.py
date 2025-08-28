# extractors/youtube.py
#
# YouTube robuste:
# - cookies automatiques via cookies-from-browser (prioritaire) ou cookies_file Netscape
# - stream fiable: yt-dlp -> stdout (pipe) -> ffmpeg (PCM) -> Discord
# - download MP3 (192 kbps, 48 kHz), nom propre "<title> - <id>.mp3"
# - recherche ytsearch5 (flat)
#
from __future__ import annotations

import os
import re
import sys
import shlex
import subprocess
from typing import Optional, Tuple, Dict, Any, List

from yt_dlp import YoutubeDL

_YT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

def is_valid(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return any(s in u for s in ("youtube.com/watch", "youtu.be/", "youtube.com/shorts/"))

def search(query: str):
    ydl_opts = {
        "quiet": True,
        "noprogress": True,
        "default_search": "ytsearch5",
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True,
        "noplaylist": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"ytsearch5:{query}", download=False)
        return results.get("entries", []) if results else []

# ------------------------ helpers ------------------------

def _sanitize(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    return (name or "greg_audio").strip()[:180]

def _parse_cookies_from_browser_spec(spec: Optional[str]):
    if not spec:
        return None
    parts = spec.split(":", 1)
    browser = parts[0].strip().lower()
    profile = parts[1].strip() if len(parts) > 1 else None
    return (browser,) if profile is None else (browser, profile)

def _base_ydl_opts(
    ffmpeg_path: str,
    *,
    download_mode: bool = False,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = None,
) -> Dict[str, Any]:
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "extract_flat": False,
        "http_headers": {
            "User-Agent": _YT_UA,
            "Accept": "*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.youtube.com/",
        },
        "ffmpeg_location": ffmpeg_path,
        "format": "bestaudio/best",
        "noplaylist": True,
        "geo_bypass": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],  # souvent plus stable
                "force_ipv4": [],              # réseaux capricieux
            }
        },
        "youtube_include_dash_manifest": False,
    }
    if ratelimit_bps and ratelimit_bps > 0:
        ydl_opts["ratelimit"] = int(ratelimit_bps)

    # cookies: navigateur (prioritaire) puis fichier
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        ydl_opts["cookiesfrombrowser"] = cfb
    elif cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    if download_mode:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        # 48 kHz pour Discord
        ydl_opts["postprocessor_args"] = ["-ar", "48000"]

    return ydl_opts

def _resolve_ytdlp_cli() -> List[str]:
    import shutil
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    return [sys.executable, "-m", "yt_dlp"]

# ------------------------ public: download ------------------------

def download(
    url: str,
    ffmpeg_path: str,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    out_dir: str = "downloads",
    ratelimit_bps: Optional[int] = 2_500_000,  # ~2.5 MB/s
) -> Tuple[str, str, int]:
    """
    Télécharge l'audio en MP3 (192 kbps, 48 kHz).
    Retourne (chemin_mp3, titre, durée_sec).
    """
    os.makedirs(out_dir, exist_ok=True)
    ydl_opts = _base_ydl_opts(
        ffmpeg_path,
        download_mode=True,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        ratelimit_bps=ratelimit_bps,
    )
    # nom propre: <title> - <id>.mp3
    ydl_opts["outtmpl"] = os.path.join(out_dir, "%(title).200B - %(id)s.%(ext)s")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if "entries" in info:
            info = info["entries"][0]
        title = info.get("title", "Musique inconnue")
        duration = int(info.get("duration", 0) or 0)

        temp_name = ydl.prepare_filename(info)
        base, _ = os.path.splitext(temp_name)
        final_mp3 = base + ".mp3"
        # sanitize basename
        d = os.path.dirname(final_mp3)
        f = _sanitize(os.path.basename(final_mp3))
        final_mp3 = os.path.join(d, f)
        return final_mp3, title, duration

# ------------------------ public: stream ------------------------

async def stream(
    url_or_query: str,
    ffmpeg_path: str,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    ratelimit_bps: Optional[int] = 0,
):
    """
    Stream robuste: yt-dlp (stdout) → ffmpeg (pipe:0) → PCM.
    Retourne (source, title). La source porte _ytdlp_proc pour cleanup.
    """
    import asyncio
    import discord

    # Résout URL & titre (et gère la recherche si pas d’URL)
    def _probe(q: str):
        with YoutubeDL({"quiet": True, "noprogress": True, "default_search": "ytsearch1"}) as ydl:
            data = ydl.extract_info(q, download=False)
            if "entries" in data:
                data = data["entries"][0]
            return data

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _probe, url_or_query)
    url = info.get("webpage_url") or url_or_query
    title = info.get("title", "Musique inconnue")

    # Construit la commande yt-dlp -> stdout
    ytdlp_cmd = _resolve_ytdlp_cli() + [
        "-f", "bestaudio/best",
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "5",
        "--fragment-retries", "5",
        "--newline",
        "-o", "-",     # → stdout
        url,
    ]

    # cookies
    cfb = _parse_cookies_from_browser_spec(cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER"))
    if cfb:
        br = cfb[0]
        prof = cfb[1] if len(cfb) > 1 else None
        spec = br if not prof else f"{br}:{prof}"
        ytdlp_cmd.insert(len(_resolve_ytdlp_cli()), "--cookies-from-browser")
        ytdlp_cmd.insert(len(_resolve_ytdlp_cli()) + 1, spec)
    elif cookies_file and os.path.exists(cookies_file):
        ytdlp_cmd.insert(len(_resolve_ytdlp_cli()), "--cookies")
        ytdlp_cmd.insert(len(_resolve_ytdlp_cli()) + 1, cookies_file)

    if ratelimit_bps and ratelimit_bps > 0:
        ytdlp_cmd.extend(["--limit-rate", str(int(ratelimit_bps))])

    try:
        yt_proc = subprocess.Popen(
            ytdlp_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        raise RuntimeError(f"Impossible de lancer yt-dlp: {e}\nCMD: {shlex.join(ytdlp_cmd)}")

    # ffmpeg lit depuis stdin (pipe=True), sort PCM 48 kHz pour Discord
    before_opts = None
    ff_opts = "-vn -ar 48000 -f s16le -ac 2 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    source = discord.FFmpegPCMAudio(
        source=yt_proc.stdout,  # type: ignore[arg-type]
        executable=ffmpeg_path,
        before_options=before_opts,
        options=ff_opts,
        pipe=True,
    )
    setattr(source, "_ytdlp_proc", yt_proc)
    setattr(source, "_title", title)
    return source, title
