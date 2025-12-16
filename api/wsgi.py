# api/wsgi.py
from __future__ import annotations

import os
import logging

from api import create_app
from api.core.extensions import socketio

log = logging.getLogger(__name__)

# App Flask (standalone web)
app = create_app(pm=None)

def main():
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "3000"))

    # Par défaut, en standalone on peut accepter eventlet si tu l’installes
    # (sinon tu peux mettre SOCKETIO_MODE=threading)
    mode = os.getenv("SOCKETIO_MODE", "eventlet")
    log.info("WSGI web starting host=%s port=%s socketio_mode=%s", host, port, mode)

    if mode == "threading":
        socketio.run(
            app,
            host=host,
            port=port,
            allow_unsafe_werkzeug=True,
            use_reloader=False,
        )
    else:
        # eventlet / gevent / etc.
        socketio.run(
            app,
            host=host,
            port=port,
            use_reloader=False,
        )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
