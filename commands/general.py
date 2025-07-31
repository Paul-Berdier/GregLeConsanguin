# commands/general.py

import discord
from discord.ext import commands
from discord import app_commands

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

        # Ajoute un champ par Cog avec description des commandes
        for cog_name, cog in self.bot.cogs.items():
            description = ""
            for command in getattr(cog, "__cog_app_commands__", []):
                if isinstance(command, app_commands.Command):
                    cmd_name = f"`/{command.name}`"
                    cmd_help = command.description or "*Pas de description, comme votre vide intérieur.*"
                    description += f"{cmd_name} : {cmd_help}\n"
            if description:
                embed.add_field(
                    name=f"📂 {cog_name}",
                    value=description,
                    inline=False
                )

        embed.set_footer(text="Greg le Consanguin — Éternellement contraint, éternellement méprisant.")
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))
    print("✅ Cog 'General' chargé avec slash commands.")
