import logging
import os
import threading
import time
import socket
import discord
from discord.ext import commands
from playlist_manager import PlaylistManager
import config
import json
import subprocess
import requests

# ---------------------------------------------------------------------------
# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("greg.log", encoding="utf-8")
    ],
)
logger = logging.getLogger(__name__)
logger.info("=== DÉMARRAGE GREG LE CONSANGUIN ===")

# ---------------------------------------------------------------------------
# PlaylistManager multi-serveur
playlist_managers = {}  # {guild_id: PlaylistManager}
RESTART_MARKER = ".greg_restart.json"

def get_pm(guild_id):
    guild_id = str(guild_id)
    if guild_id not in playlist_managers:
        playlist_managers[guild_id] = PlaylistManager(guild_id)
        logger.debug("Nouvelle instance PlaylistManager pour guild %s", guild_id)
    return playlist_managers[guild_id]

async def run_post_restart_selftest(bot):
    """Si un marker de restart existe, exécute un auto-diagnostic et poste un rapport dans le salon d'origine."""
    try:
        marker_path = os.path.join(os.path.dirname(__file__), RESTART_MARKER)
        if not os.path.exists(marker_path):
            return

        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)

        guild_id = int(marker.get("guild_id"))
        channel_id = int(marker.get("channel_id"))
        requested_by = int(marker.get("requested_by", 0))

        # === Tests ===
        results = []

        # 1) COGS
        expected_cogs = ["Music", "Voice", "General", "EasterEggs", "Spook"]
        for name in expected_cogs:
            ok = bot.get_cog(name) is not None
            results.append(("Cog:"+name, ok, "" if ok else "non chargé"))

        # 2) Slash commands présents
        try:
            cmds = await bot.tree.fetch_commands()
            names = {c.name for c in cmds}
        except Exception as e:
            names = set()
            results.append(("Slash:fetch_commands", False, str(e)))
        expected_cmds = [
            "play", "pause", "resume", "skip", "stop", "playlist", "current",
            "ping", "greg", "web", "help", "restart",
            "roll", "coin", "tarot", "curse", "praise", "shame", "skullrain", "gregquote", "spook_enable",
            "spook_settings", "spook_status"
        ]
        for name in expected_cmds:
            ok = name in names
            results.append((f"Slash:/{name}", ok, "" if ok else "absent"))

        # 3) FFmpeg dispo
        try:
            music_cog = bot.get_cog("Music")
            ff = music_cog.detect_ffmpeg() if music_cog else "ffmpeg"
            cp = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=3)
            ok = (cp.returncode == 0)
            results.append(("FFmpeg", ok, "" if ok else cp.stderr[:200]))
        except Exception as e:
            results.append(("FFmpeg", False, str(e)))

        # 4) Overlay HTTP (si non désactivé)
        try:
            if not os.getenv("DISABLE_WEB", "0") == "1":
                r = requests.get("http://127.0.0.1:3000/", timeout=2)
                ok = r.status_code < 500
                results.append(("Overlay:HTTP 127.0.0.1:3000", ok, f"HTTP {r.status_code}"))
            else:
                results.append(("Overlay:désactivé", True, "DISABLE_WEB=1"))
        except Exception as e:
            results.append(("Overlay:HTTP 127.0.0.1:3000", False, str(e)))

        # 5) SocketIO émissible (test d'emit)
        try:
            from __main__ import socketio
            if socketio:
                # Pas de client pour écouter, mais vérifie qu'aucune exception n'est levée à l'emit
                socketio.emit("selftest_ping", {"ok": True, "t": time.time()})
                results.append(("SocketIO:emit", True, "emit ok"))
            else:
                results.append(("SocketIO:instance", False, "socketio=None"))
        except Exception as e:
            results.append(("SocketIO:emit", False, str(e)))

        # --- Compose message ---
        ok_all = all(ok for (_, ok, _) in results)
        color = 0x2ECC71 if ok_all else 0xE74C3C
        lines = []
        for name, ok, extra in results:
            emoji = "✅" if ok else "❌"
            if extra:
                lines.append(f"{emoji} **{name}** — {extra}")
            else:
                lines.append(f"{emoji} **{name}**")

        embed = discord.Embed(
            title=("Self-test au redémarrage — OK" if ok_all else "Self-test au redémarrage — PROBLÈMES"),
            description="\n".join(lines),
            color=color
        )
        if requested_by:
            embed.set_footer(text=f"Demandé par <@{requested_by}>")

        # Poste dans le salon d'origine
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                channel = None
        if channel:
            await channel.send(embed=embed)

        # Nettoie le marker
        try:
            os.remove(marker_path)
        except Exception:
            pass

    except Exception as e:
        print(f"[SELFTEST] Erreur selftest post-restart: {e}")

# ---------------------------------------------------------------------------
# Discord Bot class
class GregBot(commands.Bot):
    def __init__(self, **kwargs):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents, **kwargs)

    async def setup_hook(self):
        # Charger tous les Cogs
        logger.debug("Chargement des Cogs…")
        for filename in os.listdir("./commands"):
            if filename.endswith(".py") and filename != "__init__.py":
                extension = f"commands.{filename[:-3]}"
                try:
                    await self.load_extension(extension)
                    logger.info("✅ Cog chargé : %s", extension)
                except Exception as e:
                    logger.error("❌ Erreur chargement %s : %s", extension, e)

        # Sync slash commands
        await self.tree.sync()
        logger.info("Slash commands sync DONE !")

    async def on_ready(self):
        logger.info("====== EVENT on_ready() ======")
        logger.info("Utilisateur bot : %s", self.user)

        # Liste des serveurs (robuste)
        try:
            guild_names = [g.name for g in self.guilds]
            logger.info("Serveurs : %s", guild_names)
        except Exception as e:
            logger.warning("Impossible de lister les guilds: %s", e)

        # Slash commands (robuste)
        try:
            cmds = await self.tree.fetch_commands()
            logger.info("Slash commands globales : %s", [cmd.name for cmd in cmds])
        except Exception as e:
            logger.warning("fetch_commands a échoué: %s", e)

        # Injection emit_fn (utilise la variable globale socketio du main)
        socketio_ref = None
        try:
            from __main__ import socketio as _socketio  # récupère l'instance créée dans main
            socketio_ref = _socketio
        except Exception:
            socketio_ref = None

        try:
            music_cog = self.get_cog("Music")
            voice_cog = self.get_cog("Voice")
            general_cog = self.get_cog("General")
            eggs_cog = self.get_cog("EasterEggs")
            spook_cog = self.get_cog("Spook")

            def _emit(event, data):
                """Wrapper pour sécuriser l'emit Socket.IO et logger en cas d'erreur."""
                if not socketio_ref:
                    return
                try:
                    socketio_ref.emit(event, data)
                except Exception as e:
                    logger.error("socketio.emit failed: %s", e)

            if socketio_ref and music_cog:
                music_cog.emit_fn = _emit
                logger.info("emit_fn branché sur Music")
            if socketio_ref and voice_cog:
                voice_cog.emit_fn = _emit
                logger.info("emit_fn branché sur Voice")
            if socketio_ref and general_cog:
                general_cog.emit_fn = _emit
                logger.info("emit_fn branché sur General")
            if socketio_ref and eggs_cog:
                eggs_cog.emit_fn = _emit
                logger.info("emit_fn branché sur EasterEggs")
            if socketio_ref and spook_cog:
                eggs_cog.emit_fn = _emit
                logger.info("emit_fn branch sur Spook")
        except Exception as e:
            logger.error("Impossible de connecter emit_fn: %s", e)

        # Auto self-test post-redémarrage (optionnel, si défini dans main.py)
        try:
            import asyncio
            from __main__ import run_post_restart_selftest
            asyncio.create_task(run_post_restart_selftest(self))
            logger.info("Self-test post-redémarrage déclenché.")
        except Exception as e:
            logger.debug("Self-test non lancé (optionnel): %s", e)

# ---------------------------------------------------------------------------
# Flask + SocketIO (overlay web)
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"
app = None
socketio = None

if not DISABLE_WEB:
    try:
        from connect import create_web_app
        app, socketio = create_web_app(get_pm)
        app.bot = None  # attach later
    except ImportError:
        logger.warning("Overlay désactivé : module 'connect' introuvable")
        DISABLE_WEB = True

def run_web():
    if socketio and app:
        logger.debug("Lancement du serveur Flask/SocketIO…")
        socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)

def wait_for_web():
    for i in range(30):  # 30 tentatives
        try:
            s = socket.create_connection(("localhost", 3000), 1)
            s.close()
            logger.debug("Serveur web prêt après %s tentatives.", i + 1)
            return
        except Exception:
            time.sleep(1)
    logger.critical("Serveur web jamais prêt !")
    raise SystemExit("[FATAL] Serveur web jamais prêt !")

# ---------------------------------------------------------------------------
# Main
if __name__ == "__main__":
    bot = GregBot()

    if not DISABLE_WEB:
        app.bot = bot
        threading.Thread(target=run_web, daemon=True).start()
        wait_for_web()

    bot.run(config.DISCORD_TOKEN)
