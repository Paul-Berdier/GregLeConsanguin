"""Configuration centralisée — source unique de vérité.

Toutes les variables d'environnement sont validées et typées ici.
Les services importent `settings` et c'est tout.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class GregSettings(BaseSettings):
    """Configuration globale de Greg le Consanguin."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── Général ──
    log_level: str = "INFO"
    flask_secret_key: str = "change-me-in-production"
    redis_url: str = "redis://localhost:6379"

    # ── Discord ──
    discord_token: str = ""
    discord_client_id: str = Field("", alias="DISCORD_CLIENT_ID")
    discord_client_secret: str = ""
    discord_oauth_scopes: str = "identify guilds"
    discord_redirect_uri: str = ""
    greg_owner_id: str = ""
    default_guild_id: str = ""

    # ── Sessions ──
    session_cookie_name: str = "gregsid"
    session_cookie_samesite: str = "None"
    session_cookie_secure: bool = True

    # ── Priorité ──
    priority_threshold: int = 50
    priority_role_weights: str = '{}'
    queue_per_user_cap: int = 10

    # ── Musique ──
    greg_join_sfx_delay: float = 2.5
    yt_po_token: str = ""
    ytdlp_cookies_file: str = ""
    ytdlp_cookies_b64: str = ""
    ytdlp_force_ipv4: bool = True
    ytdlp_auto_pipe_on_403: bool = True
    ytdlp_limit_bps: int = 2_500_000
    ytdlp_clients: str = ""
    ytdlp_force_ua: str = ""
    ytdlp_http_proxy: str = ""
    youtube_cookies_path: str = ""

    # ── Spotify ──
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = ""
    spotify_scopes: str = ""
    spotify_state_secret: str = ""

    # ── SoundCloud ──
    soundcloud_client_id: str = ""

    # ── Spook ──
    spook_min_delay: int = 30
    spook_max_delay: int = 120
    spook_volume: float = 0.30

    # ── Cookie Guardian ──
    ytc_test_url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ytc_notify_channel_id: int = 0
    ytbot_user: str = ""
    ytbot_pass: str = ""

    # ── Voice AI (futur) ──
    anthropic_api_key: str = ""
    elevenlabs_api_key: str = ""
    whisper_model: str = "base"

    # ── Helpers ──

    @property
    def discord_app_id(self) -> str:
        return self.discord_client_id

    @property
    def owner_id_int(self) -> int:
        try:
            return int(self.greg_owner_id)
        except (ValueError, TypeError):
            return 0

    def get_cookies_file(self) -> Optional[str]:
        """Retourne le chemin du fichier cookies YouTube s'il existe."""
        for path in [
            self.ytdlp_cookies_file,
            self.youtube_cookies_path,
            "youtube.com_cookies.txt",
        ]:
            if path and os.path.exists(path):
                return path
        return None

    def parse_role_weights(self) -> Dict[str, int]:
        """Parse PRIORITY_ROLE_WEIGHTS depuis JSON."""
        import json
        try:
            data = json.loads(self.priority_role_weights)
            return {str(k): int(v) for k, v in data.items()}
        except Exception:
            return {}


# Singleton — importé partout
settings = GregSettings()
