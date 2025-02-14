import discord
from discord.ext import commands

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx):
        """Fait rejoindre Greg le Consanguin dans le salon vocal."""
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send("Pff… Encore une corvée. Bon, me voilà dans le vocal.")
        else:
            await ctx.send("T'es même pas dans un vocal, idiot.")

    @commands.command()
    async def leave(self, ctx):
        """Fait quitter Greg le Consanguin du salon vocal."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Tsss… Je m’en vais, bande de gueux.")
        else:
            await ctx.send("Je suis pas dans un vocal, cervelle de moineau.")

def setup(bot):
    bot.add_cog(Voice(bot))
