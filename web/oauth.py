# web/app.py

from flask import Flask, render_template, request, redirect, jsonify, session, url_for
from flask_socketio import SocketIO, emit
from web.oauth import oauth_bp
import os

def create_web_app(playlist_manager):
    print("[DEBUG] create_web_app appelée")
    app = Flask(__name__, static_folder="static", template_folder="templates")
    socketio = SocketIO(app)

    # === CONFIGURATION SÉCURITÉ ===
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.register_blueprint(oauth_bp)

    # === PAGE D'ACCUEIL ===
    @app.route("/")
    def index():
        if "user" not in session:
            return redirect("/login")
        return redirect("/panel")

    # === PAGE PANEL UTILISATEUR ===
    @app.route("/panel")
    def panel():
        if "user" not in session:
            return redirect("/login")
        user = session["user"]
        return render_template("panel.html", user=user)

    # === API : ajout musique ===
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
        print(f"[DEBUG] GET /autocomplete appelé, query = {query}")
        if not query:
            return {"results": []}
        from extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        suggestions = [{"title": r["title"], "url": r["url"]} for r in results][:5]
        return {"results": suggestions}

    @socketio.on("connect")
    def ws_connect():
        print("[DEBUG] socketio: client connecté")
        emit("playlist_update", playlist_manager.to_dict())

    return app, socketio
