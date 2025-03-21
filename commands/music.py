import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio
import ffmpeg

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # File d'attente des musiques
        self.is_playing = False
        self.current_song = None  # Musique actuellement en lecture
        self.ffmpeg_path = self.detect_ffmpeg()  # Détecte automatiquement ffmpeg

    def detect_ffmpeg(self):
        """Détecte ffmpeg et retourne son chemin."""
        FFMPEG_PATHS = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "ffmpeg"]
        for path in FFMPEG_PATHS:
            if os.path.exists(path) and os.access(path, os.X_OK):  # Vérifie si exécutable
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé, Railway est en PLS.")
        return "ffmpeg"  # Tente par défaut

    @commands.command()
    async def play(self, ctx, url):
        """Ajoute une musique à la playlist et joue si inactif."""
        if ctx.voice_client is None:
            await ctx.invoke(ctx.bot.get_cog("Voice").join)  # Fait rejoindre le vocal automatiquement

        await ctx.send(f"🎵 Tss… Encore une requête ridicule. **{url}** ajouté à la playlist.")
        self.queue.append(url)
        if not self.is_playing:
            await self.play_next(ctx)

    async def play_next(self, ctx):
        """Joue la musique suivante dans la playlist."""
        if len(self.queue) == 0:
            self.is_playing = False
            await ctx.send("📭 Plus rien dans la playlist. Greg va dormir.")
            return

        self.is_playing = True
        url = self.queue.pop(0)

        # Télécharger la musique
        song_info = await self.download_audio(url)
        if song_info is None:
            await ctx.send("❌ Même ça, t'es pas foutu de me donner un lien correct. J'essaie la suivante...")
            await self.play_next(ctx)  # Essaye la suivante si erreur
            return

        filename, title, duration = song_info
        self.current_song = title

        try:
            ctx.voice_client.play(
                discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),  # Utilise le chemin détecté
                after=lambda e: self.bot.loop.create_task(self.play_next(ctx))
            )
            await ctx.send(f"🎶 Bon... **{title}** (`{duration}`), tiens, t'es content ?")
        except Exception as e:
            await ctx.send(f"❌ Bordel, ça bug encore ? {e}")

    async def download_audio(self, url):
        """Télécharge et convertit la musique en mp3."""
        os.makedirs("downloads", exist_ok=True)  # Crée le dossier si absent

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': self.ffmpeg_path,  # 🔥 Force l'utilisation de ffmpeg
            'cookiefile': "youtube.com_cookies.txt",
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'quiet': False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Musique inconnue')
                duration = info.get('duration', '??:??')
                filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")
            return filename, title, duration
        except Exception as e:
            print(f"Erreur lors du téléchargement : {e}")
            return None

    @commands.command()
    async def skip(self, ctx):
        """Passe à la musique suivante."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭ Ça me gonfle. Greg passe à la suivante.")
        else:
            await ctx.send("❌ T'écoutes quoi, là ? Y'a rien à zapper !")

    @commands.command()
    async def stop(self, ctx):
        """Stoppe la musique et vide la playlist."""
        self.queue.clear()
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.send("⏹ Marre de vos goûts éclatés, Greg coupe tout.")

    @commands.command()
    async def playlist(self, ctx):
        """Affiche la file d'attente."""
        if len(self.queue) == 0:
            await ctx.send("📭 C'est le désert ici. Vous avez que ça à foutre de me déranger ?")
            return

        queue_list = "\n".join([f"**{i+1}.** {url}" for i, url in enumerate(self.queue)])
        await ctx.send(f"🎶 **Playlist actuelle :**\n{queue_list}")

    @commands.command()
    async def pause(self, ctx):
        """Met en pause la musique."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸ J'fais une pause. Vous méritez pas cette musique.")
        else:
            await ctx.send("❌ C'est déjà silencieux, imbécile.")

    @commands.command()
    async def resume(self, ctx):
        """Reprend la musique."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶ Allez, ça reprend. Faites genre vous avez du goût.")
        else:
            await ctx.send("❌ Rien n'est en pause, abruti.")

    @commands.command()
    async def current(self, ctx):
        """Affiche la musique actuellement jouée."""
        if self.current_song:
            await ctx.send(f"🎧 Bon, pour les incultes : **{self.current_song}**.")
        else:
            await ctx.send("❌ Rien en cours. Comme votre vie.")

def setup(bot):
    bot.add_cog(Music(bot))
