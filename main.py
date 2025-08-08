# main.py
import os
import asyncio
import discord
from discord.ext import commands

import config  # doit contenir DISCORD_TOKEN
from overlay.server import OverlayServer

# ========= Discord setup =========
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

overlay = OverlayServer()  # HTTP + WebSocket overlay

async def load_basic_cogs():
    """
    Charge les cogs standards via l'extension loader.
    On NE charge PAS music ici, car on doit lui passer overlay.broadcast.
    """
    for ext in ("commands.general", "commands.voice"):
        try:
            await bot.load_extension(ext)
            print(f"✅ Extension chargée : {ext}")
        except Exception as e:
            print(f"❌ Erreur chargement {ext} : {e}")

async def load_music_cog():
    """
    Charge la cog Music en lui injectant la fonction d'émission overlay.
    """
    from commands.music import Music
    try:
        await bot.add_cog(Music(bot, overlay_emit=overlay.broadcast))
        print("✅ Cog 'Music' chargée (overlay connecté).")
    except Exception as e:
        print(f"❌ Erreur chargement cog Music : {e}")

@bot.event
async def on_ready():
    # Démarre l'overlay server (Railway fournit $PORT)
    port = int(os.getenv("PORT", "8080"))
    asyncio.create_task(overlay.start(host="0.0.0.0", port=port))

    await load_basic_cogs()
    await load_music_cog()

    await bot.tree.sync()
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user} — prêt à gémir.")

def ensure_dirs():
    os.makedirs("downloads", exist_ok=True)

if __name__ == "__main__":
    ensure_dirs()

    token = getattr(config, "DISCORD_TOKEN", None) or os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant (config.py ou variable d'env).")

    # Railway: pas d’apt-get ici, tu installes ffmpeg dans l’image/Dockerfile si besoin.
    bot.run(token)
