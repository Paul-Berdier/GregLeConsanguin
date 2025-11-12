# api/__init__.py
from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, redirect, request

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
    api_alias = app.config.get("API_ALIAS", "/api")  # mets "" ou None pour désactiver
    use_alias = bool(api_alias) and (api_alias != api_prefix)

    # Auth hors /api_prefix (ex: /auth/login, /auth/callback…)
    app.register_blueprint(auth_bp, url_prefix="/auth")

    # Enregistrement canonique
    blueprints = [users_bp, guilds_bp, playlist_bp, admin_bp, spotify_bp]
    for bp in blueprints:
        app.register_blueprint(bp, url_prefix=api_prefix)

    # Alias /api/* → redirection 307 vers /api_prefix/*
    # (on NE ré-enregistre PAS les mêmes blueprints une 2e fois)
    if use_alias:
        alias_base = api_alias.rstrip("/")
        canon_base = api_prefix.rstrip("/")

        # /api  → /api/v1
        @app.route(f"{alias_base}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
        def _api_alias_root():
            qs = ("?" + request.query_string.decode()) if request.query_string else ""
            return redirect(f"{canon_base}/{qs}".rstrip("?"), code=307)

        # /api/* → /api/v1/*
        @app.route(f"{alias_base}/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
        def _api_alias(path: str):
            qs = ("?" + request.query_string.decode()) if request.query_string else ""
            return redirect(f"{canon_base}/{path}{qs}", code=307)


def _register_socketio(app: Flask) -> None:
    from .core.extensions import socketio
    from .ws import events  # noqa: F401  (side-effects: enregistre les handlers)

    # Si init non fait dans init_extensions(), on l’assure ici
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
