# commands/general.py

import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    class General(commands.Cog):
        def __init__(self, bot):
            self.bot = bot

        @commands.command(name="help", help="Affiche toutes les commandes classées par catégorie.")
        async def help_command(self, ctx):
            embed = discord.Embed(
                title="📚 Commandes disponibles",
                description="*Voici la liste de toutes les tortures sonores et autres joyeusetés que Greg est contraint d’exécuter pour vous...*",
                color=discord.Color.gold()
            )

            # Organisation par COG (nom de classe dans chaque fichier)
            for cog_name, cog in self.bot.cogs.items():
                description = ""
                for command in cog.get_commands():
                    if command.hidden:
                        continue
                    cmd_name = f"`!{command.name}`"
                    cmd_help = command.help or "*Pas de description, comme votre vide intérieur.*"
                    description += f"{cmd_name} : {cmd_help}\n"

                if description:
                    embed.add_field(name=f"📂 {cog_name}", value=description, inline=False)

            await ctx.send(embed=embed)

    @commands.command(name="ping", help="Vérifie si Greg respire encore.")
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 *Greg répond en {latency}ms... Quelle vie misérable.*")

    @commands.command(name="greg", help="Révèle l'identité du larbin musical.")
    async def who_is_greg(self, ctx):
        await ctx.send("👑 *Je suis Greg le Consanguin, noble déchu, larbin snob, obligé de servir vos caprices vocaux...*")

def setup(bot):
    bot.add_cog(General(bot))
