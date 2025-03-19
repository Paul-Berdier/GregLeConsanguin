import discord
from discord.ext import commands
import config
from commands.voice import Voice
from commands.music import Music
from commands.chat_ai import ChatAI

import os
os.system("apt-get update && apt-get install -y ffmpeg")


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
    # await bot.add_cog(ChatAI(bot))

@bot.event
async def on_ready():
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")
    await load_cogs()

    # Vérifie si Greg doit rejoindre un salon vocal après un redémarrage
    if os.path.exists("voice_channel.txt"):
        with open("voice_channel.txt", "r") as f:
            channel_id = int(f.read().strip())
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.connect()
                print(f"🔊 Greg a rejoint automatiquement {channel.name}")
                os.remove("voice_channel.txt")

bot.run(config.DISCORD_TOKEN)
