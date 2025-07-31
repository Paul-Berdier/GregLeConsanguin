# web/app.py

from flask import Flask, render_template, request, redirect, jsonify, session
from flask_socketio import SocketIO, emit
from web.oauth import oauth_bp
import os

def create_web_app(get_pm):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    socketio = SocketIO(app)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.register_blueprint(oauth_bp)
    app.get_pm = get_pm

    # PAGE ACCUEIL
    @app.route("/")
    def index():
        user = session.get("user")
        return render_template("index.html", user=user)

    # LOGOUT (dégage)
    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    # PAGE DE SÉLECTION (serveur + salon)
    @app.route("/select")
    def select():
        user = session.get("user")
        if not user:
            return redirect("/login")
        user_guild_ids = set(g['id'] for g in user['guilds'])
        bot_guilds = app.bot.guilds
        # Affiche seulement les serveurs où Greg est
        common_guilds = [g for g in bot_guilds if str(g.id) in user_guild_ids]
        guilds_fmt = [{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in common_guilds]
        return render_template("select.html", guilds=guilds_fmt, user=user)

    # PAGE PANEL PRINCIPALE
    @app.route("/panel")
    def panel():
        try:
            print("[DEBUG][/panel] CALL", flush=True)
            user = session.get("user")
            guild_id = request.args.get("guild_id")
            channel_id = request.args.get("channel_id")
            print("[DEBUG][/panel] user:", user, "guild_id:", guild_id, "channel_id:", channel_id, flush=True)
            if not user:
                print("[DEBUG][/panel] PAS DE USER, REDIRECT LOGIN", flush=True)
                return redirect("/login")
            if not guild_id or not channel_id:
                print("[DEBUG][/panel] MISSING guild/channel, REDIRECT /select", flush=True)
                return redirect("/select")
            bot_guilds = app.bot.guilds
            print("[DEBUG][/panel] bot_guilds:", bot_guilds, flush=True)
            guild = next((g for g in bot_guilds if str(g.id) == str(guild_id)), None)
            if not guild:
                print("[DEBUG][/panel] GUILD INTROUVABLE", flush=True)
                return "Serveur introuvable ou Greg n'est pas dessus.", 400
            pm = app.get_pm(guild_id)
            playlist = pm.get_queue()
            current = pm.get_current()
            print("[DEBUG][/panel] RENDER panel.html", flush=True)
            return render_template("panel.html",
                                   guilds=[{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in
                                           bot_guilds],
                                   user=user,
                                   guild_id=guild_id,
                                   channel_id=channel_id,
                                   playlist=playlist,
                                   current=current
                                   )
        except Exception as e:
            import traceback
            print("[FATAL][panel]", e, flush=True)
            print(traceback.format_exc(), flush=True)
            return f"Erreur interne côté Greg :<br><pre>{e}\n{traceback.format_exc()}</pre>", 500

    # === ROUTES API SYNCHRONES DISCORD + WEB ===

    # --- PLAY ---
    @app.route("/api/play", methods=["POST"])
    def api_play():
        data = request.json or request.form
        url = data.get("url")
        guild_id = data.get("guild_id")
        channel_id = data.get("channel_id")
        print("[DEBUG][API/PLAY] Appel reçu :", url, guild_id, channel_id)
        music_cog = app.bot.get_cog("Music")
        print("[DEBUG][API/PLAY] Music cog :", music_cog)
        if not music_cog:
            print("[FATAL][API/PLAY] Music cog introuvable !")
            return jsonify(error="music_cog missing"), 500
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            loop.create_task(music_cog.play_for_user(guild_id, channel_id, url))
            print("[DEBUG][API/PLAY] play_for_user lancé en tâche asynchrone")
        except Exception as e:
            print("[FATAL][API/PLAY] Erreur dans create_task :", e)
            return jsonify(error=str(e)), 500
        # MAJ playlist côté web
        pm = app.get_pm(guild_id)
        socketio.emit("playlist_update", pm.to_dict(), broadcast=True)
        print("[DEBUG][API/PLAY] playlist_update emit envoyé")
        return jsonify(ok=True)

    # --- PAUSE ---
    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(music_cog.pause_for_web(guild_id))
        print(f"[DEBUG][API] pause_for_web({guild_id}) demandé via web.")
        return jsonify(ok=True)

    # --- RESUME ---
    @app.route("/api/resume", methods=["POST"])
    def api_resume():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(music_cog.resume_for_web(guild_id))
        print(f"[DEBUG][API] resume_for_web({guild_id}) demandé via web.")
        return jsonify(ok=True)

    # --- STOP ---
    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(music_cog.stop_for_web(guild_id))
        print(f"[DEBUG][API] stop_for_web({guild_id}) demandé via web.")
        return jsonify(ok=True)

    # --- SKIP ---
    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(music_cog.skip_for_web(guild_id))
        print(f"[DEBUG][API] skip_for_web({guild_id}) demandé via web.")
        return jsonify(ok=True)

    # --- PLAYLIST GET ---
    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        guild_id = request.args.get("guild_id")
        pm = app.get_pm(guild_id) if guild_id else None
        if not pm:
            return jsonify(queue=[], current=None)
        return jsonify(pm.to_dict())

    # --- AUTOCOMPLETE ---
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

    # --- TEXT CHANNELS POUR SELECT ---
    @app.route("/api/text_channels")
    def get_text_channels():
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"error": "missing guild_id"}), 400
        bot = app.bot
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return jsonify({"error": "guild not found"}), 404
        channels = [{"id": c.id, "name": c.name} for c in guild.text_channels]
        print(f"[DEBUG][API] Text channels pour {guild.name}: {channels}")
        return jsonify(channels)

    # --- SOCKET.IO ---
    @socketio.on("connect")
    def ws_connect(auth=None):
        # À la connexion, balance la playlist du 1er serveur (optionnel)
        guilds = app.bot.guilds
        if guilds:
            pm = app.get_pm(guilds[0].id)
            emit("playlist_update", pm.to_dict())
        print("[DEBUG][SocketIO] Nouvelle connexion web. Playlist envoyée !")

    return app, socketio
