import discord
from discord.ext import commands
import config
from commands.voice import Voice
from commands.music import Music
from commands.chat_ai import ChatAI

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


bot.run(config.DISCORD_TOKEN)
