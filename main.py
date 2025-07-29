# main.py

print("=== DÉMARRAGE GREG LE CONSANGUIN ===")

import os
import threading
import time
import socket

from bot_socket import start_socketio_client, pm  # pm = PlaylistManager partagé
import discord
from discord.ext import commands
from web.app import create_web_app

# ===== Création bot Discord =====
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Injecter bot dans bot_socket pour activer la lecture depuis le web
import bot_socket
bot_socket.bot = bot

# ===== Serveur Web (Flask + SocketIO) =====
app, socketio = create_web_app(pm)

def run_web():
    socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)

# ===== Chargement des Cogs =====
async def load_cogs():
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
    await load_cogs()
    await bot.tree.sync()
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")

# ===== Attente que le web soit prêt =====
def wait_for_web():
    for i in range(15):
        try:
            s = socket.create_connection(("localhost", 3000), 1)
            s.close()
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("[FATAL] Serveur web jamais prêt !")

# ===== Lancement combiné Flask + Discord bot =====
if __name__ == "__main__":
    # Lancer le serveur web dans un thread
    threading.Thread(target=run_web).start()
    wait_for_web()

    # Lancer le client SocketIO pour écoute des mises à jour playlist
    start_socketio_client("http://localhost:3000")

    # Lancer Greg le serviteur vocal
    import config
    bot.run(config.DISCORD_TOKEN)
