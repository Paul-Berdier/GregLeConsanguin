# web/app.py

# web/app.py

from flask import Flask, render_template, request, redirect, jsonify, session
from flask_socketio import SocketIO, emit
from web.oauth import oauth_bp
import os

def create_web_app(playlist_manager):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    socketio = SocketIO(app)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.register_blueprint(oauth_bp)

    @app.route("/")
    def index():
        user = session.get("user")
        return render_template("index.html", user=user)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    @app.route("/panel")
    def panel():
        user = session.get("user")
        if not user:
            return redirect("/login")
        user_guild_ids = set(g['id'] for g in user['guilds'])
        bot_guilds = app.bot.guilds  # list of discord.Guild
        # Filtre : ne montrer QUE les serveurs où Greg est présent
        common_guilds = [g for g in bot_guilds if str(g.id) in user_guild_ids]
        # Adapter le format si besoin
        guilds_fmt = [{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in common_guilds]
        return render_template("panel.html", guilds=guilds_fmt, user=user)

    @app.route("/api/play", methods=["POST"])
    def api_play():
        try:
            url = request.json["url"]
        except:
            url = request.form.get("url")
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

    @app.route("/api/channels")
    def get_channels():
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"error": "missing guild_id"}), 400

        # Accès correct à l'objet bot
        bot = app.bot
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return jsonify({"error": "guild not found"}), 404

        channels = [{"id": c.id, "name": c.name} for c in guild.voice_channels]
        return jsonify(channels)

    @socketio.on("connect")
    def ws_connect(auth=None):
        if playlist_manager is not None:
            emit("playlist_update", playlist_manager.to_dict())
        else:
            print("[FATAL] playlist_manager is None dans ws_connect !")

    return app, socketio
