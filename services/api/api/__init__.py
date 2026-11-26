"""Greg le Consanguin — API REST + WebSocket."""
from __future__ import annotations

import logging
import os
import re
from typing import List, Optional
from urllib.parse import urlsplit

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

# URL publique du front sur Railway (valeur historique de la redirection après login).
DEFAULT_WEB_URL = "https://greg-le-consanguin.up.railway.app"


def web_url() -> str:
    """URL publique du front : WEB_URL (env) > settings.web_url > défaut Railway."""
    return (os.getenv("WEB_URL") or getattr(settings, "web_url", "") or DEFAULT_WEB_URL).strip()


def _normalize_origin(raw: str) -> Optional[str]:
    """'https://Foo.example:443/x/' → 'https://foo.example' ; None si ce n'est pas une origine http(s)."""
    s = (raw or "").strip()
    if not s or s == "*":
        return None
    try:
        u = urlsplit(s)
        port = u.port
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    host = u.hostname.lower()
    if ":" in host:  # IPv6
        host = f"[{host}]"
    default_port = 443 if u.scheme == "https" else 80
    return f"{u.scheme}://{host}" + (f":{port}" if port and port != default_port else "")


def cors_origins() -> List[str]:
    """Origines autorisées (HTTP + Socket.IO) : CORS_ORIGINS (séparées par des virgules) ∪ WEB_URL.

    Jamais de joker : avec les cookies de session (SameSite=None), « * » laisserait
    n'importe quel site piloter Greg au nom de l'utilisateur connecté.
    """
    out: List[str] = []
    for raw in (os.getenv("CORS_ORIGINS") or "").split(",") + [web_url()]:
        origin = _normalize_origin(raw)
        if raw.strip() and origin is None:
            log.warning("Origine CORS ignorée (invalide) : %r", raw.strip())
        if origin and origin not in out:
            out.append(origin)
    return out or [DEFAULT_WEB_URL]


# Origine exacte d'une extension Overwolf : pas de joker, pas de chemin, pas de port, pas de métacaractère regex.
OVERLAY_ORIGIN_RE = re.compile(r"overwolf-extension://[a-z]{20,64}")


def overlay_origins() -> List[str]:
    """Origines de l'appli Overwolf : OVERLAY_ORIGINS (séparées par des virgules), vide si non définie.

    Chaque entrée (espaces retirés, minuscules) doit être `overwolf-extension://<uid>` exactement,
    sinon elle est ignorée avec un avertissement. Ces origines ne sont jamais celles du site
    (`WEB_ORIGINS`) : la garde CSRF des routes de session les refuse.
    """
    out: List[str] = []
    for raw in (os.getenv("OVERLAY_ORIGINS") or "").split(","):
        origin = raw.strip().lower()
        if not origin:
            continue
        if not OVERLAY_ORIGIN_RE.fullmatch(origin):
            log.warning("Origine de l'appli ignorée (invalide) : %r", raw.strip())
            continue
        if origin not in out:
            out.append(origin)
    return out


def create_app() -> Flask:
    app = Flask(__name__)

    # Config
    app.config["SECRET_KEY"] = settings.flask_secret_key
    # Corps JSON bornés (413 au-delà) : le chansonnier et /queue/add_many lisent des listes de titres, le reste
    # des routes de petits objets. 1 Mo couvre 500 titres pleins ; un corps énorme n'est plus lu en entier.
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    app.config["SESSION_COOKIE_NAME"] = settings.session_cookie_name
    app.config["SESSION_COOKIE_SAMESITE"] = settings.session_cookie_samesite
    app.config["SESSION_COOKIE_SECURE"] = settings.session_cookie_secure

    # Proxy fix (Railway)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Extensions
    # Même liste pour HTTP et Socket.IO : le site puis l'appli Overwolf. En prod le front
    # passe par le proxy Next (même origine pour le navigateur) mais engine.io vérifie quand
    # même l'en-tête Origin : l'origine du front DOIT être dans la liste (WEB_URL / CORS_ORIGINS).
    web = cors_origins()
    overlay = overlay_origins()
    # Origines du site seul : la garde CSRF des routes de session (authz.csrf_ok) n'admet qu'elles.
    app.config["WEB_ORIGINS"] = web
    origins = web + [o for o in overlay if o not in web]
    app.config["ALLOWED_ORIGINS"] = origins
    log.info("Origines autorisées (CORS / Socket.IO) : site %s, appli %s", web, overlay)
    CORS(app, supports_credentials=True, origins=origins)
    compress.init_app(app)
    # Mode "threading" (serveur Werkzeug threadé + simple-websocket pour le
    # transport websocket) : chaque requête a son propre thread OS, donc les
    # appels bloquants (redis-py dans send_command, requests) ne gèlent plus
    # toute l'API, et le Redis listener (thread natif) peut émettre sans risque.
    # eventlet sans monkey_patch() bloquait le hub et coinçait les files
    # d'émission des clients.
    socketio.init_app(app, cors_allowed_origins=origins, async_mode="threading")

    # Register routes
    from api.routes.health import bp as health_bp
    from api.routes.player import bp as player_bp
    from api.routes.search import bp as search_bp
    from api.routes.auth import bp as auth_bp
    from api.routes.guilds import bp as guilds_bp
    from api.routes.history import bp as history_bp
    from api.routes.library import bp as library_bp

    app.register_blueprint(health_bp, url_prefix=API_PREFIX)
    app.register_blueprint(player_bp, url_prefix=API_PREFIX)
    app.register_blueprint(search_bp, url_prefix=API_PREFIX)
    app.register_blueprint(auth_bp, url_prefix=API_PREFIX)
    app.register_blueprint(guilds_bp, url_prefix=API_PREFIX)
    app.register_blueprint(history_bp, url_prefix=API_PREFIX)
    app.register_blueprint(library_bp, url_prefix=API_PREFIX)

    # Register WebSocket handlers
    from api.websocket import events  # noqa: F401

    # Register error handlers
    from api.middleware.errors import register_error_handlers
    register_error_handlers(app)

    log.info("API created (prefix=%s)", API_PREFIX)
    return app
