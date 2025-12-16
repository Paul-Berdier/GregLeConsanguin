# main.py
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import socket
import subprocess
from typing import Any, Optional, Dict

import requests
import discord
from discord.ext import commands

import config
from api.services.player_service import PlayerService

# -----------------------------------------------------------------------------
# Logging de base
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


# -----------------------------------------------------------------------------
# Bridge API → PlayerService : source de vérité unique
# -----------------------------------------------------------------------------
class PlayerAPIBridge:
    """
    Façade API au-dessus de api.services.player_service.PlayerService.
    Toutes les méthodes acceptent un guild_id optionnel et appellent
    le PlayerService attaché au bot (unique source de vérité).
    """
    def __init__(self, default_gid: Optional[str] = None):
        self.default_gid = (default_gid or os.getenv("DEFAULT_GUILD_ID"))
        if self.default_gid:
            self.default_gid = str(self.default_gid).strip()

    def _gid(self, gid: Optional[str | int]) -> int:
        if gid is not None and str(gid).strip():
            return int(gid)
        if self.default_gid:
            return int(self.default_gid)
        raise RuntimeError("DEFAULT_GUILD_ID non défini. Passez guild_id dans l’appel API.")

    def _svc(self):
        # Récupère le PlayerService déjà attaché au bot par commands/Music (ou par main)
        b = globals().get("bot")
        svc = getattr(b, "player_service", None) if b else None
        if not svc:
            raise RuntimeError("PlayerService indisponible (bot.player_service est None).")
        return svc, b

    def _call(self, coro):
        # Exécute une coroutine du PlayerService dans la loop Discord (thread-safe)
        _, b = self._svc()
        fut = asyncio.run_coroutine_threadsafe(coro, b.loop)
        return fut.result(timeout=20)

    # ---- lecture d’état (utilisé par l’overlay / API GET) ----
    def get_state(self, guild_id: Optional[str | int] = None) -> Dict[str, Any]:
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        return svc._overlay_payload(gid)

    # ---- enqueue ----
    def enqueue(self, query: str | Dict[str, Any], user_id: Optional[str] = None, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        item = query if isinstance(query, dict) else {"url": str(query)}
        uid = int(user_id) if user_id is not None and str(user_id).strip() else 0
        return self._call(svc.enqueue(gid, uid, item))

    # ---- skip/stop ----
    def skip(self, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        return self._call(svc.skip(gid))

    def stop(self, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        return self._call(svc.stop(gid))

    # ---- remove/move/pop_next (optionnel selon tes routes) ----
    def remove_at(self, index: int, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        pm = svc._get_pm(gid)
        ok = pm.remove_at(int(index))
        svc._emit_playlist_update(gid)
        return {"ok": bool(ok), "length": pm.length()}

    def move(self, src: int, dst: int, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        pm = svc._get_pm(gid)
        ok = pm.move(int(src), int(dst))
        svc._emit_playlist_update(gid)
        return {"ok": bool(ok), "length": pm.length()}

    def pop_next(self, guild_id: Optional[str | int] = None):
        # Exposition rarement utile publiquement, conservée pour compat
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        pm = svc._get_pm(gid)
        it = pm.pop_next()
        svc._emit_playlist_update(gid)
        return {"ok": True, "item": it}


# -----------------------------------------------------------------------------
# Bot Discord
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
        self.web_app = None
        # ✅ Crée le PlayerService dès maintenant pour qu’il soit partagé
        self.player_service: PlayerService = PlayerService(self)

    async def _load_ext_dir(self, dirname: str):
        """Charge toutes les extensions (cogs) d'un dossier si présent."""
        import pkgutil
        import importlib  # noqa: F401

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
            "Music",
            "Voice",
            "General",
            "EasterEggs",
            "Spook",
            "SpotifyAccount",
            "CookieGuardian",
        ]
        for name in expected_cogs:
            ok = self.get_cog(name) is not None
            results.append(("Cog:" + name, ok, "" if ok else "non chargé"))

        # 2) Slash commands
        try:
            cmds = await self.tree.fetch_commands()
            names = {c.name for c in cmds}
        except Exception as e:
            names = set()
            results.append(("Slash:fetch_commands", False, str(e)))
        expected_cmds = [
            # music/voice/general
            "play",
            "pause",
            "resume",
            "skip",
            "stop",
            "playlist",
            "current",
            "ping",
            "greg",
            "web",
            "help",
            "restart",
            # easter eggs
            "roll",
            "coin",
            "tarot",
            "curse",
            "praise",
            "shame",
            "gregquote",
            # guardian yt cookies
            "yt_cookies_update",
            "yt_cookies_check",
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
            ok = cp.returncode == 0
            results.append(("FFmpeg", ok, "" if ok else (cp.stderr or cp.stdout)[:200]))
        except Exception as e:
            results.append(("FFmpeg", False, str(e)))

        # 4) Overlay HTTP
        try:
            if not os.getenv("DISABLE_WEB", "0") == "1":
                try:
                    r = requests.get("http://127.0.0.1:3000/healthz", timeout=2)
                except Exception:
                    r = None
                if r is None or r.status_code == 404:
                    r = requests.get("http://127.0.0.1:3000/", timeout=2)

                ok = r.status_code < 500
                results.append(("Overlay:HTTP 127.0.0.1:3000", ok, f"HTTP {r.status_code}"))
            else:
                results.append(("Overlay:désactivé", True, "DISABLE_WEB=1"))
        except Exception as e:
            results.append(("Overlay:HTTP 127.0.0.1:3000", False, str(e)))

        # 5) SocketIO emit
        try:
            si = getattr(self.web_app, "socketio", None) or globals().get("socketio")
            if si:
                try:
                    si.emit("selftest_ping", {"ok": True, "t": time.time()})
                    results.append(("SocketIO:emit", True, "emit ok"))
                except Exception as e:
                    results.append(("SocketIO:emit", False, str(e)))
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
# -----------------------------------------------------------------------------
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"

# Ces deux variables sont simplement définies au niveau module
app = None
socketio = None


def build_web_app():
    """
    Construit l'app Flask API + retourne l'instance Socket.IO partagée.
    """
    from api import create_app as create_api_app
    from api.core.extensions import socketio as api_socketio

    # 🔗 Bridge API→PlayerService (plus de APIPMAdapter)
    pm_adapter = PlayerAPIBridge(default_gid=os.getenv("DEFAULT_GUILD_ID"))
    api_app = create_api_app(pm=pm_adapter)

    # Attache pour accès via bot.web_app.socketio
    api_app.socketio = api_socketio
    return api_app, api_socketio


def run_web():
    """
    Thread serveur web (Flask + SocketIO).
    Utilise l'instance globale app/socketio initialisée dans __main__.
    """
    if socketio and app:
        mode = getattr(socketio, "async_mode", "threading")
        logger.debug("Lancement web… (mode=%s)", mode)
        if mode == "eventlet":
            socketio.run(app, host="0.0.0.0", port=3000, use_reloader=False)
        else:
            socketio.run(
                app,
                host="0.0.0.0",
                port=3000,
                allow_unsafe_werkzeug=True,
                use_reloader=False,
            )


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
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Garde-fous ENV utiles
    if not getattr(config, "DISCORD_TOKEN", None):
        raise SystemExit("DISCORD_TOKEN manquant dans config.py / env")
    if not getattr(config, "DISCORD_APP_ID", None):
        raise SystemExit("DISCORD_APP_ID manquant dans config.py / env")

    bot = GregBot()

    if not DISABLE_WEB:
        try:
            # Initialise les globals app/socketio une seule fois ici
            app, socketio = build_web_app()
            app.bot = bot
            bot.web_app = app

            # Expose PlayerService sur l’app pour d’éventuelles routes directes
            app.player_service = bot.player_service
            app.extensions["player"] = bot.player_service

            # ✅ Brancher un émetteur Socket.IO pour que PlayerService pousse "playlist_update"
            def _player_emit(event, payload, guild_id=None):
                si = getattr(app, "socketio", None) or globals().get("socketio")
                if not si:
                    return
                if guild_id is not None:
                    si.emit(event, payload, room=f"guild:{guild_id}")
                else:
                    si.emit(event, payload)

            bot.player_service.set_emit_fn(_player_emit)

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
