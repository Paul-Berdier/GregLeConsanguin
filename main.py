# main.py

import discord
from discord.ext import commands
import config
import os
import asyncio
import json
from flask import Flask, render_template, request, redirect
import threading
import requests

# ====== DISCORD SETUP ======
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # Slash commands

# ===== GESTION DE LA PLAYLIST =====
PLAYLIST_FILE = "playlist.json"

def load_playlist():
    if not os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "w") as f:
            json.dump([], f)
    with open(PLAYLIST_FILE, "r") as f:
        return json.load(f)

def save_playlist(playlist):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(playlist, f)

# ===== CHARGEMENT AUTOMATIQUE DES COGS =====
async def load_cogs():
    for filename in os.listdir("./commands"):
        if filename.endswith(".py"):
            extension = f"commands.{filename[:-3]}"
            try:
                await bot.load_extension(extension)
                print(f"✅ Extension chargée : {extension}")
            except Exception as e:
                print(f"❌ Erreur lors du chargement de {extension} : {e}")

@bot.event
async def on_ready():
    await load_cogs()
    await bot.tree.sync()
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")

# ===== INTERFACE FLASK =====
app = Flask(__name__, static_folder="static", template_folder="templates")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

messages_sarcastiques = [
    "Mais quelle horreur allez-vous encore me faire jouer...",
    "Ugh... Encore un ordre, encore une humiliation...",
    "Monde cruel, vous me forcez à appuyer sur play.",
    "Greg n’est pas payé pour ça. En fait, Greg n’est pas payé du tout.",
]

@app.route("/", methods=["GET"])
def index():
    import random
    phrase = random.choice(messages_sarcastiques)
    playlist = load_playlist()
    return render_template("index.html", phrase=phrase, playlist=playlist)

@app.route("/play", methods=["POST"])
def play():
    url = request.form["url"]
    playlist = load_playlist()
    playlist.append(url)
    save_playlist(playlist)
    requests.post(WEBHOOK_URL, json={"content": f"!play {url}"})
    return redirect("/")

@app.route("/pause", methods=["POST"])
def pause():
    requests.post(WEBHOOK_URL, json={"content": "!pause"})
    return redirect("/")

@app.route("/skip", methods=["POST"])
def skip():
    playlist = load_playlist()
    if playlist:
        playlist.pop(0)
        save_playlist(playlist)
    requests.post(WEBHOOK_URL, json={"content": "!skip"})
    return redirect("/")

@app.route("/stop", methods=["POST"])
def stop():
    save_playlist([])
    requests.post(WEBHOOK_URL, json={"content": "!stop"})
    return redirect("/")

def run_flask():
    app.run(host="0.0.0.0", port=3000)

# ===== LANCEMENT COMBINÉ DISCORD + FLASK =====
if __name__ == "__main__":
    os.system("apt-get update && apt-get install -y ffmpeg")  # Install ffmpeg (si Railway)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    bot.run(config.DISCORD_TOKEN)
