# main.py
import logging
import os
import threading
import time
import socket
import subprocess
import requests
import discord
from discord.ext import commands
from typing import Any

from utils.playlist_manager import PlaylistManager
import config

# -----------------------------------------------------------------------------
# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("greg.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
logger.info("=== DÉMARRAGE GREG LE CONSANGUIN ===")

# -----------------------------------------------------------------------------
# PlaylistManager multi-serveur
playlist_managers: dict[str, PlaylistManager] = {}  # {guild_id: PlaylistManager}
RESTART_MARKER = ".greg_restart.json"

def get_pm(guild_id: int | str) -> PlaylistManager:
    gid = str(int(guild_id))
    pm = playlist_managers.get(gid)
    if pm is None:
        pm = PlaylistManager(gid)
        playlist_managers[gid] = pm
        logger.info("PlaylistManager créée pour guild %s", gid)
    return pm

# -----------------------------------------------------------------------------
# Adaptateur pour exposer un PM “global” à l’API (fallback par DEFAULT_GUILD_ID)
class APIPMAdapter:
    """
    Façade minimaliste utilisée par l'API (backend.api.services.playlist_manager)
    qui attend un objet doté de: get_state(), enqueue(query, user_id=None),
    skip(), stop().

    - Sélectionne la guilde par défaut via l'env DEFAULT_GUILD_ID.
    - Si non défini, lève une erreur claire (503 côté API).
    """

    def __init__(self, default_gid: str | None = None):
        self.default_gid = default_gid or os.getenv("DEFAULT_GUILD_ID")

    def _pm(self) -> PlaylistManager:
        if not self.default_gid:
            raise RuntimeError(
                "DEFAULT_GUILD_ID non défini pour l'API. "
                "Définis la variable d'environnement DEFAULT_GUILD_ID."
            )
        return get_pm(self.default_gid)

    # Méthodes requises par l'API
    def get_state(self) -> dict[str, Any]:
        return self._pm().get_state()

    def enqueue(self, query: str, user_id: str | None = None) -> dict[str, Any]:
        return self._pm().enqueue(query=query, user_id=user_id)

    def skip(self) -> dict[str, Any]:
        return self._pm().skip()

    def stop(self) -> dict[str, Any]:
        return self._pm().stop()

# -----------------------------------------------------------------------------
# Bot Discord
INTENTS = discord.Intents.default()
INTENTS.message_content = False
INTENTS.members = True
INTENTS.presences = False
INTENTS.guilds = True
INTENTS.voice_states = True

class GregBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            application_id=int(config.DISCORD_APP_ID),
        )
        self.web_app = None

    async def _load_ext_dir(self, dirname: str):
        """Charge toutes les extensions (cogs) d'un dossier si présent."""
        import pkgutil, importlib
        if not os.path.isdir(dirname):
            return
        for _, modname, ispkg in pkgutil.iter_modules([dirname]):
            if ispkg:
                continue
            extension = f"{dirname}.{modname}"
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
            await self.post_restart_selftest()
        except Exception as e:
            logger.debug("Selftest skipped: %s", e)

    async def post_restart_selftest(self):
        """Check rapide de l'environnement, utile après redémarrage."""
        results: list[tuple[str, bool, str]] = []

        # 1) Cogs présents
        expected_cogs = [
            "Music", "Voice", "General", "EasterEggs", "Spook", "SpotifyAccount", "CookieGuardian"
        ]
        for name in expected_cogs:
            ok = self.get_cog(name) is not None
            results.append(("Cog:"+name, ok, "" if ok else "non chargé"))

        # 2) Slash commands
        try:
            cmds = await self.tree.fetch_commands()
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
            # guardian yt cookies
            "yt_cookies_update","yt_cookies_check",
        ]
        missing = [c for c in expected_cmds if c not in names]
        if missing:
            results.append(("Slash:manquants", False, ", ".join(missing)))
        else:
            results.append(("Slash:manquants", True, ""))

        # 3) FFmpeg
        try:
            music_cog = self.get_cog("Music")
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

        # Dump résultat
        for name, ok, info in results:
            logger.info("Selftest %-22s : %s %s", name, "OK" if ok else "KO", ("" if ok else f"({info})"))

    async def on_connect(self):
        logger.info("Bot connecté aux Gateway.")

    async def on_resumed(self):
        logger.info("Session Discord résumée.")

    async def setup_emit_fn(self):
        """
        Branche un emit(event, data, guild_id=...) utilisable par les Cogs.
        L’émetteur cible la room Socket.IO 'guild:{gid}' pour éviter les collisions.
        """
        def _resolve_socketio():
            try:
                si = globals().get("socketio")
                if si:
                    return si
            except Exception:
                pass
            app = getattr(self, "web_app", None)
            return getattr(app, "socketio", None)

        def _emit(event, data, **kwargs):
            si = _resolve_socketio()
            if not si:
                return
            try:
                gid = kwargs.get("guild_id")
                if gid is not None:
                    si.emit(event, data, room=f"guild:{gid}")
                else:
                    si.emit(event, data)
            except Exception as e:
                logger.error("socketio.emit failed: %s", e)

        for cog_name in ("Music", "Voice", "General", "EasterEggs", "Spook"):
            cog = self.get_cog(cog_name)
            if cog and not getattr(cog, "emit_fn", None):
                cog.emit_fn = _emit
                logger.info("emit_fn branché sur %s", cog_name)

        # Self-test post restart (optionnel)
        try:
            import asyncio
            asyncio.create_task(run_post_restart_selftest(self))
        except Exception as e:
            logger.debug("Self-test non lancé: %s", e)

async def run_post_restart_selftest(bot: GregBot):
    try:
        await bot.post_restart_selftest()
    except Exception as e:
        logger.debug("Self-test (async) non lancé: %s", e)

# -----------------------------------------------------------------------------
# Flask + SocketIO (overlay web)
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"
app = None
socketio = None

def build_web_app():
    """Construit l'app Flask API + retourne l'instance Socket.IO partagée."""
    # Import ici pour éviter side-effects avant la config
    from api import create_app as create_api_app
    from api.core.extensions import socketio as api_socketio

    # Injecte un adaptateur PM “global” (guilde par défaut via DEFAULT_GUILD_ID)
    pm_adapter = APIPMAdapter()
    api_app = create_api_app(pm=pm_adapter)

    # Attache la réf socketio sur l'app (utile pour bot.web_app.socketio)
    api_app.socketio = api_socketio
    return api_app, api_socketio

if not DISABLE_WEB:
    try:
        app, socketio = build_web_app()
        app.bot = None  # attaché plus tard
        logger.info("Socket.IO async_mode (effectif): %s", getattr(socketio, "async_mode", "unknown"))
    except ImportError as e:
        logger.warning("Overlay désactivé : api introuvable (%s)", e)
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

# -----------------------------------------------------------------------------
# Main
if __name__ == "__main__":
    bot = GregBot()

    if not DISABLE_WEB:
        app.bot = bot
        bot.web_app = app
        threading.Thread(target=run_web, daemon=True).start()
        wait_for_web()

    # Branche l'emit_fn après que les cogs soient chargés et les slash sync
    @bot.event
    async def on_ready():
        await bot.setup_emit_fn()  # branche emit_fn
        await GregBot.on_ready(bot)  # call parent handler

    bot.run(config.DISCORD_TOKEN)
