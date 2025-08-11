import logging
import os
import threading
import time
import socket
import discord
from discord.ext import commands
from playlist_manager import PlaylistManager
from connect.app import create_web_app
import config

# ---------------------------------------------------------------------------
# Configuration du logging
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

# --------- PlaylistManager multi-serveur -----------
playlist_managers = {}  # {guild_id: PlaylistManager}

def get_pm(guild_id):
    guild_id = str(guild_id)
    if guild_id not in playlist_managers:
        playlist_managers[guild_id] = PlaylistManager(guild_id)
        logger.debug("Nouvelle instance PlaylistManager pour guild %s", guild_id)
    return playlist_managers[guild_id]

# ===== Discord bot setup =====
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)  # préfixe inutile mais requis

# ===== Crée l'app Flask + SocketIO =====
app, socketio = create_web_app(get_pm)
app.bot = bot

def run_web():
    logger.debug("Lancement du serveur Flask/SocketIO…")
    socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)

# ===== Chargement dynamique des Cogs Discord =====
async def load_cogs():
    logger.debug("Chargement des Cogs…")
    for filename in os.listdir("./commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            extension = f"commands.{filename[:-3]}"
            try:
                await bot.load_extension(extension)
                logger.info("✅ Cog chargé : %s", extension)
            except Exception as e:
                logger.error("❌ Erreur chargement %s : %s", extension, e)

@bot.event
async def on_ready():
    logger.info("====== EVENT on_ready() ======")
    logger.info("Utilisateur bot : %s", bot.user)
    logger.info("Serveurs : %s", [g.name for g in bot.guilds])
    logger.info("Slash commands globales : %s", [cmd.name for cmd in await bot.tree.fetch_commands()])
    await load_cogs()
    await bot.tree.sync()
    logger.info("Slash commands sync DONE !")

    try:
        music_cog = bot.get_cog("Music")
        voice_cog = bot.get_cog("Voice")
        if music_cog:
            def emit(event: str, data: dict):
                socketio.emit(event, data)
            music_cog.emit_fn = emit
        if voice_cog:
            voice_cog.emit_fn = lambda event, data: socketio.emit(event, data)
    except Exception as e:
        logger.error("Impossible de connecter emit_fn: %s", e)

# ===== Attente que le serveur web réponde =====
def wait_for_web():
    for _ in range(15):
        try:
            s = socket.create_connection(("localhost", 3000), 1)
            s.close()
            logger.debug("Serveur web prêt, on peut lancer Greg.")
            return
        except Exception:
            time.sleep(1)
    logger.critical("Serveur web jamais prêt !")
    raise SystemExit("[FATAL] Serveur web jamais prêt !")

# ===== Lancement combiné Discord + Web =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    wait_for_web()
    bot.run(config.DISCORD_TOKEN)
