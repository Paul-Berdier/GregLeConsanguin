# api/__init__.py
from __future__ import annotations
import logging
from typing import Optional

from flask import Flask

from .core.config import Settings
from .core.errors import register_error_handlers
from .core.extensions import init_extensions, socketio
from .core.logging import configure_logging

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"   # une seule racine d’API

def create_app(pm: Optional[object] = None) -> Flask:
    """App factory. Injecte éventuellement un PlaylistManager (pm)."""
    if not logging.getLogger().handlers:
        configure_logging()

    app = Flask(__name__)
    app.config.from_object(Settings())

    # Extensions
    init_extensions(app)

    # Attach external deps
    app.extensions["pm"] = pm
    app.extensions.setdefault("stores", {})
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

    # Compat : certains modules importent encore 'require_login'
    try:
        from .auth.session import login_required as _lr
        # alias exporté dans le module (si besoin)
        import api.auth.session as _sessmod
        setattr(_sessmod, "require_login", _lr)
    except Exception:
        pass

    log.info("API created (env=%s, debug=%s)", app.config.get("ENV"), app.config.get("DEBUG"))
    return app


def _register_blueprints(app: Flask) -> None:
    # NOTE: respecte TA structure de modules
    from .auth.blueprint import bp as auth_bp
    from .blueprints.users import bp as users_bp
    from .blueprints.guilds import bp as guilds_bp
    from .blueprints.playlist import bp as playlist_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.spotify import bp as spotify_bp

    # 1) Auth monté SANS prefix → /auth/login, /auth/callback, et /api/v1/me (car défini ainsi dans le BP)
    app.register_blueprint(auth_bp)  # <— pas de url_prefix ici

    # 2) Tous les autres sous /api/v1
    for bp in (users_bp, guilds_bp, playlist_bp, admin_bp, spotify_bp):
        app.register_blueprint(bp, url_prefix=API_PREFIX)


def _register_socketio(app: Flask) -> None:
    # L’instance est déjà créée dans core/extensions.py
    if not getattr(socketio, "server", None):
        socketio.init_app(
            app,
            async_mode=app.config.get("SOCKETIO_MODE", "threading"),
            cors_allowed_origins="*",
        )


def _init_stores(app: Flask) -> None:
    """Initialise le store (JSON par défaut, Redis si REDIS_URL)."""
    from .storage.json_store import JsonTokenStore
    from .storage.redis_store import RedisTokenStore

    stores = {}
    if app.config.get("REDIS_URL"):
        stores["tokens"] = RedisTokenStore(app.config["REDIS_URL"])
    else:
        stores["tokens"] = JsonTokenStore(app.config["JSON_STORE_PATH"])

    app.extensions["stores"].update(stores)
