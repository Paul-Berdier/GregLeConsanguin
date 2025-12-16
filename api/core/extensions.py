# api/core/extensions.py
from __future__ import annotations

import os
from flask_cors import CORS
from flask_socketio import SocketIO

# Instance globale (handlers @socketio.on(...) se branchent dessus)
socketio = SocketIO(
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    manage_session=False,
)

def init_extensions(app) -> None:
    """
    Initialise les extensions globales:
    - CORS
    - Socket.IO (une seule init_app, idempotent)
    """
    # -------------------- CORS (HTTP) --------------------
    CORS(
        app,
        resources={
            r"/api/*": {"origins": "*"},
            r"/auth/*": {"origins": "*"},
            r"/socket.io/*": {"origins": "*"},
        },
        supports_credentials=True,
    )

    # -------------------- Socket.IO ----------------------
    # ⚠️ Une seule fois par app (évite double init)
    if app.extensions.get("__socketio_inited__"):
        return

    mode = app.config.get("SOCKETIO_MODE") or os.getenv("SOCKETIO_MODE", "eventlet")
    message_queue = app.config.get("SOCKETIO_MESSAGE_QUEUE") or os.getenv("SOCKETIO_MESSAGE_QUEUE")
    # ex: "redis://localhost:6379/0" (optionnel)

    socketio.init_app(
        app,
        async_mode=mode,
        cors_allowed_origins="*",
        message_queue=message_queue,
        logger=bool(app.config.get("SOCKETIO_LOGGER", False)),
        engineio_logger=bool(app.config.get("ENGINEIO_LOGGER", False)),
    )

    app.extensions["__socketio_inited__"] = True
