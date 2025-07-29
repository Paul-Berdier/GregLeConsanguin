# web/app.py

from flask import Flask, render_template, request, redirect, jsonify
from flask_socketio import SocketIO, emit
import os

def create_web_app(playlist_manager):
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

    return app, socketio
