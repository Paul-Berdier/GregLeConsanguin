# commands/general.py

import os
import sys
import json
import time
import asyncio
import datetime as dt
import discord
from discord.ext import commands
from discord import app_commands

# --- deps pour auto-test cookies ---
from http.cookiejar import MozillaCookieJar

RESTART_MARKER = ".greg_restart.json"  # créé à la racine du projet avant execv
COOKIES_FILENAME = "youtube.com_cookies.txt"  # utilisé côté lecture YouTube si présent
MAX_COOKIE_SIZE = 1024 * 1024  # 1 Mo max (sécurité)


def _proj_path(*parts):
    # Enregistre/lit à partir du cwd (lancement du process), pour matcher les checks relatifs.
    return os.path.abspath(os.path.join(os.getcwd(), *parts))


def _is_netscape_cookie_text(s: str) -> bool:
    head = s[:4096]
    if "# Netscape HTTP Cookie File" in head:
        return True
    # Heuristique : des lignes tabulées avec au moins 6 tabulations (7 colonnes)
    return "\t" in head and any(head.count("\t") >= 6 for head in head.splitlines()[:5])


def _json_to_netscape(json_text: str) -> str:
    """
    Convertit divers formats JSON de cookies (extensions navigateur) vers Netscape.
    Attend un tableau de cookies. Ignore ce qui n'a pas name/value/domain.
    """
    try:
        data = json.loads(json_text)
    except Exception:
        return ""

    cookies = data
    # Certains exportent {"cookies":[...]}
    if isinstance(data, dict) and "cookies" in data and isinstance(data["cookies"], list):
        cookies = data["cookies"]

    if not isinstance(cookies, list):
        return ""

    def pick_exp(c):
        for key in ("expiry", "expirationDate", "expires", "expires_utc"):
            if key in c:
                try:
                    return int(float(c[key]))
                except Exception:
                    pass
        return 0  # session cookie

    lines = ["# Netscape HTTP Cookie File", "# Converted from JSON"]
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("key")
        value = c.get("value")
        domain = c.get("domain") or c.get("host")
        path = c.get("path", "/")
        if not (name and (value is not None) and domain):
            continue
        secure = bool(c.get("secure", False))
        host_only = bool(c.get("hostOnly", False))
        include_sub = "FALSE" if host_only else "TRUE"
        # canonicalise domaine (préfixe '.' si subdomains autorisés)
        if include_sub == "TRUE" and not domain.startswith("."):
            domain = "." + domain
        expires = pick_exp(c)
        lines.append("\t".join([
            domain,
            include_sub,
            path,
            "TRUE" if secure else "FALSE",
            str(int(expires)),
            str(name),
            str(value),
        ]))
    return "\n".join(lines) + "\n"


def _summarize_netscape(text: str):
    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    count = 0
    domains = set()
    has_consent = False
    for l in lines:
        parts = l.split("\t")
        if len(parts) < 7:
            continue
        count += 1
        domains.add(parts[0])
        if parts[5] == "CONSENT":
            has_consent = True
    return count, sorted(list(domains))[:6], has_consent

# ------------------------
# Helpers auto-test cookies
# ------------------------

def _http_probe_with_cookies(cookies_path: str):
    """
    Test HTTP simple vers une vidéo publique avec les cookies chargés.
    Retourne (ok: bool, detail: str)
    """
    try:
        import requests
    except Exception as e:
        return False, f"lib requests manquante: {e}"

    try:
        jar = MozillaCookieJar()
        jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
    except Exception as e:
        return False, f"cookies illisibles: {e}"

    try:
        s = requests.Session()
        s.cookies = jar
        # vidéo de test (yt-dlp): BaW_jenozKc
        r = s.get("https://www.youtube.com/watch?v=BaW_jenozKc",
                  timeout=5, allow_redirects=False, headers={"Accept-Language": "en-US,en;q=0.7"})
        # Si redirige vers consent.youtube.com -> consent non pris en compte
        loc = r.headers.get("Location", "") if r.is_redirect else ""
        if "consent.youtube.com" in loc.lower() or "consent" in loc.lower():
            return False, f"redir CONSENT ({r.status_code})"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"requête échouée: {e}"


def _ytdlp_probe_with_cookies(cookies_path: str):
    """
    Lance yt-dlp en dry-run sur une vidéo publique en utilisant cookiefile.
    Retourne (ok: bool, detail: str)
    """
    try:
        from yt_dlp import YoutubeDL
    except Exception as e:
        return False, f"yt-dlp manquant: {e}"

    opts = {
        "quiet": True,
        "skip_download": True,
        "cookiefile": cookies_path,
        "nocheckcertificate": True,
        "ignoreerrors": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            # vidéo de test (yt-dlp)
            info = ydl.extract_info("https://www.youtube.com/watch?v=BaW_jenozKc", download=False)
        if not info:
            return False, "aucune info extraite"
        # succès: on renvoie quelques champs
        title = info.get("title", "?")
        uploader = info.get("uploader") or info.get("channel") or "?"
        return True, f"ok — {title} / {uploader}"
    except Exception as e:
        return False, f"yt-dlp erreur: {e}"

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

    # =======================
    #  YouTube cookies utils
    # =======================

    @app_commands.command(
        name="yt_cookies_update",
        description="Met à jour les cookies YouTube (cookies.txt ou JSON) + auto-test."
    )
    @app_commands.describe(
        file="Fichier cookies (Netscape cookies.txt ou export JSON d'extension)."
    )
    async def yt_cookies_update(self, interaction: discord.Interaction, file: discord.Attachment):
        await interaction.response.defer(ephemeral=True)
        if not file:
            return await interaction.followup.send("❌ Aucun fichier fourni.")

        if file.size and file.size > MAX_COOKIE_SIZE:
            return await interaction.followup.send("❌ Fichier trop gros (max 1 Mo).")

        raw = await file.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return await interaction.followup.send("❌ Impossible de décoder le fichier en UTF-8.")

        # Convertir JSON -> Netscape si nécessaire
        if _is_netscape_cookie_text(text):
            netscape = text
        else:
            netscape = _json_to_netscape(text)
            if not netscape:
                return await interaction.followup.send(
                    "❌ Format inconnu. Fournis un **cookies.txt (Netscape)** ou un **JSON** d’extension navigateur."
                )

        # Petit résumé + contrôle
        count, domains, has_consent = _summarize_netscape(netscape)
        if count == 0:
            return await interaction.followup.send("❌ Aucune entrée cookie valide trouvée.")

        # Backup éventuel puis écriture
        target = _proj_path(COOKIES_FILENAME)
        try:
            if os.path.exists(target):
                ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                os.replace(target, target + f".bak.{ts}")
            with open(target, "w", encoding="utf-8") as f:
                f.write(netscape)
        except Exception as e:
            return await interaction.followup.send(f"❌ Écriture impossible: `{e}`")

        # === AUTO-TEST (hors event loop) ===
        loop = asyncio.get_running_loop()
        http_ok, http_detail = await loop.run_in_executor(None, _http_probe_with_cookies, target)
        ydl_ok, ydl_detail = await loop.run_in_executor(None, _ytdlp_probe_with_cookies, target)

        doms = ", ".join(domains) + (" …" if len(domains) >= 6 else "")
        consent_str = "✅ CONSENT présent" if has_consent else "⚠️ CONSENT manquant"

        # Compose embed rapport
        ok_all = http_ok and ydl_ok
        color = 0x2ECC71 if ok_all else 0xE74C3C
        lines = [
            f"Cookies: **{count}** entrées ; domaines: {doms}",
            f"{consent_str}",
            "",
            f"{'✅' if http_ok else '❌'} **HTTP probe** — {http_detail}",
            f"{'✅' if ydl_ok else '❌'} **yt-dlp probe** — {ydl_detail}",
            "",
            f"📁 Fichier: `{COOKIES_FILENAME}` (pris en compte par le player lors des accès YouTube)."
        ]
        embed = discord.Embed(
            title="YouTube cookies — Mise à jour & auto-test",
            description="\n".join(lines),
            color=color
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="yt_cookies_status",
        description="Vérifie l’état des cookies YouTube et lance un auto-test (HTTP + yt-dlp)."
    )
    async def yt_cookies_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target = _proj_path(COOKIES_FILENAME)
        if not os.path.exists(target):
            return await interaction.followup.send("🚫 Aucun cookies YouTube trouvé (`youtube.com_cookies.txt`).",
                                                   ephemeral=True)

        # Lire et résumer
        try:
            with open(target, "r", encoding="utf-8") as f:
                text = f.read()
            count, domains, has_consent = _summarize_netscape(text)
        except Exception as e:
            return await interaction.followup.send(f"❌ Lecture impossible: `{e}`", ephemeral=True)

        # Lancer les mêmes probes
        loop = asyncio.get_running_loop()
        http_ok, http_detail = await loop.run_in_executor(None, _http_probe_with_cookies, target)
        ydl_ok, ydl_detail = await loop.run_in_executor(None, _ytdlp_probe_with_cookies, target)

        mtime = dt.datetime.fromtimestamp(os.path.getmtime(target))
        age = dt.datetime.now() - mtime
        doms = ", ".join(domains) + (" …" if len(domains) >= 6 else "")
        consent_str = "✅ CONSENT présent" if has_consent else "⚠️ CONSENT manquant"

        ok_all = http_ok and ydl_ok
        color = 0x2ECC71 if ok_all else 0xE74C3C
        lines = [
            f"📄 `{COOKIES_FILENAME}` — {count} cookies ; domaines: {doms}",
            f"⏱️ Dernière maj: {mtime:%Y-%m-%d %H:%M:%S} ({age.days}j {age.seconds // 3600}h)",
            f"{consent_str}",
            "",
            f"{'✅' if http_ok else '❌'} **HTTP probe** — {http_detail}",
            f"{'✅' if ydl_ok else '❌'} **yt-dlp probe** — {ydl_detail}",
        ]
        embed = discord.Embed(
            title="YouTube cookies — Status & auto-test",
            description="\n".join(lines),
            color=color
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # =======================
    #  Redémarrage complet
    # =======================

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
