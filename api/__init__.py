# api/__init__.py
from __future__ import annotations

import logging
from typing import Callable, Optional

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
    configure_logging()
    app = Flask(__name__)
    app.config.from_object(Settings())

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

    log.info("API created (env=%s, debug=%s)", app.config["ENV"], app.config["DEBUG"])
    return app


def _register_blueprints(app: Flask) -> None:
    from .auth.blueprint import bp as auth_bp
    from .blueprints.users import bp as users_bp
    from .blueprints.guilds import bp as guilds_bp
    from .blueprints.playlist import bp as playlist_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.spotify import bp as spotify_bp

    api_prefix = app.config.get("API_PREFIX", "/api/v1")
    api_alias = app.config.get("API_ALIAS", "/api")

    app.register_blueprint(auth_bp, url_prefix="/auth")

    for bp in (users_bp, guilds_bp, playlist_bp, admin_bp, spotify_bp):
        app.register_blueprint(bp, url_prefix=api_prefix)
        # Alias de compatibilité (expose aussi /api/*)
        app.register_blueprint(bp, url_prefix=api_alias)


def _register_socketio(app: Flask) -> None:
    from .core.extensions import socketio
    from .ws import events  # noqa: F401  # side-effects: enregistre les handlers
    socketio.server_options = socketio.server_options or {}


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
