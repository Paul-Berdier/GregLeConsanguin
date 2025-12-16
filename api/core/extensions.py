# api/core/extensions.py

from __future__ import annotations

import logging
import os

from flask_cors import CORS
from flask_socketio import SocketIO

log = logging.getLogger(__name__)

# Instance globale unique
socketio = SocketIO(
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    manage_session=False,
)

def _pick_async_mode(preferred: str) -> str:
    """
    Choisit un async_mode utilisable.
    - si preferred == eventlet/gevent mais non installé => fallback threading
    """
    pref = (preferred or "").strip().lower() or "eventlet"

    if pref == "eventlet":
        try:
            import eventlet  # noqa: F401
            return "eventlet"
        except Exception:
            log.warning("SOCKETIO_MODE=eventlet mais eventlet absent → fallback threading")
            return "threading"

    if pref == "gevent":
        try:
            import gevent  # noqa: F401
            return "gevent"
        except Exception:
            log.warning("SOCKETIO_MODE=gevent mais gevent absent → fallback threading")
            return "threading"

    if pref in {"threading", "asyncio"}:
        return pref

    # valeur inconnue
    log.warning("SOCKETIO_MODE=%s inconnu → fallback threading", pref)
    return "threading"


def init_extensions(app):
    """
    - CORS pour API, Auth et Socket.IO
    - Socket.IO : init UNIQUE (idempotent)
      • mode via app.config["SOCKETIO_MODE"] ou env SOCKETIO_MODE
      • MQ Redis optionnelle via SOCKETIO_MESSAGE_QUEUE
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

    preferred = app.config.get("SOCKETIO_MODE") or os.getenv("SOCKETIO_MODE", "eventlet")
    mode = _pick_async_mode(preferred)
    message_queue = os.getenv("SOCKETIO_MESSAGE_QUEUE")  # ex: redis://localhost:6379/0

    # ✅ idempotent : n'init qu'une fois
    if not getattr(socketio, "server", None):
        socketio.init_app(
            app,
            async_mode=mode,
            cors_allowed_origins="*",
            message_queue=message_queue,
        )
        log.info("Socket.IO init_app: async_mode=%s mq=%s", mode, "yes" if message_queue else "no")
    else:
        log.debug("Socket.IO déjà initialisé, skip init_app()")
