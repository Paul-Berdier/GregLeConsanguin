# api/__init__.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from flask import Flask, render_template

from .core.config import Settings
from .core.errors import register_error_handlers
from .core.extensions import init_extensions, socketio
from .core.logging import configure_logging

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"   # une seule racine d’API


def create_app(pm: Optional[object] = None) -> Flask:
    """
    App factory Flask.
    - Monte l'API sous /api/v1
    - Sert l’UI web (index + static) :
        • GET /              -> assets/pages/index.html
        • GET /static/*      -> assets/static/*
    - Injecte éventuellement un bridge Player (pm).
    """
    if not logging.getLogger().handlers:
        configure_logging()

    # === Résolution des chemins projet =======================================
    # api/__init__.py -> api/ -> parent = racine projet (GregLeConsanguin)
    BASE_DIR = Path(__file__).resolve().parent.parent
    templates_dir = BASE_DIR / "assets" / "pages"
    static_dir = BASE_DIR / "assets" / "static"

    # === Création app Flask avec templates + static ==========================
    app = Flask(
        __name__,
        template_folder=str(templates_dir),
        static_folder=str(static_dir),
        static_url_path="/static",  # donc /static/player.css, /static/player.js, etc.
    )
    app.config.from_object(Settings())

    # Extensions (db, Socket.IO, etc.)
    init_extensions(app)

    # Attach external deps / stores
    app.extensions["pm"] = pm
    app.extensions.setdefault("stores", {})
    _init_stores(app)

    # Blueprints & Socket.IO
    _register_blueprints(app)
    _register_socketio(app)

    # === Routes "web" (UI) ===================================================

    @app.get("/")
    def index():
        """
        Page principale : player web.
        assets/pages/index.html
        """
        return render_template("index.html")

    # Health check simple
    @app.get("/healthz")
    def _healthz():
        return {"ok": True}, 200

    # Compat : certains modules importent encore 'require_login'
    try:
        from .auth.session import login_required as _lr
        # alias exporté dans le module (si besoin)
        import api.auth.session as _sessmod
        setattr(_sessmod, "require_login", _lr)
    except Exception:
        pass

    log.info(
        "API created (env=%s, debug=%s, templates=%s, static=%s)",
        app.config.get("ENV"),
        app.config.get("DEBUG"),
        templates_dir,
        static_dir,
    )
    return app


def _register_blueprints(app: Flask) -> None:
    """
    Montage des blueprints :
      - /auth/* + /api/v1/me depuis auth_bp (pas de prefix)
      - /api/v1/* pour le reste
    """
    from .auth.blueprint import bp as auth_bp
    from .blueprints.users import bp as users_bp
    from .blueprints.guilds import bp as guilds_bp
    from .blueprints.playlist import bp as playlist_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.spotify import bp as spotify_bp
    from .blueprints.search import bp as search_bp

    # 1) Auth monté SANS prefix → /auth/login, /auth/callback, /auth/device/*, /api/v1/me
    app.register_blueprint(auth_bp)  # pas de url_prefix ici

    # 2) Tous les autres sous /api/v1
    for bp in (users_bp, guilds_bp, playlist_bp, admin_bp, spotify_bp, search_bp):
        app.register_blueprint(bp, url_prefix=API_PREFIX)


def _register_socketio(app: Flask) -> None:
    """
    Initialise l’instance Socket.IO globale avec cette app.
    """
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
