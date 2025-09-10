# connect/spotify_backend.py
from __future__ import annotations

import os
import time
import json
import hmac
import base64
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import requests
from flask import request, jsonify, redirect, session

# --- Try to import current_user helper (same pattern as app.py) ---
try:
    from connect.session_auth import current_user, login_required
except Exception:
    try:
        from .session_auth import current_user, login_required
    except Exception:
        from session_auth import current_user, login_required  # type: ignore

# ====== Config (env) ======
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
SPOTIFY_SCOPES = os.getenv(
    "SPOTIFY_SCOPES",
    "playlist-read-private playlist-read-collaborative user-read-email"
)
STATE_SECRET = os.getenv("SPOTIFY_STATE_SECRET", "").encode("utf-8")

# ====== Storage ======
_STORE = Path(".spotify_tokens.json")

def _load_store() -> Dict[str, Any]:
    if _STORE.exists():
        try:
            return json.loads(_STORE.read_text("utf-8"))
        except Exception:
            pass
    return {"users": {}}

def _save_store(data: Dict[str, Any]) -> None:
    _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

def _now() -> int:
    return int(time.time())

def _require_cfg() -> None:
    missing = []
    if not SPOTIFY_CLIENT_ID: missing.append("SPOTIFY_CLIENT_ID")
    if not SPOTIFY_CLIENT_SECRET: missing.append("SPOTIFY_CLIENT_SECRET")
    if not SPOTIFY_REDIRECT_URI: missing.append("SPOTIFY_REDIRECT_URI")
    if not STATE_SECRET: missing.append("SPOTIFY_STATE_SECRET")
    if missing:
        raise RuntimeError(f"Spotify config manquante: {', '.join(missing)}")

# ====== STATE (uid + sid) signé HMAC ======
def _b64u_encode(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).decode("ascii").rstrip("=")

def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _sign(uid: str, sid: str, ts: int) -> str:
    msg = f"{uid}|{sid}|{ts}".encode("utf-8")
    return hmac.new(STATE_SECRET, msg, hashlib.sha256).hexdigest()

def _pack_state(uid: str, sid: str) -> str:
    ts = _now()
    data = {"uid": str(uid), "sid": str(sid or ""), "ts": ts}
    data["sig"] = _sign(data["uid"], data["sid"], data["ts"])
    return _b64u_encode(json.dumps(data, separators=(",", ":")).encode("utf-8"))

def _unpack_state(state: str, max_age: int = 900) -> Tuple[Optional[str], Optional[str]]:
    try:
        raw = json.loads(_b64u_decode(state))
        uid, sid, ts, sig = str(raw.get("uid")), str(raw.get("sid", "")), int(raw.get("ts", 0)), str(raw.get("sig", ""))
        if not uid or not ts or not sig:
            return None, None
        if abs(_now() - ts) > max_age:
            return None, None
        if not hmac.compare_digest(sig, _sign(uid, sid, ts)):
            return None, None
        return uid, sid
    except Exception:
        return None, None

# ====== OAuth helpers ======
def _auth_url(state: str) -> str:
    from urllib.parse import urlencode, quote_plus
    params = {
        "response_type": "code",
        "client_id": SPOTIFY_CLIENT_ID,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SPOTIFY_SCOPES,
        "state": state
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params, quote_via=quote_plus)

def _token_request(data: Dict[str, str]) -> Dict[str, Any]:
    auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_header}"}
    resp = requests.post("https://accounts.spotify.com/api/token", data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _exchange_code_for_token(code: str) -> Dict[str, Any]:
    _require_cfg()
    payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": SPOTIFY_REDIRECT_URI}
    return _token_request(payload)

def _refresh_token(refresh_token: str) -> Dict[str, Any]:
    _require_cfg()
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    return _token_request(payload)

# ====== User tokens ======
def _get_user_tokens(discord_user_id: str) -> Optional[Dict[str, Any]]:
    data = _load_store()
    return data["users"].get(str(discord_user_id))

def _set_user_tokens(discord_user_id: str, tok: Dict[str, Any]) -> None:
    data = _load_store()
    data["users"][str(discord_user_id)] = tok
    _save_store(data)

def _del_user_tokens(discord_user_id: str) -> None:
    data = _load_store()
    data["users"].pop(str(discord_user_id), None)
    _save_store(data)

def _ensure_access_token(discord_user_id: str) -> Tuple[str, Dict[str, Any]]:
    tokens = _get_user_tokens(discord_user_id)
    if not tokens:
        raise RuntimeError("Compte Spotify non lié.")
    access_token = tokens.get("access_token")
    expires_at = int(tokens.get("expires_at") or 0)
    refresh_token = tokens.get("refresh_token")
    if not access_token or _now() >= expires_at - 15:
        if not refresh_token:
            raise RuntimeError("Jeton expiré et pas de refresh_token.")
        new_tok = _refresh_token(refresh_token)
        access_token = new_tok.get("access_token")
        expires_in = int(new_tok.get("expires_in") or 3600)
        tokens["access_token"] = access_token
        tokens["expires_at"] = _now() + expires_in
        if new_tok.get("refresh_token"):
            tokens["refresh_token"] = new_tok["refresh_token"]
        _set_user_tokens(discord_user_id, tokens)
    return access_token, tokens

# ====== Web API helpers ======
def _sp_get(access_token: str, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://api.spotify.com/v1" + path, headers=headers, params=params or {}, timeout=10)
    r.raise_for_status()
    return r.json()

def _me(access_token: str) -> Dict[str, Any]:
    return _sp_get(access_token, "/me")

def _playlists(access_token: str, limit: int = 50) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    url_path = "/me/playlists"
    params = {"limit": min(limit, 50), "offset": 0}
    while True:
        data = _sp_get(access_token, url_path, params=params)
        items.extend(data.get("items") or [])
        if not data.get("next") or len(items) >= limit:
            break
        params["offset"] += params["limit"]
    return items[:limit]

def _playlist_tracks(access_token: str, playlist_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    url_path = f"/playlists/{playlist_id}/tracks"
    params = {"limit": min(limit, 100), "offset": 0, "additional_types": "track,episode"}
    while True:
        data = _sp_get(access_token, url_path, params=params)
        items.extend(data.get("items") or [])
        if not data.get("next") or len(items) >= limit:
            break
        params["offset"] += params["limit"]
    return items[:limit]

# ====== Public: register routes on Flask app ======
def register_spotify_routes(app, socketio=None):
    """
    Call from create_web_app(app, socketio) once to register routes.
    If socketio is provided, emits 'spotify:linked' on callback:
      - room = <socket_id> (sid)
      - room = user:<discord_user_id>
    """
    # try to reuse socketio on app if not passed
    if socketio is None:
        socketio = getattr(app, "socketio", None)

    def _emit(event: str, data: Dict[str, Any], sid: Optional[str], uid: Optional[str]):
        if not socketio:
            return
        try:
            if sid:
                socketio.emit(event, data, room=sid)
            if uid:
                socketio.emit(event, data, room=f"user:{uid}")
        except Exception:
            pass

    @app.route("/spotify/login")
    @login_required
    def spotify_login():
        try:
            _require_cfg()
        except Exception as e:
            return jsonify(error=str(e)), 500

        u = current_user()
        uid = str(u["id"])
        sid = (request.args.get("sid") or "").strip()  # optionnel: socket.id
        state = _pack_state(uid, sid)

        # CSRF: on garde aussi en session pour double protection
        session["spotify_state"] = state
        return redirect(_auth_url(state))

    @app.route("/spotify/callback")
    def spotify_callback():
        err = request.args.get("error")
        if err:
            return f"Spotify auth error: {err}", 400

        code = request.args.get("code")
        state = request.args.get("state") or ""
        if not code or not state:
            return "Missing code/state", 400

        # 1) Vérifie state signé (uid + sid)
        uid_from_state, sid = _unpack_state(state)
        if not uid_from_state:
            return "Invalid state", 400

        # 2) Optionnel: double check CSRF via session (si présent)
        saved = session.pop("spotify_state", None)
        if not saved or saved != state:
            # on continue (le state HMAC suffit), mais on peut logguer si besoin
            pass

        # 3) Si une session Discord est présente, elle doit matcher uid
        u = current_user()
        if u and str(u["id"]) != uid_from_state:
            return "User mismatch", 401

        bind_uid = uid_from_state  # on associe aux tokens de cet utilisateur
        try:
            tok = _exchange_code_for_token(code)
            access_token = tok["access_token"]
            expires_in = int(tok.get("expires_in", 3600))
            refresh_token = tok.get("refresh_token")
            profile = _me(access_token)

            _set_user_tokens(bind_uid, {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": _now() + expires_in,
                "scope": tok.get("scope"),
                "spotify_user": {
                    "id": profile.get("id"),
                    "display_name": profile.get("display_name"),
                },
            })

            payload = {
                "linked": True,
                "profile": {"id": profile.get("id"), "display_name": profile.get("display_name")},
                "scope": tok.get("scope"),
                "uid": bind_uid,
                "sid": sid or None,
            }
            _emit("spotify:linked", payload, sid, bind_uid)

            return (
                "<!doctype html><meta charset='utf-8'>"
                "<title>Spotify lié</title>"
                "<style>body{font-family:system-ui;padding:24px}</style>"
                "<h1>Compte Spotify lié ✅</h1>"
                "<p>Tu peux fermer cette fenêtre.</p>"
                "<script>setTimeout(()=>window.close(), 700);</script>"
            )
        except Exception as e:
            return f"Spotify token exchange failed: {e}", 400

    @app.route("/api/spotify/status")
    @login_required
    def api_spotify_status():
        u = current_user()
        st = _get_user_tokens(u["id"])
        if not st:
            return jsonify(linked=False)
        try:
            access, tokens = _ensure_access_token(u["id"])
            prof = tokens.get("spotify_user") or {}
            return jsonify(linked=True, profile=prof, scope=tokens.get("scope"))
        except Exception as e:
            return jsonify(linked=False, error=str(e))

    @app.route("/api/spotify/me")
    @login_required
    def api_spotify_me():
        u = current_user()
        access, _ = _ensure_access_token(u["id"])
        return jsonify(_me(access))

    @app.route("/api/spotify/playlists")
    @login_required
    def api_spotify_playlists():
        u = current_user()
        limit = int(request.args.get("limit", 50))
        access, _ = _ensure_access_token(u["id"])
        pls = _playlists(access, limit=limit)
        out = []
        for p in pls:
            images = p.get("images") or []
            img = images[0]["url"] if images else None
            out.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "tracks_total": (p.get("tracks") or {}).get("total"),
                "image": img,
                "owner": ((p.get("owner") or {}).get("display_name") or (p.get("owner") or {}).get("id")),
                "public": p.get("public"),
                "snapshot_id": p.get("snapshot_id"),
                "uri": p.get("uri"),
                "href": p.get("href"),
                "external_url": (p.get("external_urls") or {}).get("spotify"),
            })
        return jsonify(playlists=out)

    @app.route("/api/spotify/playlist_tracks")
    @login_required
    def api_spotify_playlist_tracks():
        u = current_user()
        pid = (request.args.get("playlist_id") or "").strip()
        if not pid:
            return jsonify(error="missing playlist_id"), 400
        access, _ = _ensure_access_token(u["id"])
        rows = _playlist_tracks(access, pid, limit=int(request.args.get("limit", 100)))
        out = []
        for it in rows:
            tr = it.get("track") or {}
            if not tr:
                continue
            artists = ", ".join(a.get("name") for a in (tr.get("artists") or []) if a.get("name"))
            alb = tr.get("album") or {}
            imgs = alb.get("images") or []
            img = (imgs[0]["url"] if imgs else None)
            out.append({
                "id": tr.get("id"),
                "name": tr.get("name"),
                "artists": artists,
                "duration_ms": tr.get("duration_ms"),
                "album": alb.get("name"),
                "image": img,
                "is_playable": tr.get("is_playable", True),
                "preview_url": tr.get("preview_url"),
                "external_url": (tr.get("external_urls") or {}).get("spotify"),
                "uri": tr.get("uri"),
            })
        return jsonify(tracks=out)

    # --- helpers internes: choix du 1er bon match YouTube ---
    def _to_seconds(v):
        try:
            iv = int(v);
            return iv // 1000 if iv > 86400 else iv
        except Exception:
            if isinstance(v, str) and v.isdigit(): return int(v)
        return None

    def _yt_first_match(query: str, duration_ms: int | None = None) -> dict | None:
        try:
            from extractors import get_search_module  # paresseux pour éviter cycles
            searcher = get_search_module("youtube")
            rows = searcher.search(query) or []
            if not rows:
                return None
            # Si on a la durée Spotify, privilégier un match proche (+/- 7s ou +/- 10%)
            target = _to_seconds(duration_ms) if duration_ms else None
            if target:
                window = max(7, int(target * 0.10))
                close = []
                for r in rows:
                    d = _to_seconds(r.get("duration"))
                    if d is None:
                        continue
                    if abs(d - target) <= window:
                        # bonus "officiel"
                        ch = (r.get("channel") or r.get("uploader") or "").lower()
                        score = 0
                        if "vevo" in ch or "topic" in ch or "official" in ch: score += 3
                        if "lyrics" in (r.get("title") or "").lower(): score -= 1
                        close.append((score, r))
                if close:
                    close.sort(key=lambda x: (-x[0]))
                    return close[0][1]
            return rows[0]
        except Exception:
            return None

    # --- endpoint one-shot: résout + joue ---
    @app.route("/api/spotify/quickplay", methods=["POST"])
    @login_required
    def api_spotify_quickplay():
        import asyncio
        data = request.get_json(force=True) or {}
        tr = (data.get("track") or {})
        guild_id = (data.get("guild_id") or "").strip()
        name = (tr.get("name") or "").strip()
        artists = (tr.get("artists") or tr.get("artist") or "").strip()
        duration_ms = tr.get("duration_ms")
        image = tr.get("image")
        if not guild_id or not name:
            return jsonify(error="missing guild_id/name"), 400

        query = f"{name} - {artists}" if artists else name
        yt = _yt_first_match(query, duration_ms)
        if not yt:
            return jsonify(ok=False, error="no_youtube_match"), 404

        # Récup bot + Music cog
        bot = getattr(app, "bot", None)
        if not bot:
            return jsonify(error="bot_unavailable"), 500
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return jsonify(error="music_cog_missing"), 500

        u = current_user()
        item = {
            "title": name,
            "url": yt.get("webpage_url") or yt.get("url"),
            "artist": artists or (yt.get("artist") or yt.get("uploader")),
            "duration": _to_seconds(duration_ms) or _to_seconds(yt.get("duration")),
            "thumb": image or yt.get("thumb") or yt.get("thumbnail"),
            "provider": "youtube",
            "mode": "auto",
        }

        loop = getattr(bot, "loop", None)
        try:
            if loop and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    music_cog.play_for_user(guild_id, u["id"], item), loop
                )
                fut.result(timeout=90)
            else:
                new_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(
                        music_cog.play_for_user(guild_id, u["id"], item)
                    )
                finally:
                    try:
                        new_loop.run_until_complete(asyncio.sleep(0))
                    except Exception:
                        pass
                    new_loop.close()
                    asyncio.set_event_loop(None)
        except Exception as e:
            # mêmes codes que /api/play
            msg = str(e).lower()
            if "voice" in msg or "vocal" in msg:
                return jsonify(ok=False, error="Tu dois être en salon vocal.", error_code="USER_NOT_IN_VOICE"), 409
            return jsonify(ok=False, error=str(e)), 500

        return jsonify(ok=True, resolved=item,
                       youtube={"title": yt.get("title"), "url": yt.get("webpage_url") or yt.get("url")})

    @app.route("/api/spotify/logout", methods=["POST"])
    @login_required
    def api_spotify_logout():
        u = current_user()
        _del_user_tokens(u["id"])
        return jsonify(ok=True)
