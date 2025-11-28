# commands/music.py
from __future__ import annotations

import os
import shutil
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from api.services.player_service import PlayerService
from utils.priority_rules import PER_USER_CAP  # feedback quota

def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))

class Music(commands.Cog):
    """Cog FIN: délègue au PlayerService (priorités appliquées partout)."""
    def __init__(self, bot: commands.Bot, service: Optional[PlayerService] = None, emit_fn=None):
        self.bot = bot
        self.emit_fn = emit_fn
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

    # --------- util: détecter ffmpeg pour le selftest de main.py ----------
    def detect_ffmpeg(self) -> str:
        """
        Utilisé par main.py/post_restart_selftest().
        Cherche dans ENV (FFMPEG, FFMPEG_BIN, FF) puis dans PATH.
        """
        for key in ("FFMPEG", "FFMPEG_BIN", "FF"):
            v = os.getenv(key)
            if v:
                p = shutil.which(v) or v
                return p
        return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe") or "ffmpeg"

    # ----------------- SLASH COMMANDS -----------------

    @app_commands.describe(
        query_or_url="Recherche (titre/artiste) ou URL YouTube/playlist/mix",
    )
    @app_commands.command(name="play", description="Joue un son (YouTube). Gère aussi playlist/mix.")
    async def play(self, interaction: discord.Interaction, query_or_url: str):
        await interaction.response.defer()

        # Prépare l'item : si recherche → autocomplete, sinon URL direct
        if _is_url(query_or_url):
            item = {"url": query_or_url}
        else:
            try:
                from api.services.search import autocomplete
                res = autocomplete(query_or_url, limit=1)
                if not res:
                    return await interaction.followup.send("❌ Rien trouvé.")
                top = res[0]
                item = {
                    "url": top["url"],
                    "title": top.get("title"),
                    "duration": top.get("duration"),
                    "thumb": top.get("thumbnail"),
                }
            except Exception:
                # fallback minimal si le module de search n'est pas dispo
                item = {"url": query_or_url}

        out = await self.svc.play_for_user(interaction.guild_id, interaction.user.id, item)
        if not out.get("ok"):
            code = out.get("error") or "ERROR"
            msg = {
                "GUILD_NOT_FOUND": "❌ Guilde introuvable.",
                "USER_NOT_IN_VOICE": "❌ Tu dois être en vocal.",
                "VOICE_CONNECT_FAILED": "❌ Connexion vocale impossible.",
            }.get(code, f"❌ Échec: {code}")
            # si quota, ajoute le cap
            if "Quota" in msg:
                msg += f" (cap={PER_USER_CAP})"
            return await interaction.followup.send(msg)

        await interaction.followup.send("🎵 Ajouté (et connexion si besoin).")

    @app_commands.command(name="skip", description="Passe au morceau suivant (priorité requise).")
    async def skip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.svc.skip(interaction.guild_id, requester_id=interaction.user.id)
            await interaction.followup.send("⏭️ Skip.")
        except PermissionError:
            await interaction.followup.send("⛔ Tu n’as pas assez de priorité pour skipper ce morceau.", ephemeral=True)

    @app_commands.command(name="stop", description="Vide la playlist et stoppe la lecture (priorité requise).")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.svc.stop(interaction.guild_id, requester_id=interaction.user.id)
            await interaction.followup.send("⏹️ Stop.")
        except PermissionError:
            await interaction.followup.send("⛔ Tu n’as pas assez de priorité pour stopper.", ephemeral=True)

    @app_commands.command(name="pause", description="Met la musique en pause (priorité requise).")
    async def pause(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            ok = await self.svc.pause(interaction.guild_id, requester_id=interaction.user.id)
            await interaction.followup.send("⏸️ Pause." if ok else "❌ Rien à mettre en pause.")
        except PermissionError:
            await interaction.followup.send("⛔ Tu n’as pas assez de priorité pour mettre en pause.", ephemeral=True)

    @app_commands.command(name="resume", description="Reprend la musique (priorité requise).")
    async def resume(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            ok = await self.svc.resume(interaction.guild_id, requester_id=interaction.user.id)
            await interaction.followup.send("▶️ Resume." if ok else "❌ Rien à reprendre.")
        except PermissionError:
            await interaction.followup.send("⛔ Tu n’as pas assez de priorité pour reprendre.", ephemeral=True)

    @app_commands.command(name="remove", description="Supprime un item de la file (index 1-based, priorité requise).")
    @app_commands.describe(index="Index dans /playlist (1, 2, 3…)")
    async def remove(self, interaction: discord.Interaction, index: int):
        await interaction.response.defer(ephemeral=True)
        if index <= 0:
            return await interaction.followup.send("❌ Index invalide.")
        try:
            ok = self.svc.remove_at(interaction.guild_id, interaction.user.id, index - 1)
            await interaction.followup.send("🗑️ Supprimé." if ok else "❌ Échec de suppression (index hors limites).")
        except PermissionError:
            await interaction.followup.send("⛔ Priorité insuffisante pour supprimer cet item.")

    @app_commands.command(name="move", description="Déplace un item (src→dst, 1-based, priorité requise).")
    @app_commands.describe(src="Index source", dst="Nouvelle position")
    async def move(self, interaction: discord.Interaction, src: int, dst: int):
        await interaction.response.defer(ephemeral=True)
        if src <= 0 or dst <= 0:
            return await interaction.followup.send("❌ Index invalides.")
        try:
            ok = self.svc.move(interaction.guild_id, interaction.user.id, src - 1, dst - 1)
            await interaction.followup.send("🔀 Déplacé." if ok else "❌ Échec du déplacement (index hors limites).")
        except PermissionError:
            await interaction.followup.send("⛔ Priorité insuffisante / barrière de priorité.")

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
        # si en lecture → on tente de relancer pour appliquer l'afilter (protégé par priorité)
        g = interaction.guild
        vc = g.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            try:
                await self.svc.skip(interaction.guild_id, requester_id=interaction.user.id)
            except PermissionError:
                # Pas grave si pas la priorité, le mode est quand même mémorisé
                pass
        await interaction.followup.send(f"🎚️ Mode musique: **{'ON' if on else 'OFF'}**", ephemeral=True)


async def setup(bot):
    # Instancie/branche le service si besoin
    svc = getattr(bot, "player_service", None) or PlayerService(bot)
    bot.player_service = svc
    # Expose au web app (REST) si présent
    if getattr(bot, "web_app", None) and not getattr(bot.web_app, "player_service", None):
        bot.web_app.player_service = svc
    await bot.add_cog(Music(bot, service=svc))
