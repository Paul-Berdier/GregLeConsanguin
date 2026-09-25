"""Greg le Consanguin — API REST + WebSocket."""
from __future__ import annotations

import logging
from typing import Optional

from flask import Flask
from flask_compress import Compress
from flask_cors import CORS
from flask_socketio import SocketIO
from werkzeug.middleware.proxy_fix import ProxyFix

from greg_shared.config import settings

log = logging.getLogger("greg.api")

socketio = SocketIO()
compress = Compress()

API_PREFIX = "/api/v1"


def create_app() -> Flask:
    app = Flask(__name__)

    # Config
    app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["SESSION_COOKIE_NAME"] = settings.session_cookie_name
    app.config["SESSION_COOKIE_SAMESITE"] = settings.session_cookie_samesite
    app.config["SESSION_COOKIE_SECURE"] = settings.session_cookie_secure

    # Proxy fix (Railway)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Extensions
    CORS(app, supports_credentials=True)
    compress.init_app(app)
    # Mode "threading" (serveur Werkzeug threadé + simple-websocket pour le
    # transport websocket) : chaque requête a son propre thread OS, donc les
    # appels bloquants (redis-py dans send_command, requests) ne gèlent plus
    # toute l'API, et le Redis listener (thread natif) peut émettre sans risque.
    # eventlet sans monkey_patch() bloquait le hub et coinçait les files
    # d'émission des clients.
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # Register routes
    from api.routes.health import bp as health_bp
    from api.routes.player import bp as player_bp
    from api.routes.search import bp as search_bp
    from api.routes.auth import bp as auth_bp
    from api.routes.guilds import bp as guilds_bp
    from api.routes.spotify import bp as spotify_bp
    from api.routes.history import bp as history_bp

    app.register_blueprint(health_bp, url_prefix=API_PREFIX)
    app.register_blueprint(player_bp, url_prefix=API_PREFIX)
    app.register_blueprint(search_bp, url_prefix=API_PREFIX)
    app.register_blueprint(auth_bp, url_prefix=API_PREFIX)
    app.register_blueprint(guilds_bp, url_prefix=API_PREFIX)
    app.register_blueprint(spotify_bp, url_prefix=API_PREFIX)
    app.register_blueprint(history_bp, url_prefix=API_PREFIX)

    # Register WebSocket handlers
    from api.websocket import events  # noqa: F401

    # Register error handlers
    from api.middleware.errors import register_error_handlers
    register_error_handlers(app)

    log.info("API created (prefix=%s)", API_PREFIX)
    return app
