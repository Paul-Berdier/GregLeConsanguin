# api/core/extensions.py
from __future__ import annotations
import os
from flask_cors import CORS
from flask_socketio import SocketIO

# Instance globale (config finale appliquée dans init_app)
socketio = SocketIO(
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    manage_session=False,
)

def init_extensions(app):
    """
    - CORS pour API, Auth et Socket.IO
    - Socket.IO : mode asynchrone via app.config["SOCKETIO_MODE"] ou env, MQ Redis optionnelle
    """
    CORS(
        app,
        resources={
            r"/api/*": {"origins": "*"},
            r"/auth/*": {"origins": "*"},
            r"/socket.io/*": {"origins": "*"},
        },
        supports_credentials=True,
    )

    mode = app.config.get("SOCKETIO_MODE") or os.getenv("SOCKETIO_MODE", "eventlet")  # "eventlet" recommandé
    message_queue = os.getenv("SOCKETIO_MESSAGE_QUEUE")  # ex: "redis://localhost:6379/0"

    socketio.init_app(
        app,
        async_mode=mode,
        cors_allowed_origins="*",
        message_queue=message_queue,
    )
