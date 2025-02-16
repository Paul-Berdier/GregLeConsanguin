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
        """Télécharge et joue une musique YouTube."""
        if not ctx.voice_client:
            await ctx.send("Je dois être dans un salon vocal ! Utilise `!join` d'abord.")
            return

        await ctx.send("🎵 Pff… Je vais chercher ta musique.")

        # Options de yt-dlp pour télécharger l'audio
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'song.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

            if not os.path.exists(filename):
                await ctx.send("❌ Erreur : Fichier audio introuvable.")
                return

            # Convertir avec ffmpeg-python si nécessaire
            ffmpeg.input(filename).output("converted.mp3", format="mp3").run(overwrite_output=True)

            # Lire l'audio dans Discord
            ctx.voice_client.play(discord.FFmpegPCMAudio("converted.mp3"))

            await ctx.send("🎶 Voilà… J'espère que tu vas aimer.")

        except Exception as e:
            await ctx.send(f"❌ Erreur en téléchargeant la musique : {e}")

def setup(bot):
    bot.add_cog(Music(bot))
