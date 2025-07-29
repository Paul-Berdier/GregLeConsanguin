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

# Instance partagée de PlaylistManager
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

# Bot Discord injecté depuis main.py
bot = None  # sera défini après l'initialisation du bot dans main.py

@sio.event
def connect():
    print("[SocketIO] Bot Discord connecté au serveur web pour la synchro playlist.")

@sio.on('playlist_update')
def on_playlist_update(data):
    print("[SocketIO] Event 'playlist_update' reçu : rechargement + déclenchement lecture")
    try:
        import asyncio
        pm.reload()
        asyncio.run(trigger_play(bot))
    except Exception as e:
        print(f"[FATAL] Erreur dans on_playlist_update : {e}")

async def trigger_play(bot):
    if bot is None:
        print("[FATAL] bot non initialisé dans trigger_play()")
        return

    music_cog = bot.get_cog("Music")
    if not music_cog:
        print("[FATAL] Music cog introuvable.")
        return

    for guild in bot.guilds:
        voice_channel = None

        # Trouver un utilisateur humain en vocal
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    voice_channel = vc
                    break
            if voice_channel:
                break

        if not voice_channel:
            print("[INFO] Aucun humain en vocal, Greg ne bouge pas.")
            return

        # Greg rejoint si nécessaire
        if guild.voice_client is None:
            try:
                await voice_channel.connect()
                print(f"[DEBUG] Greg a rejoint le vocal : {voice_channel.name}")
            except Exception as e:
                print(f"[ERROR] Échec de connexion vocal : {e}")
                return

        # Faux interaction pour déclencher play_next()
        class FakeInteraction:
            def __init__(self, guild):
                self.guild = guild
                self.user = voice_channel.members[0]
                self.followup = self
            async def send(self, msg): print(f"[GregFake] {msg}")

        try:
            await music_cog.play_next(FakeInteraction(guild))
            print("[DEBUG] play_next() lancé depuis le web")
        except Exception as e:
            print(f"[ERROR] Erreur lors du déclenchement play_next : {e}")

def start_socketio_client(server_url="http://localhost:3000"):
    print(f"[DEBUG] start_socketio_client avec URL = {server_url}")
    try:
        sio.connect(server_url)
        print("[SocketIO] Connecté à", server_url)
    except Exception as e:
        print("[SocketIO] Erreur de connexion à SocketIO :", e)
