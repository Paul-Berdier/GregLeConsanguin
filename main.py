# main.py
from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import threading
import time
from typing import Any, Optional, Dict

import requests
import discord
from discord.ext import commands

import config
from api.services.player_service import PlayerService

# -----------------------------------------------------------------------------
# Logging
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
# Bridge API → PlayerService (source de vérité unique)
# -----------------------------------------------------------------------------
class PlayerAPIBridge:
    """
    Façade API au-dessus de PlayerService.
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
        b = globals().get("bot")
        svc = getattr(b, "player_service", None) if b else None
        if not svc:
            raise RuntimeError("PlayerService indisponible (bot.player_service est None).")
        return svc, b

    def _call(self, coro):
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

    # ---- remove/move/pop_next (compat routes/WS ctrl) ----
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
        self.player_service: PlayerService = PlayerService(self)

    async def _load_ext_dir(self, dirname: str):
        import pkgutil

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
        results: list[tuple[str, bool, str]] = []

        expected_cogs = [
            "Music", "Voice", "General", "EasterEggs", "Spook", "CookieGuardian"
        ]
        for name in expected_cogs:
            ok = self.get_cog(name) is not None
            results.append(("Cog:" + name, ok, "" if ok else "non chargé"))

        try:
            cmds = await self.tree.fetch_commands()
            names = {c.name for c in cmds}
        except Exception as e:
            names = set()
            results.append(("Slash:fetch_commands", False, str(e)))

        expected_cmds = [
            "play", "pause", "resume", "skip", "stop", "playlist", "current",
            "ping", "greg", "web", "help", "restart",
            "roll", "coin", "tarot", "curse", "praise", "shame", "gregquote",
            "yt_cookies_update", "yt_cookies_check",
        ]
        missing = [c for c in expected_cmds if c not in names]
        results.append(("Slash:manquants", not bool(missing), "" if not missing else ", ".join(missing)))

        try:
            music_cog = self.get_cog("Music")
            ff = music_cog.detect_ffmpeg() if music_cog and hasattr(music_cog, "detect_ffmpeg") else "ffmpeg"
            cp = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=3)
            ok = cp.returncode == 0
            results.append(("FFmpeg", ok, "" if ok else (cp.stderr or cp.stdout)[:200]))
        except Exception as e:
            results.append(("FFmpeg", False, str(e)))

        try:
            if not os.getenv("DISABLE_WEB", "0") == "1":
                r = None
                try:
                    r = requests.get("http://127.0.0.1:3000/healthz", timeout=2)
                except Exception:
                    pass
                if r is None or r.status_code == 404:
                    r = requests.get("http://127.0.0.1:3000/", timeout=2)

                ok = r.status_code < 500
                results.append(("Overlay:HTTP 127.0.0.1:3000", ok, f"HTTP {r.status_code}"))
            else:
                results.append(("Overlay:désactivé", True, "DISABLE_WEB=1"))
        except Exception as e:
            results.append(("Overlay:HTTP 127.0.0.1:3000", False, str(e)))

        try:
            app = getattr(self, "web_app", None)
            si = getattr(app, "socketio", None) if app else None
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

        for name, ok, info in results:
            logger.info("Selftest %-22s : %s %s", name, "OK" if ok else "KO", ("" if ok else f"({info})"))

    async def setup_emit_fn(self):
        """
        Branche un emit(event, data, guild_id=...) utilisable par les Cogs.
        Room Socket.IO: 'guild:{gid}'
        """
        def _emit(event, data, **kwargs):
            app = getattr(self, "web_app", None)
            si = getattr(app, "socketio", None) if app else None
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

        try:
            asyncio.create_task(self.post_restart_selftest())
        except Exception as e:
            logger.debug("Self-test non lancé: %s", e)


# -----------------------------------------------------------------------------
# Flask + SocketIO (overlay web)
# -----------------------------------------------------------------------------
DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"

# globals runtime (remplis dans __main__)
app = None
web_socketio = None


def build_web_app():
    """
    Construit l'app Flask API + retourne l'instance Socket.IO partagée.
    Important: en mode "bot + web même process", threading est le plus stable.
    """
    # Par défaut: threading (stable avec discord.py)
    # Si tu veux eventlet, export SOCKETIO_MODE=eventlet AVANT lancement.
    os.environ.setdefault("SOCKETIO_MODE", "threading")

    from api import create_app as create_api_app
    from api.core.extensions import socketio as api_socketio

    pm_adapter = PlayerAPIBridge(default_gid=os.getenv("DEFAULT_GUILD_ID"))
    api_app = create_api_app(pm=pm_adapter)

    # exposition pratique
    api_app.socketio = api_socketio
    return api_app, api_socketio


def run_web():
    """
    Thread serveur web (Flask + SocketIO).
    Utilise globals app/web_socketio initialisées dans __main__.
    """
    if not app or not web_socketio:
        return

    mode = getattr(web_socketio, "async_mode", "threading")
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "3000"))

    logger.info("Lancement web… host=%s port=%s (socketio_mode=%s)", host, port, mode)

    if mode == "threading":
        web_socketio.run(
            app,
            host=host,
            port=port,
            allow_unsafe_werkzeug=True,
            use_reloader=False,
        )
    else:
        # eventlet / gevent
        web_socketio.run(
            app,
            host=host,
            port=port,
            use_reloader=False,
        )


def wait_for_web():
    for i in range(30):
        try:
            s = socket.create_connection(("127.0.0.1", int(os.getenv("WEB_PORT", "3000"))), 1)
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
    if not getattr(config, "DISCORD_TOKEN", None):
        raise SystemExit("DISCORD_TOKEN manquant dans config.py / env")
    if not getattr(config, "DISCORD_APP_ID", None):
        raise SystemExit("DISCORD_APP_ID manquant dans config.py / env")

    bot = GregBot()

    if not DISABLE_WEB:
        try:
            app, web_socketio = build_web_app()
            app.bot = bot
            bot.web_app = app

            # Expose PlayerService sur l’app
            app.player_service = bot.player_service
            app.extensions["player"] = bot.player_service

            # Emit Socket.IO côté PlayerService (push playlist_update, etc.)
            def _player_emit(event, payload, guild_id=None):
                si = getattr(app, "socketio", None) or web_socketio
                if not si:
                    return
                if guild_id is not None:
                    si.emit(event, payload, room=f"guild:{guild_id}")
                else:
                    si.emit(event, payload)

            bot.player_service.set_emit_fn(_player_emit)

            logger.info("Socket.IO async_mode (effectif): %s", getattr(web_socketio, "async_mode", "unknown"))

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
