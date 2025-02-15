import discord
from discord.ext import commands
import yt_dlp

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def play(self, ctx, url):
        """Joue une musique YouTube en utilisant yt-dlp avec des cookies."""
        if not ctx.voice_client:
            await ctx.send("Je dois être dans un salon vocal, imbécile. Utilise `!join` d'abord.")
            return

        await ctx.send("🎵 Pff… Je vais chercher ta musique.")

        # Télécharger l'audio avec les cookies YouTube
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'song.mp3',
            'cookies': 'youtube.com_cookies.txt'  # Utiliser les cookies exportés
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Lire l'audio dans le vocal
            ctx.voice_client.play(discord.FFmpegPCMAudio("song.mp3"))

            await ctx.send("🎶 Voilà… J'espère que tu vas aimer, sombre idiot.")

        except Exception as e:
            await ctx.send(f"Erreur en téléchargeant la musique : {e}")

def setup(bot):
    bot.add_cog(Music(bot))
