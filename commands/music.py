import discord
from discord.ext import commands
import yt_dlp
import ffmpeg
import discord

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

        # Récupérer le bon chemin des cookies
        cookies_path = os.getenv("YOUTUBE_COOKIES_PATH", "/app/youtube.com_cookies.txt")

        # Vérifier si le fichier existe
        if not os.path.exists(cookies_path):
            await ctx.send("❌ Erreur : Le fichier de cookies YouTube est introuvable.")
            return

        # Télécharger l'audio avec yt-dlp et les cookies
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'song.mp3',
            'cookies': cookies_path,  # Utilisation des cookies YouTube
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'quiet': False  # Debugging
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

            # Convertir avec ffmpeg-python si nécessaire
            ffmpeg.input(filename).output("converted.mp3", format="mp3").run(overwrite_output=True)

            # Lire l'audio dans le vocal
            ctx.voice_client.play(discord.FFmpegPCMAudio("converted.mp3"))

            await ctx.send("🎶 Voilà… J'espère que tu vas aimer, sombre idiot.")

        except Exception as e:
            await ctx.send(f"❌ Erreur en téléchargeant la musique : {e}")

def setup(bot):
    bot.add_cog(Music(bot))
