# commands/music.py

import discord
from discord.ext import commands
from extractors import get_extractor, get_search_module
import yt_dlp
import os
import asyncio
import json

PLAYLIST_FILE = "playlist.json"

def load_playlist():
    if not os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "w") as f:
            json.dump([], f)
    with open(PLAYLIST_FILE, "r") as f:
        return json.load(f)

def save_playlist(playlist):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(playlist, f)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []  # File d'attente des musiques
        self.is_playing = False
        self.current_song = None
        self.search_results = {}  # Stockage des résultats de recherche
        self.ffmpeg_path = self.detect_ffmpeg()  # Détecte automatiquement ffmpeg

    def detect_ffmpeg(self):
        """Détecte ffmpeg et retourne son chemin."""
        FFMPEG_PATHS = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "ffmpeg"]
        for path in FFMPEG_PATHS:
            if os.path.exists(path) and os.access(path, os.X_OK):
                print(f"🔥 FFmpeg détecté : {path}")
                return path
        print("❌ Aucun ffmpeg trouvé, Railway est en PLS.")
        return "ffmpeg"

    def sanitize_url(self, url: str) -> str:
        """Nettoie l’URL YouTube pour virer les listes et autres fragments inutiles."""
        from urllib.parse import urlparse, parse_qs, urlencode

        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if 'v' not in query:
            return url  # Rien à nettoyer

        clean_query = {'v': query['v'][0]}  # On garde uniquement l'ID de la vidéo
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(clean_query)}"
        return clean_url

    async def ask_play_mode(self, ctx, url):
        await ctx.send(
            "**📦 Dois-je souffrir en le téléchargeant ou simplement le vomir dans vos oreilles ?**\n"
            "**1.** Télécharger puis jouer\n"
            "**2.** Lecture directe (stream)\n"
            "*Votre choix, Ô Plaie royale...*"
        )

        def check(m):
            return m.author == ctx.author and m.content in ["1", "2"]

        try:
            response = await self.bot.wait_for("message", check=check, timeout=30)
            if response.content == "1":
                await self.add_to_queue(ctx, url)
            else:
                extractor = get_extractor(url)
                if not extractor or not hasattr(extractor, "stream"):
                    return await ctx.send("❌ *Greg ne sait pas vomir ce son en streaming...*")

                source, title = await extractor.stream(url, self.ffmpeg_path)

                if ctx.voice_client.is_playing():
                    ctx.voice_client.stop()

                ctx.voice_client.play(source,
                                      after=lambda e: print(f"▶️ Terminé : {e}" if e else f"🎶 Lecture finie : {title}")
                                      )
                self.current_song = title
                await ctx.send(f"▶️ *Votre infâme sélection est lancée en streaming :* **{title}**")
        except asyncio.TimeoutError:
            await ctx.send("⏳ *Trop lent... Greg ira se pendre avec un câble Jack 3.5mm...*")

    @commands.command()
    async def play(self, ctx, *, query_or_url):
        """
        Joue une URL ou une recherche YouTube, en mode téléchargement ou streaming.
        """
        if ctx.voice_client is None:
            await ctx.invoke(self.bot.get_command("join"))

        await ctx.send("🎵 *Ugh... Encore une de vos requêtes, Majesté ? Que souhaitez-vous cette fois ?...*")

        if "http://" in query_or_url or "https://" in query_or_url:
            await self.ask_play_mode(ctx, query_or_url)
            return

        # Sinon, recherche sur Soundcloud automatiquement
        extractor = get_search_module("soundcloud")
        results = extractor.search(query_or_url)

        if not results:
            await ctx.send("❌ *Rien, Majesté. Même Soundcloud a fui votre exigence...*")
            return

        self.search_results[ctx.author.id] = results

        msg = "**🔍 Résultats Soundcloud :**\n"
        for i, item in enumerate(results[:3], 1):
            msg += f"**{i}.** [{item['title']}]({item['url']})\n"

        msg += "\n*Majesté, un chiffre s'il vous plaît...*"
        await ctx.send(msg)

        def check_choice(m):
            return m.author == ctx.author and m.content.isdigit() and 1 <= int(m.content) <= len(results[:3])

        try:
            reply = await self.bot.wait_for("message", check=check_choice, timeout=30)
            choice = int(reply.content) - 1
            selected_url = results[choice]["url"]
            await self.ask_play_mode(ctx, selected_url)
        except asyncio.TimeoutError:
            await ctx.send("⏳ *Trop lent, Majesté... Greg retourne se lamenter dans l’ombre...*")

    async def search_source(self, ctx, query, source: str):
        """
        Recherche sur un extracteur (youtube, soundcloud, etc.) via son module.
        """
        extractor = get_search_module(source)
        if extractor is None or not hasattr(extractor, "search"):
            await ctx.send(
                f"❌ *Majesté, je ne sais pas comment chercher sur « {source} ». Que la honte s'abatte sur moi...*")
            return

        try:
            results = extractor.search(query)
        except Exception as e:
            await ctx.send(f"❌ *L'Oracle {source} s’est tu :* {e}")
            return

        if not results:
            await ctx.send(f"❌ *Pas de réponse, Majesté. Ce royaume musical est vide comme votre foi en moi...*")
            return

        self.search_results[ctx.author.id] = results

        message = f"**🔍 Résultats depuis {source.capitalize()} :**\n"
        for i, item in enumerate(results[:3], 1):
            message += f"**{i}.** [{item['title']}]({item['url']})\n"

        message += "\n*Choisissez votre poison sonore avec un chiffre, Ô Excellence...*"
        await ctx.send(message)

        def check(m):
            return m.author == ctx.author and m.content.isdigit() and 1 <= int(m.content) <= len(results[:3])

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=30.0)
            choice = int(msg.content) - 1
            url = results[choice]['url']
            await self.add_to_queue(ctx, url)
        except asyncio.TimeoutError:
            await ctx.send("⏳ *Trop lent... Greg retourne gémir en silence...*")

    async def add_to_queue(self, ctx, url):
        await ctx.send(f"🎵 **{url}** ajouté à la playlist. *Puisse-t-elle ne pas être une insulte au bon goût, Majesté...*")
        self.queue.append(url)
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", url)
            except Exception:
                title = url

        playlist = load_playlist()
        playlist.append({"title": title, "url": url})
        save_playlist(playlist)

        if not self.is_playing:
            await self.play_next(ctx)

    async def play_next(self, ctx):
        if len(self.queue) == 0:
            self.is_playing = False
            await ctx.send("📍 *Oh, plus rien à jouer ? Dois-je considérer cela comme une grâce divine ?*")
            return

        self.is_playing = True
        url = self.queue.pop(0)

        try:
            # Utilise un extracteur personnalisé en fonction de l'URL
            extractor = get_extractor(url)
            if extractor is None:
                await ctx.send("❌ *Greg ne connaît pas cette source musicale... Quelle ignominie !*")
                await self.play_next(ctx)
                return

            filename, title, duration = await extractor.download(
                url,
                ffmpeg_path=self.ffmpeg_path,
                cookies_file="youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None
            )

            self.current_song = title
            await asyncio.sleep(2)

            ctx.voice_client.play(
                discord.FFmpegPCMAudio(filename, executable=self.ffmpeg_path),
                after=lambda e: self.bot.loop.create_task(self.play_next(ctx))
            )

            await ctx.send(
                f"🎶 *Majesté, voici votre requête, aussi abominable soit-elle :* **{title}** (`{duration}` sec).")
            self.bot.loop.create_task(self.bot.get_cog("Voice").auto_disconnect(ctx))

        except Exception as e:
            await ctx.send(f"❌ *Greg s’étrangle sur cette bouillie sonore :* {e}")
            await self.play_next(ctx)

    @commands.command()
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()

            # Supprime la première entrée dans la playlist JSON
            playlist = load_playlist()
            if playlist:
                playlist.pop(0)
                save_playlist(playlist)

            await ctx.send("⏭ *Qu’on en finisse ! Que je puisse un jour me reposer !*")
        else:
            await ctx.send("❌ *Voyons, Votre Altesse... Il n'y a rien à zapper...*")

    @commands.command()
    async def stop(self, ctx):
        self.queue.clear()
        save_playlist([])
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            playlist = load_playlist()
            if playlist:
                playlist.pop(0)
                save_playlist(playlist)

        await ctx.send("⏹ *Majesté a tranché ! L’infamie musicale cesse ici.*")

    @commands.command()
    async def playlist(self, ctx):
        if len(self.queue) == 0:
            await ctx.send("📋 *Majesté... c'est le vide sidéral ici. Une playlist digne de votre grandeur, j’imagine...*")
            return

        queue_list = "\n".join([f"**{i+1}.** {url}" for i, url in enumerate(self.queue)])
        await ctx.send(f"🎶 *Oh, quelle misérable sélection musicale ! Mais voici votre liste, Ô Souverain :*\n{queue_list}")

    @commands.command()
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸ *Ah ! Enfin une pause dans ce supplice sonore. Votre Majesté a peut-être retrouvé la raison.*")
        else:
            await ctx.send("❌ *Pardonnez mon insolence, Ô Éminence, mais il n’y a rien à interrompre... Peut-être que votre majestueux cerveau a oublié ce détail ?*")

    @commands.command()
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶ *Oh non… Il faut que je reprenne cette immondice ? Très bien, Majesté, votre humble serviteur s'exécute...*")
        else:
            await ctx.send("❌ *Que voulez-vous que je reprenne, Majesté ? Le son du silence ? Ah, quelle sagesse... si seulement c'était volontaire de votre part.*")

    @commands.command()
    async def current(self, ctx):
        if self.current_song:
            await ctx.send(f"🎧 *Majesté, vos oreilles saignent peut-être, mais voici l’ignoble bruit qui souille ce canal :* **{self.current_song}**. *Profitez donc de cette... ‘expérience’.*")
        else:
            await ctx.send("❌ *Rien ne joue actuellement, Ô Suprême Créature... Un silence à la hauteur de votre magnificence.*")

def setup(bot):
    bot.add_cog(Music(bot))
