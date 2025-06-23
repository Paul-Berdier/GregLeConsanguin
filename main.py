import discord
from discord.ext import commands
import config
from commands.voice import Voice
from commands.music import Music
from commands.chat_ai import ChatAI

import os
os.system("apt-get update && apt-get install -y ffmpeg")
import config
import asyncio
from flask import Flask, render_template, request, redirect
import threading
import requests

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True  # Active l'accès aux messages
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    await bot.add_cog(Music(bot))
    await bot.add_cog(Voice(bot))
    await bot.add_cog(ChatAI(bot))

@bot.event
async def on_ready():
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")
    await load_cogs()


# Flask web interface
app = Flask(__name__, static_folder="static", template_folder="templates")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/play", methods=["POST"])
def play():
    url = request.form["url"]
    requests.post(DISCORD_WEBHOOK_URL, json={"content": f"!play {url}"})
    return redirect("/")

def run_flask():
    app.run(host="0.0.0.0", port=3000)

# Démarrage parallèle
if __name__ == "__main__":
    os.system("apt-get update && apt-get install -y ffmpeg")

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    bot.run(config.DISCORD_TOKEN)