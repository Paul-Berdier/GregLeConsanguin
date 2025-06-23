import discord
from discord.ext import commands
import config
from commands.voice import Voice
from commands.music import Music
from commands.chat_ai import ChatAI

import os
os.system("apt-get update && apt-get install -y ffmpeg")
import asyncio
from flask import Flask, render_template, request, redirect
import threading
import requests
import json

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

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

# # Ajoute les musiques venant de Discord dans le fichier JSON
# @bot.event
# async def on_message(message):
#     if message.author == bot.user:
#         return
#
#     if message.content.startswith("!play "):
#         url = message.content[6:].strip()
#         playlist = load_playlist()
#         playlist.append(url)
#         save_playlist(playlist)
#
#     elif message.content.startswith("!skip"):
#         playlist = load_playlist()
#         if playlist:
#             playlist.pop(0)
#             save_playlist(playlist)
#
#     elif message.content.startswith("!stop"):
#         save_playlist([])
#
#     await bot.process_commands(message)

# ===== CHARGEMENT DES COGS DISCORD =====
async def load_cogs():
    await bot.add_cog(Music(bot))
    await bot.add_cog(Voice(bot))
    await bot.add_cog(ChatAI(bot))

@bot.event
async def on_ready():
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")
    await load_cogs()

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

# ===== LANCEMENT COMBINÉ BOT + FLASK =====
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    bot.run(config.DISCORD_TOKEN)
