import discord
from discord.ext import commands
import yt_dlp
import ffmpeg
import os

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def play(self, ctx, url):
        """Télécharge et joue une musique YouTube avec des cookies."""

        if not ctx.voice_client:
            await ctx.send("Je dois être dans un salon vocal ! Utilise `!join` d'abord.")
            return

        await ctx.send("🎵 Pff… Je vais chercher ta musique.")

        # Récupérer le chemin des cookies YouTube
        cookies_path = os.getenv("YOUTUBE_COOKIES_PATH", "/app/youtube.com_cookies.txt")

        # Vérifier si le fichier existe
        if not os.path.exists(cookies_path):
            await ctx.send(f"❌ Erreur : Le fichier de cookies YouTube est introuvable à `{cookies_path}`.")
            return

        # Options yt-dlp avec cookies
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'song.mp3',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'cookiefile': cookies_path,  # ✅ Utilisation correcte des cookies
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

            await ctx.send("🎶 Voilà… J'espère que tu vas aimer.")

        except Exception as e:
            await ctx.send(f"❌ Erreur en téléchargeant la musique : {e}")

def setup(bot):
    bot.add_cog(Music(bot))
