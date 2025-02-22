import discord
from discord.ext import commands

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx):
        """Fait rejoindre Greg dans un salon vocal."""
        if ctx.author.voice is None:
            await ctx.send("❌ T'es même pas dans un vocal, sombre idiot.")
            return

        voice_channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await voice_channel.connect()
            await ctx.send(
                f"👑 Greg le Consanguin se ramène dans **{voice_channel.name}**. C'est quoi cet endroit miteux ?")
        else:
            await ctx.voice_client.move_to(voice_channel)
            await ctx.send(
                f"👑 Greg le Consanguin s’installe dans **{voice_channel.name}**. Vous allez faire quoi ? Me virer ?")

    @commands.command()
    async def leave(self, ctx):
        """Fait quitter Greg le Consanguin du salon vocal."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Tsss… Je m’en vais, bande de gueux.")
        else:
            await ctx.send("Je suis pas dans un salon vocal, cervelle de moineau.")

def setup(bot):
    bot.add_cog(Voice(bot))