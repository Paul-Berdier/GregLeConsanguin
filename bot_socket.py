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
        import asyncio
        asyncio.run(trigger_play(bot))  # 👈 lance la lecture !
    except Exception as e:
        print(f"[FATAL] pm.reload() dans on_playlist_update : {e}")


def start_socketio_client(server_url="http://localhost:3000"):
    print(f"[DEBUG] start_socketio_client appelé avec URL={server_url}")
    try:
        sio.connect(server_url)
        print("[SocketIO] Connecté à", server_url)
    except Exception as e:
        print("[SocketIO] Erreur de connexion à SocketIO :", e)

async def trigger_play(bot):
    music_cog = bot.get_cog("Music")
    if not music_cog:
        print("[FATAL] Music cog introuvable.")
        return

    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.id == bot.user.id:
                    print(f"[DEBUG] Greg est déjà dans {vc.name}")
                    break
            else:
                continue
            break
        else:
            # Greg n'est pas connecté, essayer de rejoindre le premier utilisateur humain
            for vc in guild.voice_channels:
                if vc.members:
                    await vc.connect()
                    print(f"[DEBUG] Greg a rejoint le vocal : {vc.name}")
                    break

        # Fake interaction
        class FakeInteraction:
            def __init__(self, guild):
                self.guild = guild
                self.user = guild.members[0]  # 👈 n’importe quel user
                self.followup = self
            async def send(self, msg): print(f"[GregFake] {msg}")

        fake = FakeInteraction(guild)
        await music_cog.play_next(fake)

