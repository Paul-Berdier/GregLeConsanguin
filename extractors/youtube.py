"""YouTube audio extraction for Greg refonte.

This module provides a small wrapper around the ``yt_dlp`` library to
search, download and stream audio from YouTube.  It is designed for
integration with the Discord bot, returning track metadata and audio
streams via ``discord.FFmpegPCMAudio``.

The implementation strives to be resilient against YouTube's frequent
changes by using conservative yt_dlp options and by falling back to
direct streaming if downloading fails.  A cookies file may be provided
via environment variable to allow access to age‑gated content.

References
----------
The original project used yt_dlp with custom headers and cookie file
options to handle YouTube downloads【800920760689218†L31-L77】.  The refonte
builds on this by exposing a simple interface and updating to modern
yt_dlp usage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
import yt_dlp

from ..bot.config import YTDLP_COOKIES_FILE


class YouTubeExtractor:
    """Extractor for YouTube audio using yt_dlp.

    Instances of this class can be used to search for tracks, download
    them to disk or obtain a live audio stream for playback.  The
    ``cookies_file`` attribute may be set to allow access to restricted
    content; by default it pulls from ``YTDLP_COOKIES_FILE``.
    """

    def __init__(self, cookies_file: str | None = None) -> None:
        self.cookies_file = cookies_file or YTDLP_COOKIES_FILE

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search YouTube for the given query and return a list of results.

        Parameters
        ----------
        query: str
            The search term.
        limit: int
            Maximum number of results to return.

        Returns
        -------
        list of dict
            Each dict contains ``title`` and ``url`` keys.
        """
        opts = {
            "quiet": True,
            "skip_download": True,
            "no_check_certificate": True,
            "format": "bestaudio/best",
            "noplaylist": True,
        }
        # Prepend ytsearch to ensure yt_dlp performs a search
        search_term = f"ytsearch{limit}:{query}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_term, download=False)
        results: List[Dict[str, Any]] = []
        for entry in info.get("entries", [])[:limit]:
            title = entry.get("title") or entry.get("id") or query
            # Use the watch URL which is more stable for later extraction
            if "url" in entry and entry.get("original_url"):
                url = entry["original_url"]
            elif "url" in entry:
                url = entry["url"]
            else:
                url = f"https://www.youtube.com/watch?v={entry.get('id')}"
            results.append({"title": title, "url": url})
        return results

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def download(
        self, url: str, *, ffmpeg_path: str = "ffmpeg", cookies_file: str | None = None
    ) -> Tuple[str, str, float]:
        """Download a YouTube video's audio to a file and return metadata.

        Parameters
        ----------
        url: str
            The video URL to download.
        ffmpeg_path: str
            Path to the FFmpeg executable.  Unused here but included for
            signature compatibility.
        cookies_file: str | None
            Optional path to a cookies.txt file for yt_dlp.

        Returns
        -------
        tuple
            A triple of ``(filepath, title, duration)``.  ``filepath`` is
            the path to the downloaded audio file.
        """
        # Determine an output directory for downloads
        downloads_dir = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        # Use yt_dlp to download the best audio only
        outtmpl = str(downloads_dir / "%(title)s.%(ext)s")
        opts: Dict[str, Any] = {
            "quiet": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            "no_check_certificate": True,
            "cookiesfrombrowser": None,
        }
        # If a cookies file is provided use it
        cookies = cookies_file or self.cookies_file
        if cookies:
            opts["cookiefile"] = cookies
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        # Determine the actual file path
        filename = ydl.prepare_filename(info)
        title = info.get("title", "Unknown")
        duration = info.get("duration") or 0.0
        return filename, title, float(duration)

    # ------------------------------------------------------------------
    # Stream
    # ------------------------------------------------------------------
    async def stream(
        self, url: str, ffmpeg_path: str = "ffmpeg", cookies_file: str | None = None
    ) -> Tuple[discord.FFmpegPCMAudio, str]:
        """Create a Discord audio source for streaming from YouTube.

        This method attempts to obtain a direct audio URL via yt_dlp
        without downloading the entire file.  If that fails it falls
        back to downloading the file and streaming from disk.

        Parameters
        ----------
        url: str
            The video URL to stream.
        ffmpeg_path: str
            Path to the FFmpeg executable.
        cookies_file: str | None
            Optional path to a cookies.txt file for yt_dlp.

        Returns
        -------
        tuple
            A pair of ``(audio_source, title)`` where ``audio_source`` is
            an instance of :class:`discord.FFmpegPCMAudio` and ``title``
            is the track title.
        """
        # First try to get a direct audio stream URL
        opts: Dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "no_check_certificate": True,
            "format": "bestaudio/best",
        }
        cookies = cookies_file or self.cookies_file
        if cookies:
            opts["cookiefile"] = cookies
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            # Choose the best available audio format
            audio_url = None
            for fmt in info.get("formats", []):
                if fmt.get("acodec") != "none" and fmt.get("protocol") in {"https", "http"}:
                    audio_url = fmt.get("url")
                    break
            if audio_url:
                title = info.get("title", "Unknown")
                source = discord.FFmpegPCMAudio(audio_url, executable=ffmpeg_path)
                return source, title
        except Exception:
            pass
        # Fallback: download the file then stream from disk
        filename, title, _duration = self.download(url, ffmpeg_path=ffmpeg_path, cookies_file=cookies)
        source = discord.FFmpegPCMAudio(filename, executable=ffmpeg_path)
        return source, title
