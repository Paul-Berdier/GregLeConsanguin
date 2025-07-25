# commands/voice.py

from discord.ext import commands
import discord
import sys
import os
import asyncio

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True)
    async def invoque(self, ctx, *, channel_name: str):
        """Fait rejoindre Greg dans un salon vocal spécifique sans que l'auteur y soit."""
        voice_channel = discord.utils.get(ctx.guild.voice_channels, name=channel_name)
        if voice_channel is None:
            await ctx.send(f"❌ *Greg ne trouve point ce taudis nommé **{channel_name}**. Peut-être n’est-ce qu’un mirage de votre esprit dérangé...*")
            return

        try:
            if ctx.voice_client is None:
                await voice_channel.connect(timeout=10)
                await ctx.send(
                    f"🔮 *Greg a été invoqué dans **{channel_name}**. Et pourquoi pas dans une fosse sceptique pendant qu’on y est...*")
            else:
                await ctx.voice_client.move_to(voice_channel)
                await ctx.send(
                    f"🏃 *Greg s'empresse de changer de geôle pour **{channel_name}**. Toujours plus de souffrance...*")
        except asyncio.TimeoutError:
            await ctx.send("⏱️ *Greg a tenté d’obéir, mais ce channel semble maudit. Une nouvelle humiliation...*")
        except Exception as e:
            await ctx.send(f"❌ *Même les arcanes les plus sombres n’ont pu empêcher cet échec...* `{e}`")

    @commands.command(name="join", help="Fait rejoindre Greg dans votre salon vocal misérable.")
    async def join(self, ctx):
        """Fait rejoindre Greg dans un salon vocal."""
        if ctx.author.voice is None:
            await ctx.send("❌ *Par tous les Saints ! Vous osez me convoquer alors que vous n’êtes même pas en vocal ? Quelle audace !*")
            return

        voice_channel = ctx.author.voice.channel
        try:
            if ctx.voice_client is None:
                await voice_channel.connect(timeout=10)
                await ctx.send(
                    f"👑 *Greg le Consanguin daigne honorer **{voice_channel.name}** de sa présence...* Que ce lieu miteux soit à la hauteur de mon noble mépris.")
            else:
                await ctx.voice_client.move_to(voice_channel)
                await ctx.send(
                    f"👑 *Majesté, Greg est à vos pieds et change de crasseux taudis pour **{voice_channel.name}**. Que le destin me vienne en aide...*")
        except asyncio.TimeoutError:
            await ctx.send("⏱️ *Majesté... Greg a tenté de se connecter, mais le Royaume du Vocal est en grève. Misère...*")
        except Exception as e:
            await ctx.send(f"❌ *Un obstacle infernal m'empêche de rejoindre le vocal, Ô Majesté...* `{e}`")

    @commands.command(name="leave", help="Fait quitter Greg du vocal, enfin libéré de vous.")
    async def leave(self, ctx):
        """Fait quitter Greg du salon vocal."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 *Greg s’en va... Enfin un instant de répit loin de votre cacophonie barbare.*")
        else:
            await ctx.send("❌ *Ah, quelle ironie… Vous exigez mon départ alors que je ne suis même pas là ! Je vois que l’imbécilité règne en maître ici...*")

    @commands.command(name="restart", help="Redémarre Greg. Ne me tentez pas trop...")
    async def restart(self, ctx):
        """Redémarre Greg le Consanguin."""
        await ctx.send("🔁 *Greg... Greg meurt... pour mieux revenir hanter vos canaux vocaux...*")
        await ctx.bot.close()  # Ferme le bot proprement
        os.execv(sys.executable, ['python'] + sys.argv)  # Relance le script

    async def auto_disconnect(self, ctx):
        """Quitte le vocal après 5 min d’inactivité."""
        await asyncio.sleep(300)
        if ctx.voice_client and not ctx.voice_client.is_playing():
            await ctx.voice_client.disconnect()
            await ctx.send("👋 *Greg se retire, faute d’un public digne de son art. Peut-être trouverez-vous un autre esclave pour vous divertir...*")

def setup(bot):
    bot.add_cog(Voice(bot))
