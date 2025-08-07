"""SoundCloud audio extraction for Greg refonte.

This module wraps ``yt_dlp`` to search, download and stream tracks
from SoundCloud.  SoundCloud has an official API but it requires
client credentials and rate limits apply.  Using yt_dlp allows
extraction of audio without an API key.  The original project used
yt_dlp with options to convert opus to mp3 and to stream via
FFmpeg【645914700203540†L30-L83】.  Here we provide a simplified and
updated interface.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
import yt_dlp


class SoundCloudExtractor:
    """Extractor for SoundCloud using yt_dlp.

    Supports searching for tracks, downloading audio to disk and
    streaming directly using FFmpeg.  No API key is required as
    yt_dlp performs the scraping under the hood.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search SoundCloud for the given query.

        Parameters
        ----------
        query: str
            The search term.
        limit: int
            Maximum number of results to return.

        Returns
        -------
        list of dict
            Each dict contains ``title`` and ``url`` keys referencing the
            track's page on soundcloud.com.
        """
        # Use scsearch to search SoundCloud via yt_dlp
        # Note: scsearchN:query returns at most N results
        search_term = f"scsearch{limit}:{query}"
        opts: Dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "default_search": "auto",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_term, download=False)
        results: List[Dict[str, Any]] = []
        for entry in info.get("entries", [])[:limit]:
            title = entry.get("title") or entry.get("id") or query
            # 'webpage_url' is the canonical page; fall back to 'url'
            url = entry.get("webpage_url") or entry.get("url")
            results.append({"title": title, "url": url})
        return results

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def download(
        self, url: str, *, ffmpeg_path: str = "ffmpeg", cookies_file: str | None = None
    ) -> Tuple[str, str, float]:
        """Download a SoundCloud track's audio to disk.

        Parameters
        ----------
        url: str
            The track URL.
        ffmpeg_path: str
            Path to the FFmpeg executable (unused here but kept for
            signature compatibility).
        cookies_file: str | None
            Unused; present for API compatibility.

        Returns
        -------
        tuple
            A triple of ``(filepath, title, duration)``.  The file will
            be stored in the ``data/downloads`` directory.
        """
        downloads_dir = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(downloads_dir / "%(title)s.%(ext)s")
        opts: Dict[str, Any] = {
            "quiet": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            "no_check_certificate": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
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
        """Create a Discord audio source for streaming a SoundCloud track.

        This implementation attempts to obtain a direct audio link via
        yt_dlp.  If that fails, it falls back to downloading the file
        and streaming from disk.

        Parameters
        ----------
        url: str
            The SoundCloud track URL.
        ffmpeg_path: str
            Path to the FFmpeg executable.
        cookies_file: str | None
            Unused; present for API compatibility.

        Returns
        -------
        tuple
            A pair ``(audio_source, title)`` where ``audio_source`` is
            an instance of :class:`discord.FFmpegPCMAudio` and
            ``title`` is the track title.
        """
        opts: Dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "no_check_certificate": True,
            "format": "bestaudio/best",
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            # Attempt to find a direct audio stream
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
        # Fallback: download then play
        filename, title, _duration = self.download(url, ffmpeg_path=ffmpeg_path)
        source = discord.FFmpegPCMAudio(filename, executable=ffmpeg_path)
        return source, title
