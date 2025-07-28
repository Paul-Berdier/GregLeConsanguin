# bot_socket.py

print("[DEBUG] TOP bot_socket.py")

try:
    import socketio
    print("[DEBUG] Import socketio OK")
except Exception as e:
    print(f"[FATAL] Import socketio : {e}")

try:
    from playlist_manager import PlaylistManager
    print("[DEBUG] Import PlaylistManager OK")
except Exception as e:
    print(f"[FATAL] Import playlist_manager : {e}")

try:
    pm = PlaylistManager()
    print("[DEBUG] Instance PlaylistManager créée")
except Exception as e:
    print(f"[FATAL] Création PlaylistManager : {e}")

try:
    sio = socketio.Client()
    print("[DEBUG] Instance socketio.Client créée")
except Exception as e:
    print(f"[FATAL] Création socketio.Client : {e}")

@sio.event
def connect():
    print("[SocketIO] Bot Discord connecté au serveur web pour la synchro playlist.")

@sio.on('playlist_update')
def on_playlist_update(data):
    print("[SocketIO] Event 'playlist_update' reçu du web : reload playlist !")
    try:
        pm.reload()
        print("[SocketIO] PlaylistManager.reload() OK")
    except Exception as e:
        print(f"[FATAL] pm.reload() dans on_playlist_update : {e}")

def start_socketio_client(server_url="http://localhost:5000"):
    print(f"[DEBUG] start_socketio_client appelé avec URL={server_url}")
    try:
        sio.connect(server_url)
        print("[SocketIO] Connecté à", server_url)
    except Exception as e:
        print("[SocketIO] Erreur de connexion à SocketIO :", e)
