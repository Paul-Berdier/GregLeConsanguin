"""Entry point for Greg refonte.

This module starts the Discord bot and the Flask/SocketIO web panel in
parallel.  The Discord bot is configured via environment variables
(see :mod:`greg_refonte.bot.config`).  The web panel runs on the port
specified by ``WEB_PORT`` and communicates with the bot via an
``emit_fn`` callback passed to the Music cog.  The Flask app and
SocketIO server are created by :func:`greg_refonte.web.app.create_web_app`.

To run the bot simply execute this file.  It will block until the
bot is disconnected or terminated.
"""

from __future__ import annotations

import asyncio
import threading

import discord
from discord.ext import commands

from greg_refonte.bot.config import DISCORD_TOKEN, WEB_PORT
from greg_refonte.web.app import create_web_app


async def start_bot() -> None:
    """Asynchronously start the Discord bot and the web panel."""
    # Ensure we have a token
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is not set.  Please set it in your environment."
        )

    # Configure Discord intents
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready() -> None:
        print(f"====== EVENT on_ready() ======")
        print(f"Utilisateur bot : {bot.user} (ID: {bot.user.id})")
        print("Serveurs :", [g.name for g in bot.guilds])

    async def load_cogs(emit_fn) -> None:
        """Load all Discord cogs with the given emit function."""
        from greg_refonte.bot.commands.music import Music
        from greg_refonte.bot.commands.voice import Voice
        # Reload in case already loaded
        await bot.add_cog(Music(bot, emit_fn))
        await bot.add_cog(Voice(bot, emit_fn))
        print("✅ Cogs chargés")

    # Create the web application and socket server
    app, socketio = create_web_app(bot)

    # Define an emit function capturing this socketio instance
    def emit(event: str, data: dict) -> None:
        socketio.emit(event, data)

    # Load cogs now that we have emit
    await load_cogs(emit)

    # Start the web server in a separate thread
    def run_web() -> None:
        # socketio.run manages both the Flask and SocketIO servers
        socketio.run(app, port=WEB_PORT)

    web_thread = threading.Thread(target=run_web, name="WebThread", daemon=True)
    web_thread.start()

    # Finally run the bot.  This call blocks until logout.
    await bot.start(DISCORD_TOKEN)


def main() -> None:
    """Entry point for running from the command line."""
    asyncio.run(start_bot())


if __name__ == "__main__":
    main()