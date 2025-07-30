# web/app.py

from flask import Flask, render_template, request, redirect, jsonify, session
from flask_socketio import SocketIO, emit
from web.oauth import oauth_bp
import os

def create_web_app(get_pm):  # get_pm(guild_id) retourne le bon PlaylistManager !
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

        # IDs des serveurs où l'utilisateur est membre
        user_guild_ids = set(g['id'] for g in user['guilds'])
        print("\n[DEBUG] Guilds côté utilisateur (user['guilds']):")
        for g in user['guilds']:
            print(f" - {g['id']} : {g['name']}")

        # Serveurs où Greg est présent (bot_guilds)
        bot_guilds = app.bot.guilds  # liste de discord.Guild
        print("[DEBUG] Guilds côté Greg (bot.guilds):")
        for g in bot_guilds:
            print(f" - {g.id} : {g.name}")

        # Serveurs communs user + Greg
        common_guilds = [g for g in bot_guilds if str(g.id) in user_guild_ids]
        print("[DEBUG] Guilds communs (affichés dans le select):")
        for g in common_guilds:
            print(f" - {g.id} : {g.name}")

        # Salons vocaux pour chaque serveur commun
        for g in common_guilds:
            print(f"   [DEBUG] {g.name} (ID {g.id}) salons vocaux :")
            for c in g.voice_channels:
                print(f"     - {c.id} : {c.name}")

        # Adapter le format si besoin
        guilds_fmt = [{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in common_guilds]
        return render_template("panel.html", guilds=guilds_fmt, user=user)

    @app.route("/api/play", methods=["POST"])
    def api_play():
        data = request.get_json() or request.form
        guild_id = data.get("guild_id")
        url = data.get("url")
        if not guild_id or not url:
            return jsonify({"error": "missing guild_id or url"}), 400
        pm = get_pm(guild_id)
        pm.add(url)
        socketio.emit("playlist_update", pm.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        data = request.get_json() or request.form
        guild_id = data.get("guild_id")
        if not guild_id:
            return jsonify({"error": "missing guild_id"}), 400
        pm = get_pm(guild_id)
        pm.skip()
        socketio.emit("playlist_update", pm.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        data = request.get_json() or request.form
        guild_id = data.get("guild_id")
        if not guild_id:
            return jsonify({"error": "missing guild_id"}), 400
        pm = get_pm(guild_id)
        pm.stop()
        socketio.emit("playlist_update", pm.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"error": "missing guild_id"}), 400
        pm = get_pm(guild_id)
        return jsonify(pm.to_dict())

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
        # Ce WS n'est plus lié à une guild unique !
        pass

    return app, socketio
