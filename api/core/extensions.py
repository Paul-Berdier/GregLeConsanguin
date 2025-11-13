# api/core/extensions.py
from __future__ import annotations
import os
from flask_socketio import SocketIO

# Par défaut on reste sur threading (Werkzeug) => long-polling
ASYNC_MODE = os.getenv("SOCKETIO_ASYNC_MODE", "threading").strip() or "threading"
CORS_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "*")

# NOTE: avec threading, les websockets ne sont pas gérées par Werkzeug.
# On n'impose donc rien côté serveur ; le client doit accepter 'polling'.
socketio = SocketIO(
    async_mode=ASYNC_MODE,
    cors_allowed_origins=CORS_ORIGINS if CORS_ORIGINS != "*" else "*",
    cookie="gregsid",
    ping_interval=25,
    ping_timeout=30,
    max_http_buffer_size=20_000_000,
    logger=False,
    engineio_logger=False,
    # option engineio: empêche upgrade si le client a démarré en polling;
    # ne bloque pas un 'websocket only' côté client → d'où le patch front.
    allow_upgrades=True,
)

def init_extensions(app):
    # Idempotent : si l'instance a déjà un serveur, on ne réinitialise pas
    if getattr(socketio, "server", None) is None:
        socketio.init_app(app, cors_allowed_origins=CORS_ORIGINS if CORS_ORIGINS != "*" else "*")
    return app, socketio
