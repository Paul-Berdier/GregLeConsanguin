import discord
from discord.ext import commands
import asyncio

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx):
        """Fait rejoindre Greg dans un salon vocal."""
        if ctx.author.voice is None:
            await ctx.send("❌ *Par tous les Saints ! Vous osez me convoquer alors que vous n’êtes même pas en vocal ? Quelle audace !*")
            return

        voice_channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await voice_channel.connect()
            await ctx.send(
                f"👑 *Greg le Consanguin daigne honorer **{voice_channel.name}** de sa présence...* Que ce lieu miteux soit à la hauteur de mon noble mépris.")
        else:
            await ctx.voice_client.move_to(voice_channel)
            await ctx.send(
                f"👑 *Majesté, Greg est à vos pieds et change de crasseux taudis pour **{voice_channel.name}**. Que le destin me vienne en aide...*")

    @commands.command()
    async def leave(self, ctx):
        """Fait quitter Greg du salon vocal."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 *Greg s’en va... Enfin un instant de répit loin de votre cacophonie barbare.*")
        else:
            await ctx.send("❌ *Ah, quelle ironie… Vous exigez mon départ alors que je ne suis même pas là ! Je vois que l’imbécilité règne en maître ici...*")

    async def auto_disconnect(self, ctx):
        """Quitte le vocal après 5 min d’inactivité."""
        await asyncio.sleep(300)  # 5 minutes (300s)
        if ctx.voice_client and not ctx.voice_client.is_playing():
            await ctx.voice_client.disconnect()
            await ctx.send("👋 *Greg se retire, faute d’un public digne de son art. Peut-être trouverez-vous un autre esclave pour vous divertir...*")

def setup(bot):
    bot.add_cog(Voice(bot))
