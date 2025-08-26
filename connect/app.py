# connect/app.py

from __future__ import annotations
from typing import Callable, Any, Dict, Optional, List

from flask import (
    Flask, render_template, render_template_string,
    request, jsonify, session, redirect, url_for
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import os, asyncio, requests, time, secrets
from urllib.parse import quote_plus

# --- Imports helpers (compat: exécution directe OU en package) ---
try:
    from connect.session_auth import (
        login_required, current_user, set_user_session,
        clear_user_session, save_oauth_state, pop_oauth_state, is_logged_in
    )
    from connect.oauth import (
        start_oauth_flow, exchange_code_for_token, fetch_user_me, fetch_user_guilds
    )
except Exception:
    try:
        from .session_auth import (
            login_required, current_user, set_user_session,
            clear_user_session, save_oauth_state, pop_oauth_state, is_logged_in
        )
        from .oauth import (
            start_oauth_flow, exchange_code_for_token, fetch_user_me, fetch_user_guilds
        )
    except Exception:
        from session_auth import (
            login_required, current_user, set_user_session,
            clear_user_session, save_oauth_state, pop_oauth_state, is_logged_in
        )
        from oauth import (
            start_oauth_flow, exchange_code_for_token, fetch_user_me, fetch_user_guilds
        )

# --- Constantes/état overlay (rooms & présence) ---
OVERLAY_ROOM_PREFIX_USER = "user:"
OVERLAY_ROOM_PREFIX_GUILD = "guild:"
ACTIVE_OVERLAY_USERS: Dict[str, float] = {}   # user_id -> last_seen_ts


def create_web_app(get_pm: Callable[[str | int], Any]):
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # 🔥 Autoriser les cookies cross-origin si nécessaire
    CORS(app, supports_credentials=True)

    # 🔧 threading: évite les problèmes websocket avec le dev server Werkzeug
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    # --- Session & sécurité ---
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-override-me")
    app.config.update(
        SESSION_COOKIE_NAME=os.getenv("SESSION_COOKIE_NAME", "gregsid"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "None"),  # <-- None en string
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1",  # <-- doit être True en prod HTTPS
    )

    app.get_pm = get_pm

    # ---- Device Login (OAuth via navigateur par défaut) ----
    DEVICE_BY_STATE: dict[str, str] = {}   # oauth_state -> device_id
    DEVICE_STORE: dict[str, dict] = {}     # device_id -> {"user": {...} or None, "ts": float}
    DEVICE_TTL = 300  # 5 minutes

    def _device_gc():
        now = time.time()
        # purge states or devices trop vieux
        for st, did in list(DEVICE_BY_STATE.items()):
            info = DEVICE_STORE.get(did)
            if not info or (now - info.get("ts", now)) > DEVICE_TTL:
                DEVICE_BY_STATE.pop(st, None)
        for did, info in list(DEVICE_STORE.items()):
            if (now - info.get("ts", now)) > DEVICE_TTL:
                DEVICE_STORE.pop(did, None)

    def _oauth_authorize_url_for_state(state: str) -> str:
        """Construit l'URL d'autorisation Discord SANS toucher à la session (device flow)."""
        client_id = os.environ["DISCORD_CLIENT_ID"]
        redirect  = os.environ["DISCORD_REDIRECT_URI"]
        scopes    = os.getenv("DISCORD_OAUTH_SCOPES", "identify guilds")
        scope_enc = quote_plus(scopes)
        redir_enc = quote_plus(redirect)
        return (
            "https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redir_enc}"
            "&response_type=code"
            f"&scope={scope_enc}"
            f"&state={state}"
        )

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

    def _clean_field(v):
        if v is None:
            return None
        s = str(v).strip().strip('\'" \t\r\n')
        while s.endswith(';'):
            s = s[:-1]
        return s

    # ------------------------ Pages HTML --------------------------
    @app.route("/")
    def index():
        # Fallback si templates/index.html absent (évite 500)
        try:
            return render_template("index.html")
        except Exception:
            return render_template_string(
                "<!doctype html><meta charset='utf-8'>"
                "<title>Greg Overlay</title>"
                "<h1>Greg Overlay</h1>"
                "<p>Pas de <code>templates/index.html</code>. Utilise la fenêtre Paramètres pour te connecter.</p>"
            )

    # ------------------------ AUTH (Discord OAuth2) --------------------------
    # ---- Device flow (navigateur par défaut) ----
    @app.route("/auth/device/start", methods=["POST", "GET"])
    def auth_device_start():
        """Démarre un device-login : retourne device_id + URL à ouvrir dans le navigateur par défaut."""
        _device_gc()
        device_id = secrets.token_urlsafe(16)
        state = secrets.token_urlsafe(24)
        DEVICE_BY_STATE[state] = device_id
        DEVICE_STORE[device_id] = {"user": None, "ts": time.time()}
        login_url = _oauth_authorize_url_for_state(state)  # pas d'écriture session ici
        return jsonify({"device_id": device_id, "login_url": login_url})

    @app.route("/auth/device/poll", methods=["GET"])
    def auth_device_poll():
        """Poll côté overlay: quand user prêt, on SET le cookie de session ici et on renvoie ok."""
        _device_gc()
        device_id = (request.args.get("device_id") or "").strip()
        if not device_id or device_id not in DEVICE_STORE:
            return jsonify({"error": "invalid_device"}), 400
        info = DEVICE_STORE.get(device_id) or {}
        user = info.get("user")
        if not user:
            return jsonify({"pending": True})
        # Dépose la session sur CETTE requête (cookie côté overlay)
        set_user_session(user)
        # Cleanup
        DEVICE_STORE.pop(device_id, None)
        for st, did in list(DEVICE_BY_STATE.items()):
            if did == device_id:
                DEVICE_BY_STATE.pop(st, None)
        return jsonify({"ok": True, "user": {"id": user.get("id"), "username": user.get("username"), "global_name": user.get("global_name")}})

    # ---- Flow classique (webview) ----
    @app.route("/auth/login")
    def auth_login():
        st, url = start_oauth_flow()
        save_oauth_state(st)
        nxt = request.args.get("next")
        if nxt:
            session["post_login_redirect"] = nxt
        return redirect(url)

    @app.route("/auth/callback")
    def auth_callback():
        sent_state = request.args.get("state") or ""
        code = request.args.get("code")
        if not code:
            return _bad_request("code manquant", 400)

        # Branche device flow: state connu côté serveur (pas dans la session)
        if sent_state in DEVICE_BY_STATE:
            device_id = DEVICE_BY_STATE.get(sent_state)
            try:
                tok = exchange_code_for_token(code)
                user = fetch_user_me(tok["access_token"])
                if device_id in DEVICE_STORE:
                    DEVICE_STORE[device_id]["user"] = user
                    DEVICE_STORE[device_id]["ts"] = time.time()
                # Petite page informative dans le navigateur par défaut
                return (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>Greg — Connexion faite</title>"
                    "<style>body{font-family:system-ui;padding:24px}</style>"
                    "<h1>Connexion réussie ✅</h1>"
                    "<p>Retourne à Greg — l’overlay va détecter la connexion.</p>"
                )
            except Exception as e:
                return _bad_request(f"OAuth device échoué: {e}", 400)

        # Sinon: flow classique (session) → vérif CSRF
        saved_state = pop_oauth_state()
        if not saved_state or saved_state != sent_state:
            return _bad_request("state CSRF invalide", 400)

        try:
            tok = exchange_code_for_token(code)
            user = fetch_user_me(tok["access_token"])

            must_guild = os.getenv("RESTRICT_TO_GUILD_ID")
            if must_guild:
                try:
                    guilds = fetch_user_guilds(tok["access_token"])
                    ok = any(str(g.get("id")) == str(must_guild) for g in (guilds or []))
                    if not ok:
                        return _bad_request("Tu n'es pas membre du serveur requis.", 403)
                except Exception:
                    pass

            set_user_session(user)
            redirect_to = session.pop("post_login_redirect", None) or url_for("auth_close")
            return redirect(redirect_to)
        except Exception as e:
            return _bad_request(f"OAuth échoué: {e}", 400)

    @app.route("/auth/logout")
    def auth_logout():
        clear_user_session()
        return redirect(url_for("index"))

    @app.route("/auth/close")
    def auth_close():
        # ferme la fenêtre pop-up une fois la session posée
        return """
    <!doctype html><meta charset="utf-8">
    <title>Connecté</title>
    <script>window.close();</script>
    <p>Connecté. Vous pouvez fermer cette fenêtre.</p>
    """, 200

    @app.route("/api/me")
    def api_me():
        """Retourne l'utilisateur connecté (session) ou 401."""
        u = current_user()
        if not u:
            return jsonify({"error": "auth_required"}), 401
        return jsonify({
            "id": u["id"],
            "username": u.get("username"),
            "global_name": u.get("global_name"),
            "avatar": u.get("avatar"),
        })

    # ------------------------ API JSON ---------------------------
    @app.route("/api/health")
    def api_health():
        _dbg("GET /api/health — oui ça tourne, quelle surprise.")
        # On garde ok=True pour compat ; on ajoute des infos utiles.
        return jsonify(
            ok=True,
            socketio=True,
            active_overlays=len(ACTIVE_OVERLAY_USERS),
            ts=int(time.time())
        )

    # app.py — ajoute :
    @app.route("/api/overlays_online", methods=["GET"])
    def overlays_online():
        gid = (request.args.get("guild_id") or "").strip()
        rows = [{"user_id": uid} for uid, _ts in ACTIVE_OVERLAY_USERS.items()]
        # si tu gères les rooms guild: tu peux filtrer si tu stockes user->guild
        return jsonify(rows)

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
            return jsonify({"queue": [], "current": None, "is_paused": False,
                            "progress": {"elapsed": 0, "duration": None},
                            "thumbnail": None, "repeat_all": False})

        music_cog = app.bot.get_cog("Music") if hasattr(app, "bot") else None
        if not music_cog:
            return jsonify(error="Music cog not ready"), 503

        try:
            gid = int(guild_id)
            payload = music_cog._overlay_payload(gid)  # << SOURCE DE VÉRITÉ
            qlen = len(payload.get("queue") or [])
            cur = payload.get("current")
            print(f"🤦‍♂️ [WEB] GET /api/playlist — guild={guild_id}, "
                  f"payload_queue={qlen}, current={'oui' if cur else 'non'}, "
                  f"elapsed={(payload.get('progress') or {}).get('elapsed', 0)}")
            return jsonify(payload)
        except Exception as e:
            print(f"/api/playlist — 💥 {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/play", methods=["POST"])
    @login_required
    def api_play():
        data = request.get_json(silent=True) or request.form
        raw_url = (data or {}).get("url")
        url = _clean_field(raw_url)
        title = _clean_field((data or {}).get("title")) or url
        guild_id = (data or {}).get("guild_id")

        u = current_user()
        user_id = u["id"] if u else None

        _dbg(f"[api_play] RAW url={raw_url!r}, CLEAN url={url!r}")
        _dbg(f"POST /api/play — title={title!r}, url={url!r}, guild={guild_id}, user_session={user_id}")

        if not all([title, url, guild_id, user_id]):
            return _bad_request("Paramètres manquants : title, url, guild_id (et session utilisateur)")

        music_cog, err = _music_cog_required()
        if err:
            return err

        try:
            extra = {}
            for k in ("thumb", "artist", "duration"):
                v = _clean_field((data or {}).get(k))
                if v is None:
                    continue
                if k == "duration":
                    try:
                        v = int(float(v))
                    except Exception:
                        v = None
                extra[k] = v

            item = {"title": title, "url": url, **extra}
            _dbg(f"[api_play] ITEM FINAL: {item}")

            _dispatch(music_cog.play_for_user(guild_id, user_id, item), timeout=90)
            return jsonify(ok=True)
        except Exception as e:
            _dbg(f"POST /api/play — 💥 Exception : {e}")
            return jsonify(error=str(e)), 500

    @app.route("/api/play_at", methods=["POST"])
    @login_required
    def api_play_at():
        data = request.get_json(silent=True) or {}
        guild_id = (data or {}).get("guild_id")
        index = (data or {}).get("index")
        try:
            idx = int(index)
        except Exception:
            return _bad_request("index invalide")

        if not guild_id:
            return _bad_request("guild_id manquant")

        music_cog, err = _music_cog_required()
        if err:
            return err

        u = current_user()
        try:
            _dispatch(music_cog.play_at_for_web(guild_id, u["id"], idx), timeout=30)
            return jsonify(ok=True, moved_to=0)
        except PermissionError as e:
            return jsonify(error=str(e)), 403
        except Exception as e:
            return jsonify(error=str(e)), 500

    @app.route("/api/pause", methods=["POST"])
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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

    # ------------------------ Jumpscare (HTTP fallback) ----------------------
    @app.route("/api/jumpscare", methods=["POST"])
    def api_jumpscare():
        """
        Déclenche un jumpscare vers l'overlay d'un user (si connecté),
        via HTTP interne protégé (fallback si bridge direct non utilisé).
        """
        needed = os.getenv("OVERLAY_INTERNAL_TOKEN")
        token = request.headers.get("X-Overlay-Token") or request.args.get("token")
        if not needed or token != needed:
            return _bad_request("unauthorized", 401)

        try:
            data = request.get_json(force=True) or {}
        except Exception:
            data = {}

        user_id = str(data.get("user_id") or "").strip()
        if not user_id:
            return _bad_request("user_id manquant", 400)

        effect = (data.get("effect") or "scream").strip()
        img = data.get("img") or None
        sound = data.get("sound") or None
        duration_ms = int(data.get("duration_ms") or 1500)
        message = data.get("message") or None

        try:
            push_jumpscare(user_id, effect, img, sound, duration_ms, message)
            return jsonify(ok=True)
        except Exception as e:
            return _bad_request(str(e), 500)


    # ------------------------ Autocomplete (GET) ------------------
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
                page_url = (r.get("webpage_url") or r.get("url") or "").strip().strip(";")
                if not page_url:
                    continue
                title = r.get("title") or None
                artist = r.get("uploader") or r.get("artist") or r.get("channel") or r.get("author") or None
                duration = _to_seconds(r.get("duration") or r.get("duration_ms"))
                thumb = r.get("thumbnail") or None
                if (not title or not artist or not thumb) and page_url:
                    t2, a2, th2 = _oembed_enrich(page_url)
                    title = title or t2
                    artist = artist or a2
                    thumb = thumb or th2
                item = {
                    "title": title or page_url or "Sans titre",
                    "url": page_url,
                    "webpage_url": page_url,
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

    @socketio.on("overlay_register")
    def ws_overlay_register(data: Optional[Dict[str, Any]] = None):
        """
        Un overlay s'enregistre et rejoint ses rooms :
        - user:<user_id>
        - guild:<guild_id> (si fourni)
        """
        data = data or {}
        uid = str(data.get("user_id") or "").strip()
        gid = str(data.get("guild_id") or "").strip()
        if not uid:
            emit("overlay_registered", {"ok": False, "reason": "missing_user_id"})
            return
        join_room(OVERLAY_ROOM_PREFIX_USER + uid)
        if gid:
            join_room(OVERLAY_ROOM_PREFIX_GUILD + gid)
        ACTIVE_OVERLAY_USERS[uid] = time.time()
        emit("overlay_registered", {"ok": True})

    @socketio.on("overlay_ping")
    def ws_overlay_ping(data: Optional[Dict[str, Any]] = None):
        """Keepalive : l’overlay peut pinger périodiquement pour indiquer sa présence."""
        data = data or {}
        uid = str(data.get("user_id") or "").strip()
        if uid:
            ACTIVE_OVERLAY_USERS[uid] = time.time()

    # ------------------------ Helper jumpscare (bridge direct) ---------------
    def push_jumpscare(
        user_id: int | str,
        effect: str = "scream",
        img: Optional[str] = None,
        sound: Optional[str] = None,
        duration_ms: int = 1500,
        message: Optional[str] = None,
    ) -> bool:
        """
        Envoie un évènement 'jumpscare' à l’overlay de l’utilisateur ciblé.
        L’overlay (HUD) doit écouter `socket.on('jumpscare', handler)`.
        """
        payload = {
            "effect": effect,
            "img": img,
            "sound": sound,
            "duration_ms": int(duration_ms),
            "message": message,
        }
        room = f"{OVERLAY_ROOM_PREFIX_USER}{user_id}"
        socketio.emit("jumpscare", payload, room=room)
        return True

    # Rendez le helper accessible côté bot (bridge intra-process)
    app.push_jumpscare = push_jumpscare  # type: ignore[attr-defined]

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
