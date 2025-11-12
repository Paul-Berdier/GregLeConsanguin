# api/core/extensions.py
from __future__ import annotations

import os
from typing import Iterable, Optional

from flask import Flask
from flask_cors import CORS
from flask_compress import Compress
from flask_socketio import SocketIO


# Extensions uniques (instanciées ici, initialisées dans create_app)
cors = CORS()
compress = Compress()
socketio = SocketIO(
    async_mode=os.getenv("SOCKETIO_ASYNC_MODE", "threading"),
    cors_allowed_origins=os.getenv("SOCKETIO_CORS", "*"),
    logger=False,
    engineio_logger=False,
    json=None,  # laisser Flask/rapidjson si branché
)


def init_extensions(app: Flask) -> None:
    # CORS
    allow_origins = _parse_origins(os.getenv("ALLOWED_ORIGINS", "*"))
    cors.init_app(
        app,
        resources={r"/*": {"origins": allow_origins}},
        supports_credentials=True,
        always_send=True,
    )
    # Compression
    compress.init_app(app)

    # Socket.IO
    # Ne pas appeler socketio.init_app trop tôt si on a besoin du 'cors_allowed_origins'
    socketio.init_app(
        app,
        cors_allowed_origins=allow_origins or "*",
        cookie=os.getenv("SOCKETIO_COOKIE", "gregsid"),
        ping_interval=20,
        ping_timeout=25,
    )


def _parse_origins(value: str) -> Optional[Iterable[str]]:
    if not value or value.strip() == "*":
        return "*"
    return [o.strip() for o in value.split(",") if o.strip()]
