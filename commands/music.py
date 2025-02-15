import discord
from discord.ext import commands
import yt_dlp
import os

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

        # Récupérer le chemin des cookies depuis Railway
        cookies_path = os.getenv("YOUTUBE_COOKIES_PATH", "youtube.com_cookies.txt")

        # Vérifier si le fichier de cookies existe
        if not os.path.exists(cookies_path):
            await ctx.send("❌ Erreur : Le fichier de cookies est introuvable. Vérifie qu'il est bien ajouté.")
            return

        # Télécharger l'audio avec yt-dlp et les cookies YouTube
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'song.mp3',
            'cookies': cookies_path,  # Utiliser les cookies exportés
            'noplaylist': True,  # Évite les playlists
            'quiet': False  # Active les logs pour voir si les cookies sont bien lus
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Lire l'audio dans le vocal
            ctx.voice_client.play(discord.FFmpegPCMAudio("song.mp3"))

            await ctx.send("🎶 Voilà… J'espère que tu vas aimer, sombre idiot.")

        except Exception as e:
            await ctx.send(f"❌ Erreur en téléchargeant la musique : {e}")

def setup(bot):
    bot.add_cog(Music(bot))
