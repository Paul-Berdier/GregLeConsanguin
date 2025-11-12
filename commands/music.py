# commands/music.py
from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from api.services.player_service import PlayerService
from utils.priority_rules import PER_USER_CAP  # pour feedback

def _u(interaction: discord.Interaction):
    return getattr(interaction, "user", getattr(interaction, "author", None))

class Music(commands.Cog):
    """Cog FIN: délègue tout au PlayerService."""
    def __init__(self, bot: commands.Bot, service: Optional[PlayerService] = None, emit_fn=None):
        self.bot = bot
        self.emit_fn = emit_fn             # sera rempli par main.py (setup_emit_fn)
        self.svc: PlayerService = service or getattr(bot, "player_service", None) or PlayerService(bot)

        # expose service sur le bot si absent
        if not getattr(bot, "player_service", None):
            bot.player_service = self.svc

    async def cog_load(self):
        # si l’app web existe, expose aussi le service pour REST
        app = getattr(self.bot, "web_app", None)
        if app and not getattr(app, "player_service", None):
            app.player_service = self.svc

    @commands.Cog.listener()
    async def on_ready(self):
        # dès que main.py aura injecté emit_fn sur ce Cog, on le relaie au service
        if self.emit_fn and hasattr(self.svc, "set_emit_fn"):
            self.svc.set_emit_fn(self.emit_fn)

    # ----------------- SLASH COMMANDS -----------------

    @app_commands.describe(
        query_or_url="Recherche (titre/artiste) ou URL YouTube",
    )
    @app_commands.command(name="play", description="Joue un son (stream YouTube).")
    async def play(self, interaction: discord.Interaction, query_or_url: str):
        await interaction.response.defer()

        # connexion vocale si besoin
        member = interaction.user
        if not member or not member.voice or not member.voice.channel:
            return await interaction.followup.send("❌ Tu dois être en vocal.")
        ok = await self.svc.ensure_connected(interaction.guild, member.voice.channel)
        if not ok:
            return await interaction.followup.send("❌ Connexion vocale impossible.")

        # si URL, enfile direct; sinon, recherche rapide via api/services/search.py
        item = {"url": query_or_url} if query_or_url.startswith(("http://", "https://")) else None
        if not item:
            # recherche côté service/yt (ou via API search si tu préfères)
            from api.services.search import autocomplete
            res = autocomplete(query_or_url, limit=1)
            if not res:
                return await interaction.followup.send("❌ Rien trouvé.")
            top = res[0]
            item = {"url": top["url"], "title": top.get("title"), "duration": top.get("duration"), "thumb": top.get("thumbnail")}

        r = await self.svc.enqueue(interaction.guild_id, interaction.user.id, item)
        if not r.get("ok"):
            msg = r.get("error") or "échec d’ajout"
            if "Quota" in msg:
                msg += f" (cap={PER_USER_CAP})"
            return await interaction.followup.send(f"❌ {msg}")

        await interaction.followup.send(f"🎵 Ajouté: **{r['item']['title']}**")

        # si idle → jouer
        if not self.svc.is_playing.get(int(interaction.guild_id), False):
            await self.svc.play_next(interaction.guild)

    @app_commands.command(name="skip", description="Passe au morceau suivant.")
    async def skip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.svc.skip(interaction.guild_id)
        await interaction.followup.send("⏭️ Skip.")

    @app_commands.command(name="stop", description="Vide la playlist et stoppe la lecture.")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.svc.stop(interaction.guild_id)
        await interaction.followup.send("⏹️ Stop.")

    @app_commands.command(name="pause", description="Met la musique en pause.")
    async def pause(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ok = await self.svc.pause(interaction.guild_id)
        await interaction.followup.send("⏸️ Pause." if ok else "❌ Rien à mettre en pause.")

    @app_commands.command(name="resume", description="Reprend la musique.")
    async def resume(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ok = await self.svc.resume(interaction.guild_id)
        await interaction.followup.send("▶️ Resume." if ok else "❌ Rien à reprendre.")

    @app_commands.command(name="playlist", description="Affiche la file d’attente.")
    async def playlist(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = self.svc._overlay_payload(int(interaction.guild_id))
        q = data.get("queue") or []
        cur = data.get("current")
        if not q and not cur:
            return await interaction.followup.send("📋 Playlist vide.")
        lines = []
        if cur:
            lines.append(f"🎧 **En cours :** [{cur.get('title','?')}]({cur.get('url','')})")
        if q:
            lines += [f"**{i+1}.** [{it.get('title','?')}]({it.get('url','')})" for i, it in enumerate(q)]
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="current", description="Montre le morceau en cours.")
    async def current(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cur = self.svc.now_playing.get(int(interaction.guild_id))
        if not cur:
            return await interaction.followup.send("❌ Rien en cours.")
        await interaction.followup.send(f"🎧 **[{cur['title']}]({cur['url']})**")

    @app_commands.describe(mode="on/off (vide pour basculer)")
    @app_commands.command(name="repeat", description="Active/désactive le repeat ALL.")
    async def repeat(self, interaction: discord.Interaction, mode: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        state = await self.svc.toggle_repeat(interaction.guild_id, mode)
        await interaction.followup.send(f"🔁 Repeat: **{'ON' if state else 'OFF'}**", ephemeral=True)

    @app_commands.describe(mode="on/off (vide pour basculer)")
    @app_commands.command(name="musicmode", description="Rendu audio 'musique' (EQ/limiter).")
    async def musicmode(self, interaction: discord.Interaction, mode: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        on = await self.svc.set_music_mode(interaction.guild_id, mode)
        # si en lecture → restart courant pour appliquer l'afilter
        g = interaction.guild
        vc = g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            await self.svc.skip(interaction.guild_id)  # simple: on relance la piste suivante
        await interaction.followup.send(f"🎚️ Mode musique: **{'ON' if on else 'OFF'}**", ephemeral=True)


async def setup(bot):
    # Instancie/branche le service si besoin
    svc = getattr(bot, "player_service", None) or PlayerService(bot)
    bot.player_service = svc
    # Expose au web app (REST) si présent
    if getattr(bot, "web_app", None) and not getattr(bot.web_app, "player_service", None):
        bot.web_app.player_service = svc
    await bot.add_cog(Music(bot, service=svc))
