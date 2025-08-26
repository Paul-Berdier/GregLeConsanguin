# commands/eastereggs.py
import os
import re
import asyncio
import random
import discord
from discord.ext import commands
from discord import app_commands

# --------- Contrôle d'accès "easter eggs" ----------
# Autorisés : administrateurs OU IDs listés dans EGG_USERS="123,456"
_EGG_ALLOW = {s.strip() for s in os.getenv("EGG_USERS", "").split(",") if s.strip().isdigit()}

def _is_allowed(member: discord.Member) -> bool:
    try:
        if member.guild_permissions.administrator:
            return True
    except Exception:
        pass
    return str(member.id) in _EGG_ALLOW

def _egg_only():
    async def predicate(interaction: discord.Interaction):
        m = interaction.user
        if isinstance(m, discord.Member) and _is_allowed(m):
            return True
        # échec silencieux (la commande reste discrète)
        raise app_commands.CheckFailure("forbidden")
    return app_commands.check(predicate)

def _guild_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.guild is None:
            raise app_commands.CheckFailure("guild_only")
        return True
    return app_commands.check(predicate)

# --------- Utilitaires ---------
def _clamp(n, lo, hi):
    return max(lo, min(hi, n))

def _parse_dice(expr: str):
    """
    Parse 'NdM(+/-)K' -> (N, M, K). Ex: '1d20+5', '4d6', 'd100-1'
    """
    expr = expr.strip().lower().replace(" ", "")
    m = re.fullmatch(r'(?:(\d*))d(\d+)([+-]\d+)?', expr)
    if not m:
        raise ValueError("format attendu: NdM(+/-)K (ex: 1d20+5)")
    n = int(m.group(1)) if m.group(1) else 1
    d = int(m.group(2))
    k = int(m.group(3)) if m.group(3) else 0
    n = _clamp(n, 1, 100)
    d = _clamp(d, 2, 1000)
    k = _clamp(k, -10000, 10000)
    return n, d, k

TAROT_CARDS = [
    ("The Fool", "Nouveaux départs, élan naïf.", "Imprudence, faux pas."),
    ("The Magician", "Volonté, astuce, focus.", "Manipulation, illusions."),
    ("The High Priestess", "Intuition, secrets.", "Silence, blocage intérieur."),
    ("The Lovers", "Choix, union.", "Dissonance, tentation."),
    ("The Hermit", "Retraite, sagesse.", "Isolement, entêtement."),
    ("Wheel of Fortune", "Cycle, tournant.", "Instabilité, fatalité."),
    ("Justice", "Équilibre, vérité.", "Partialité, dette."),
    ("Death", "Transformation, mue.", "Résistance au changement."),
    ("The Tower", "Révélation, choc.", "Ruinette, entêtement dangereux."),
    ("The Star", "Espoir, apaisement.", "Doute, foi fragile."),
    ("The Sun", "Clarté, vitalité.", "Arrogance, burn-out."),
    ("Judgement", "Appel, réveil.", "Auto-jugement, rumination."),
]

PRAISES = [
    "Ta présence élève ce bouge d’un demi-ton, ce qui n’est pas rien.",
    "Ton goût musical est presque supportable. Bravo.",
    "Si l'élégance était un bitrate, tu serais en FLAC.",
    "On m’oblige à le dire : tu gères.",
    "Tu fais mentir les statistiques. Dans le bon sens, pour une fois.",
]

QUIPS = [
    "Je ne suis pas grognon, je suis en **mode économie d’empathie**.",
    "On m’a invoqué pour des **goûts douteux**. Mission acceptée.",
    "Je suis comme un vin millésimé : acide, mais inévitable.",
    "Votre silence était une amélioration notable. Dommage.",
    "Qui a appuyé sur *lecture* ? Ah, c’est vous. Quelle audace.",
]

# Thèmes pour /curse (basés sur tes anecdotes, version ‘safe’)
CURSE_THEMES = [
    app_commands.Choice(name="somnambule", value="somnambule"),
    app_commands.Choice(name="coupure-edf", value="coupure"),
    app_commands.Choice(name="sur-les-genoux", value="genoux"),
    app_commands.Choice(name="mystérieux-invisible", value="mystere"),
    app_commands.Choice(name="niakoue", value="niakoue"),
]

def _curse_text(theme: str, target_mention: str) -> str:
    if theme == "somnambule":
        return (f"🩸 *Par l’esprit des nuits blanches,* {target_mention} — "
                "que ta pisse te mènent toujours vers les enceintes éteintes, et que la fumée ne soit plus que souvenir.")
    if theme == "coupure":
        return (f"⚡ *Par l’autorité parentale des disjoncteurs antiques,* {target_mention} — "
                "que ton courant vacille dès que la partie devient intéressante.")
    if theme == "genoux":
        return (f"🪑 *Par la légende des genoux confortable,* {target_mention} — "
                "qu’une rumeur persiste : tu joues si près du mentor qu’on entend sa sagesse résonner en arrière-plan.")
    if theme == "mystere":
        return (f"🕯️ *Par le voile des avatars sans visage,* {target_mention} — "
                "que tu tombe dans les escaliers avec ton fauteuil roulant, toi qu'on a jamais vu")
    if theme == "niakoué":
        return (f"🎮 *Par les dieux du teamfight,* {target_mention} — "
                "que ta main tremble au moment clutch, et que tu trouves quand même le bouton *mute* pour l’excuse parfaite.")
    # défaut (aléatoire doux)
    return (f"🔮 *Par le sel et la latence,* {target_mention} — "
            "que tes tops plays restent hors-cam et tes fails en 1080p.")

class EasterEggs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.emit_fn = None  # injecté par on_ready si dispo (overlay)

    # --- util overlay ---
    def _emit(self, event, data):
        if callable(getattr(self, "emit_fn", None)):
            try:
                self.emit_fn(event, data)
            except Exception:
                pass

    # ============== COMMANDES SECRÈTES (ADMIN/ALLOWLIST) ==============

    @app_commands.command(name="roll", description="Lance des dés façon JDR (ex: 1d20+5).")
    @_guild_only()
    @_egg_only()
    async def roll(self, interaction: discord.Interaction, expr: str):
        try:
            n, d, k = _parse_dice(expr)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        rolls = [random.randint(1, d) for _ in range(n)]
        total = sum(rolls) + k
        detail = " + ".join(map(str, rolls))
        if k:
            detail += f" {'+' if k>0 else ''}{k}"
        await interaction.response.send_message(f"🎲 **{expr}** → **{total}**  ({detail})")

    @app_commands.command(name="coin", description="Pile ou face, sans triche (promis).")
    @_guild_only()
    @_egg_only()
    async def coin(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await asyncio.sleep(0.5)
        side = random.choice(["Pile", "Face"])
        flair = "👑" if side == "Face" else "🪙"
        await interaction.followup.send(f"{flair} **{side}** !")

    @app_commands.command(name="tarot", description="Tire une carte de tarot (upright/reversed).")
    @_guild_only()
    @_egg_only()
    async def tarot(self, interaction: discord.Interaction):
        upright = random.choice([True, False])
        name, up, rev = random.choice(TAROT_CARDS)
        meaning = up if upright else rev
        arrow = "↑" if upright else "↓"
        color = discord.Color.from_str("#66d9e8") if upright else discord.Color.from_str("#e8590c")
        embed = discord.Embed(title=f"🃏 {name} {arrow}", description=meaning, color=color)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="curse", description="Jette une (fausse) malédiction taillée sur mesure.")
    @app_commands.describe(user="La victime consentante.", theme="Choisis un thème (facultatif).")
    @app_commands.choices(theme=CURSE_THEMES)
    @_guild_only()
    @_egg_only()
    async def curse(self, interaction: discord.Interaction, user: discord.Member,
                    theme: app_commands.Choice[str] = None):
        chosen = (theme.value if theme else random.choice([t.value for t in CURSE_THEMES]))
        text = _curse_text(chosen, user.mention)
        await interaction.response.send_message(
            text,
            allowed_mentions=discord.AllowedMentions(users=[user])
        )

    @app_commands.command(name="praise", description="Accorde un compliment rare (ne t’habitue pas).")
    @app_commands.describe(user="Chanceux du jour.")
    @_guild_only()
    @_egg_only()
    async def praise(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.send_message(
            f"✨ {user.mention} — {random.choice(PRAISES)}",
            allowed_mentions=discord.AllowedMentions(users=[user])
        )

    @app_commands.command(name="shame", description="La cloche retentit. 🔔")
    @app_commands.describe(user="Coupable présumé.")
    @_guild_only()
    @_egg_only()
    async def shame(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.send_message(
            f"🔔 **Shame!** {user.mention}", allowed_mentions=discord.AllowedMentions(users=[user])
        )
        for _ in range(2):
            await asyncio.sleep(1.2)
            await interaction.followup.send("🔔 **Shame!**", allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="skullrain", description="Déclenche une pluie de crânes (overlay si dispo).")
    @_guild_only()
    @_egg_only()
    async def skullrain(self, interaction: discord.Interaction):
        self._emit("fx_skullrain", {"intensity": random.randint(3, 8)})
        await interaction.response.send_message("💀 *Pluie de crânes invoquée.* (si l’overlay écoute)")

    @app_commands.command(name="gregquote", description="Une petite maxime méprisante de Greg.")
    @_guild_only()
    @_egg_only()
    async def gregquote(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"💬 {random.choice(QUIPS)}")

    # Gestion propre des erreurs de permission (silencieux pour les non-autorisés)
    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("⛔", ephemeral=True)
                else:
                    await interaction.followup.send("⛔", ephemeral=True)
            except Exception:
                pass

async def setup(bot):
    await bot.add_cog(EasterEggs(bot))
    print("✅ Cog 'EasterEggs' chargé (easter commands cachées).")
