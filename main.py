# main.py

import os
import threading
from bot_socket import start_socketio_client, pm  # pm = PlaylistManager partagé
import discord
from discord.ext import commands

# Import web/app
from web.app import create_web_app

print("[DEBUG] Démarrage main.py")

# ===== Lancer le serveur Web (Flask + SocketIO) =====
app, socketio = create_web_app(pm)
print("[DEBUG] Flask app et SocketIO créés")

def run_web():
    print("[DEBUG] Lancement de socketio.run ...")
    socketio.run(app, host="0.0.0.0", port=3000)
    print("[DEBUG] Fin de socketio.run (ne devrait jamais s'afficher sauf crash Flask)")

# ===== Discord Bot Setup =====
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
print("[DEBUG] Instance bot Discord créée")

# Charger les cogs comme d'habitude, mais en passant 'pm' au Music Cog si besoin
async def load_cogs():
    print("[DEBUG] Début load_cogs")
    for filename in os.listdir("./commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            extension = f"commands.{filename[:-3]}"
            try:
                await bot.load_extension(extension)
                print(f"✅ Extension chargée : {extension}")
            except Exception as e:
                print(f"❌ Erreur lors du chargement de {extension} : {e}")
    print("[DEBUG] Fin load_cogs")

@bot.event
async def on_ready():
    print("[DEBUG] on_ready appelé")
    await load_cogs()
    await bot.tree.sync()
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")

if __name__ == "__main__":
    print("[DEBUG] Thread Flask démarrage...")
    flask_thread = threading.Thread(target=run_web)
    flask_thread.start()

    print("[DEBUG] Lancement SocketIO client bot ...")
    start_socketio_client("http://localhost:3000")  # Mets bien l'URL de ton web/socketio ici

    print("[DEBUG] Lancement bot Discord...")
    import config  # Mets ton token dans config.py
    bot.run(config.DISCORD_TOKEN)
    print("[DEBUG] Fin bot.run (ne devrait jamais s’afficher sauf crash Discord bot)")

