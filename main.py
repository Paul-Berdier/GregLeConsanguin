import logging
import os
import threading
import time
import socket
import json
import subprocess
import requests
import discord
from discord.ext import commands

from utils.playlist_manager import PlaylistManager
import config
from __main__ import socketio as _socketio
from typing import Any


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
    """Auto-diagnostic après restart s’il y a un marker."""
    try:
        marker_path = os.path.join(os.path.dirname(__file__), RESTART_MARKER)
        if not os.path.exists(marker_path):
            return

        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)

        guild_id = int(marker.get("guild_id"))
        channel_id = int(marker.get("channel_id"))
        requested_by = int(marker.get("requested_by", 0))

        results = []

        # 1) COGS
        expected_cogs = [
            "Music", "Voice", "General",
            "EasterEggs", "Spook", "SpotifyAccount", "CookieGuardian"
        ]
        for name in expected_cogs:
            ok = bot.get_cog(name) is not None
            results.append(("Cog:"+name, ok, "" if ok else "non chargé"))

        # 2) Slash commands
        try:
            cmds = await bot.tree.fetch_commands()
            names = {c.name for c in cmds}
        except Exception as e:
            names = set()
            results.append(("Slash:fetch_commands", False, str(e)))
        expected_cmds = [
            # music/voice/general habituels…
            "play","pause","resume","skip","stop","playlist","current",
            "ping","greg","web","help","restart",
            # easter eggs
            "roll","coin","tarot","curse","praise","shame","skullrain","gregquote",
            # spook
            "spook_enable","spook_settings","spook_status",
            "spook_test","spook_files","spook_reload","spook_scare",
            # spotify account
            "set_spotify_account","unset_spotify_account",
            # guardian yt cookies
            "yt_cookies_update","yt_cookies_check",
        ]
        for name in expected_cmds:
            ok = name in names
            results.append((f"Slash:/{name}", ok, "" if ok else "absent"))

        # 3) FFmpeg
        try:
            music_cog = bot.get_cog("Music")
            ff = music_cog.detect_ffmpeg() if music_cog and hasattr(music_cog, "detect_ffmpeg") else "ffmpeg"
            cp = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=3)
            ok = (cp.returncode == 0)
            results.append(("FFmpeg", ok, "" if ok else (cp.stderr or cp.stdout)[:200]))
        except Exception as e:
            results.append(("FFmpeg", False, str(e)))

        # 4) Overlay HTTP
        try:
            if not os.getenv("DISABLE_WEB", "0") == "1":
                r = requests.get("http://127.0.0.1:3000/", timeout=2)
                ok = r.status_code < 500
                results.append(("Overlay:HTTP 127.0.0.1:3000", ok, f"HTTP {r.status_code}"))
            else:
                results.append(("Overlay:désactivé", True, "DISABLE_WEB=1"))
        except Exception as e:
            results.append(("Overlay:HTTP 127.0.0.1:3000", False, str(e)))

        # 5) SocketIO emit
        try:
            from __main__ import socketio
            if socketio:
                socketio.emit("selftest_ping", {"ok": True, "t": time.time()})
                results.append(("SocketIO:emit", True, "emit ok"))
            else:
                results.append(("SocketIO:instance", False, "socketio=None"))
        except Exception as e:
            results.append(("SocketIO:emit", False, str(e)))

        ok_all = all(ok for (_, ok, _) in results)
        color = 0x2ECC71 if ok_all else 0xE74C3C
        lines = []
        for name, ok, extra in results:
            emoji = "✅" if ok else "❌"
            lines.append(f"{emoji} **{name}**" + (f" — {extra}" if extra else ""))

        embed = discord.Embed(
            title=("Self-test au redémarrage — OK" if ok_all else "Self-test au redémarrage — PROBLÈMES"),
            description="\n".join(lines),
            color=color
        )
        if requested_by:
            embed.set_footer(text=f"Demandé par <@{requested_by}>")

        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        await channel.send(embed=embed)

        try: os.remove(marker_path)
        except Exception: pass

    except Exception as e:
        print(f"[SELFTEST] Erreur selftest post-restart: {e}")

# ---------------------------------------------------------------------------
# Discord Bot
class GregBot(commands.Bot):
    def __init__(self, **kwargs):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents, **kwargs)

    async def _load_ext_dir(self, dir_name: str):
        if not os.path.isdir(f"./{dir_name}"):
            return
        for filename in os.listdir(f"./{dir_name}"):
            if filename.endswith(".py") and filename != "__init__.py":
                extension = f"{dir_name}.{filename[:-3]}"
                try:
                    await self.load_extension(extension)
                    logging.getLogger(__name__).info("✅ Cog chargé : %s", extension)
                except Exception as e:
                    logging.getLogger(__name__).error("❌ Erreur chargement %s : %s", extension, e)

    async def setup_hook(self):
        # Charge d'abord /commands puis /cogs (pour cookie_guardian, etc.)
        for dir_name in ("commands", "cogs"):
            await self._load_ext_dir(dir_name)
        await self.tree.sync()
        logging.getLogger(__name__).info("Slash commands sync DONE !")

    async def on_ready(self):
        logger.info("====== EVENT on_ready() ======")
        logger.info("Utilisateur bot : %s", self.user)
        try:
            cmds = await self.tree.fetch_commands()
            logger.info("Slash commands globales : %s", [cmd.name for cmd in cmds])
        except Exception as e:
            logger.warning("fetch_commands a échoué: %s", e)

        # Injecte emit_fn (utilise l’instance socketio globale)
        try:
            from __main__ import socketio as _socketio
            def _emit(event: str, data: Any, *, guild_id: int | str | None = None, user_id: int | str | None = None):
                if not _socketio:
                    return
                try:
                    sent = False
                    if guild_id is not None:
                        _socketio.emit(event, data, room=f"guild:{int(guild_id)}")
                        sent = True
                    if user_id is not None:
                        _socketio.emit(event, data, room=f"user:{int(user_id)}")
                        sent = True
                    if not sent:
                        _socketio.emit(event, data)  # fallback broadcast
                except Exception as e:
                    logger.error("socketio.emit failed: %s", e)

            for cog_name in ("Music","Voice","General","EasterEggs","Spook"):
                cog = self.get_cog(cog_name)
                if cog and not getattr(cog, "emit_fn", None):
                    cog.emit_fn = _emit
                    logger.info("emit_fn branché sur %s", cog_name)
        except Exception as e:
            logger.error("Impossible de connecter emit_fn: %s", e)

        # Self-test post restart (optionnel)
        try:
            import asyncio
            asyncio.create_task(run_post_restart_selftest(self))
        except Exception as e:
            logger.debug("Self-test non lancé: %s", e)

# ---------------------------------------------------------------------------
# Flask + SocketIO (overlay web)
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"
app = None
socketio = None

if not DISABLE_WEB:
    try:
        from connect import create_web_app
        app, socketio = create_web_app(get_pm)
        app.bot = None  # attaché plus tard
        logger.info("Socket.IO async_mode (effectif): %s", getattr(socketio, "async_mode", "unknown"))
    except ImportError:
        logger.warning("Overlay désactivé : module 'connect' introuvable")
        DISABLE_WEB = True

def run_web():
    if socketio and app:
        mode = getattr(socketio, "async_mode", "threading")
        logger.debug("Lancement web… (mode=%s)", mode)
        if mode == "eventlet":
            socketio.run(app, host="0.0.0.0", port=3000)
        else:
            socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)

def wait_for_web():
    for i in range(30):
        try:
            s = socket.create_connection(("127.0.0.1", 3000), 1)
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
        bot.web_app = app
        threading.Thread(target=run_web, daemon=True).start()
        wait_for_web()

    bot.run(config.DISCORD_TOKEN)
