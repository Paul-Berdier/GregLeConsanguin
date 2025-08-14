# web/app.py
from __future__ import annotations
import os
import asyncio
from typing import Callable, Any, Dict, Optional, List

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os, asyncio
from typing import List, Dict, Any
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
    def _dbg(msg: str): print(f"🤦‍♂️ [WEB] {msg}")

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
        Exécute une coroutine sur la loop du bot si existante, sinon localement.
        """
        loop = getattr(getattr(app, "bot", None), "loop", None)
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            return fut.result(timeout=timeout)
        # Fallback (dev) : run dans la loop courante
        return asyncio.get_event_loop().run_until_complete(asyncio.wait_for(coro, timeout))

    # même structure que le payload Socket.IO
    def _overlay_payload_for(guild_id: int | str) -> Dict[str, Any]:
        music_cog = getattr(app, "bot", None)
        music_cog = music_cog and app.bot.get_cog("Music")
        if music_cog:
            try:
                return music_cog._overlay_payload(int(guild_id))
            except Exception as e:
                _dbg(f"_overlay_payload_for — fallback (music): {e}")

        # Fallback minimal si pas de Music: queue/current only
        pm = app.get_pm(guild_id)
        data = pm.to_dict()
        current = data.get("current")
        thumb = current.get("thumb") if isinstance(current, dict) else None
        return {
            "queue": data.get("queue", []),
            "current": current,
            "is_paused": False,
            "progress": {"elapsed": 0, "duration": None},
            "thumbnail": thumb,
            "repeat_all": False,
        }

    def _sc_search_with_streams(client_id: str, query: str, limit: int = 3, timeout: float = 8.0) -> List[
        Dict[str, Any]]:
        """
        Cherche des pistes SoundCloud et tente d'obtenir un stream direct:
        - On cherche via /search/tracks
        - Pour chaque piste, on inspecte media.transcodings
        - On privilégie 'progressive' (MP3), fallback 'hls'
        - Pour obtenir l'URL signée, on GET <transcoding.url>?client_id=...

        Retour: liste de dicts prêts pour l'overlay.
        """
        ses = requests.Session()
        ses.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })

        # 1) Recherche
        # Doc non officielle: https://api-v2.soundcloud.com/search/tracks?q=...&client_id=...&limit=...
        search_url = "https://api-v2.soundcloud.com/search/tracks"
        params = {
            "q": query,
            "client_id": client_id,
            "limit": max(1, min(limit, 10)),
        }
        r = ses.get(search_url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()

        collection = data.get("collection", []) or []
        out: List[Dict[str, Any]] = []

        for item in collection[:limit]:
            title = item.get("title") or "Sans titre"
            permalink_url = item.get("permalink_url") or ""
            duration_ms = item.get("duration") or 0
            duration = int(round(duration_ms / 1000)) if duration_ms else None
            user = (item.get("user") or {})
            author = user.get("username") or "Unknown"

            stream_url = None

            # 2) Choisir un transcoding (progressive > hls)
            media = item.get("media") or {}
            transcodings = media.get("transcodings") or []
            progressive = None
            hls = None
            for t in transcodings:
                fmt = (t.get("format") or {}).get("protocol")
                if fmt == "progressive" and not progressive:
                    progressive = t
                elif fmt == "hls" and not hls:
                    hls = t

            chosen = progressive or hls
            if chosen and chosen.get("url"):
                # 3) Résoudre l'URL signée
                resolve_url = chosen["url"]
                # Il faut ajouter client_id en query pour obtenir {"url": "<signed_url>"}
                rr = ses.get(resolve_url, params={"client_id": client_id}, timeout=timeout)
                if rr.ok:
                    j = rr.json()
                    candidate = j.get("url")
                    if isinstance(candidate, str) and candidate.startswith("http"):
                        stream_url = candidate

            # 4) Construire l'item
            #   - url = stream direct si disponible, sinon le permalink (plus stable)
            #   - on fournit toujours permalink_url et stream_url (si trouvé)
            out.append({
                "title": title,
                "url": stream_url or permalink_url,  # <- le front utilisera d'abord url
                "provider": "soundcloud",
                "permalink_url": permalink_url,
                "stream_url": stream_url,  # <- utile si tu veux l’exploiter plus tard
                "duration": duration,
                "author": author,
            })

        return out

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
            payload = _overlay_payload_for(guild_id)
            _dbg(
                f"GET /api/playlist — guild={guild_id}, "
                f"items={len(payload.get('queue', []))}, "
                f"elapsed={payload.get('progress',{}).get('elapsed')}"
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
        _dbg(f"GET /api_text_channels — guild={guild_id}")
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
    # --- remplace ENTIEREMENT ta route /api/autocomplete par ceci ---
    @app.route("/api/autocomplete", methods=["GET"])
    def autocomplete():
        """
        Recherche (3 max) + métadonnées pour l'UI :
        { results: [{title, url, artist, duration, thumb, provider}] }
        - url = URL DE PAGE (webpage_url) — pas de HLS/CDN
        - duration en secondes (si connue)
        - provider: "soundcloud" | "youtube"
        """
        import re
        q = (request.args.get("q") or "").strip()
        provider = (request.args.get("provider") or "auto").lower().strip()
        if len(q) < 2:
            return jsonify(results=[])

        _dbg(f"GET /api/autocomplete — q={q!r}, provider={provider}")

        def _search_sync(p: str, query: str):
            try:
                from extractors import get_search_module
                searcher = get_search_module(p)
                return searcher.search(query) or []
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

        def _norm(rows, chosen):
            out = []
            for r in rows[:3]:
                # IMPORTANT: privilégier la page officielle (webpage_url)
                page_url = r.get("webpage_url") or r.get("url") or ""
                out.append({
                    "title": r.get("title") or page_url or "Sans titre",
                    "url": page_url,  # <- URL DE PAGE (clé pour le stream côté bot)
                    "artist": r.get("uploader") or r.get("artist") or r.get("channel") or r.get("author"),
                    "duration": _to_seconds(r.get("duration") or r.get("duration_ms")),
                    "thumb": r.get("thumbnail"),
                    "provider": chosen,
                })
                print(f"L'  URL autocomplete /// {out}")
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

            return jsonify(results=_norm(results, chosen or "soundcloud"))
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
