# api/__init__.py
from __future__ import annotations

import logging
from typing import Optional

from flask import Flask

from .core.config import Settings
from .core.errors import register_error_handlers
from .core.extensions import init_extensions
from .core.logging import configure_logging

log = logging.getLogger(__name__)


def create_app(pm: Optional[object] = None) -> Flask:
    """
    App factory. Injecte éventuellement un PlaylistManager (pm).
    """
    if not logging.getLogger().handlers:
        configure_logging()

    app = Flask(__name__)
    app.config.from_object(Settings())

    # Force un API prefix versionné et désactive tout alias legacy (/api -> /api/v1)
    app.config.setdefault("API_PREFIX", "/api/v1")
    app.config["API_ALIAS"] = ""  # hard-off (pas de 307)

    # Extensions
    init_extensions(app)

    # Attach external dependencies
    app.extensions["pm"] = pm  # PlaylistManager externe (bot)
    app.extensions.setdefault("stores", {})  # sera rempli par storage config
    _init_stores(app)

    # Blueprints & WS
    _register_blueprints(app)
    _register_socketio(app)

    # Erreurs
    register_error_handlers(app)

    # Health
    @app.get("/healthz")
    def _healthz():
        return {"ok": True}, 200

    log.info("API created (env=%s, debug=%s)", app.config.get("ENV"), app.config.get("DEBUG"))
    return app


def _register_blueprints(app: Flask) -> None:
    # Blueprints “réels”
    from .auth.blueprint import bp as auth_bp
    from .blueprints.users import bp as users_bp
    from .blueprints.guilds import bp as guilds_bp
    from .blueprints.playlist import bp as playlist_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.spotify import bp as spotify_bp

    api_prefix = app.config.get("API_PREFIX", "/api/v1")

    # Auth hors /api_prefix (ex: /auth/login, /auth/callback…)
    app.register_blueprint(auth_bp, url_prefix="/auth")

    # Enregistrement canonique SEULEMENT sous /api/v1
    blueprints = [users_bp, guilds_bp, playlist_bp, admin_bp, spotify_bp]
    for bp in blueprints:
        app.register_blueprint(bp, url_prefix=api_prefix)

    # ATTENTION: plus d'alias /api -> /api/v1. On supprime les 307.


def _register_socketio(app: Flask) -> None:
    from .core.extensions import socketio
    from .ws import events  # noqa: F401  (side-effects: enregistre les handlers)

    if not getattr(socketio, "server", None):
        socketio.init_app(
            app,
            async_mode=app.config.get("SOCKETIO_MODE", "threading"),
            cors_allowed_origins="*",
        )


def _init_stores(app: Flask) -> None:
    """
    Initialise le store (JSON par défaut, Redis si REDIS_URL).
    """
    from .storage.json_store import JsonTokenStore
    from .storage.redis_store import RedisTokenStore

    stores = {}
    if app.config.get("REDIS_URL"):
        stores["tokens"] = RedisTokenStore(app.config["REDIS_URL"])
    else:
        stores["tokens"] = JsonTokenStore(app.config["JSON_STORE_PATH"])

    app.extensions["stores"].update(stores)
