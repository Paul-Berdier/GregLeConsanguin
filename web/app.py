# web/app.py

from flask import Flask, render_template, request, redirect, jsonify
from flask_socketio import SocketIO, emit
import os

def create_web_app(playlist_manager):
    playlist_manager.bot = app.bot if hasattr(app, "bot") else None
    app = Flask(__name__, static_folder="static", template_folder="templates")
    socketio = SocketIO(app)

    @app.route("/")
    def index():
        playlist = playlist_manager.get_queue()
        current = playlist_manager.get_current()
        return render_template("index.html", playlist=playlist, current=current)

    @app.route("/api/play", methods=["POST"])
    def api_play():
        try:
            url = request.json["url"]
        except:
            url = request.form.get("url")

        print(f"[DEBUG] POST /api/play appelé avec url = {url}")
        playlist_manager.add(url)
        socketio.emit("playlist_update", playlist_manager.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        playlist_manager.skip()
        socketio.emit("playlist_update", playlist_manager.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        playlist_manager.stop()
        socketio.emit("playlist_update", playlist_manager.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        return jsonify(ok=True)

    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        return jsonify(playlist_manager.to_dict())

    @app.route("/autocomplete", methods=["GET"])
    def autocomplete():
        query = request.args.get("q", "").strip()
        if not query:
            return {"results": []}
        from extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        suggestions = [{"title": r["title"], "url": r["url"]} for r in results][:5]
        return {"results": suggestions}

    @app.route("/search", methods=["POST"])
    def search():
        query = request.form["url"]
        from extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        return render_template("search_results.html", results=results, query=query)

    @socketio.on("connect")
    def ws_connect():
        emit("playlist_update", playlist_manager.to_dict())

    @app.route("/api/debug_trigger", methods=["POST"])
    def debug_trigger():
        from bot_socket import trigger_play, bot
        import asyncio
        asyncio.run_coroutine_threadsafe(trigger_play(bot), bot.loop)
        return jsonify(ok=True)

    @app.route("/api/channels")
    def get_voice_channels():
        if "user" not in session:
            return jsonify({"error": "unauthorized"}), 401

        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"error": "missing guild_id"}), 400

        # Parcourir les guilds connectés
        for g in playlist_manager.bot.guilds:
            if str(g.id) == guild_id:
                channels = [
                    {"id": c.id, "name": c.name}
                    for c in g.voice_channels
                ]
                return jsonify(channels)

        return jsonify([])  # Si le bot n’est pas dans ce serveur

    @app.route("/api/command/<action>", methods=["POST"])
    def trigger_command(action):
        if "user" not in session:
            return jsonify({"error": "unauthorized"}), 401

        data = request.json
        guild_id = int(data.get("guild_id"))
        channel_id = int(data.get("channel_id"))
        url = data.get("url", "")

        bot = playlist_manager.bot
        if bot is None:
            return jsonify({"error": "bot not ready"}), 500

        guild = discord.utils.get(bot.guilds, id=guild_id)
        if guild is None:
            return jsonify({"error": "guild not found"}), 404

        voice_channel = discord.utils.get(guild.voice_channels, id=channel_id)
        if voice_channel is None:
            return jsonify({"error": "voice channel not found"}), 404

        # Créer une fausse interaction
        class FakeInteraction:
            def __init__(self):
                self.guild = guild
                self.user = guild.members[0]
                self.channel = None
                self.followup = self
            async def send(self, msg): print(f"[GregFake] {msg}")

        async def run_action():
            try:
                await voice_channel.connect()
            except:
                pass  # déjà connecté

            music_cog = bot.get_cog("Music")
            if music_cog is None:
                print("[ERROR] Music cog non trouvé.")
                return

            fake = FakeInteraction()
            if action == "play":
                await music_cog.play(fake, url=url)
            elif action == "skip":
                await music_cog.skip(fake)
            elif action == "stop":
                await music_cog.stop(fake)

        import asyncio
        asyncio.create_task(run_action())

        return jsonify({"status": "ok"})

    return app, socketio
