"""API entry point — lance Flask + Socket.IO + Redis listener."""
from __future__ import annotations

import logging
import os
import sys
import threading

from greg_shared.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("greg.api")

# Silence the "socket shutdown error: Bad file descriptor" spam
# from simple-websocket when Railway health checks hit /socket.io/
logging.getLogger("simple_websocket").setLevel(logging.ERROR)
logging.getLogger("engineio.server").setLevel(logging.WARNING)
logging.getLogger("socketio.server").setLevel(logging.WARNING)
# Serveur Werkzeug (async_mode="threading") : pas de log d'accès par requête
# (polling Socket.IO toutes les 3 s), comme avant avec eventlet.
logging.getLogger("werkzeug").setLevel(logging.WARNING)


class _DropWsCloseGarbage(logging.Filter):
    """Werkzeug logge « code 400, message Bad request syntax/version » quand un client
    envoie encore une trame websocket après la fermeture (octets lus comme du HTTP)."""

    def filter(self, record):
        return "code 400, message Bad " not in record.getMessage()


logging.getLogger("werkzeug").addFilter(_DropWsCloseGarbage())

# Also suppress the stderr prints from simple-websocket
_orig_stderr_write = sys.stderr.write
def _filtered_stderr(msg):
    if "socket shutdown error" in msg or "Bad file descriptor" in msg:
        return 0
    return _orig_stderr_write(msg)
sys.stderr.write = _filtered_stderr


def main():
    from api import create_app, socketio
    from api.services.redis_listener import start_redis_listener

    app = create_app()

    port = int(os.getenv("PORT", "3000"))
    host = os.getenv("HOST", "::")  # Railway private networking: bind IPv6/dual-stack

    # Thread OS natif : sûr en async_mode="threading" (socketio.emit est
    # thread-safe dans ce mode ; ce ne l'était pas avec eventlet non patché).
    threading.Thread(
        target=start_redis_listener,
        args=(socketio,),
        daemon=True,
    ).start()
    logger.info("Redis listener started in background thread.")

    logger.info("Starting API on %s:%d (Socket.IO async_mode=%s)", host, port, socketio.async_mode)
    # async_mode="threading" → serveur Werkzeug threadé (app.run(threaded=True)),
    # websocket via simple-websocket ; allow_unsafe_werkzeug requis hors TTY (Docker).
    socketio.run(
        app,
        host=host,
        port=port,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()