# api/wsgi.py

from api import create_app
from api.core.extensions import socketio

# En WSGI pur, pas de bridge Discord => pm=None
# (tes routes doivent gérer proprement le cas pm absent si tu utilises wsgi.py)
app = create_app(pm=None)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=3000, use_reloader=False)
