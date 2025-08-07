"""Flask + SocketIO web interface for Greg refonte.

This module defines ``create_web_app``, a factory that sets up a Flask
application and binds a SocketIO server.  The web panel provides
pages for selecting a guild and channel, managing the playlist and
issuing playback commands.  API endpoints expose play/pause/skip/stop
actions as well as autocomplete and playlist retrieval.

All interactions with the Discord bot are marshalled through
``asyncio.run_coroutine_threadsafe`` to ensure that coroutines run on
the bot's event loop rather than the Flask thread.  This avoids the
"Future attached to a different loop" error seen previously and
ensures thread safety.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, emit

from ..bot.playlist_manager import PlaylistManager


def create_web_app(bot) -> Tuple[Flask, SocketIO]:
    """Create and configure the Flask application and SocketIO server.

    Parameters
    ----------
    bot
        The Discord bot instance.  Must expose ``loop`` and the
        ``Music`` cog via ``bot.get_cog("Music")``.

    Returns
    -------
    (Flask, SocketIO)
        A tuple containing the Flask app and SocketIO server.  The app
        attaches helper functions to access the playlist manager for a
        guild (``app.get_pm``) and references the bot instance as
        ``app.bot``.
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")
    socketio = SocketIO(app)
    # Secret key for sessions; use an env var in production
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me")
    # Attach bot on the app for access in routes
    app.bot = bot

    # Helper to get a playlist manager for a guild
    def get_pm(guild_id: str | int) -> PlaylistManager:
        return bot.get_cog("Music").get_pm(guild_id)
    app.get_pm = get_pm  # type: ignore

    # ------------------------------------------------------------------
    # Page routes
    # ------------------------------------------------------------------
    @app.route("/")
    def index() -> Any:
        """Home page: redirect to select."""
        return redirect(url_for("select"))

    @app.route("/logout")
    def logout() -> Any:
        """Clear session and redirect to select."""
        session.clear()
        return redirect(url_for("select"))

    @app.route("/select")
    def select() -> Any:
        """Show a page to pick a guild and text channel."""
        # In a more complete implementation the user would authenticate
        # via OAuth to determine accessible guilds.  Here we simply list
        # all guilds the bot is connected to.
        user = {"id": "anonymous", "guilds": []}
        guilds_fmt: list[Dict[str, Any]] = []
        for g in bot.guilds:
            guilds_fmt.append({"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)})
        return render_template("select.html", guilds=guilds_fmt, user=user)

    @app.route("/panel")
    def panel() -> Any:
        """Main control panel for a specific guild/channel."""
        guild_id = request.args.get("guild_id")
        channel_id = request.args.get("channel_id")
        if not guild_id or not channel_id:
            return redirect(url_for("select"))
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return "Serveur introuvable", 404
        pm = app.get_pm(guild_id)
        # Reload the playlist synchronously to ensure we serve the latest
        pm.reload()
        return render_template(
            "panel.html",
            user={"id": "anonymous"},
            guild_id=guild_id,
            channel_id=channel_id,
            playlist=pm.get_queue(),
            current=pm.get_current(),
        )

    # ------------------------------------------------------------------
    # API endpoints
    # ------------------------------------------------------------------
    @app.route("/api/play", methods=["POST"])
    def api_play() -> Any:
        data = request.json or request.form
        title = data.get("title")
        url = data.get("url")
        guild_id = data.get("guild_id")
        user_id = data.get("user_id")
        if not (title and url and guild_id and user_id):
            return jsonify(error="Missing parameters"), 400
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return jsonify(error="Music cog not loaded"), 500
        try:
            fut = asyncio.run_coroutine_threadsafe(
                music_cog.play_for_user(guild_id, user_id, {"title": str(title), "url": str(url)}),
                bot.loop,
            )
            fut.result(timeout=60)
            pm = app.get_pm(guild_id)
            socketio.emit("playlist_update", pm.to_dict())
        except Exception as e:
            import traceback
            return jsonify(error=str(e), trace=traceback.format_exc()), 500
        return jsonify(ok=True)

    @app.route("/api/pause", methods=["POST"])
    def api_pause() -> Any:
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return jsonify(error="Music cog not loaded"), 500
        try:
            fut = asyncio.run_coroutine_threadsafe(
                music_cog.pause_for_web(guild_id), bot.loop
            )
            fut.result(timeout=30)
        except Exception as e:
            return jsonify(error=str(e)), 500
        return jsonify(ok=True)

    @app.route("/api/resume", methods=["POST"])
    def api_resume() -> Any:
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return jsonify(error="Music cog not loaded"), 500
        try:
            fut = asyncio.run_coroutine_threadsafe(
                music_cog.resume_for_web(guild_id), bot.loop
            )
            fut.result(timeout=30)
        except Exception as e:
            return jsonify(error=str(e)), 500
        return jsonify(ok=True)

    @app.route("/api/stop", methods=["POST"])
    def api_stop() -> Any:
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return jsonify(error="Music cog not loaded"), 500
        try:
            fut = asyncio.run_coroutine_threadsafe(
                music_cog.stop_for_web(guild_id), bot.loop
            )
            fut.result(timeout=30)
        except Exception as e:
            return jsonify(error=str(e)), 500
        return jsonify(ok=True)

    @app.route("/api/skip", methods=["POST"])
    def api_skip() -> Any:
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return jsonify(error="Music cog not loaded"), 500
        try:
            fut = asyncio.run_coroutine_threadsafe(
                music_cog.skip_for_web(guild_id), bot.loop
            )
            fut.result(timeout=30)
        except Exception as e:
            return jsonify(error=str(e)), 500
        return jsonify(ok=True)

    @app.route("/api/playlist", methods=["GET"])
    def api_playlist() -> Any:
        guild_id = request.args.get("guild_id")
        pm = app.get_pm(guild_id) if guild_id else None
        if not pm:
            return jsonify(queue=[], current=None)
        return jsonify(pm.to_dict())

    @app.route("/autocomplete", methods=["GET"])
    def autocomplete() -> Any:
        query = request.args.get("q", "").strip()
        if not query:
            return {"results": []}
        from ..extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        suggestions = [
            {"title": r["title"], "url": r.get("url") or r.get("webpage_url")}
            for r in results
        ][:5]
        return {"results": suggestions}

    @app.route("/api/text_channels")
    def get_text_channels() -> Any:
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify(error="missing guild_id"), 400
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return jsonify(error="guild not found"), 404
        channels = [
            {"id": c.id, "name": c.name}
            for c in guild.text_channels
        ]
        return jsonify(channels)

    # ------------------------------------------------------------------
    # Socket events
    # ------------------------------------------------------------------
    @socketio.on("connect")
    def ws_connect(auth: Any | None = None) -> None:
        """When a web client connects send the current playlist for the first guild.

        In a multi‑guild setup the client should request updates for a
        specific guild; here we simply send the first guild as a default.
        """
        guilds = bot.guilds
        if guilds:
            pm = app.get_pm(guilds[0].id)
            emit("playlist_update", pm.to_dict())
        print("[DEBUG][SocketIO] Nouvelle connexion web. Playlist envoyée !")

    return app, socketio
