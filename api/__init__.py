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

API_PREFIX = "/api/v1"


def create_app(pm: Optional[object] = None) -> Flask:
    """
    App factory Flask.
    - Monte l'API sous /api/v1
    - Sert l’UI web :
        • GET /         -> assets/pages/index.html
        • GET /static/* -> assets/static/*
    - Injecte un bridge Player (pm) si fourni
    """
    if not logging.getLogger().handlers:
        configure_logging()

    BASE_DIR = Path(__file__).resolve().parent.parent
    templates_dir = BASE_DIR / "assets" / "pages"
    static_dir = BASE_DIR / "assets" / "static"

    app = Flask(
        __name__,
        template_folder=str(templates_dir),
        static_folder=str(static_dir),
        static_url_path="/static",
    )
    app.config.from_object(Settings())

    init_extensions(app)

    app.extensions["pm"] = pm
    app.extensions.setdefault("stores", {})
    _init_stores(app)

    register_error_handlers(app)

    _register_blueprints(app)
    _register_socketio_handlers()  # ✅ important: charge les events

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/healthz")
    def _healthz():
        return {"ok": True}, 200

    # Compat : certains modules importent encore 'require_login'
    try:
        from .auth.session import login_required as _lr
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
    from .auth.blueprint import bp as auth_bp
    from .blueprints.users import bp as users_bp
    from .blueprints.guilds import bp as guilds_bp
    from .blueprints.playlist import bp as playlist_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.spotify import bp as spotify_bp
    from .blueprints.search import bp as search_bp

    app.register_blueprint(auth_bp)  # /auth/* + /api/v1/me
    for bp in (users_bp, guilds_bp, playlist_bp, admin_bp, spotify_bp, search_bp):
        app.register_blueprint(bp, url_prefix=API_PREFIX)


def _register_socketio_handlers() -> None:
    """
    IMPORTANT:
    Flask-SocketIO enregistre les handlers au moment de l'import (decorators).
    Si tu n'importes jamais api.ws.events, tu n'auras aucun event WS.
    """
    # noqa: F401
    from .ws import events  # déclenche l'enregistrement des @socketio.on(...)
    from .ws import presence  # si tu l'utilises ailleurs


def _init_stores(app: Flask) -> None:
    from .storage.json_store import JsonTokenStore
    from .storage.redis_store import RedisTokenStore

    stores = {}
    if app.config.get("REDIS_URL"):
        stores["tokens"] = RedisTokenStore(app.config["REDIS_URL"])
    else:
        stores["tokens"] = JsonTokenStore(app.config["JSON_STORE_PATH"])

    app.extensions["stores"].update(stores)
