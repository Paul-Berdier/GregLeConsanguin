import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # File d'attente des musiques
        self.is_playing = False
        self.current_song = None
        self.ffmpeg_path = self.detect_ffmpeg()  # Détecte automatiquement ffmpeg

    def detect_ffmpeg(self):
        """Détecte ffmpeg et retourne son chemin."""
        FFMPEG_PATHS = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "ffmpeg"]
        for path in FFMPEG_PATHS:
            if os.path.exists(path) and os.access(path, os.X_OK):
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé, Railway est en PLS.")
        return "ffmpeg"  # Tente par défaut

    @commands.command()
    async def play(self, ctx, *, query_or_url):
        """Cherche une vidéo YouTube par texte ou joue directement un lien."""
        if ctx.voice_client is None:
            await ctx.invoke(self.bot.get_command("join"))  # Fait rejoindre le vocal

        await ctx.send(
            f"🎵 *Ugh... Encore une de vos requêtes, Majesté ? Bien sûr... Que ne ferais-je pas pour vous...*")

        # Vérifie si c'est un lien YouTube
        if query_or_url.startswith(("http://", "https://")) and (
                "youtube.com/watch?v=" in query_or_url or "youtu.be/" in query_or_url):
            await self.add_to_queue(ctx, query_or_url)
        else:
            await self.search_youtube(ctx, query_or_url)

    async def search_youtube(self, ctx, query):
        """Recherche YouTube et ajoute directement la première vidéo trouvée."""
        ydl_opts = {
            'quiet': False,
            'format': 'bestaudio/best',
            'default_search': 'ytsearch1',  # Prend UNIQUEMENT la première vidéo
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'extract_flat': False,  # Désactive extract_flat pour récupérer les bonnes infos
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)

            if not info or 'entries' not in info or len(info['entries']) == 0:
                await ctx.send("❌ *Hélas, Majesté... je ne trouve rien. Peut-être votre goût musical est-il tout simplement introuvable...*")
                return

            video = info['entries'][0]  # Prend uniquement la première vidéo
            chosen_url = video['url']
            title = video['title']

            await ctx.send(f"🎵 *Majesté, voici votre requête :* [{title}]({chosen_url})")
            await self.add_to_queue(ctx, chosen_url, title)

        except Exception as e:
            await ctx.send(f"❌ *Ah... encore un imprévu... Comme la vie est cruelle envers un simple serf...* {e}")
            print(f"Erreur dans search_youtube: {e}")

    async def add_to_queue(self, ctx, url, title=None):
        """Ajoute une musique à la playlist et joue si inactif."""
        song_info = await self.download_audio(ctx, url)

        if song_info is None:
            await ctx.send("❌ *Impossible de télécharger ce caprice musical...*")
            return

        filename, title = song_info
        self.queue.append(filename)

        await ctx.send(f"🎵 **{title}** ajouté à la playlist. *Que cette abomination commence...*")


        if not self.is_playing:
            await self.play_next(ctx)

    async def play_next(self, ctx):
        """Joue la musique suivante dans la playlist."""
        if len(self.queue) == 0:
            self.is_playing = False
            await ctx.send("📭 *Oh, plus rien à jouer ? Dois-je considérer cela comme une grâce divine ?*")
            return

        self.is_playing = True
        url = self.queue.pop(0)

        song_info = await self.download_audio(ctx, url)
        if song_info is None:
            await ctx.send("❌ *Impossible de télécharger cela... Mon incompétence est sans limite, Majesté...*")
            await self.play_next(ctx)
            return

        filename, title, duration = song_info
        self.current_song = title

        await asyncio.sleep(2)  # Greg râle avant de jouer

        try:
            ctx.voice_client.play(
                discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),
                after=lambda e: self.bot.loop.create_task(self.play_next(ctx))
            )
            await ctx.send(f"🎶 *Majesté, voici votre requête, aussi abominable soit-elle :* **{title}** (`{duration}`).")
        except Exception as e:
            await ctx.send(f"❌ *Oh, quelle horreur... Encore un problème...* {e}")

    async def download_audio(self, ctx, url):
        """Télécharge et convertit la musique en mp3 avec contrôle de durée."""
        os.makedirs("downloads", exist_ok=True)  # Crée le dossier si absent


        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': self.ffmpeg_path,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'quiet': False,
            'cookiefile': "youtube.com_cookies.txt"
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)  # Ne télécharge pas encore, on vérifie d'abord
                title = info.get('title', 'Musique inconnue')
                duration = info.get('duration', 0)

                # Vérifie que la durée est raisonnable
                if duration > 1200:  # 20 minutes max
                    await ctx.send(f"⛔ *Combien de temps ?! Êtes-vous devenu fou, Ô Maître cruel ? (20 minutes max)*")
                    return None

                ydl.download([url])  # Maintenant, on télécharge

                # Génère le bon nom de fichier en .mp3
                filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

            return filename, title, duration

        except Exception as e:
            print(f"Erreur dans download_audio: {e}")
            await ctx.send(f"❌ *Majesté, impossible de récupérer ce titre... Encore une de vos idées de génie.*")
            return None

    @commands.command()
    async def skip(self, ctx):
        """Passe à la musique suivante."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭ *Qu’on en finisse ! Que je puisse un jour me reposer !*")
        else:
            await ctx.send("❌ *Voyons, Votre Altesse... Il n'y a rien à zapper...*")

    @commands.command()
    async def stop(self, ctx):
        """Stoppe la musique et vide la playlist."""
        self.queue.clear()
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.send("⏹ *Majesté a tranché ! L’infamie musicale cesse ici.*")

    @commands.command()
    async def playlist(self, ctx):
        """Affiche la file d'attente."""
        if len(self.queue) == 0:
            await ctx.send("📭 *Majesté... c'est le vide sidéral ici. Une playlist digne de votre grandeur, j’imagine...*")
            return

        queue_list = "\n".join([f"**{i+1}.** {url}" for i, url in enumerate(self.queue)])
        await ctx.send(f"🎶 *Oh, quelle misérable sélection musicale ! Mais voici votre liste, Ô Souverain :*\n{queue_list}")

    @commands.command()
    async def pause(self, ctx):
        """Met en pause la musique."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸ *Ah ! Enfin une pause dans ce supplice sonore. Votre Majesté a peut-être retrouvé la raison.*")
        else:
            await ctx.send("❌ *Pardonnez mon insolence, Ô Éminence, mais il n’y a rien à interrompre... Peut-être que votre majestueux cerveau a oublié ce détail ?*")

    @commands.command()
    async def resume(self, ctx):
        """Reprend la musique."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶ *Oh non… Il faut que je reprenne cette immondice ? Très bien, Majesté, votre humble serviteur s'exécute...*")
        else:
            await ctx.send("❌ *Que voulez-vous que je reprenne, Majesté ? Le son du silence ? Ah, quelle sagesse... si seulement c'était volontaire de votre part.*")

    @commands.command()
    async def current(self, ctx):
        """Affiche la musique actuellement jouée."""
        if self.current_song:
            await ctx.send(f"🎧 *Majesté, vos oreilles saignent peut-être, mais voici l’ignoble bruit qui souille ce canal :* **{self.current_song}**. *Profitez donc de cette... ‘expérience’.*")
        else:
            await ctx.send("❌ *Rien ne joue actuellement, Ô Suprême Créature... Un silence à la hauteur de votre magnificence.*")

def setup(bot):
    bot.add_cog(Music(bot))
