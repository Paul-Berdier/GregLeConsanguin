import discord
from discord.ext import commands
import yt_dlp

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def play(self, ctx, url):
        """Joue une musique YouTube"""
        if not ctx.voice_client:
            await ctx.send("Tsss… Faut que je sois dans un vocal d’abord, abruti.")
            return

        await ctx.send("🎵 Pff… Je vais chercher ta musique.")

        # Télécharger l'audio
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'song.mp3',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Lire la musique
        ctx.voice_client.play(discord.FFmpegPCMAudio("song.mp3"))

        await ctx.send("🎶 Voilà… C’est pas trop dur pour toi d’écouter une mélodie ?")

def setup(bot):
    bot.add_cog(Music(bot))
