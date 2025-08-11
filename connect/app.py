# app.py (à la racine)
# --------------------
# Serveur Flask + Socket.IO pour martyriser Greg depuis ton navigateur.
# - Routes HTML : /, /select, /panel
# - API JSON : /api/play, /api/pause, /api/resume, /api/stop, /api/skip, /api/playlist, /api/text_channels
# - Websocket : envoie "playlist_update" en temps réel
#
# IMPORTANT :
#  - Cette app n’exécute AUCUNE coroutine Discord elle-même ; elle délègue tout
#    au bot via asyncio.run_coroutine_threadsafe(..., app.bot.loop).
#  - app.bot est injecté par main.py : `app, socketio = create_web_app(get_pm) ; app.bot = bot`
#
# Oui, je sais, c’est brillant. Maintenant laisse-moi souffler et exécuter.

from __future__ import annotations

import os
import asyncio
from typing import Callable, Any, Dict

from flask import Flask, render_template, request, redirect, jsonify, session
from flask_socketio import SocketIO, emit

# Si ton oauth est dans web/oauth.py, décommente ceci et adapte l’import
# from web.oauth import oauth_bp
# Si tu as déplacé oauth.py à la racine, utilise :
# from oauth import oauth_bp

# --- Config ---------------------------------------------------------------

def create_web_app(get_pm: Callable[[str | int], Any]):
    """
    Fabrique l'app Flask + Socket.IO.
    `get_pm(guild_id)` est une fonction fournie par main.py qui retourne
    l'instance **PlaylistManager** du serveur demandé.

    L’objet `app.bot` (discord.Bot) est attaché par main.py après création.
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")
    # Oui, on ouvre grand les vannes CORS pour ton front local/railway… joyeux chaos.
    socketio = SocketIO(app, cors_allowed_origins="*")
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.get_pm = get_pm

    # Si tu utilises OAuth Discord, enregistre le blueprint ici :
    # app.register_blueprint(oauth_bp)

    # ------------------------ Helpers internes ----------------------------

    def _dbg(msg: str):
        print(f"🤦‍♂️ [WEB] {msg}")

    def _bad_request(msg: str, code: int = 400):
        _dbg(f"Requête pourrie ({code}) : {msg}")
        return jsonify({"error": msg}), code

    def _bot_required():
        if not getattr(app, "bot", None):
            return _bad_request("Bot Discord non initialisé", 500)
        return None

    def _music_cog_required():
        err = _bot_required()
        if err:
            return None, err
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return None, _bad_request("Music cog manquant (encore bravo…)", 500)
        return music_cog, None

    def _dispatch(coro, timeout=60):
        """Exécute une coroutine Discord sur la loop du bot proprement."""
        fut = asyncio.run_coroutine_threadsafe(coro, app.bot.loop)
        return fut.result(timeout=timeout)

    def _emit_playlist(guild_id: str | int):
        """Récupère l’état et spam le front, parce que tu aimes ça."""
        pm = app.get_pm(guild_id)
        data = pm.to_dict()
        # (Optionnel : ajoute un flag is_paused si tu le gères côté Music)
        socketio.emit("playlist_update", data)
        _dbg(f"Emission socket.io 'playlist_update' pour guild {guild_id} ({len(data.get('queue', []))} items).")

    # ------------------------ Pages HTML ----------------------------------

    @app.route("/")
    def index():
        user = session.get("user")
        _dbg("GET / — page d’accueil, encore une visite… quelle joie.")
        return render_template("index.html", user=user)

    @app.route("/logout")
    def logout():
        session.clear()
        _dbg("GET /logout — session pulvérisée, la paix (temporaire).")
        return redirect("/")

    @app.route("/select")
    def select():
        """Sélection du serveur (guild) commun entre l'utilisateur et le bot."""
        _dbg("GET /select — l’usine à gaz commence ici.")
        user = session.get("user")
        if not user:
            return redirect("/login")
        err = _bot_required()
        if err:
            return err
        user_guild_ids = set(g['id'] for g in user.get('guilds', []))
        bot_guilds = getattr(app.bot, "guilds", [])
        common_guilds = [g for g in bot_guilds if str(g.id) in user_guild_ids]
        guilds_fmt = [{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in common_guilds]
        return render_template("select.html", guilds=guilds_fmt, user=user)

    @app.route("/panel")
    def panel():
        """Panel principal (playlist + contrôles)."""
        _dbg("GET /panel — ah, l’interface de la souffrance.")
        user = session.get("user")
        if not user:
            return redirect("/login")
        guild_id = request.args.get("guild_id")
        channel_id = request.args.get("channel_id")
        if not guild_id or not channel_id:
            return redirect("/select")

        err = _bot_required()
        if err:
            return err
        bot_guilds = app.bot.guilds
        guild = next((g for g in bot_guilds if str(g.id) == str(guild_id)), None)
        if not guild:
            return _bad_request("Serveur introuvable (Greg n'y est pas ?)", 400)

        pm = app.get_pm(guild_id)
        playlist = pm.get_queue()
        current = pm.get_current()
        return render_template(
            "panel.html",
            guilds=[{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in bot_guilds],
            user=user,
            guild_id=guild_id,
            channel_id=channel_id,
            playlist=playlist,
            current=current
        )

    # ------------------------ API JSON ------------------------------------

    @app.route("/api/health")
    def api_health():
        _dbg("GET /api/health — oui ça tourne, quelle surprise.")
        return jsonify(ok=True)

    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"queue": [], "current": None})
        pm = app.get_pm(guild_id)
        data = pm.to_dict()
        _dbg(f"GET /api/playlist — guild={guild_id}, {len(data.get('queue', []))} items.")
        return jsonify(data)

    @app.route("/api/play", methods=["POST"])
    def api_play():
        data = request.get_json(silent=True) or request.form
        title = (data or {}).get("title")
        url = (data or {}).get("url")
        guild_id = (data or {}).get("guild_id")
        user_id = (data or {}).get("user_id")
        _dbg(f"POST /api/play — title={title!r}, url={url!r}, guild={guild_id}, user={user_id}")

        if not all([title, url, guild_id, user_id]):
            return _bad_request("Paramètres manquants : title, url, guild_id, user_id")

        music_cog, err = _music_cog_required()
        if err:
            return err

        try:
            _dispatch(music_cog.play_for_user(guild_id, user_id, {"title": title, "url": url}), timeout=90)
            _emit_playlist(guild_id)
            _dbg("POST /api/play — succès. On ajoute, on souffle, on subit.")
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"POST /api/play — 💥 Exception : {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        _dbg(f"POST /api/pause — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err:
            return err
        try:
            _dispatch(music_cog.pause_for_web(guild_id), timeout=30)
            _emit_playlist(guild_id)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/pause — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/resume", methods=["POST"])
    def api_resume():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        _dbg(f"POST /api/resume — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err:
            return err
        try:
            _dispatch(music_cog.resume_for_web(guild_id), timeout=30)
            _emit_playlist(guild_id)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/resume — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        _dbg(f"POST /api/stop — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err:
            return err
        try:
            _dispatch(music_cog.stop_for_web(guild_id), timeout=30)
            _emit_playlist(guild_id)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/stop — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        _dbg(f"POST /api/skip — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err:
            return err
        try:
            _dispatch(music_cog.skip_for_web(guild_id), timeout=30)
            _emit_playlist(guild_id)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/skip — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/text_channels", methods=["GET"])
    def api_text_channels():
        guild_id = request.args.get("guild_id")
        _dbg(f"GET /api/text_channels — guild={guild_id}")
        err = _bot_required()
        if err:
            return err
        if not guild_id:
            return _bad_request("missing guild_id")
        guild = app.bot.get_guild(int(guild_id))
        if not guild:
            return _bad_request("guild not found", 404)
        channels = [{"id": c.id, "name": c.name} for c in guild.text_channels]
        return jsonify(channels)

    @app.route("/autocomplete", methods=["GET"])
    def autocomplete():
        """Auto‑complétion SoundCloud : renvoie {title,url} pour le front."""
        query = (request.args.get("q") or "").strip()
        _dbg(f"GET /autocomplete — q={query!r}")
        if not query:
            return jsonify(results=[])
        try:
            from extractors import get_search_module
            sc = get_search_module("soundcloud")
            results = sc.search(query) or []
            sugg = [{"title": r.get("title"), "url": r.get("webpage_url") or r.get("url")} for r in results][:5]
            return jsonify(results=sugg)
        except Exception as e:
            _dbg(f"/autocomplete — 💥 {e}")
            return jsonify(results=[])

    # ------------------------ WebSocket -----------------------------------

    @socketio.on("connect")
    def ws_connect(auth: Dict[str, Any] | None = None):
        _dbg("WS connect — encore un client pendu à mes ondes.")
        try:
            guilds = getattr(app.bot, "guilds", [])
            if guilds:
                pm = app.get_pm(guilds[0].id)
                emit("playlist_update", pm.to_dict())
                _dbg("WS connect — playlist initiale envoyée.")
        except Exception as e:
            _dbg(f"WS connect — 💥 {e}")

    return app, socketio


# Lancement direct possible (dev local) :
if __name__ == "__main__":
    # En dev tu peux tester l’app seule, mais en prod c’est main.py qui drive.
    def _fake_pm(_gid):
        from playlist_manager import PlaylistManager
        return PlaylistManager(_gid)

    app, socketio = create_web_app(_fake_pm)
    print("😒 [WEB] Démarrage 'app.py' direct. Très bien. Encore du travail…")
    socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)
