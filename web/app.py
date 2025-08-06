from flask import Flask, render_template, request, redirect, jsonify, session
from flask_socketio import SocketIO, emit
from web.oauth import oauth_bp
import os
import asyncio

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

    # LOGOUT
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
        common_guilds = [g for g in bot_guilds if str(g.id) in user_guild_ids]
        guilds_fmt = [{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in common_guilds]
        return render_template("select.html", guilds=guilds_fmt, user=user)

    # PAGE PANEL PRINCIPALE
    @app.route("/panel")
    def panel():
        try:
            user = session.get("user")
            guild_id = request.args.get("guild_id")
            channel_id = request.args.get("channel_id")
            if not user:
                return redirect("/login")
            if not guild_id or not channel_id:
                return redirect("/select")
            bot_guilds = app.bot.guilds
            guild = next((g for g in bot_guilds if str(g.id) == str(guild_id)), None)
            if not guild:
                return "Serveur introuvable ou Greg n'est pas dessus.", 400
            pm = app.get_pm(guild_id)

            # Correction ici : Création d'une event loop pour chaque accès async
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            playlist = pm.get_queue()  # direct, pas async
            current = pm.get_current()  # direct, pas async
            loop.close()

            return render_template(
                "panel.html",
                guilds=[{"id": str(g.id), "name": g.name, "icon": getattr(g, "icon", None)} for g in bot_guilds],
                user=user,
                guild_id=guild_id,
                channel_id=channel_id,
                playlist=playlist,
                current=current
            )
        except Exception as e:
            import traceback
            return f"Erreur interne côté Greg :<br><pre>{e}\n{traceback.format_exc()}</pre>", 500

    # --- PLAY (corrigé) ---
    @app.route("/api/play", methods=["POST"])
    def api_play():
        data = request.json or request.form
        title = data.get("title")  # <-- On récupère bien le titre
        url = data.get("url")      # <-- ... et l'URL
        guild_id = data.get("guild_id")
        user_id = data.get("user_id")
        print(f"[DEBUG][API_PLAY] Reçu : title={title}, url={url}, guild_id={guild_id}, user_id={user_id}")

        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            print("[ERROR] Music cog non chargé")
            return jsonify(error="music_cog missing"), 500

        if not url or not title:
            print("[ERROR] Titre ou URL manquants")
            return jsonify(error="url or title missing"), 400

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # Passe un dict {"title": ..., "url": ...} à play_for_user
            print(f"[DEBUG][API_PLAY] Appel à play_for_user avec track={{'title': '{title}', 'url': '{url}'}}")
            loop.run_until_complete(music_cog.play_for_user(guild_id, user_id, {"title": title, "url": url}))
            pm = app.get_pm(guild_id)
            print("[DEBUG][API_PLAY] Emission de la playlist via socketio.emit")
            socketio.emit("playlist_update", pm.to_dict())
            loop.close()
            print("[DEBUG][API_PLAY] Succès /api/play")
        except Exception as e:
            import traceback
            print(f"[ERROR][API_PLAY] Exception : {e}")
            return jsonify(error=str(e), trace=traceback.format_exc()), 500

        return jsonify(ok=True)

    # --- PAUSE ---
    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(music_cog.pause_for_web(guild_id))
            loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify(ok=True)

    # --- RESUME ---
    @app.route("/api/resume", methods=["POST"])
    def api_resume():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(music_cog.resume_for_web(guild_id))
            loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify(ok=True)

    # --- STOP ---
    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(music_cog.stop_for_web(guild_id))
            loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify(ok=True)

    # --- SKIP ---
    @app.route("/api/skip", methods=["POST"])
    def api_skip():
        data = request.get_json(force=True)
        guild_id = data.get("guild_id")
        music_cog = app.bot.get_cog("Music")
        if not music_cog:
            return jsonify({"error": "Music cog not loaded"}), 500
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(music_cog.skip_for_web(guild_id))
            loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify(ok=True)

    # --- PLAYLIST GET ---
    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        guild_id = request.args.get("guild_id")
        pm = app.get_pm(guild_id) if guild_id else None
        if not pm:
            return jsonify(queue=[], current=None)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = pm.to_dict()  # Sûr, car to_dict n'est pas async !
        loop.close()
        return jsonify(result)

    # --- AUTOCOMPLETE ---
    @app.route("/autocomplete", methods=["GET"])
    def autocomplete():
        query = request.args.get("q", "").strip()
        if not query:
            return {"results": []}
        from extractors import get_search_module
        extractor = get_search_module("soundcloud")
        results = extractor.search(query)
        # On propose un dict avec titre et url
        suggestions = [{"title": r["title"], "url": r.get("webpage_url") or r.get("url")} for r in results][:5]
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
        return jsonify(channels)

    # --- SOCKET.IO ---
    @socketio.on("connect")
    def ws_connect(auth=None):
        guilds = app.bot.guilds
        if guilds:
            pm = app.get_pm(guilds[0].id)
            emit("playlist_update", pm.to_dict())
        print("[DEBUG][SocketIO] Nouvelle connexion web. Playlist envoyée !")

    return app, socketio
