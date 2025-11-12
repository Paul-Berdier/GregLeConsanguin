# main.py
import asyncio
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

# Windows: boucle événementielle plus stable pour discord.py
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# -----------------------------------------------------------------------------
playlist_managers: dict[str, PlaylistManager] = {}  # {guild_id: PlaylistManager}
RESTART_MARKER = ".greg_restart.json"
_pm_lock = threading.Lock()

def get_pm(guild_id: int | str) -> PlaylistManager:
    gid = str(guild_id).strip()
    pm = playlist_managers.get(gid)
    if pm is not None:
        return pm
    with _pm_lock:
        pm = playlist_managers.get(gid)
        if pm is None:
            pm = PlaylistManager(gid)
            playlist_managers[gid] = pm
            logger.info("PlaylistManager créée pour guild %s", gid)
        return pm

# -----------------------------------------------------------------------------
class APIPMAdapter:
    def __init__(self, default_gid: str | None = None):
        self.default_gid = default_gid or os.getenv("DEFAULT_GUILD_ID")

    def _pm(self, gid: str | int | None) -> PlaylistManager:
        if gid is not None and str(gid).strip():
            return get_pm(gid)
        if self.default_gid:
            return get_pm(self.default_gid)
        raise RuntimeError(
            "DEFAULT_GUILD_ID non défini pour l'API. "
            "Définis la variable d'environnement DEFAULT_GUILD_ID ou passe guild_id."
        )

    def get_state(self, guild_id: str | int | None = None) -> dict[str, Any]:
        return self._pm(guild_id).to_dict()

    def enqueue(self, query: str, user_id: str | None = None, guild_id: str | int | None = None) -> dict[str, Any]:
        pm = self._pm(guild_id)
        pm.add(query, added_by=user_id)
        return {"ok": True, "length": pm.length()}

    def skip(self, guild_id: str | int | None = None) -> dict[str, Any]:
        pm = self._pm(guild_id)
        pm.skip()
        return {"ok": True, "length": pm.length()}

    def stop(self, guild_id: str | int | None = None) -> dict[str, Any]:
        pm = self._pm(guild_id)
        pm.stop()
        return {"ok": True, "length": pm.length()}

    def remove_at(self, index: int, guild_id: str | int | None = None) -> dict[str, Any]:
        pm = self._pm(guild_id)
        ok = pm.remove_at(index)
        return {"ok": bool(ok), "length": pm.length()}

    def move(self, src: int, dst: int, guild_id: str | int | None = None) -> dict[str, Any]:
        pm = self._pm(guild_id)
        ok = pm.move(src, dst)
        return {"ok": bool(ok), "length": pm.length()}

    def pop_next(self, guild_id: str | int | None = None) -> dict[str, Any]:
        it = self._pm(guild_id).pop_next()
        return {"ok": True, "item": it}

# -----------------------------------------------------------------------------
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
        self.web_app = None  # Flask app
        self._emit_fn_bridged = False

    async def _load_ext_dir(self, dirname: str):
        import pkgutil, importlib, sys
        if not os.path.isdir(dirname):
            return
        # Assure que le dossier est sur le path
        if dirname not in sys.path:
            sys.path.insert(0, os.getcwd())
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
        """
        Self-test non bloquant : HTTP via thread, SocketIO via self.web_app si dispo.
        """
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
            "play","pause","resume","skip","stop","playlist","current",
            "ping","greg","web","help","restart",
            "roll","coin","tarot","curse","praise","shame","skullrain","gregquote",
            "spook_enable","spook_settings","spook_status",
            "spook_test","spook_files","spook_reload","spook_scare",
            "yt_cookies_update","yt_cookies_check",
        ]
        missing = [c for c in expected_cmds if c not in names]
        results.append(("Slash:manquants", len(missing) == 0, "" if not missing else ", ".join(missing)))

        # 3) FFmpeg
        try:
            music_cog = self.get_cog("Music")
            ff = music_cog.detect_ffmpeg() if music_cog and hasattr(music_cog, "detect_ffmpeg") else "ffmpeg"
            cp = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=3)
            ok = (cp.returncode == 0)
            results.append(("FFmpeg", ok, "" if ok else (cp.stderr or cp.stdout)[:200]))
        except Exception as e:
            results.append(("FFmpeg", False, str(e)))

        # 4) Overlay HTTP (non bloquant)
        async def http_get(url, timeout=2):
            return await asyncio.to_thread(requests.get, url, timeout=timeout)

        try:
            if os.getenv("DISABLE_WEB", "0") != "1":
                r = await http_get("http://127.0.0.1:3000/healthz", timeout=2)
                if r.status_code == 404:
                    r = await http_get("http://127.0.0.1:3000/", timeout=2)
                ok = r.status_code < 500
                results.append(("Overlay:HTTP 127.0.0.1:3000", ok, f"HTTP {r.status_code}"))
            else:
                results.append(("Overlay:désactivé", True, "DISABLE_WEB=1"))
        except Exception as e:
            results.append(("Overlay:HTTP 127.0.0.1:3000", False, str(e)))

        # 5) SocketIO emit (ne dépend pas de __main__)
        try:
            si = getattr(self.web_app, "socketio", None)
            if si:
                si.emit("selftest_ping", {"ok": True, "t": time.time()})
                results.append(("SocketIO:emit", True, "emit ok"))
            else:
                results.append(("SocketIO:instance", False, "socketio=None"))
        except Exception as e:
            results.append(("SocketIO:emit", False, str(e)))

        for name, ok, info in results:
            logger.info("Selftest %-22s : %s %s", name, "OK" if ok else "KO", ("" if ok else f"({info})"))

    async def on_connect(self):
        logger.info("Bot connecté aux Gateway.")

    async def on_resumed(self):
        logger.info("Session Discord résumée.")

    async def setup_emit_fn(self):
        """
        Branche un emit(event, data, guild_id=...) utilisable par les Cogs.
        """
        if self._emit_fn_bridged:
            return

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

        self._emit_fn_bridged = True

        # Self-test asynchrone de confort (optionnel)
        try:
            asyncio.create_task(run_post_restart_selftest(self))
        except Exception as e:
            logger.debug("Self-test non lancé: %s", e)

async def run_post_restart_selftest(bot: GregBot):
    try:
        await bot.post_restart_selftest()
    except Exception as e:
        logger.debug("Self-test (async) non lancé: %s", e)

# -----------------------------------------------------------------------------
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"
app = None
socketio = None

def build_web_app():
    """Construit l'app Flask API + retourne l'instance Socket.IO partagée."""
    from api import create_app as create_api_app
    from api.core.extensions import socketio as api_socketio

    pm_adapter = APIPMAdapter()
    api_app = create_api_app(pm=pm_adapter)

    # Attache pour accès via bot.web_app.socketio
    api_app.socketio = api_socketio
    return api_app, api_socketio

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

if __name__ == "__main__":
    # Garde-fous ENV utiles
    if not getattr(config, "DISCORD_TOKEN", None):
        raise SystemExit("DISCORD_TOKEN manquant dans config.py / env")
    if not getattr(config, "DISCORD_APP_ID", None):
        raise SystemExit("DISCORD_APP_ID manquant dans config.py / env")

    bot = GregBot()

    if not DISABLE_WEB:
        try:
            app, socketio = build_web_app()   # <-- PAS de 'global' ici
            app.bot = bot
            bot.web_app = app
            logger.info("Socket.IO async_mode (effectif): %s", getattr(socketio, "async_mode", "unknown"))
            threading.Thread(target=run_web, daemon=True).start()
            wait_for_web()
        except Exception as e:
            logger.warning("Overlay désactivé (fallback) : %s", e)

    # Wrapper pour brancher emit_fn puis appeler le on_ready d'origine
    @bot.event
    async def on_ready():
        await bot.setup_emit_fn()
        await GregBot.on_ready(bot)

    bot.run(config.DISCORD_TOKEN)
