# bot_socket.py

import socketio
from playlist_manager import PlaylistManager

pm = PlaylistManager()  # Import/instancie le même PlaylistManager que partout

sio = socketio.Client()

@sio.event
def connect():
    print("[SocketIO] Bot Discord connecté au serveur web pour la synchro playlist.")

@sio.on('playlist_update')
def on_playlist_update(data):
    print("[SocketIO] Event 'playlist_update' reçu du web : reload playlist !")
    pm.reload()

def start_socketio_client(server_url="http://localhost:3000"):
    try:
        sio.connect(server_url)
        print("[SocketIO] Connecté à", server_url)
    except Exception as e:
        print("[SocketIO] Erreur de connexion à SocketIO :", e)
