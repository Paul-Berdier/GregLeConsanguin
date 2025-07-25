# commands/voice.py

import discord
from discord.ext import commands
from discord import app_commands
import sys
import os
import asyncio

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="join", description="Fait rejoindre Greg dans votre salon vocal misérable.")
    async def join(self, interaction: discord.Interaction):
        """Slash command pour rejoindre le vocal."""
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ *Par tous les Saints ! Vous osez me convoquer alors que vous n’êtes même pas en vocal ? Quelle audace !*")

        channel = interaction.user.voice.channel

        try:
            if interaction.guild.voice_client is None:
                await channel.connect(timeout=10)
                await interaction.response.send_message(
                    f"👑 *Greg le Consanguin daigne honorer **{channel.name}** de sa présence...* Que ce lieu miteux soit à la hauteur de mon noble mépris.")
            else:
                await interaction.guild.voice_client.move_to(channel)
                await interaction.response.send_message(
                    f"👑 *Majesté, Greg est à vos pieds et change de crasseux taudis pour **{channel.name}**. Que le destin me vienne en aide...*")
        except asyncio.TimeoutError:
            await interaction.response.send_message("⏱️ *Majesté... Greg a tenté de se connecter, mais le Royaume du Vocal est en grève. Misère...*")
        except Exception as e:
            await interaction.response.send_message(f"❌ *Un obstacle infernal m'empêche de rejoindre le vocal, Ô Majesté...* `{e}`")

    @app_commands.command(name="leave", description="Fait quitter Greg du vocal, enfin libéré de vous.")
    async def leave(self, interaction: discord.Interaction):
        """Slash command pour quitter le vocal."""
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            await interaction.response.send_message("👋 *Greg s’en va... Enfin un instant de répit loin de votre cacophonie barbare.*")
        else:
            await interaction.response.send_message("❌ *Ah, quelle ironie… Vous exigez mon départ alors que je ne suis même pas là ! Je vois que l’imbécilité règne en maître ici...*")

    @app_commands.command(name="restart", description="Redémarre Greg le Consanguin.")
    async def restart(self, interaction: discord.Interaction):
        """Slash command pour redémarrer le bot."""
        await interaction.response.send_message("🔁 *Greg... Greg meurt... pour mieux revenir hanter vos canaux vocaux...*")
        await self.bot.close()
        os.execv(sys.executable, ['python'] + sys.argv)

    async def auto_disconnect(self, ctx):
        """Méthode appelée en interne pour quitter après 5 minutes d'inactivité."""
        await asyncio.sleep(300)
        if ctx.voice_client and not ctx.voice_client.is_playing():
            await ctx.voice_client.disconnect()
            await ctx.send("👋 *Greg se retire, faute d’un public digne de son art. Peut-être trouverez-vous un autre esclave pour vous divertir...*")

async def setup(bot):
    await bot.add_cog(Voice(bot))
    print("✅ Cog 'Voice' chargé avec slash commands.")
