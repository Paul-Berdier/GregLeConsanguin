# web/app.py

from flask import Flask, render_template, request, redirect, jsonify
from flask_socketio import SocketIO, emit

import os
print("=== DEBUG CWD:", os.getcwd())
print("=== DEBUG LIST templates:", os.listdir("web/templates"))
print("=== DEBUG PATH index.html:", os.path.exists("web/templates/index.html"))
print("=== DEBUG ABS INDEX:", os.path.abspath("web/templates/index.html"))

print("[DEBUG] Import app.py OK")

def create_web_app(playlist_manager):
    print("[DEBUG] create_web_app appelée")
    app = Flask(__name__, static_folder="web/static", template_folder="web/templates")
    socketio = SocketIO(app)

from flask import Flask, render_template_string

    @app.route("/")
    def index():
        print("[DEBUG] GET / appelé")
        playlist = playlist_manager.get_queue()
        current = playlist_manager.get_current()
        return render_template("index.html", playlist=playlist, current=current)

    @app.route("/api/play", methods=["POST"])
    def api_play():
        url = request.json["url"]
        print(f"[DEBUG] POST /api/play appelé avec url = {url}")
        playlist_manager.add(url)
        socketio.emit("playlist_update", playlist_manager.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        print("[DEBUG] POST /api/skip appelé")
        playlist_manager.skip()
        socketio.emit("playlist_update", playlist_manager.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        print("[DEBUG] POST /api/stop appelé")
        playlist_manager.stop()
        socketio.emit("playlist_update", playlist_manager.to_dict(), broadcast=True)
        return jsonify(ok=True)

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        print("[DEBUG] POST /api/pause appelé")
        # À compléter si tu veux piloter un vrai player, sinon laisse en no-op
        return jsonify(ok=True)

    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        print("[DEBUG] GET /api/playlist appelé")
        return jsonify(playlist_manager.to_dict())

    @app.route("/autocomplete", methods=["GET"])
    def autocomplete():
        query = request.args.get("q", "")
        print(f"[DEBUG] GET /autocomplete appelé, query = {query}")
        if not query.strip():
            return {"results": []}
        from extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        suggestions = [{"title": r["title"], "url": r["url"]} for r in results][:5]
        return {"results": suggestions}

    @app.route("/search", methods=["POST"])
    def search():
        query = request.form["url"]
        print(f"[DEBUG] POST /search appelé avec query = {query}")
        from extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        return render_template("search_results.html", results=results, query=query)

    @socketio.on("connect")
    def ws_connect():
        print("[DEBUG] socketio: client connecté")
        emit("playlist_update", playlist_manager.to_dict())

        print("[DEBUG] create_web_app terminé, prêt à return")
        return app, socketio

