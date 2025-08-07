"""Configuration for Greg refonte bot.

This module exposes configuration values used by the bot.  In production the
DISCORD_TOKEN environment variable must be defined to authenticate the bot.
"""

import os

# Discord bot token.  Use an environment variable to avoid hard‑coding secrets.
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

# Optional: path to a cookies file for yt_dlp.  If provided this can help
# with YouTube downloads when videos require login.  The default will be
# ``None`` meaning no cookies are used.
YTDLP_COOKIES_FILE: str | None = os.getenv("YTDLP_COOKIES_FILE") or None

# Port on which the Flask web panel will run.  Defaults to 3000 if not set.
WEB_PORT: int = int(os.getenv("WEB_PORT", "3000"))