print("=== TOP MAIN.PY ===")

import os
print("[DEBUG] Import os OK")

import threading
print("[DEBUG] Import threading OK")

try:
    from bot_socket import start_socketio_client, pm  # pm = PlaylistManager partagé
    print("[DEBUG] Import bot_socket OK")
except Exception as e:
    print(f"[FATAL] Erreur import bot_socket : {e}")

try:
    import discord
    print("[DEBUG] Import discord OK")
    from discord.ext import commands
    print("[DEBUG] Import discord.ext.commands OK")
except Exception as e:
    print(f"[FATAL] Erreur import discord : {e}")

try:
    from web.app import create_web_app
    print("[DEBUG] Import web.app.create_web_app OK")
except Exception as e:
    print(f"[FATAL] Erreur import web.app : {e}")

print("[DEBUG] Démarrage main.py (après tous imports)")

# ===== Lancer le serveur Web (Flask + SocketIO) =====
try:
    app, socketio = create_web_app(pm)
    print("[DEBUG] Flask app et SocketIO créés")
except Exception as e:
    print(f"[FATAL] Erreur création Flask app : {e}")

def run_web():
    print("[DEBUG] Lancement de socketio.run ...")
    try:
        socketio.run(app, host="0.0.0.0", port=3000)
        print("[DEBUG] Fin de socketio.run (ne devrait jamais s'afficher sauf crash Flask)")
    except Exception as e:
        print(f"[FATAL] Erreur socketio.run : {e}")

# ===== Discord Bot Setup =====
try:
    intents = discord.Intents.all()
    print("[DEBUG] Création intents OK")
    bot = commands.Bot(command_prefix="!", intents=intents)
    print("[DEBUG] Instance bot Discord créée")
except Exception as e:
    print(f"[FATAL] Erreur setup bot Discord : {e}")

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
    try:
        flask_thread = threading.Thread(target=run_web)
        flask_thread.start()
        print("[DEBUG] Thread Flask démarré")
    except Exception as e:
        print(f"[FATAL] Erreur démarrage thread Flask : {e}")

    print("[DEBUG] Lancement SocketIO client bot ...")
    try:
        start_socketio_client("http://localhost:5000")
        print("[DEBUG] SocketIO client démarré")
    except Exception as e:
        print(f"[FATAL] Erreur démarrage SocketIO client : {e}")

    print("[DEBUG] Lancement bot Discord...")
    try:
        import config  # Mets ton token dans config.py
        print("[DEBUG] Import config OK")
        bot.run(config.DISCORD_TOKEN)
    except Exception as e:
        print(f"[FATAL] Erreur bot.run ou import config : {e}")

    print("[DEBUG] Fin bot.run (ne devrait jamais s’afficher sauf crash Discord bot)")
