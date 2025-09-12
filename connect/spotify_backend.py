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

# =============================================================================
#                               CONFIG / ENV
# =============================================================================
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
SPOTIFY_SCOPES = os.getenv(
    "SPOTIFY_SCOPES",
    # Add/keep modify scopes so we can create playlists & add tracks
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private "
    "user-read-email"
)
STATE_SECRET = os.getenv("SPOTIFY_STATE_SECRET", "").encode("utf-8")

# Small helper for consistent logs
def _log(msg: str, **kw: Any) -> None:
    """
    Print a single-line JSON-ish debug message prefixed with [SPOTIFY].
    Avoid logging secrets!
    """
    if kw:
        try:
            safe = json.dumps(kw, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            safe = str(kw)
        print(f"[SPOTIFY] {msg} {safe}")
    else:
        print(f"[SPOTIFY] {msg}")

# On boot, log minimal cfg presence (pas de secrets dans les logs)
_log("Config loaded", has_client_id=bool(SPOTIFY_CLIENT_ID), has_client_secret=bool(SPOTIFY_CLIENT_SECRET),
     has_redirect=bool(SPOTIFY_REDIRECT_URI), scopes=SPOTIFY_SCOPES, has_state_secret=bool(STATE_SECRET))


# =============================================================================
#                               TOKEN STORE (DISK)
# =============================================================================
_STORE = Path(".spotify_tokens.json")

def _load_store() -> Dict[str, Any]:
    """Load the on-disk token store; returns basic structure if empty."""
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text("utf-8"))
            return data
    except Exception as e:
        _log("Failed to load token store, using empty", error=str(e))
    return {"users": {}}

def _save_store(data: Dict[str, Any]) -> None:
    """Persist the token store safely."""
    try:
        _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        _log("Failed to save token store", error=str(e))


def _now() -> int:
    return int(time.time())


def _require_cfg() -> None:
    """Raises if mandatory env vars are missing."""
    missing = []
    if not SPOTIFY_CLIENT_ID: missing.append("SPOTIFY_CLIENT_ID")
    if not SPOTIFY_CLIENT_SECRET: missing.append("SPOTIFY_CLIENT_SECRET")
    if not SPOTIFY_REDIRECT_URI: missing.append("SPOTIFY_REDIRECT_URI")
    if not STATE_SECRET: missing.append("SPOTIFY_STATE_SECRET")
    if missing:
        _log("Missing Spotify env config", missing=missing)
        raise RuntimeError(f"Spotify config manquante: {', '.join(missing)}")


# =============================================================================
#                        STATE (uid + sid) signé HMAC
# =============================================================================
def _b64u_encode(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).decode("ascii").rstrip("=")

def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _sign(uid: str, sid: str, ts: int) -> str:
    msg = f"{uid}|{sid}|{ts}".encode("utf-8")
    return hmac.new(STATE_SECRET, msg, hashlib.sha256).hexdigest()

def _pack_state(uid: str, sid: str) -> str:
    """Pack uid/sid/ts into a signed compact state string for OAuth."""
    ts = _now()
    data = {"uid": str(uid), "sid": str(sid or ""), "ts": ts}
    data["sig"] = _sign(data["uid"], data["sid"], data["ts"])
    enc = _b64u_encode(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    _log("STATE packed", uid=str(uid), sid=str(sid or ""), ts=ts)
    return enc

def _unpack_state(state: str, max_age: int = 900) -> Tuple[Optional[str], Optional[str]]:
    """Unpack & verify state; returns (uid, sid) or (None, None)."""
    try:
        raw = json.loads(_b64u_decode(state))
        uid = str(raw.get("uid"))
        sid = str(raw.get("sid", ""))
        ts  = int(raw.get("ts", 0))
        sig = str(raw.get("sig", ""))
        if not uid or not ts or not sig:
            _log("STATE missing fields", raw=raw)
            return None, None
        if abs(_now() - ts) > max_age:
            _log("STATE expired", issued_at=ts, now=_now(), max_age=max_age)
            return None, None
        if not hmac.compare_digest(sig, _sign(uid, sid, ts)):
            _log("STATE signature mismatch")
            return None, None
        _log("STATE verified", uid=uid, sid=sid)
        return uid, sid
    except Exception as e:
        _log("STATE unpack error", error=str(e))
        return None, None


# =============================================================================
#                           SPOTIFY OAUTH HELPERS
# =============================================================================
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
    """POST /api/token with client creds; raises for non-2xx."""
    auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_header}"}
    _log("POST /api/token", grant_type=data.get("grant_type"))
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


# =============================================================================
#                            USER TOKENS (per Discord UID)
# =============================================================================
def _get_user_tokens(discord_user_id: str) -> Optional[Dict[str, Any]]:
    data = _load_store()
    tok = data["users"].get(str(discord_user_id))
    _log("Loaded user tokens", uid=str(discord_user_id), exists=bool(tok))
    return tok

def _set_user_tokens(discord_user_id: str, tok: Dict[str, Any]) -> None:
    data = _load_store()
    data["users"][str(discord_user_id)] = tok
    _save_store(data)
    _log("Saved user tokens", uid=str(discord_user_id), has_refresh=bool(tok.get("refresh_token")))

def _del_user_tokens(discord_user_id: str) -> None:
    data = _load_store()
    existed = data["users"].pop(str(discord_user_id), None) is not None
    _save_store(data)
    _log("Deleted user tokens", uid=str(discord_user_id), existed=existed)

def _ensure_access_token(discord_user_id: str) -> Tuple[str, Dict[str, Any]]:
    """
    Returns a valid access_token (refreshing if needed) + full token dict.
    Raises if nothing linked.
    """
    tokens = _get_user_tokens(discord_user_id)
    if not tokens:
        _log("Access token requested but account not linked", uid=str(discord_user_id))
        raise RuntimeError("Compte Spotify non lié.")

    access_token = tokens.get("access_token")
    expires_at = int(tokens.get("expires_at") or 0)
    refresh_token = tokens.get("refresh_token")

    if not access_token or _now() >= expires_at - 15:
        _log("Access token expired or missing, refreshing…", uid=str(discord_user_id))
        if not refresh_token:
            _log("No refresh_token present, cannot refresh", uid=str(discord_user_id))
            raise RuntimeError("Jeton expiré et pas de refresh_token.")
        new_tok = _refresh_token(refresh_token)
        access_token = new_tok.get("access_token")
        expires_in = int(new_tok.get("expires_in") or 3600)
        tokens["access_token"] = access_token
        tokens["expires_at"] = _now() + expires_in
        if new_tok.get("refresh_token"):
            tokens["refresh_token"] = new_tok["refresh_token"]
        _set_user_tokens(discord_user_id, tokens)
        _log("Access token refreshed", uid=str(discord_user_id), expires_in=expires_in)

    return access_token, tokens


# =============================================================================
#                           SPOTIFY WEB API WRAPPERS
# =============================================================================
def _sp_get(access_token: str, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    url = "https://api.spotify.com/v1" + path
    _log("GET Spotify API", path=path, params=bool(params))
    r = requests.get(url, headers=headers, params=params or {}, timeout=10)
    r.raise_for_status()
    return r.json()

def _me(access_token: str) -> Dict[str, Any]:
    return _sp_get(access_token, "/me")

def _playlists(access_token: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch current user's playlists (paginated)."""
    items: List[Dict[str, Any]] = []
    url_path = "/me/playlists"
    params = {"limit": min(limit, 50), "offset": 0}
    while True:
        data = _sp_get(access_token, url_path, params=params)
        chunk = data.get("items") or []
        items.extend(chunk)
        _log("Fetched playlists page", count=len(chunk), total=len(items), next=bool(data.get("next")))
        if not data.get("next") or len(items) >= limit:
            break
        params["offset"] += params["limit"]
    return items[:limit]

def _playlist_tracks(access_token: str, playlist_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch tracks of a playlist (paginated)."""
    items: List[Dict[str, Any]] = []
    url_path = f"/playlists/{playlist_id}/tracks"
    params = {"limit": min(limit, 100), "offset": 0, "additional_types": "track,episode"}
    while True:
        data = _sp_get(access_token, url_path, params=params)
        chunk = data.get("items") or []
        items.extend(chunk)
        _log("Fetched playlist_tracks page", pid=playlist_id, got=len(chunk), total=len(items), next=bool(data.get("next")))
        if not data.get("next") or len(items) >= limit:
            break
        params["offset"] += params["limit"]
    return items[:limit]

def _sp_post(access_token: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """POST to Spotify v1; raises on non-2xx."""
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    url = "https://api.spotify.com/v1" + path
    _log("POST Spotify API", path=path)
    r = requests.post(url, headers=headers, json=json_body or {}, timeout=10)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        # Some endpoints return 201 with empty body; normalize to {}
        return {}

def _search_tracks(access_token: str, q: str, limit: int = 5) -> List[Dict[str, Any]]:
    data = _sp_get(access_token, "/search", params={"q": q, "type": "track", "limit": min(limit, 50)})
    rows = (data.get("tracks") or {}).get("items") or []
    _log("Search tracks", q=q, results=len(rows))
    return rows

def _add_tracks_to_playlist(access_token: str, playlist_id: str, uris: List[str]) -> Dict[str, Any]:
    # Spotify limite à 100 URIs par appel
    _log("Add tracks to playlist", pid=playlist_id, count=len(uris))
    return _sp_post(access_token, f"/playlists/{playlist_id}/tracks", {"uris": uris[:100]})

def _create_playlist(access_token: str, user_id: str, name: str, public: bool, description: Optional[str]) -> Dict[str, Any]:
    body = {"name": name, "public": bool(public)}
    if description:
        body["description"] = description
    _log("Create playlist", owner=user_id, name=name, public=bool(public))
    return _sp_post(access_token, f"/users/{user_id}/playlists", body)

def _sp_delete(access_token: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """DELETE générique sur Web API Spotify. JSON facultatif (utile pour /tracks)."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    r = requests.delete("https://api.spotify.com/v1" + path, headers=headers, json=json_body or {}, timeout=10)
    # Beaucoup d’endpoints DELETE renvoient 200/204 sans corps → on tolère l’absence de JSON
    if r.status_code >= 400:
        r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {}

def _unfollow_playlist(access_token: str, playlist_id: str) -> Dict[str, Any]:
    """
    'Supprimer' une playlist côté utilisateur = se désabonner (DELETE /playlists/{id}/followers).
    Si l’utilisateur est le propriétaire, elle disparaît de sa bibliothèque.
    """
    return _sp_delete(access_token, f"/playlists/{playlist_id}/followers")

def _remove_tracks_from_playlist(access_token: str, playlist_id: str, uris: List[str]) -> Dict[str, Any]:
    """
    Supprime des éléments d’une playlist via DELETE /playlists/{id}/tracks
    Par paquets de 100 URIs.
    """
    last = {}
    batch = []
    for uri in uris:
        if not uri:
            continue
        batch.append({"uri": uri})
        # Spotify limite le payload
        if len(batch) >= 100:
            last = _sp_delete(access_token, f"/playlists/{playlist_id}/tracks", {"tracks": batch})
            batch.clear()
    if batch:
        last = _sp_delete(access_token, f"/playlists/{playlist_id}/tracks", {"tracks": batch})
    return last

def _build_track_query(title: Optional[str], artist: Optional[str]) -> str:
    t = (title or "").strip()
    a = (artist or "").strip()
    if t and a:
        return f"{t} {a}"
    return t or a or ""


# =============================================================================
#                      PUBLIC: register routes on Flask app
# =============================================================================
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

    # --- helpers: read playlist + editability ---------------------------------
    import requests

    def _get_playlist(access_token: str, playlist_id: str, fields: str | None = None) -> dict:
        """
        GET /v1/playlists/{playlist_id}
        Retourne le JSON de la playlist (raise si 4xx/5xx).
        """
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {}
        if fields:
            params["fields"] = fields
        r = requests.get(url, headers=headers, params=params, timeout=8)
        if r.status_code == 404:
            raise ValueError("playlist_not_found")
        r.raise_for_status()
        return r.json()

    def _assert_can_edit_playlist(access_token: str, user_spotify_id: str, playlist_id: str) -> dict:
        """
        Vérifie que l’utilisateur peut modifier la playlist :
          - owner == user_spotify_id  OU  playlist collaborative.
        Retourne l’objet playlist (au passage).
        """
        pl = _get_playlist(
            access_token,
            playlist_id,
            fields="id,name,owner(id),collaborative,public,uri"
        )
        owner_id = (pl.get("owner") or {}).get("id")
        is_collab = bool(pl.get("collaborative"))
        if not (owner_id == user_spotify_id or is_collab):
            # 403 "Forbidden" côté Spotify arrive aussi si scopes insuffisants.
            raise PermissionError("not_owner_or_collaborator")
        return pl

    def _emit(event: str, data: Dict[str, Any], sid: Optional[str], uid: Optional[str]):
        if not socketio:
            _log("SocketIO not available; skip emit", event=event)
            return
        try:
            if sid:
                socketio.emit(event, data, room=sid)
            if uid:
                socketio.emit(event, data, room=f"user:{uid}")
            _log("Socket emit done", event=event, sid=bool(sid), uid=bool(uid))
        except Exception as e:
            _log("Socket emit failed", event=event, error=str(e))

    def _playlist_is_editable(access_token: str, playlist_id: str, me_id: str) -> bool:
        info = _get_playlist(access_token, playlist_id)  # GET /v1/playlists/{id}
        owner_id = ((info or {}).get("owner") or {}).get("id")
        is_collab = bool((info or {}).get("collaborative"))
        return (owner_id == me_id) or is_collab


    # -------------------------------------------------------------------------
    @app.route("/spotify/login")
    @login_required
    def spotify_login():
        _log("Route /spotify/login")
        try:
            _require_cfg()
        except Exception as e:
            _log("Config invalid on /spotify/login", error=str(e))
            return jsonify(error=str(e)), 500

        u = current_user()
        uid = str(u["id"])
        sid = (request.args.get("sid") or "").strip()  # optionnel: socket.id
        state = _pack_state(uid, sid)

        # CSRF: on garde aussi en session pour double protection
        session["spotify_state"] = state
        url = _auth_url(state)
        _log("Redirect to Spotify /authorize", uid=uid, has_sid=bool(sid))
        return redirect(url)

    # -------------------------------------------------------------------------
    @app.route("/spotify/callback")
    def spotify_callback():
        _log("Route /spotify/callback", args=dict(request.args))
        err = request.args.get("error")
        if err:
            _log("Callback error", error=err)
            return f"Spotify auth error: {err}", 400

        code = request.args.get("code")
        state = request.args.get("state") or ""
        if not code or not state:
            _log("Callback missing code/state")
            return "Missing code/state", 400

        uid_from_state, sid = _unpack_state(state)
        if not uid_from_state:
            _log("Callback state invalid")
            return "Invalid state", 400

        saved = session.pop("spotify_state", None)
        if not saved or saved != state:
            _log("Callback CSRF state mismatch (session missing or different)")

        u = current_user()
        if u and str(u["id"]) != uid_from_state:
            _log("Callback user mismatch", current_uid=str(u["id"]), state_uid=uid_from_state)
            return "User mismatch", 401

        bind_uid = uid_from_state
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
            _log("Spotify linked OK", uid=bind_uid, sid=bool(sid), display_name=profile.get("display_name"))

            return (
                "<!doctype html><meta charset='utf-8'>"
                "<title>Spotify lié</title>"
                "<style>body{font-family:system-ui;padding:24px}</style>"
                "<h1>Compte Spotify lié ✅</h1>"
                "<p>Tu peux fermer cette fenêtre.</p>"
                "<script>setTimeout(()=>window.close(), 700);</script>"
            )
        except Exception as e:
            _log("Token exchange failed", error=str(e))
            return f"Spotify token exchange failed: {e}", 400

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/status")
    @login_required
    def api_spotify_status():
        _log("Route /api/spotify/status")
        u = current_user()
        st = _get_user_tokens(u["id"])
        if not st:
            _log("Status: not linked")
            return jsonify(linked=False)
        try:
            access, tokens = _ensure_access_token(u["id"])
            prof = tokens.get("spotify_user") or {}
            _log("Status: linked", display_name=prof.get("display_name"), uid=u["id"])
            return jsonify(linked=True, profile=prof, scope=tokens.get("scope"))
        except Exception as e:
            _log("Status: linked but token invalid", error=str(e))
            return jsonify(linked=False, error=str(e))

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/me")
    @login_required
    def api_spotify_me():
        _log("Route /api/spotify/me")
        u = current_user()
        access, _ = _ensure_access_token(u["id"])
        data = _me(access)
        _log("/me fetched", id=data.get("id"))
        return jsonify(data)

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/playlists")
    @login_required
    def api_spotify_playlists():
        _log("Route /api/spotify/playlists")
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
        _log("Playlists returned", count=len(out))
        return jsonify(playlists=out)

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/playlist_tracks")
    @login_required
    def api_spotify_playlist_tracks():
        _log("Route /api/spotify/playlist_tracks", args=dict(request.args))
        u = current_user()
        pid = (request.args.get("playlist_id") or "").strip()
        if not pid:
            _log("Missing playlist_id")
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
        _log("Playlist tracks returned", pid=pid, count=len(out))
        return jsonify(tracks=out)

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/search_tracks")
    @login_required
    def api_spotify_search_tracks():
        _log("Route /api/spotify/search_tracks", args=dict(request.args))
        u = current_user()
        q = (request.args.get("q") or "").strip()
        limit = int(request.args.get("limit", 5))
        if len(q) < 2:
            _log("Query too short", q=q)
            return jsonify(tracks=[])
        access, _ = _ensure_access_token(u["id"])
        rows = _search_tracks(access, q, limit=limit)
        _log("Search returned", q=q, count=len(rows))
        out = []
        for tr in rows:
            artists = ", ".join(a.get("name") for a in (tr.get("artists") or []) if a.get("name"))
            alb = tr.get("album") or {}
            imgs = alb.get("images") or []
            img = imgs[0]["url"] if imgs else None
            out.append({
                "id": tr.get("id"),
                "name": tr.get("name"),
                "artists": artists,
                "duration_ms": tr.get("duration_ms"),
                "album": alb.get("name"),
                "image": img,
                "uri": tr.get("uri"),
                "external_url": (tr.get("external_urls") or {}).get("spotify"),
                "is_playable": tr.get("is_playable", True),
            })
        return jsonify(tracks=out)

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/playlist_create", methods=["POST"])
    @login_required
    def api_spotify_playlist_create():
        _log("Route /api/spotify/playlist_create")
        u = current_user()
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        public = bool(data.get("public", False))
        description = (data.get("description") or "").strip() or None
        if not name:
            _log("Create: missing name")
            return jsonify(error="missing name"), 400
        access, _ = _ensure_access_token(u["id"])
        me = _me(access)
        created = _create_playlist(access, me.get("id"), name, public, description)
        images = created.get("images") or []
        _log("Playlist created", pid=created.get("id"), name=created.get("name"), public=created.get("public"))
        return jsonify(
            id=created.get("id"),
            name=created.get("name"),
            public=created.get("public"),
            snapshot_id=created.get("snapshot_id"),
            image=(images[0]["url"] if images else None),
            external_url=(created.get("external_urls") or {}).get("spotify"),
        )

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/playlist_add_track", methods=["POST"])
    @login_required
    def api_spotify_playlist_add_track():
        _log("Route /api/spotify/playlist_add_track")
        u = current_user()
        data = request.get_json(force=True) or {}
        pid = (data.get("playlist_id") or "").strip()
        track_id = (data.get("track_id") or "").strip()
        track_uri = (data.get("track_uri") or "").strip()
        if not pid or not (track_id or track_uri):
            _log("Playlist add: missing params", pid=bool(pid), track_id=bool(track_id), track_uri=bool(track_uri))
            return jsonify(error="missing playlist_id/track_id|track_uri"), 400
        uri = track_uri or (f"spotify:track:{track_id}")
        access, _ = _ensure_access_token(u["id"])
        res = _add_tracks_to_playlist(access, pid, [uri])
        _log("Track added by uri/id", pid=pid, uri=uri)
        return jsonify(ok=True, snapshot_id=res.get("snapshot_id"), added=[uri])

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/playlist_add_by_query", methods=["POST"])
    @login_required
    def api_spotify_playlist_add_by_query():
        _log("Route /api/spotify/playlist_add_by_query")
        u = current_user()
        data = request.get_json(force=True) or {}
        pid = (data.get("playlist_id") or "").strip()
        title = (data.get("title") or "").strip()
        artist = (data.get("artist") or "").strip()
        if not pid or not (title or artist):
            _log("Add by query: missing params", pid=bool(pid), title=bool(title), artist=bool(artist))
            return jsonify(error="missing playlist_id/title|artist"), 400
        access, _ = _ensure_access_token(u["id"])
        q = _build_track_query(title, artist)
        items = _search_tracks(access, q, limit=1)
        if not items:
            _log("Add by query: no match", q=q)
            return jsonify(ok=False, error="no_spotify_match"), 404
        tr = items[0]
        uri = tr.get("uri") or f"spotify:track:{tr.get('id')}"
        res = _add_tracks_to_playlist(access, pid, [uri])
        _log("Add by query: added", pid=pid, q=q, uri=uri)
        return jsonify(
            ok=True,
            snapshot_id=res.get("snapshot_id"),
            matched={
                "id": tr.get("id"),
                "name": tr.get("name"),
                "artists": ", ".join(a.get("name") for a in (tr.get("artists") or [])),
                "duration_ms": tr.get("duration_ms"),
                "uri": uri
            }
        )

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/add_current_to_playlist", methods=["POST"])
    @login_required
    def api_spotify_add_current_to_playlist():
        """
        Takes the current 'Now Playing' (title/artist) from the guild's PlaylistManager
        and adds the first Spotify search match to the given playlist.
        """
        _log("Route /api/spotify/add_current_to_playlist")
        u = current_user()
        data = request.get_json(force=True) or {}
        pid = (data.get("playlist_id") or "").strip()
        gid = (data.get("guild_id") or "").strip()
        if not pid or not gid:
            _log("Add current: missing playlist_id/guild_id", pid=bool(pid), gid=bool(gid))
            return jsonify(error="missing playlist_id/guild_id"), 400

        # Pull current from PM (same source as /api/playlist)
        try:
            pm = app.get_pm(int(gid))
            payload = pm.to_dict()
        except Exception as e:
            _log("Add current: guild not found", gid=gid, error=str(e))
            return jsonify(error="guild_not_found"), 404

        current = payload.get("current") or {}
        title = (current.get("title") or "").strip()
        artist = (current.get("artist") or "").strip()

        if not title and not artist:
            _log("Add current: no current item")
            return jsonify(error="no_current_item"), 404

        access, _ = _ensure_access_token(u["id"])
        q = _build_track_query(title, artist)
        items = _search_tracks(access, q, limit=1)
        if not items:
            _log("Add current: no Spotify match", q=q)
            return jsonify(ok=False, error="no_spotify_match"), 404

        tr = items[0]
        uri = tr.get("uri") or f"spotify:track:{tr.get('id')}"
        res = _add_tracks_to_playlist(access, pid, [uri])
        _log("Add current: added", pid=pid, q=q, uri=uri)
        return jsonify(
            ok=True,
            snapshot_id=res.get("snapshot_id"),
            matched={"title": title, "artist": artist},
            added_uri=uri
        )

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/add_queue_to_playlist", methods=["POST"])
    @login_required
    def api_spotify_add_queue_to_playlist():
        """
        Adds a batch of items from the guild's queue to a playlist
        by searching (title + artist) and taking the first match.
        """
        _log("Route /api/spotify/add_queue_to_playlist")
        u = current_user()
        data = request.get_json(force=True) or {}
        pid = (data.get("playlist_id") or "").strip()
        gid = (data.get("guild_id") or "").strip()
        max_items = int(data.get("max_items", 20))
        if not pid or not gid:
            _log("Add queue: missing playlist_id/guild_id", pid=bool(pid), gid=bool(gid))
            return jsonify(error="missing playlist_id/guild_id"), 400

        try:
            pm = app.get_pm(int(gid))
            payload = pm.to_dict()
        except Exception as e:
            _log("Add queue: guild not found", gid=gid, error=str(e))
            return jsonify(error="guild_not_found"), 404

        queue = payload.get("queue") or []
        if not queue:
            _log("Add queue: empty queue")
            return jsonify(error="queue_empty"), 400

        access, _ = _ensure_access_token(u["id"])

        added, skipped = [], []
        for it in queue[:max(1, max_items)]:
            q = _build_track_query(it.get("title"), it.get("artist"))
            if not q:
                skipped.append({"title": it.get("title"), "reason": "no_title_or_artist"})
                continue
            items = _search_tracks(access, q, limit=1)
            if not items:
                skipped.append({"title": it.get("title"), "reason": "no_spotify_match"})
                continue
            tr = items[0]
            uri = tr.get("uri") or f"spotify:track:{tr.get('id')}"
            added.append(uri)

        if not added:
            _log("Add queue: no matches at all")
            return jsonify(ok=False, error="no_matches"), 404

        res = _add_tracks_to_playlist(access, pid, added)
        _log("Add queue: done", pid=pid, added=len(added), skipped=len(skipped))
        return jsonify(ok=True, snapshot_id=res.get("snapshot_id"), added=len(added), uris=added, skipped=skipped)

    # -------------------------------------------------------------------------
    # --- helpers internes: choix du 1er bon match YouTube ---
    def _to_seconds(v):
        try:
            iv = int(v)
            return iv // 1000 if iv > 86400 else iv
        except Exception:
            if isinstance(v, str) and v.isdigit():
                return int(v)
        return None

    def _yt_first_match(query: str, duration_ms: int | None = None) -> dict | None:
        """Search YT via our extractors and try to pick the closest duration match."""
        try:
            from extractors import get_search_module  # paresseux pour éviter cycles
            searcher = get_search_module("youtube")
            rows = searcher.search(query) or []
            _log("YouTube search", q=query, got=len(rows), has_target=bool(duration_ms))
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
                    pick = close[0][1]
                    _log("YouTube pick (close match)", duration=target, window=window, title=pick.get("title"))
                    return pick
            _log("YouTube pick (first row)", title=rows[0].get("title"))
            return rows[0]
        except Exception as e:
            _log("YouTube search failed", error=str(e))
            return None

    # -------------------------------------------------------------------------
    # --- endpoint one-shot: résout + joue ---
    @app.route("/api/spotify/quickplay", methods=["POST"])
    @login_required
    def api_spotify_quickplay():
        import asyncio
        _log("Route /api/spotify/quickplay")
        data = request.get_json(force=True) or {}
        tr = (data.get("track") or {})
        guild_id = (data.get("guild_id") or "").strip()
        name = (tr.get("name") or "").strip()
        artists = (tr.get("artists") or tr.get("artist") or "").strip()
        duration_ms = tr.get("duration_ms")
        image = tr.get("image")
        if not guild_id or not name:
            _log("Quickplay: missing guild_id/name")
            return jsonify(error="missing guild_id/name"), 400

        query = f"{name} - {artists}" if artists else name
        yt = _yt_first_match(query, duration_ms)
        if not yt:
            _log("Quickplay: no YouTube match", q=query)
            return jsonify(ok=False, error="no_youtube_match"), 404

        # Récup bot + Music cog
        bot = getattr(app, "bot", None)
        if not bot:
            _log("Quickplay: bot unavailable")
            return jsonify(error="bot_unavailable"), 500
        music_cog = bot.get_cog("Music")
        if not music_cog:
            _log("Quickplay: music cog missing")
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
        _log("Quickplay: resolved", url=item["url"], duration=item["duration"])

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
                _log("Quickplay: user not in voice", error=str(e))
                return jsonify(ok=False, error="Tu dois être en salon vocal.", error_code="USER_NOT_IN_VOICE"), 409
            _log("Quickplay: playback error", error=str(e))
            return jsonify(ok=False, error=str(e)), 500

        _log("Quickplay: enqueued OK", guild_id=guild_id, title=name)
        return jsonify(ok=True, resolved=item,
                       youtube={"title": yt.get("title"), "url": yt.get("webpage_url") or yt.get("url")})

    # -------------------------------------------------------------------------
    @app.route("/api/spotify/logout", methods=["POST"])
    @login_required
    def api_spotify_logout():
        _log("Route /api/spotify/logout")
        u = current_user()
        _del_user_tokens(u["id"])
        _log("Unlinked Spotify", uid=u["id"])
        return jsonify(ok=True)

    @app.route("/api/spotify/playlist_delete", methods=["POST"])
    @login_required
    def api_spotify_playlist_delete():
        """
        'Supprime' une playlist pour l'utilisateur courant (unfollow).
        """
        print("[spotify] /api/spotify/playlist_delete called")
        u = current_user()
        data = request.get_json(force=True) or {}
        pid = (data.get("playlist_id") or "").strip()
        if not pid:
            print("[spotify] missing playlist_id")
            return jsonify(error="missing playlist_id"), 400

        try:
            access, _ = _ensure_access_token(u["id"])
            _unfollow_playlist(access, pid)
            print(f"[spotify] unfollowed playlist {pid}")
            return jsonify(ok=True)
        except Exception as e:
            print(f"[spotify] playlist_delete error: {e}")
            return jsonify(ok=False, error=str(e)), 400

    @app.route("/api/spotify/playlist_remove_tracks", methods=["POST"])
    @login_required
    def api_spotify_playlist_remove_tracks():
        print("[spotify] /api/spotify/playlist_remove_tracks called")
        u = current_user()
        data = request.get_json(force=True) or {}

        pid = (data.get("playlist_id") or "").strip()
        uris = list(data.get("track_uris") or [])
        ids = list(data.get("track_ids") or [])

        # NEW: also accept single
        uri_single = (data.get("track_uri") or "").strip()
        id_single = (data.get("track_id") or "").strip()
        if uri_single: uris.append(uri_single)
        if id_single:  ids.append(id_single)

        if not pid or (not uris and not ids):
            return jsonify(error="missing playlist_id/track_uris|track_ids"), 400

        # Normalize all to URIs
        norm_uris = []
        for s in uris:
            s = str(s or "").strip()
            if s: norm_uris.append(s)
        for s in ids:
            s = str(s or "").strip()
            if s: norm_uris.append(f"spotify:track:{s}")

        if not norm_uris:
            return jsonify(error="no_valid_uris"), 400

        try:
            access, _ = _ensure_access_token(u["id"])
            me = _get_me(access)
            if not _playlist_is_editable(access, pid, me["id"]):
                return jsonify(ok=False, error="Tu ne peux pas modifier cette playlist.", code="NOT_OWNER"), 403

            res = _remove_tracks_from_playlist(access, pid, norm_uris)
            return jsonify(ok=True, removed=len(norm_uris), snapshot_id=res.get("snapshot_id"))
        except Exception as e:
            print(f"[spotify] playlist_remove_tracks error: {e}")
            return jsonify(ok=False, error=str(e)), 400

    @app.route("/api/spotify/playlist_clear", methods=["POST"])
    @login_required
    def api_spotify_playlist_clear():
        """
        Vide complètement la playlist (remove all).
        """
        print("[spotify] /api/spotify/playlist_clear called")
        u = current_user()
        data = request.get_json(force=True) or {}
        pid = (data.get("playlist_id") or "").strip()
        if not pid:
            return jsonify(error="missing playlist_id"), 400

        try:
            access, _ = _ensure_access_token(u["id"])
            rows = _playlist_tracks(access, pid, limit=1000)
            uris = []
            for it in rows:
                tr = it.get("track") or {}
                uri = tr.get("uri")
                if uri:
                    uris.append(uri)
            if not uris:
                return jsonify(ok=True, removed=0)
            res = _remove_tracks_from_playlist(access, pid, uris)
            print(f"[spotify] cleared {len(uris)} items from {pid}")
            return jsonify(ok=True, removed=len(uris), snapshot_id=res.get("snapshot_id"))
        except Exception as e:
            print(f"[spotify] playlist_clear error: {e}")
            return jsonify(ok=False, error=str(e)), 400