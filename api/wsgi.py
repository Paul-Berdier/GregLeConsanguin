# wsgi.py
from api import create_app
from api.core.extensions import socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=3000)  # eventlet si installé
