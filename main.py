import logging
import os
import threading
import time
import socket
import discord
from discord.ext import commands
from playlist_manager import PlaylistManager
import config

# ---------------------------------------------------------------------------
# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("greg.log", encoding="utf-8")
    ],
)
logger = logging.getLogger(__name__)
logger.info("=== DÉMARRAGE GREG LE CONSANGUIN ===")

# ---------------------------------------------------------------------------
# PlaylistManager multi-serveur
playlist_managers = {}  # {guild_id: PlaylistManager}

def get_pm(guild_id):
    guild_id = str(guild_id)
    if guild_id not in playlist_managers:
        playlist_managers[guild_id] = PlaylistManager(guild_id)
        logger.debug("Nouvelle instance PlaylistManager pour guild %s", guild_id)
    return playlist_managers[guild_id]

# ---------------------------------------------------------------------------
# Discord Bot class
class GregBot(commands.Bot):
    def __init__(self, **kwargs):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents, **kwargs)

    async def setup_hook(self):
        # Charger tous les Cogs
        logger.debug("Chargement des Cogs…")
        for filename in os.listdir("./commands"):
            if filename.endswith(".py") and filename != "__init__.py":
                extension = f"commands.{filename[:-3]}"
                try:
                    await self.load_extension(extension)
                    logger.info("✅ Cog chargé : %s", extension)
                except Exception as e:
                    logger.error("❌ Erreur chargement %s : %s", extension, e)

        # Sync slash commands
        await self.tree.sync()
        logger.info("Slash commands sync DONE !")

    async def on_ready(self):
        logger.info("====== EVENT on_ready() ======")
        logger.info("Utilisateur bot : %s", self.user)
        logger.info("Serveurs : %s", [g.name for g in self.guilds])
        logger.info("Slash commands globales : %s", [cmd.name for cmd in await self.tree.fetch_commands()])

        # Injection emit_fn si overlay dispo
        try:
            music_cog = self.get_cog("Music")
            voice_cog = self.get_cog("Voice")
            general_cog = self.get_cog("General")
            if music_cog and hasattr(app, "socketio"):
                music_cog.emit_fn = lambda event, data: app.socketio.emit(event, data)
            if voice_cog and hasattr(app, "socketio"):
                voice_cog.emit_fn = lambda event, data: app.socketio.emit(event, data)
            if general_cog and hasattr(app, "socketio"):
                voice_cog.emit_fn = lambda event, data: app.socketio.emit(event, data)
        except Exception as e:
            logger.error("Impossible de connecter emit_fn: %s", e)

# ---------------------------------------------------------------------------
# Flask + SocketIO (overlay web)
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"
app = None
socketio = None

if not DISABLE_WEB:
    try:
        from connect import create_web_app
        app, socketio = create_web_app(get_pm)
        app.bot = None  # attach later
    except ImportError:
        logger.warning("Overlay désactivé : module 'connect' introuvable")
        DISABLE_WEB = True

def run_web():
    if socketio and app:
        logger.debug("Lancement du serveur Flask/SocketIO…")
        socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)

def wait_for_web():
    for i in range(30):  # 30 tentatives
        try:
            s = socket.create_connection(("localhost", 3000), 1)
            s.close()
            logger.debug("Serveur web prêt après %s tentatives.", i + 1)
            return
        except Exception:
            time.sleep(1)
    logger.critical("Serveur web jamais prêt !")
    raise SystemExit("[FATAL] Serveur web jamais prêt !")

# ---------------------------------------------------------------------------
# Main
if __name__ == "__main__":
    bot = GregBot()

    if not DISABLE_WEB:
        app.bot = bot
        threading.Thread(target=run_web, daemon=True).start()
        wait_for_web()

    bot.run(config.DISCORD_TOKEN)
