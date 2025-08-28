# commands/spotify_account.py
import discord
from discord.ext import commands
from discord import app_commands

from utils import spotify_auth

def _guild_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.guild is None:
            raise app_commands.CheckFailure("guild_only")
        return True
    return app_commands.check(predicate)

class SpotifyAccount(commands.Cog):
    """Active/désactive l'usage Spotify pour un utilisateur (allowlist locale)."""

    def __init__(self, bot):
        self.bot = bot

    @_guild_only()
    @app_commands.command(
        name="set_spotify_account",
        description="Active Spotify pour vous (lecture via YouTube, métadonnées Spotify)."
    )
    async def set_spotify_account(self, interaction: discord.Interaction, note: str | None = None):
        """
        Pas d'OAuth ici : on place simplement l'utilisateur en allowlist locale.
        (Le son est lu via YouTube en se basant sur les titres/ artistes Spotify.)
        """
        uid = interaction.user.id
        spotify_auth.allow(uid, note)
        await interaction.response.send_message(
            "✅ Spotify activé pour vous. "
            "Quand vous donnerez une URL Spotify (track/album/playlist), Greg jouera l’équivalent via YouTube.",
            ephemeral=True
        )

    @_guild_only()
    @app_commands.command(
        name="unset_spotify_account",
        description="Désactive Spotify pour vous."
    )
    async def unset_spotify_account(self, interaction: discord.Interaction):
        uid = interaction.user.id
        spotify_auth.disallow(uid)
        await interaction.response.send_message("🛑 Spotify désactivé pour vous.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SpotifyAccount(bot))
