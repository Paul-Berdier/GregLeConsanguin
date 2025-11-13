# api/core/extensions.py
from flask_cors import CORS
from flask_socketio import SocketIO

socketio = SocketIO(
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    manage_session=False,
)

def init_extensions(app):
    # CORS pour API + auth + Socket.IO
    CORS(
        app,
        resources={
            r"/api/*": {"origins": "*"},
            r"/auth/*": {"origins": "*"},
            r"/socket.io/*": {"origins": "*"},
        },
        supports_credentials=True,
    )
    # Socket.IO
    socketio.init_app(
        app,
        async_mode=app.config.get("SOCKETIO_MODE", "threading"),
        cors_allowed_origins="*",
    )
