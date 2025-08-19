# web/app.py

from __future__ import annotations
from typing import Callable, Any, Dict, Optional, List

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os, asyncio
import requests


def create_web_app(get_pm: Callable[[str | int], Any]):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    CORS(app)  # 🔥 Autorise les requêtes cross-origin (overlay, overwolf, etc.)

    # 🔧 threading: évite les problèmes websocket avec le dev server Werkzeug
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.get_pm = get_pm

    # ------------------------ Helpers ----------------------------
    def _dbg(msg: str) -> None:
        print(f"🤦‍♂️ [WEB] {msg}")

    def _bad_request(msg: str, code: int = 400):
        _dbg(f"Requête pourrie ({code}) : {msg}")
        return jsonify({"error": msg}), code

    def _bot_required():
        bot = getattr(app, "bot", None)
        if not bot:
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
        """
        Exécute une coroutine sur la loop du bot si existante, sinon dans une
        loop dédiée à ce thread. Remonte les exceptions Python (attrapées par
        l'appelant et renvoyées en JSON propre).
        """
        loop = getattr(getattr(app, "bot", None), "loop", None)
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            return fut.result(timeout=timeout)
        # Fallback (dev / tests): loop dédiée et fermée proprement
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(asyncio.wait_for(coro, timeout))
        finally:
            try:
                new_loop.run_until_complete(asyncio.sleep(0))
            except Exception:
                pass
            new_loop.close()
            asyncio.set_event_loop(None)

    # même structure que le payload Socket.IO
    def _overlay_payload_for(guild_id: int | str) -> Dict[str, Any]:
        music_cog = getattr(app, "bot", None)
        music_cog = music_cog and app.bot.get_cog("Music")
        if music_cog:
            try:
                return music_cog._overlay_payload(int(guild_id))
            except Exception as e:
                _dbg(f"_overlay_payload_for — fallback (music): {e}")

        # 🎵 Fallback si pas de Music cog : on tente avec PlaylistManager
        pm = app.get_pm(guild_id)
        data = pm.to_dict()
        current = data.get("current")

        if isinstance(current, dict):
            return {
                "queue": data.get("queue", []),
                "current": {
                    "title": current.get("title"),
                    "url": current.get("url"),
                    "artist": current.get("artist"),
                    "thumb": current.get("thumb"),
                    "duration": current.get("duration"),
                    "added_by": current.get("added_by"),
                    "ts": current.get("ts"),
                },
                "is_paused": data.get("is_paused", False),
                "progress": {
                    "elapsed": data.get("elapsed", 0),
                    "duration": current.get("duration"),
                },
                "thumbnail": current.get("thumb"),
                "repeat_all": data.get("repeat_all", False),
            }
        else:
            # Aucun morceau en cours
            return {
                "queue": data.get("queue", []),
                "current": None,
                "is_paused": False,
                "progress": {"elapsed": 0, "duration": None},
                "thumbnail": None,
                "repeat_all": False,
            }

    # ------------------------ Pages HTML --------------------------
    @app.route("/")
    def index():
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
        if err:
            return err
        bot = getattr(app, "bot", None)
        bot_guilds = getattr(bot, "guilds", []) or []
        payload = [{"id": str(g.id), "name": g.name} for g in bot_guilds]
        _dbg(f"GET /api/guilds — bot_guilds={len(payload)}")
        return jsonify(payload)

    @app.route("/api/playlist", methods=["GET"])
    def api_playlist():
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({
                "queue": [],
                "current": None,
                "is_paused": False,
                "progress": {"elapsed": 0, "duration": None},
                "thumbnail": None,
                "repeat_all": False
            })

        try:
            # récupération brute PlaylistManager
            pm = get_pm(guild_id)  # ⚠️ assure-toi d’avoir cette fonction dispo comme dans main.py
            queue_raw = getattr(pm, "queue", [])

            # payload enrichi (celui renvoyé normalement)
            payload = _overlay_payload_for(guild_id)

            # 🟢 Ajout debug complet
            _dbg(
                f"GET /api/playlist — guild={guild_id}, "
                f"raw_queue={len(queue_raw)} items {[s.get('title') for s in queue_raw]}, "
                f"payload_queue={len(payload.get('queue', []))}, "
                f"elapsed={payload.get('progress', {}).get('elapsed')}"
            )

            return jsonify(payload)

        except Exception as e:
            _dbg(f"/api/playlist — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/play", methods=["POST"])
    def api_play():
        data = request.get_json(silent=True) or request.form
        title    = (data or {}).get("title")
        url      = (data or {}).get("url")
        guild_id = (data or {}).get("guild_id")
        user_id  = (data or {}).get("user_id")
        # ⚠️ OBLIGATOIRE côté client désormais
        print(f"L'  URL /// {url}")

        _dbg(f"POST /api/play — title={title!r}, url={url!r}, guild={guild_id}, user={user_id}")
        if not all([title, url, guild_id, user_id]):
            return _bad_request("Paramètres manquants : title, url, guild_id, user_id")

        music_cog, err = _music_cog_required()
        if err:
            return err
        try:
            extra = {}
            for k in ("thumb", "artist", "duration"):
                v = (data or {}).get(k)
                if v is not None:
                    extra[k] = v
            item = {"title": title, "url": url, **extra}
            _dispatch(music_cog.play_for_user(guild_id, user_id, item), timeout=90)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"POST /api/play — 💥 Exception : {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        data = request.get_json(force=True); guild_id = data.get("guild_id")
        _dbg(f"POST /api/pause — guild={guild_id}")
        music_cog, err = _music_cog_required()
        if err:
            return err
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
        if err:
            return err
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
        if err:
            return err
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
        if err:
            return err
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
        if err:
            return err
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
        if err:
            return err
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
        if err:
            return err
        try:
            result = _dispatch(music_cog.repeat_for_web(guild_id, mode or None), timeout=30)
            return jsonify(repeat_all=bool(result))
        except Exception as e:
            _dbg(f"/api/repeat — 💥 {e}")
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

    # ------------------------ Autocomplete (GET) ------------------
    # Compat : on expose /autocomplete ET /api/autocomplete
    @app.route("/api/autocomplete", methods=["GET"])
    def autocomplete():
        """
        Recherche (max 3) pour l'UI :
        { results: [{title, url, webpage_url, artist, duration, thumb, provider}] }
        - url = URL DE PAGE (Jamais de CDN HLS)
        - duration en secondes (peut être None)
        - provider: "soundcloud" | "youtube"
        """
        import re
        from urllib.parse import urlparse

        q = (request.args.get("q") or "").strip()
        provider = (request.args.get("provider") or "auto").lower().strip()
        if len(q) < 2:
            return jsonify(results=[])

        _dbg(f"GET /api/autocomplete — q={q!r}, provider={provider}")

        def _search_sync(p: str, query: str):
            try:
                from extractors import get_search_module
                searcher = get_search_module(p)
                rows = searcher.search(query) or []
                return rows
            except Exception as e:
                _dbg(f"extractors search({p}) failed: {e}")
                return []

        def _to_seconds(v):
            if v is None:
                return None
            try:
                iv = int(v)
                return iv // 1000 if iv > 86400 else iv
            except Exception:
                pass
            if isinstance(v, str) and re.match(r"^\d+:\d{2}$", v):
                m, s = v.split(":")
                return int(m) * 60 + int(s)
            return None

        def _oembed_enrich(page_url: str):
            """Retourne (title, author_name, thumbnail_url) si trouvé, sinon (None, None, None)."""
            try:
                host = re.sub(r"^www\.", "", urlparse(page_url).hostname or "")
                if "soundcloud.com" in host:
                    oe = requests.get(
                        "https://soundcloud.com/oembed",
                        params={"format": "json", "url": page_url},
                        timeout=4
                    ).json()
                    return oe.get("title"), oe.get("author_name"), oe.get("thumbnail_url")
                if "youtube.com" in host or "youtu.be" in host:
                    oe = requests.get(
                        "https://www.youtube.com/oembed",
                        params={"format": "json", "url": page_url},
                        timeout=4
                    ).json()
                    return oe.get("title"), oe.get("author_name"), oe.get("thumbnail_url")
            except Exception:
                pass
            return None, None, None

        def _norm(rows, chosen):
            out = []
            for r in rows[:3]:
                # 1) Toujours une URL de page (jamais les CDN m3u8/mp3)
                page_url = (r.get("webpage_url") or r.get("url") or "").strip().strip(";")
                if not page_url:
                    continue
                # 2) Métadonnées initiales
                title = r.get("title") or None
                artist = r.get("uploader") or r.get("artist") or r.get("channel") or r.get("author") or None
                duration = _to_seconds(r.get("duration") or r.get("duration_ms"))
                thumb = r.get("thumbnail") or None
                # 3) Enrichissement via oEmbed si nécessaire
                if (not title or not artist or not thumb) and page_url:
                    t2, a2, th2 = _oembed_enrich(page_url)
                    title = title or t2
                    artist = artist or a2
                    thumb = thumb or th2

                # 4) Nettoyage simple (jamais de ';' ajoutés, pas de CDN)
                item = {
                    "title": title or page_url or "Sans titre",
                    "url": page_url,                  # <- clé que ton front poste à /api/play
                    "webpage_url": page_url,          # <- exposée aussi pour plus de clarté
                    "artist": artist,
                    "duration": duration,
                    "thumb": thumb,
                    "provider": chosen or "unknown",
                }
                out.append(item)
            return out

        try:
            results = []
            chosen = None

            def _run(p):
                nonlocal results, chosen
                rows = _search_sync(p, q)
                if rows and not results:
                    results = rows
                    chosen = p

            if provider == "auto":
                _run("soundcloud")
                if not results:
                    _run("youtube")
            else:
                _run("youtube" if provider == "youtube" else "soundcloud")

            out = _norm(results, chosen or "soundcloud")
            _dbg(f"autocomplete → {len(out)} résultats")
            return jsonify(results=out)
        except Exception as e:
            _dbg(f"/api/autocomplete — 💥 {e}")
            return jsonify(results=[])

    # ------------------------ WebSocket ---------------------------
    @socketio.on("connect")
    def ws_connect(auth: Dict[str, Any] | None = None):
        _dbg("WS connect — encore un client pendu à mes ondes.")
        try:
            guilds = getattr(getattr(app, "bot", None), "guilds", []) or []
            if guilds:
                payload = _overlay_payload_for(guilds[0].id)
                emit("playlist_update", payload)
                _dbg("WS connect — état initial envoyé.")
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
    socketio.run(
        app,
        host="0.0.0.0",
        port=3000,
        allow_unsafe_werkzeug=True,  # dev only
    )
