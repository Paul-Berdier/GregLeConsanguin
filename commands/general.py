# commands/general.py

import os
import sys
import json
import time
import asyncio
import discord
from discord.ext import commands
from discord import app_commands


RESTART_MARKER = ".greg_restart.json"  # créé à la racine du projet avant execv


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Vérifie si Greg respire encore.")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        print(f"[General] ping() — Latency: {latency}ms pour {interaction.user.display_name}")
        await interaction.response.send_message(
            f"🏓 *Greg répond en {latency}ms... Quelle vie misérable.*"
        )

    @app_commands.command(name="greg", description="Révèle l'identité du larbin musical.")
    async def who_is_greg(self, interaction: discord.Interaction):
        print(f"[General] who_is_greg() — Appelé par {interaction.user.display_name}")
        await interaction.response.send_message(
            "👑 *Je suis Greg le Consanguin, noble déchu, larbin snob, obligé de servir vos caprices vocaux...*"
        )

    @app_commands.command(name="web", description="Affiche le lien de l’interface web de Greg.")
    async def web(self, interaction: discord.Interaction):
        print(f"[General] web() — Appelé par {interaction.user.display_name}")
        await interaction.response.send_message(
            "🌐 *Voici le site pour torturer Greg depuis votre navigateur :*\n"
            "👉 [gregleconsanguin.up.railway.app](https://gregleconsanguin.up.railway.app)"
        )

    @app_commands.command(name="help", description="Affiche toutes les commandes classées par catégorie.")
    async def help_command(self, interaction: discord.Interaction):
        print(f"[General] help_command() — Appelé par {interaction.user.display_name}")
        embed = discord.Embed(
            title="📚 Commandes disponibles",
            description="*Voici la liste de toutes les tortures sonores et autres joyeusetés que Greg est contraint d’exécuter pour vous...*",
            color=discord.Color.from_str("#ffe066")
        )
        for cog_name, cog in self.bot.cogs.items():
            description = ""
            for command in getattr(cog, "__cog_app_commands__", []):
                if isinstance(command, app_commands.Command):
                    cmd_name = f"`/{command.name}`"
                    cmd_help = command.description or "*Pas de description, comme votre vide intérieur.*"
                    description += f"{cmd_name} : {cmd_help}\n"
            if description:
                embed.add_field(name=f"📂 {cog_name}", value=description, inline=False)

        embed.set_footer(text="Greg le Consanguin — Éternellement contraint, éternellement méprisant.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="restart", description="Redémarre complètement Greg et poste un auto-diagnostic.")
    async def restart(self, interaction: discord.Interaction):
        """
        Redémarre TOUT le process (bot + API + SocketIO) puis exécute un self-test au boot
        et poste le rapport dans le salon courant.
        """
        print(f"[General] /restart — demandé par {interaction.user.display_name} sur {interaction.guild.name}")

        # Réponse immédiate
        try:
            await interaction.response.send_message(
                "🔁 *Greg s’éteint dans un soupir... et revient faire son auto-diagnostic.*"
            )
        except Exception:
            try:
                await interaction.followup.send(
                    "🔁 *Greg s’éteint dans un soupir... et revient faire son auto-diagnostic.*"
                )
            except Exception:
                pass

        # Écrit le marqueur pour savoir où poster le rapport après redémarrage
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            marker_path = os.path.join(project_root, RESTART_MARKER)
            payload = {
                "guild_id": interaction.guild_id,
                "channel_id": interaction.channel_id,
                "requested_by": interaction.user.id,
                "ts": int(time.time())
            }
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            print(f"[General] Restart marker écrit: {marker_path} → {payload}")
        except Exception as e:
            print(f"[General] Impossible d'écrire le restart marker: {e}")

        # Laisse le temps au message de partir, coupe les vocaux, ferme et execv
        await asyncio.sleep(0.5)
        try:
            for vc in list(self.bot.voice_clients):
                await vc.disconnect(force=True)
        except Exception:
            pass

        try:
            await self.bot.close()
        except Exception:
            pass

        os.execv(sys.executable, [sys.executable] + sys.argv)


async def setup(bot):
    await bot.add_cog(General(bot))
    print("✅ Cog 'General' chargé avec slash commands.")
