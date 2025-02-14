import discord
from discord.ext import commands
import config
from commands import music, voice, chat_ai

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Charger les commandes
bot.add_cog(music.Music(bot))
bot.add_cog(voice.Voice(bot))
bot.add_cog(chat_ai.ChatAI(bot))

@bot.event
async def on_ready():
    print(f"👑 Greg le Consanguin est en ligne en tant que {bot.user}")

bot.run(config.DISCORD_TOKEN)
