"""Cog General — ping, help, priority config, cookies, restart."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
import time
from http.cookiejar import MozillaCookieJar
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from greg_shared.config import settings
from greg_shared.constants import greg_says
from greg_shared.priority import (
    get_overrides, get_weights, list_keys,
    reset_role_weight, set_key_weight, set_per_user_cap, set_role_weight,
)

OWNER_ID = settings.owner_id_int
COOKIES_FILENAME = "youtube.com_cookies.txt"
MAX_COOKIE_SIZE = 1024 * 1024


def _owner_only():
    async def predicate(inter: discord.Interaction):
        if OWNER_ID and inter.user.id == OWNER_ID:
            return True
        try:
            app = await inter.client.application_info()
            if inter.user.id == app.owner.id:
                return True
        except Exception:
            pass
        raise app_commands.CheckFailure("owner_only")
    return app_commands.check(predicate)


def _is_netscape(s: str) -> bool:
    head = s[:4096]
    if "# Netscape HTTP Cookie File" in head:
        return True
    return any(line.count("\t") >= 6 for line in head.splitlines()[:5])


def _json_to_netscape(text: str) -> str:
    try:
        data = json.loads(text)
    except Exception:
        return ""
    cookies = data if isinstance(data, list) else data.get("cookies", [])
    if not isinstance(cookies, list):
        return ""
    lines = ["# Netscape HTTP Cookie File", "# Converted from JSON"]
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("key")
        value = c.get("value")
        domain = c.get("domain") or c.get("host")
        if not (name and value is not None and domain):
            continue
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        host_only = c.get("hostOnly", False)
        sub = "FALSE" if host_only else "TRUE"
        if sub == "TRUE" and not domain.startswith("."):
            domain = "." + domain
        exp = 0
        for k in ("expiry", "expirationDate", "expires"):
            if k in c:
                try:
                    exp = int(float(c[k]))
                    break
                except Exception:
                    pass
        lines.append("\t".join([domain, sub, path, secure, str(exp), str(name), str(value)]))
    return "\n".join(lines) + "\n"


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Priority commands ───

    priority = app_commands.Group(name="priority", description="Gérer la hiérarchie des priorités (owner only)")

    @priority.command(name="weights", description="Lister les poids effectifs.")
    @_owner_only()
    async def list_weights(self, inter: discord.Interaction):
        weights = get_weights()
        lines = [f"{k}: {v}" for k, v in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))]
        over = get_overrides()
        await inter.response.send_message(
            "### Poids effectifs\n```\n" + "\n".join(lines) + "\n```\n"
            f"Overrides: {json.dumps(over, ensure_ascii=False)}",
            ephemeral=True,
        )

    @priority.command(name="setrole", description="Définir le poids d'un rôle.")
    @_owner_only()
    @app_commands.describe(role="Rôle à pondérer", weight="Poids (plus haut = plus prioritaire)")
    async def setrole(self, inter: discord.Interaction, role: discord.Role, weight: app_commands.Range[int, -9999, 9999]):
        set_role_weight(role.name, weight)
        await inter.response.send_message(f"✅ Poids de **{role.name}** fixé à **{weight}**.", ephemeral=True)

    @priority.command(name="resetrole", description="Reset l'override d'un rôle.")
    @_owner_only()
    @app_commands.describe(role="Rôle à reset")
    async def resetrole(self, inter: discord.Interaction, role: discord.Role):
        reset_role_weight(role.name)
        await inter.response.send_message(f"♻️ Override de **{role.name}** supprimé.", ephemeral=True)

    @priority.command(name="setkey", description="Définir un poids spécial.")
    @_owner_only()
    @app_commands.describe(key="Clé spéciale", weight="Poids")
    @app_commands.choices(key=[app_commands.Choice(name=k, value=k) for k in list_keys()])
    async def setkey(self, inter: discord.Interaction, key: app_commands.Choice[str], weight: app_commands.Range[int, -9999, 9999]):
        set_key_weight(key.value, weight)
        await inter.response.send_message(f"✅ Poids **{key.value}** fixé à **{weight}**.", ephemeral=True)

    @priority.command(name="setcap", description="Quota de pistes par utilisateur.")
    @_owner_only()
    @app_commands.describe(cap="Nombre max en file par utilisateur")
    async def setcap(self, inter: discord.Interaction, cap: app_commands.Range[int, 0, 50]):
        set_per_user_cap(cap)
        await inter.response.send_message(f"✅ Cap fixé à **{cap}**.", ephemeral=True)

    # ─── General commands ───

    @app_commands.command(name="ping", description="Vérifie si Greg respire encore.")
    async def ping(self, inter: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await inter.response.send_message(greg_says("ping", latency=latency, user=inter.user.mention))

    @app_commands.command(name="greg", description="Révèle l'identité du larbin musical.")
    async def who_is_greg(self, inter: discord.Interaction):
        await inter.response.send_message(greg_says("who_is_greg", user=inter.user.mention))

    @app_commands.command(name="web", description="Affiche le lien de l'interface web.")
    async def web(self, inter: discord.Interaction):
        url = os.getenv("WEB_URL", "https://gregleconsanguin.up.railway.app")
        await inter.response.send_message(greg_says("web_link", user=inter.user.mention, url=url))

    @app_commands.command(name="help", description="Affiche toutes les commandes.")
    async def help_command(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="📚 Commandes disponibles",
            description=greg_says("help_header"),
            color=discord.Color.from_str("#c9a84c"),
        )
        for cog_name, cog in self.bot.cogs.items():
            desc = ""
            for cmd in getattr(cog, "__cog_app_commands__", []):
                if isinstance(cmd, app_commands.Command):
                    desc += f"`/{cmd.name}` : {cmd.description or '…'}\n"
            if desc:
                embed.add_field(name=f"📂 {cog_name}", value=desc, inline=False)
        embed.set_footer(text=greg_says("help_footer"))
        await inter.response.send_message(embed=embed)

    # ─── Cookie management ───

    @app_commands.command(name="yt_cookies_update", description="Met à jour les cookies YouTube + auto-test.")
    @app_commands.describe(file="Fichier cookies (Netscape ou JSON)")
    async def yt_cookies_update(self, inter: discord.Interaction, file: discord.Attachment):
        await inter.response.defer(ephemeral=True)
        if not file or (file.size and file.size > MAX_COOKIE_SIZE):
            return await inter.followup.send("❌ Fichier manquant ou trop gros (max 1 Mo).", ephemeral=True)

        raw = await file.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return await inter.followup.send("❌ Impossible de décoder le fichier.", ephemeral=True)

        netscape = text if _is_netscape(text) else _json_to_netscape(text)
        if not netscape:
            return await inter.followup.send("❌ Format inconnu. Fournis un cookies.txt ou JSON.", ephemeral=True)

        target = os.path.abspath(COOKIES_FILENAME)
        try:
            if os.path.exists(target):
                ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                os.replace(target, target + f".bak.{ts}")
            with open(target, "w", encoding="utf-8") as f:
                f.write(netscape)
        except Exception as e:
            return await inter.followup.send(f"❌ Écriture impossible: `{e}`", ephemeral=True)

        # Count cookies
        count = sum(1 for l in netscape.splitlines() if l and not l.startswith("#") and l.count("\t") >= 6)
        color = 0x2ECC71 if count > 0 else 0xE74C3C
        embed = discord.Embed(title="YouTube cookies — Mise à jour", description=f"**{count}** cookies importés.", color=color)
        await inter.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="yt_cookies_check", description="Vérifie l'état des cookies YouTube.")
    async def yt_cookies_check(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        target = os.path.abspath(COOKIES_FILENAME)
        if not os.path.exists(target):
            return await inter.followup.send("🚫 Aucun cookies trouvé.", ephemeral=True)
        try:
            with open(target, "r", encoding="utf-8") as f:
                text = f.read()
            count = sum(1 for l in text.splitlines() if l and not l.startswith("#") and l.count("\t") >= 6)
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(target))
            age = dt.datetime.now() - mtime
            embed = discord.Embed(
                title="YouTube cookies — Status",
                description=f"📄 `{COOKIES_FILENAME}` — **{count}** cookies\n⏱️ Dernière maj: {mtime:%Y-%m-%d %H:%M} ({age.days}j)",
                color=0x2ECC71 if count > 5 else 0xE74C3C,
            )
            await inter.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await inter.followup.send(f"❌ Erreur: `{e}`", ephemeral=True)

    # ─── Restart ───

    @app_commands.command(name="restart", description="Redémarre Greg complètement.")
    @_owner_only()
    async def restart(self, inter: discord.Interaction):
        try:
            await inter.response.send_message("🔁 Greg s'éteint dans un soupir… et revient.")
        except Exception:
            pass
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
