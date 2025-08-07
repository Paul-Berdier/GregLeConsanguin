# main.py

print("=== DÉMARRAGE GREG LE CONSANGUIN ===")

import os
import threading
import time
import socket
import discord
from discord.ext import commands
from playlist_manager import PlaylistManager
from pathlib import Path

from web.app import create_web_app
import config

# --------- PlaylistManager multi-serveur (la seule source de vérité) -----------
playlist_managers = {}  # {guild_id: PlaylistManager}

def get_pm(guild_id):
    guild_id = str(guild_id)
    if guild_id not in playlist_managers:
        playlist_managers[guild_id] = PlaylistManager(guild_id)
        print(f"[DEBUG][main.py] Nouvelle instance PlaylistManager pour guild {guild_id}")
    return playlist_managers[guild_id]

# -------------------------------------------------------------
# Setup of runtime directories
#
# As a convenience for development and deployment, we ensure
# that commonly used filesystem locations exist before the bot
# starts.  In particular the extractors write downloaded media
# files into a `downloads/` directory.  Without creating this
# directory ahead of time, yt-dlp will raise an exception when
# attempting to write files (e.g. ``FileNotFoundError: [Errno 2]
# No such file or directory: 'downloads/greg_audio.mp3'``).  A
# senior developer would ensure that such prerequisites are
# satisfied at startup rather than relying on implicit
# behaviour deep in third‑party libraries.
# -------------------------------------------------------------

# Create a downloads directory if it does not already exist.
DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# ===== Discord bot setup =====
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Crée l'app Flask + SocketIO, lie l'accès à get_pm et le bot =====
app, socketio = create_web_app(get_pm)
app.bot = bot

def run_web():
    print("[DEBUG][main.py] Lancement du serveur Flask/SocketIO…")
    socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)

# ===== Chargement dynamique des Cogs Discord =====
async def load_cogs():
    print("[DEBUG][main.py] Chargement des Cogs…")
    for filename in os.listdir("./commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            extension = f"commands.{filename[:-3]}"
            try:
                await bot.load_extension(extension)
                print(f"✅ Cog chargé : {extension}")
            except Exception as e:
                print(f"❌ Erreur chargement {extension} : {e}")

@bot.event
async def on_ready():
    print("====== EVENT on_ready() ======")
    print("Utilisateur bot :", bot.user)
    print("Serveurs :", [g.name for g in bot.guilds])
    print("Slash commands globales :", [cmd.name for cmd in await bot.tree.fetch_commands()])
    await load_cogs()
    await bot.tree.sync()
    print("Slash commands sync DONE !")


# ===== Attente que le serveur web réponde =====
def wait_for_web():
    for i in range(15):
        try:
            s = socket.create_connection(("localhost", 3000), 1)
            s.close()
            print("[DEBUG][main.py] Serveur web prêt, on peut lancer Greg.")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("[FATAL] Serveur web jamais prêt !")

# ===== Lancement combiné Discord + Web =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    wait_for_web()
    bot.run(config.DISCORD_TOKEN)
