# extractors/youtube.py
import yt_dlp
import discord
import os
import random

class YouTubeExtractor:
    def __init__(self):
        self.ytdl_opts_base = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": False,
            "nocheckcertificate": True,
            "ignoreerrors": True,
            "forceipv4": True,
            "extract_flat": False,
            "cachedir": False,
            "source_address": "0.0.0.0",
            "geo_bypass": True,
            "http_headers": {
                "User-Agent": self.get_random_user_agent(),
                "Accept-Language": "en-US,en;q=0.5"
            }
        }
        self.cookies_file = "youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
        if self.cookies_file:
            self.ytdl_opts_base["cookiefile"] = self.cookies_file

    def get_random_user_agent(self):
        agents = [
            # Chrome Win10
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            # Chrome macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/15.4 Safari/605.1.15",
            # Firefox Win10
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0"
        ]
        return random.choice(agents)

    # ---------- STREAM ----------
    async def stream(self, url, ffmpeg_path):
        opts = self.ytdl_opts_base.copy()
        opts.update({"noplaylist": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if "entries" in info:  # si playlist → prend premier
                info = info["entries"][0]
            audio_url = info["url"]
            title = info.get("title", "Titre inconnu")
            source = discord.FFmpegPCMAudio(audio_url, executable=ffmpeg_path)
            return source, title

    # ---------- DOWNLOAD ----------
    async def download(self, url, ffmpeg_path):
        opts = self.ytdl_opts_base.copy()
        opts.update({
            "outtmpl": "downloads/greg_audio.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"
            }],
            "ffmpeg_location": ffmpeg_path
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
            return filename, info.get("title", "Titre inconnu"), info.get("duration", 0)

    # ---------- GET PLAYLIST ----------
    def get_playlist(self, url):
        """Retourne tous les items d’une playlist/mix."""
        opts = self.ytdl_opts_base.copy()
        opts.update({"extract_flat": True, "forcejson": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            items = []
            if "entries" in info:
                for e in info["entries"]:
                    if not e:
                        continue
                    items.append({
                        "title": e.get("title", "Sans titre"),
                        "url": e.get("url") if e.get("url", "").startswith("http") else f"https://www.youtube.com/watch?v={e.get('id')}"
                    })
            return items

# ---------- Factory ----------
def get_extractor(url):
    if "youtube.com" in url or "youtu.be" in url:
        return YouTubeExtractor()
    return None
