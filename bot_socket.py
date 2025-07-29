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

# Bot injecté dynamiquement
bot = None

@sio.event
def connect():
    print("[SocketIO] Bot Discord connecté au serveur web pour la synchro playlist.")

@sio.on('playlist_update')
def on_playlist_update(data):
    print("[SocketIO] Event 'playlist_update' reçu du web : reload playlist !")
    try:
        import asyncio
        pm.reload()
        loop = asyncio.get_event_loop()
        loop.create_task(trigger_play(bot))  # 🔥 propre et non-bloquant
    except Exception as e:
        print(f"[FATAL] Erreur dans on_playlist_update : {e}")

def start_socketio_client(server_url="http://localhost:3000"):
    print(f"[DEBUG] start_socketio_client appelé avec URL={server_url}")
    try:
        sio.connect(server_url)
        print("[SocketIO] Connecté à", server_url)
    except Exception as e:
        print("[SocketIO] Erreur de connexion à SocketIO :", e)

async def trigger_play(bot):
    if not bot:
        print("[FATAL] Bot non défini dans trigger_play()")
        return

    music_cog = bot.get_cog("Music")
    if not music_cog:
        print("[FATAL] Music cog introuvable.")
        return

    for guild in bot.guilds:
        voice_channel = None

        # Cherche un utilisateur humain connecté en vocal
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    voice_channel = vc
                    break
            if voice_channel:
                break

        if not voice_channel:
            print("[INFO] Aucun humain en vocal, Greg reste planqué.")
            return

        # Connect Greg si nécessaire
        if not guild.voice_client:
            try:
                await voice_channel.connect()
                print(f"[DEBUG] Greg a rejoint le vocal : {voice_channel.name}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[ERROR] Connexion vocale échouée : {e}")
                return

        if guild.voice_client:
            class FakeInteraction:
                def __init__(self, guild):
                    self.guild = guild
                    self.user = guild.members[0]
                    self.followup = self
                async def send(self, msg): print(f"[GregFake] {msg}")

            try:
                await music_cog.play_next(FakeInteraction(guild))
                print("[DEBUG] play_next() lancé depuis le web")
            except Exception as e:
                print(f"[ERROR] play_next() échoué : {e}")
