# web/app.py
from __future__ import annotations
import os
import asyncio
from typing import Callable, Any, Dict
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS


def create_web_app(get_pm: Callable[[str | int], Any]):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    CORS(app)  # 🔥 ajoute ça pour autoriser les fetch cross-origin
    socketio = SocketIO(app, cors_allowed_origins="*")
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.get_pm = get_pm

    # ------------------------ Helpers ----------------------------
    def _dbg(msg: str): print(f"🤦‍♂️ [WEB] {msg}")
    def _bad_request(msg: str, code: int = 400):
        _dbg(f"Requête pourrie ({code}) : {msg}")
        return jsonify({"error": msg}), code
    def _bot_required():
        if not getattr(app, "bot", None):
            return _bad_request("Bot Discord non initialisé", 500)
        return None
    def _music_cog_required():
        err = _bot_required()
        if err: return None, err
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return None, _bad_request("Music cog manquant (encore bravo…)", 500)
        return music_cog, None
    def _dispatch(coro, timeout=60):
        fut = asyncio.run_coroutine_threadsafe(coro, app.bot.loop)
        return fut.result(timeout=timeout)

    # ------------------------ Pages HTML --------------------------
    @app.route("/")
    def index():
        # Sert l’overlay (templates/index.html)
        # Pas d’auth: l’overlay renseigne lui-même guild_id + user_id côté client
        return render_template("index.html")

    # ------------------------ API JSON ---------------------------
    @app.route("/api/health")
    def api_health():
        _dbg("GET /api/health — oui ça tourne, quelle surprise.")
        return jsonify(ok=True)

    @app.route("/api/guilds", methods=["GET"])
    def api_guilds():
        """Retourne simplement les serveurs où le bot est présent."""
        err = _bot_required()
        if err: return err
        bot_guilds = getattr(app.bot, "guilds", [])
        payload = [{"id": str(g.id), "name": g.name} for g in bot_guilds]
        _dbg(f"GET /api/guilds — bot_guilds={len(payload)}")
        return jsonify(payload)

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
        title    = (data or {}).get("title")
        url      = (data or {}).get("url")
        guild_id = (data or {}).get("guild_id")
        user_id  = (data or {}).get("user_id")  # ⚠️ OBLIGATOIRE côté client désormais

        _dbg(f"POST /api/play — title={title!r}, url={url!r}, guild={guild_id}, user={user_id}")
        if not all([title, url, guild_id, user_id]):
            return _bad_request("Paramètres manquants : title, url, guild_id, user_id")

        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.play_for_user(guild_id, user_id, {"title": title, "url": url}), timeout=90)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"POST /api/play — 💥 Exception : {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/pause — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.pause_for_web(guild_id), timeout=30)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/pause — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/resume", methods=["POST"])
    def api_resume():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/resume — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.resume_for_web(guild_id), timeout=30)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/resume — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/stop — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.stop_for_web(guild_id), timeout=30)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/stop — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/skip — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.skip_for_web(guild_id), timeout=30)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/skip — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/toggle_pause", methods=["POST"])
    def api_toggle_pause():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/toggle_pause — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.toggle_pause_for_web(guild_id), timeout=30)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/toggle_pause — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/restart", methods=["POST"])
    def api_restart():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/restart — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            _dispatch(music_cog.restart_current_for_web(guild_id), timeout=30)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"/api/restart — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/repeat", methods=["POST"])
    def api_repeat():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        mode = (data.get("mode") or "").lower().strip() if isinstance(data, dict) else ""
        _dbg(f"POST /api/repeat — guild={guild_id}, mode={mode or 'toggle'}")
        music_cog, err = _music_cog_required()
        if err: return err
        try:
            result = _dispatch(music_cog.repeat_for_web(guild_id, mode or None), timeout=30)
            return jsonify(repeat_all=bool(result))
        except Exception as e:
            _dbg(f"/api/repeat — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/text_channels", methods=["GET"])
    def api_text_channels():
        guild_id = request.args.get("guild_id")
        _dbg(f"GET /api_text_channels — guild={guild_id}")
        err = _bot_required()
        if err: return err
        if not guild_id:
            return _bad_request("missing guild_id")
        guild = app.bot.get_guild(int(guild_id))
        if not guild:
            return _bad_request("guild not found", 404)
        channels = [{"id": c.id, "name": c.name} for c in guild.text_channels]
        return jsonify(channels)

    # ------------------------ WebSocket ---------------------------
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

    # --- Debug : afficher toutes les routes enregistrées ---
    print("\n📜 Routes Flask enregistrées :")
    for rule in app.url_map.iter_rules():
        methods = ",".join(rule.methods - {"HEAD", "OPTIONS"})
        print(f"  {methods:10s} {rule.rule}")
    print()

    return app, socketio

if __name__ == "__main__":
    def _fake_pm(_gid):
        from playlist_manager import PlaylistManager
        return PlaylistManager(_gid)
    app, socketio = create_web_app(_fake_pm)
    print("😒 [WEB] Démarrage 'app.py' direct.")
    socketio.run(app, host="0.0.0.0", port=3000, allow_unsafe_werkzeug=True)
