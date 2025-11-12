# api/core/config.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _get_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # Flask
    ENV: str = os.getenv("FLASK_ENV", "production")
    DEBUG: bool = _get_bool("FLASK_DEBUG", False)
    SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret-override-me")
    JSON_SORT_KEYS: bool = False

    # Session cookie
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "gregsid")
    SESSION_COOKIE_SECURE: bool = _get_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_SAMESITE: str = os.getenv("SESSION_COOKIE_SAMESITE", "None")
    SESSION_COOKIE_HTTPONLY: bool = True
    PERMANENT_SESSION_LIFETIME: int = int(os.getenv("SESSION_TTL_SECONDS", "1209600"))  # 14j

    # OAuth Discord
    DISCORD_CLIENT_ID: str | None = os.getenv("DISCORD_CLIENT_ID")
    DISCORD_CLIENT_SECRET: str | None = os.getenv("DISCORD_CLIENT_SECRET")
    DISCORD_REDIRECT_URI: str | None = os.getenv("DISCORD_REDIRECT_URI")
    DISCORD_OAUTH_SCOPES: str = os.getenv("DISCORD_OAUTH_SCOPES", "identify guilds")
    RESTRICT_TO_GUILD_ID: str | None = os.getenv("RESTRICT_TO_GUILD_ID")

    # Spotify
    SPOTIFY_CLIENT_ID: str | None = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET: str | None = os.getenv("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REDIRECT_URI: str | None = os.getenv("SPOTIFY_REDIRECT_URI")
    SPOTIFY_SCOPES: str = os.getenv(
        "SPOTIFY_SCOPES",
        "playlist-read-private playlist-read-collaborative "
        "playlist-modify-public playlist-modify-private user-read-email",
    )
    SPOTIFY_STATE_SECRET: str = os.getenv("SPOTIFY_STATE_SECRET", "dev-spotify-state")

    # Stores
    REDIS_URL: str | None = os.getenv("REDIS_URL")
    JSON_STORE_PATH: str = os.getenv("JSON_STORE_PATH", ".data/store.json")

    # Presence (overlay)
    PRESENCE_TTL_SECONDS: int = int(os.getenv("PRESENCE_TTL_SECONDS", "45"))
    PRESENCE_SWEEP_SECONDS: int = int(os.getenv("PRESENCE_SWEEP_SECONDS", "20"))

    # CORS
    ALLOWED_ORIGINS: List[str] = field(default_factory=list)

    # API Versioning
    API_PREFIX: str = os.getenv("API_PREFIX", "/api/v1")
    API_ALIAS: str = os.getenv("API_ALIAS", "/api")
