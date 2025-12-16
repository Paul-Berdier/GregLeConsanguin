# main.py

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, Optional

import requests
import discord
from discord.ext import commands

import config
from api.services.player_service import PlayerService

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


class PlayerAPIBridge:
    """
    Façade API au-dessus de PlayerService (source de vérité unique).
    Toutes les méthodes acceptent guild_id optionnel.
    """

    def __init__(self, default_gid: Optional[str] = None):
        self.default_gid = (default_gid or os.getenv("DEFAULT_GUILD_ID") or "").strip() or None

    def _gid(self, gid: Optional[str | int]) -> int:
        if gid is not None and str(gid).strip():
            return int(gid)
        if self.default_gid:
            return int(self.default_gid)
        raise RuntimeError("DEFAULT_GUILD_ID non défini. Passe guild_id dans l’appel API.")

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

    def get_state(self, guild_id: Optional[str | int] = None) -> Dict[str, Any]:
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        return svc._overlay_payload(gid)

    def enqueue(self, query: str | Dict[str, Any], user_id: Optional[str] = None, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        item = query if isinstance(query, dict) else {"url": str(query)}
        uid = int(user_id) if user_id is not None and str(user_id).strip() else 0
        return self._call(svc.enqueue(gid, uid, item))

    def skip(self, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        return self._call(svc.skip(gid))

    def stop(self, guild_id: Optional[str | int] = None):
        svc, _ = self._svc()
        gid = self._gid(guild_id)
        return self._call(svc.stop(gid))

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

        expected_cogs = ["Music", "Voice", "General", "EasterEggs", "Spook", "SpotifyAccount", "CookieGuardian"]
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
            "play", "pause", "resume", "skip", "stop", "playlist", "current", "ping", "greg", "web", "help", "restart",
            "roll", "coin", "tarot", "curse", "praise", "shame", "gregquote",
            "yt_cookies_update", "yt_cookies_check",
        ]
        missing = [c for c in expected_cmds if c not in names]
        results.append(("Slash:manquants", not bool(missing), ", ".join(missing) if missing else ""))

        try:
            music_cog = self.get_cog("Music")
            ff = music_cog.detect_ffmpeg() if music_cog and hasattr(music_cog, "detect_ffmpeg") else "ffmpeg"
            cp = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=3)
            results.append(("FFmpeg", cp.returncode == 0, "" if cp.returncode == 0 else (cp.stderr or cp.stdout)[:200]))
        except Exception as e:
            results.append(("FFmpeg", False, str(e)))

        try:
            if os.getenv("DISABLE_WEB", "0") != "1":
                r = requests.get("http://127.0.0.1:3000/healthz", timeout=2)
                results.append(("Overlay:HTTP 127.0.0.1:3000", r.status_code < 500, f"HTTP {r.status_code}"))
            else:
                results.append(("Overlay:désactivé", True, "DISABLE_WEB=1"))
        except Exception as e:
            results.append(("Overlay:HTTP 127.0.0.1:3000", False, str(e)))

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
            logger.info("Selftest %-28s : %s %s", name, "OK" if ok else "KO", ("" if ok else f"({info})"))

    async def setup_emit_fn(self):
        def _emit(event, data, **kwargs):
            si = getattr(self.web_app, "socketio", None)
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


DISABLE_WEB = os.getenv("DISABLE_WEB", "0") == "1"

web_app = None
web_socketio = None


def build_web_app():
    from api import create_app as create_api_app
    from api.core.extensions import socketio as api_socketio

    pm_adapter = PlayerAPIBridge(default_gid=os.getenv("DEFAULT_GUILD_ID"))
    api_app = create_api_app(pm=pm_adapter)

    api_app.socketio = api_socketio
    return api_app, api_socketio


def run_web():
    if web_socketio and web_app:
        mode = getattr(web_socketio, "async_mode", "threading")
        logger.info("Lancement web… host=0.0.0.0 port=3000 (socketio_mode=%s)", mode)
        if mode == "eventlet":
            web_socketio.run(web_app, host="0.0.0.0", port=3000, use_reloader=False)
        else:
            web_socketio.run(
                web_app,
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
    raise SystemExit("[FATAL] Serveur web jamais prêt !")


if __name__ == "__main__":
    if not getattr(config, "DISCORD_TOKEN", None):
        raise SystemExit("DISCORD_TOKEN manquant")
    if not getattr(config, "DISCORD_APP_ID", None):
        raise SystemExit("DISCORD_APP_ID manquant")

    bot = GregBot()

    if not DISABLE_WEB:
        try:
            web_app, web_socketio = build_web_app()
            web_app.bot = bot
            bot.web_app = web_app

            web_app.player_service = bot.player_service
            web_app.extensions["player"] = bot.player_service

            def _player_emit(event, payload, guild_id=None):
                si = getattr(web_app, "socketio", None)
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

    @bot.event
    async def on_ready():
        await bot.setup_emit_fn()
        await GregBot.on_ready(bot)

    bot.run(config.DISCORD_TOKEN)
