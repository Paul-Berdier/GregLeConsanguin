"""API entry point — lance Flask + Socket.IO + Redis listener."""
from __future__ import annotations

import logging
import os
import threading

from greg_shared.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("greg.api")


def main():
    from api import create_app, socketio
    from api.services.redis_listener import start_redis_listener

    app = create_app()
    port = int(os.getenv("PORT", "3000"))

    # Start Redis listener in background thread
    threading.Thread(target=start_redis_listener, args=(socketio,), daemon=True).start()
    logger.info("Redis listener started in background thread.")

    logger.info("Starting API on 0.0.0.0:%d", port)
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
