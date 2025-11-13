# api/blueprints/spotify.py
from __future__ import annotations

import os
import re
import time
import json
import hmac
import base64
import hashlib
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import requests
from flask import Blueprint, current_app, request, jsonify, redirect, session

# Auth helpers (session)
try:
    from api.auth.session import current_user, require_login  # standard
except Exception:
    # Back-compat if your module exposes `require_login`
    from api.auth.session import current_user, require_login as login_required  # type: ignore

# Player service (source de vérité)
try:
    from api.services.player_service import PlayerService
except Exception:
    PlayerService = None  # type: ignore

bp = Blueprint("spotify", __name__)

# =============================================================================
#                               CONFIG / ENV
# =============================================================================
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
SPOTIFY_SCOPES = os.getenv(
    "SPOTIFY_SCOPES",
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private "
    "user-read-email"
)
STATE_SECRET = os.getenv("SPOTIFY_STATE_SECRET", "").encode("utf-8")


# =============================================================================
#                               LOGGING
# =============================================================================
def _log(msg: str, **kw: Any) -> None:
    """Print a single-line JSON-ish debug message prefixed with [SPOTIFY]."""
    try:
        if kw:
            try:
                safe = json.dumps(kw, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                safe = str(kw)
            print(f"[SPOTIFY] {msg} {safe}")
        else:
            print(f"[SPOTIFY] {msg}")
    except Exception:
        # évite toute exception de log qui casserait la route
        pass


def _json_error(message: str, status: int = 400, **extra: Any):
    payload = {"ok": False, "error": message}
    payload.update(extra or {})
    return jsonify(payload), status


_log(
    "Config loaded",
    has_client_id=bool(SPOTIFY_CLIENT_ID),
    has_client_secret=bool(SPOTIFY_CLIENT_SECRET),
    has_redirect=bool(SPOTIFY_REDIRECT_URI),
    scopes=SPOTIFY_SCOPES,
    has_state_secret=bool(STATE_SECRET),
)


# =============================================================================
#                           STRING NORMALIZATION
# =============================================================================
_NOISE_RE = re.compile(
    r'\s*[\(\[\{][^\)\]\}]*\b(official|officiel|clip|lyrics?|paroles|audio|video|vid[ée]o|visualizer|hd|4k)\b[^\)\]\}]*[\)\]\}]\s*',
    re.I
)


def _strip_accents(s: str) -> str:
    try:
        return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    except Exception:
        return s or ""


def _norm(s: str) -> str:
    s = _strip_accents(s or "").lower()
    s = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', s)           # remove (…) […] {…}
    s = re.sub(r'[^a-z0-9\s]+', ' ', s)                  # punctuation
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _clean_title_artist(title: Optional[str], artist: Optional[str]) -> tuple[str, str]:
    """
    Nettoie le couple (title, artist) venant souvent de YouTube :
      - "ARTIST - Titre" → isole le vrai titre et l’artiste s’il manque
      - supprime les numéros / lettres de piste (ex: "Θ. ", "A. ", "1. ")
      - supprime le bruit (clip officiel, paroles, etc.)
      - nettoie artiste ("- Topic", "official", etc.)
    """
    t = (title or "").strip()
    a = (artist or "").strip()

    if " - " in t:
        left, right = t.split(" - ", 1)
        if not a or left.lower().startswith(a.lower()):
            a = a or left
            t = right

    # Préfixes de piste type "Θ." / "1." / "A." / "IV."
    t = re.sub(r'^\s*(?:[A-Za-zÀ-ÿΑ-Ωα-ω]|[IVXLCDM]+|\d+)\.\s*', '', t)

    # Bruit entre ()/[]/{}
    t = _NOISE_RE.sub(' ', t)
    t = re.sub(r'\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*', ' ', t)
    t = re.sub(r'\s*[-–—]\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()

    a = re.sub(r'(?i)\s*-\s*topic$', '', a)
    a = re.sub(r'(?i)\b(official|officiel)\b', '', a)
    a = re.sub(r'\s+', ' ', a).strip()

    return t, a


def _queries_for(title: str, artist: str) -> list[str]:
    qs: list[str] = []
    if title and artist:
        qs += [
            f'track:"{title}" artist:"{artist}"',
            f'"{title}" "{artist}"',
            f'{title} {artist}',
            f'artist:"{artist}" {title}',
        ]
    if title:
        qs += [f'track:"{title}"', title]
    # dédup en gardant l’ordre
    seen, out = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _sec_to_ms(x: Any) -> Optional[int]:
    try:
        fx = float(x)
        return int(fx if fx > 10000 else fx * 1000)  # si déjà très grand → probablement ms
    except Exception:
        return None


def _score_candidate(r: dict, ttoks: set[str], atoks: set[str], target_ms: Optional[int]) -> float:
    r_title = _norm(r.get("name") or "")
    r_ttoks = set(r_title.split())
    title_overlap = len(ttoks & r_ttoks) / (len(ttoks) or 1)

    r_artists = [a.get("name") for a in (r.get("artists") or []) if a.get("name")]
    art_scores = []
    for ra in r_artists:
        ra_toks = set(_norm(ra).split())
        if atoks:
            art_scores.append(len(atoks & ra_toks) / (len(atoks) or 1))
        else:
            art_scores.append(1.0 if ra_toks & r_ttoks else 0.0)
    artist_overlap = max(art_scores) if art_scores else 0.0

    dur_score = 0.5
    if target_ms:
        d = r.get("duration_ms") or 0
        if d:
            window = max(7000, int(target_ms * 0.12))  # ±7s ou ±12%
            diff = abs(d - target_ms)
            if diff <= window:
                dur_score = 1 - (diff / window) * 0.5  # 0.5..1
            else:
                dur_score = max(0.0, 0.5 - (diff - window) / (4 * window))

    w_dur = 0.10 if target_ms else 0.0
    w_title, w_artist = 0.55, 0.35
    total = w_title * title_overlap + w_artist * artist_overlap + w_dur * dur_score

    if r_title == " ".join(ttoks):
        total += 0.05
    if atoks and any(_norm(a) == " ".join(atoks) for a in r_artists):
        total += 0.05
    total += (r.get("popularity") or 0) / 10000.0  # tiny tie-breaker
    return total


# =============================================================================
#                               TOKEN STORE (DISK)
# =============================================================================
_STORE = Path(".spotify_tokens.json")


def _load_store() -> Dict[str, Any]:
    try:
        if _STORE.exists():
            return json.loads(_STORE.read_text("utf-8"))
    except Exception as e:
        _log("Failed to load token store, using empty", error=str(e))
    return {"users": {}}


def _save_store(data: Dict[str, Any]) -> None:
    try:
        _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        _log("Failed to save token store", error=str(e))


def _now() -> int:
    return int(time.time())


def _require_cfg() -> None:
    missing = []
    if not SPOTIFY_CLIENT_ID:
        missing.append("SPOTIFY_CLIENT_ID")
    if not SPOTIFY_CLIENT_SECRET:
        missing.append("SPOTIFY_CLIENT_SECRET")
    if not SPOTIFY_REDIRECT_URI:
        missing.append("SPOTIFY_REDIRECT_URI")
    if not STATE_SECRET:
        missing.append("SPOTIFY_STATE_SECRET")
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
    ts = _now()
    data = {"uid": str(uid), "sid": str(sid or ""), "ts": ts}
    data["sig"] = _sign(data["uid"], data["sid"], data["ts"])
    enc = _b64u_encode(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    _log("STATE packed", uid=str(uid), sid=str(sid or ""), ts=ts)
    return enc


def _unpack_state(state: str, max_age: int = 900) -> Tuple[Optional[str], Optional[str]]:
    try:
        raw = json.loads(_b64u_decode(state))
        uid = str(raw.get("uid"))
        sid = str(raw.get("sid", ""))
        ts = int(raw.get("ts", 0))
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
        "state": state,
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params, quote_via=quote_plus)


def _token_request(data: Dict[str, str]) -> Dict[str, Any]:
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
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    url = "https://api.spotify.com/v1" + path
    _log("POST Spotify API", path=path)
    r = requests.post(url, headers=headers, json=json_body or {}, timeout=10)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {}


def _sp_delete(access_token: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    r = requests.delete("https://api.spotify.com/v1" + path, headers=headers, json=json_body or {}, timeout=10)
    if r.status_code >= 400:
        r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {}


def _search_tracks(access_token: str, q: str, limit: int = 5, market: str = "from_token") -> List[Dict[str, Any]]:
    params = {"q": q, "type": "track", "limit": min(limit, 50)}
    if market:
        params["market"] = market
    data = _sp_get(access_token, "/search", params=params)
    rows = (data.get("tracks") or {}).get("items") or []
    _log("Search tracks", q=q, results=len(rows))
    return rows


def _add_tracks_to_playlist(access_token: str, playlist_id: str, uris: List[str]) -> Dict[str, Any]:
    _log("Add tracks to playlist", pid=playlist_id, count=len(uris))
    return _sp_post(access_token, f"/playlists/{playlist_id}/tracks", {"uris": uris[:100]})


def _create_playlist(access_token: str, user_id: str, name: str, public: bool, description: Optional[str]) -> Dict[str, Any]:
    body = {"name": name, "public": bool(public)}
    if description:
        body["description"] = description
    _log("Create playlist", owner=user_id, name=name, public=bool(public))
    return _sp_post(access_token, f"/users/{user_id}/playlists", body)


def _unfollow_playlist(access_token: str, playlist_id: str) -> Dict[str, Any]:
    return _sp_delete(access_token, f"/playlists/{playlist_id}/followers")


def _remove_tracks_from_playlist(access_token: str, playlist_id: str, uris: List[str]) -> Dict[str, Any]:
    last = {}
    batch = []
    for uri in uris:
        if not uri:
            continue
        batch.append({"uri": uri})
        if len(batch) >= 100:
            last = _sp_delete(access_token, f"/playlists/{playlist_id}/tracks", {"tracks": batch})
            batch.clear()
    if batch:
        last = _sp_delete(access_token, f"/playlists/{playlist_id}/tracks", {"tracks": batch})
    return last


# =============================================================================
#                          HELPERS: Player / SocketIO
# =============================================================================
def _emit(event: str, data: Dict[str, Any], sid: Optional[str], uid: Optional[str]):
    socketio = getattr(current_app, "socketio", None)
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


def _player_payload_for_guild(gid: int) -> Dict[str, Any]:
    svc: PlayerService = getattr(current_app, "player_service", None)  # type: ignore
    if not svc:
        raise RuntimeError("player_service_unavailable")
    # chemin “officiel” si dispo
    try:
        return svc._overlay_payload(gid)  # contient {current, queue, ...}
    except Exception:
        # fallback très léger si besoin
        pm = svc._get_pm(gid)
        return pm.to_dict()


# =============================================================================
#                      ROUTES (Blueprint, sans /api prefix)
# =============================================================================
@bp.get("/spotify/login")
@login_required
def spotify_login():
    _log("Route /spotify/login")
    try:
        _require_cfg()
    except Exception as e:
        _log("Config invalid on /spotify/login", error=str(e))
        return _json_error(str(e), 500)

    u = current_user()
    uid = str(u["id"])
    sid = (request.args.get("sid") or "").strip()  # optional socket.id
    state = _pack_state(uid, sid)

    session["spotify_state"] = state
    url = _auth_url(state)
    _log("Redirect to Spotify /authorize", uid=uid, has_sid=bool(sid))
    return redirect(url)


@bp.get("/spotify/callback")
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
    if u and str(u.get("id")) != uid_from_state:
        _log("Callback user mismatch", current_uid=str(u.get("id")), state_uid=uid_from_state)
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
            "spotify_user": {"id": profile.get("id"), "display_name": profile.get("display_name")},
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


@bp.get("/spotify/status")
@login_required
def api_spotify_status():
    _log("Route /spotify/status")
    u = current_user()
    st = _get_user_tokens(u["id"])
    if not st:
        _log("Status: not linked")
        return jsonify(linked=False)
    try:
        _, tokens = _ensure_access_token(u["id"])
        prof = tokens.get("spotify_user") or {}
        _log("Status: linked", display_name=prof.get("display_name"), uid=u["id"])
        return jsonify(linked=True, profile=prof, scope=tokens.get("scope"))
    except Exception as e:
        _log("Status: linked but token invalid", error=str(e))
        return jsonify(linked=False, error=str(e))


@bp.get("/spotify/me")
@login_required
def api_spotify_me():
    _log("Route /spotify/me")
    u = current_user()
    try:
        access, _ = _ensure_access_token(u["id"])
    except Exception as e:
        _log("/me: spotify not linked / token invalid", error=str(e))
        return _json_error("spotify_not_linked", 401)
    data = _me(access)
    _log("/me fetched", id=data.get("id"))
    return jsonify(data)


@bp.get("/spotify/playlists")
@login_required
def api_spotify_playlists():
    _log("Route /spotify/playlists")
    u = current_user()
    limit = int(request.args.get("limit", 50))
    try:
        access, _ = _ensure_access_token(u["id"])
        pls = _playlists(access, limit=limit)
    except Exception as e:
        _log("Playlists: error", error=str(e))
        return _json_error("spotify_not_linked", 401)

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


@bp.get("/spotify/playlist_tracks")
@login_required
def api_spotify_playlist_tracks():
    _log("Route /spotify/playlist_tracks", args=dict(request.args))
    u = current_user()
    pid = (request.args.get("playlist_id") or "").strip()
    if not pid:
        return _json_error("missing playlist_id", 400)
    try:
        access, _ = _ensure_access_token(u["id"])
        rows = _playlist_tracks(access, pid, limit=int(request.args.get("limit", 100)))
    except Exception as e:
        _log("Playlist tracks error", error=str(e))
        return _json_error("spotify_not_linked", 401)

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


@bp.get("/spotify/search_tracks")
@login_required
def api_spotify_search_tracks():
    _log("Route /spotify/search_tracks", args=dict(request.args))
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


@bp.post("/spotify/playlist_create")
@login_required
def api_spotify_playlist_create():
    _log("Route /spotify/playlist_create")
    u = current_user()
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    public = bool(data.get("public", False))
    description = (data.get("description") or "").strip() or None
    if not name:
        return _json_error("missing name", 400)
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


@bp.post("/spotify/playlist_add_track")
@login_required
def api_spotify_playlist_add_track():
    _log("Route /spotify/playlist_add_track")
    u = current_user()
    data = request.get_json(force=True) or {}
    pid = (data.get("playlist_id") or "").strip()
    track_id = (data.get("track_id") or "").strip()
    track_uri = (data.get("track_uri") or "").strip()
    if not pid or not (track_id or track_uri):
        return _json_error("missing playlist_id/track_id|track_uri", 400)
    uri = track_uri or (f"spotify:track:{track_id}")
    access, _ = _ensure_access_token(u["id"])
    try:
        res = _add_tracks_to_playlist(access, pid, [uri])
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("Add by id/uri failed", status=status)
        if status == 403:
            return _json_error("forbidden_or_not_editable", 403)
        return _json_error(f"http_{status}", status)
    _log("Track added by uri/id", pid=pid, uri=uri)
    return jsonify(ok=True, snapshot_id=res.get("snapshot_id"), added=[uri])


@bp.post("/spotify/playlist_add_by_query")
@login_required
def api_spotify_playlist_add_by_query():
    _log("Route /spotify/playlist_add_by_query")
    u = current_user()
    data = request.get_json(force=True) or {}
    pid = (data.get("playlist_id") or "").strip()
    raw_title = (data.get("title") or "").strip()
    raw_artist = (data.get("artist") or "").strip()
    target_ms = _sec_to_ms(data.get("duration"))

    if not pid or not (raw_title or raw_artist):
        return _json_error("missing playlist_id/title|artist", 400)

    try:
        access, _ = _ensure_access_token(u["id"])
    except Exception as e:
        _log("Add by query: spotify not linked / token invalid", error=str(e))
        return _json_error("spotify_not_linked", 401)

    title, artist = _clean_title_artist(raw_title, raw_artist)
    queries = _queries_for(title, artist)

    candidates: list[dict] = []
    seen_ids = set()
    for q in queries:
        rows = _search_tracks(access, q, limit=10, market="from_token")
        for r in rows or []:
            rid = r.get("id")
            if not rid or rid in seen_ids:
                continue
            seen_ids.add(rid)
            candidates.append(r)
        if candidates:
            break

    if not candidates:
        fb = f"{raw_title} {raw_artist}".strip()
        candidates = _search_tracks(access, fb, limit=10, market="from_token") or []

    if not candidates:
        _log("Add by query: no match", title=raw_title, artist=raw_artist)
        return _json_error("no_spotify_match", 404)

    ttoks = set(_norm(title or raw_title).split())
    atoks = set(_norm(artist or raw_artist).split()) if (artist or raw_artist) else set()
    candidates.sort(key=lambda r: _score_candidate(r, ttoks, atoks, target_ms), reverse=True)
    best = candidates[0]

    uri = best.get("uri") or f"spotify:track:{best.get('id')}"
    try:
        res = _add_tracks_to_playlist(access, pid, [uri])
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("Add by query -> add failed", status=status)
        if status == 403:
            return _json_error("forbidden_or_not_editable", 403)
        return _json_error(f"http_{status}", status)

    _log("Add by query: added", pid=pid, uri=uri)
    return jsonify(
        ok=True,
        snapshot_id=res.get("snapshot_id"),
        matched={
            "title_raw": raw_title, "artist_raw": raw_artist,
            "title_used": title, "artist_used": artist,
            "target_duration_ms": target_ms,
        },
        picked={
            "id": best.get("id"),
            "name": best.get("name"),
            "artists": [a.get("name") for a in (best.get("artists") or []) if a.get("name")],
            "duration_ms": best.get("duration_ms"),
            "uri": uri,
        },
        added_uri=uri
    )


@bp.post("/spotify/add_current_to_playlist")
@login_required
def api_spotify_add_current_to_playlist():
    _log("Route /spotify/add_current_to_playlist")
    u = current_user()
    data = request.get_json(force=True) or {}
    pid = (data.get("playlist_id") or "").strip()
    gid = (data.get("guild_id") or "").strip()
    if not pid or not gid:
        return _json_error("missing_playlist_id/guild_id", 400)

    # Récup Now Playing
    try:
        payload = _player_payload_for_guild(int(gid))
    except Exception as e:
        _log("Add current: guild not found", gid=gid, error=str(e))
        return _json_error("guild_not_found", 404)

    current = (payload or {}).get("current") or {}
    raw_title = (current.get("title") or "").strip()
    raw_artist = ((current.get("artist") or current.get("uploader") or current.get("author")) or "").strip()
    if not raw_title and not raw_artist:
        return _json_error("no_current_item", 404)

    # Spotify auth
    try:
        access, _ = _ensure_access_token(u["id"])
    except Exception as e:
        _log("Add current: spotify not linked / token invalid", error=str(e))
        return _json_error("spotify_not_linked", 401)

    # Nettoyage + durée
    title, artist = _clean_title_artist(raw_title, raw_artist)
    target_ms = _sec_to_ms(current.get("duration"))

    # Candidats
    queries = _queries_for(title, artist)
    candidates: list[dict] = []
    seen_ids = set()

    for q in queries:
        rows = _search_tracks(access, q, limit=10, market="from_token")
        for r in rows or []:
            rid = r.get("id")
            if not rid or rid in seen_ids:
                continue
            seen_ids.add(rid)
            candidates.append(r)
        if candidates:
            break

    if not candidates:
        fb = f"{raw_title} {raw_artist}".strip()
        candidates = _search_tracks(access, fb, limit=10, market="from_token") or []

    if not candidates:
        _log("Add current: no Spotify match", title=raw_title, artist=raw_artist)
        return _json_error("no_spotify_match", 404)

    ttoks = set(_norm(title or raw_title).split())
    atoks = set(_norm(artist or raw_artist).split()) if (artist or raw_artist) else set()
    candidates.sort(key=lambda r: _score_candidate(r, ttoks, atoks, target_ms), reverse=True)
    best = candidates[0]
    uri = best.get("uri") or f"spotify:track:{best.get('id')}"

    try:
        res = _add_tracks_to_playlist(access, pid, [uri])
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("Add current -> add failed", status=status)
        if status == 403:
            return _json_error("forbidden_or_not_editable", 403)
        return _json_error(f"http_{status}", status)

    _log("Add current: added", pid=pid, chosen=best.get("name"), uri=uri)
    return jsonify(
        ok=True,
        snapshot_id=res.get("snapshot_id"),
        matched={
            "title_raw": raw_title, "artist_raw": raw_artist,
            "title_used": title, "artist_used": artist,
            "target_duration_ms": target_ms,
        },
        picked={
            "id": best.get("id"),
            "name": best.get("name"),
            "artists": [a.get("name") for a in (best.get("artists") or []) if a.get("name")],
            "duration_ms": best.get("duration_ms"),
            "uri": uri,
        },
        added_uri=uri
    )


@bp.post("/spotify/add_queue_to_playlist")
@login_required
def api_spotify_add_queue_to_playlist():
    _log("Route /spotify/add_queue_to_playlist")
    u = current_user()
    data = request.get_json(force=True) or {}
    pid = (data.get("playlist_id") or "").strip()
    gid = (data.get("guild_id") or "").strip()
    max_items = int(data.get("max_items", 20))
    if not pid or not gid:
        return _json_error("missing_playlist_id/guild_id", 400)

    try:
        payload = _player_payload_for_guild(int(gid))
    except Exception as e:
        _log("Add queue: guild not found", gid=gid, error=str(e))
        return _json_error("guild_not_found", 404)

    queue = (payload or {}).get("queue") or []
    if not queue:
        return _json_error("queue_empty", 400)

    try:
        access, _ = _ensure_access_token(u["id"])
    except Exception as e:
        _log("Add queue: spotify not linked / token invalid", error=str(e))
        return _json_error("spotify_not_linked", 401)

    added_uris: List[str] = []
    skipped: List[Dict[str, Any]] = []

    batch = queue[:max(1, max_items)]

    for it in batch:
        raw_title = (it.get("title") or "").strip()
        raw_artist = ((it.get("artist") or it.get("uploader") or it.get("author")) or "").strip()
        if not raw_title and not raw_artist:
            skipped.append({"title": raw_title, "reason": "no_title_or_artist"})
            continue

        title, artist = _clean_title_artist(raw_title, raw_artist)
        target_ms = _sec_to_ms(it.get("duration"))
        queries = _queries_for(title, artist)

        candidates: list[dict] = []
        seen = set()
        for q in queries:
            rows = _search_tracks(access, q, limit=10, market="from_token")
            for r in rows or []:
                rid = r.get("id")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                candidates.append(r)
            if candidates:
                break

        if not candidates:
            fb = f"{raw_title} {raw_artist}".strip()
            candidates = _search_tracks(access, fb, limit=10, market="from_token") or []

        if not candidates:
            skipped.append({"title": raw_title, "reason": "no_spotify_match"})
            continue

        ttoks = set(_norm(title or raw_title).split())
        atoks = set(_norm(artist or raw_artist).split()) if (artist or raw_artist) else set()
        candidates.sort(key=lambda r: _score_candidate(r, ttoks, atoks, target_ms), reverse=True)
        best = candidates[0]
        uri = best.get("uri") or f"spotify:track:{best.get('id')}"
        added_uris.append(uri)

    if not added_uris:
        _log("Add queue: no matches at all")
        return _json_error("no_matches", 404, skipped=skipped)

    try:
        res = _add_tracks_to_playlist(access, pid, added_uris)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("Add queue -> add failed", status=status)
        if status == 403:
            return _json_error("forbidden_or_not_editable", 403, skipped=skipped)
        return _json_error(f"http_{status}", status, skipped=skipped)

    _log("Add queue: done", pid=pid, added=len(added_uris), skipped=len(skipped))
    return jsonify(ok=True, snapshot_id=res.get("snapshot_id"), added=len(added_uris), uris=added_uris, skipped=skipped)


@bp.post("/spotify/quickplay")
@login_required
def api_spotify_quickplay():
    import asyncio
    _log("Route /spotify/quickplay")
    data = request.get_json(force=True) or {}
    tr = (data.get("track") or {})
    guild_id = (data.get("guild_id") or "").strip()
    name = (tr.get("name") or "").strip()
    artists = (tr.get("artists") or tr.get("artist") or "").strip()
    duration_ms = tr.get("duration_ms")
    image = tr.get("image")
    if not guild_id or not name:
        return _json_error("missing guild_id/name", 400)

    def _to_seconds(v):
        try:
            iv = int(v)
            return iv // 1000 if iv > 86400 else iv
        except Exception:
            if isinstance(v, str) and v.isdigit():
                return int(v)
        return None

    def _yt_first_match(query: str, duration_ms: Optional[int] = None) -> Optional[dict]:
        try:
            from extractors import get_search_module  # lazy to avoid cycles
            searcher = get_search_module("youtube")
            rows = searcher.search(query) or []
            _log("YouTube search", q=query, got=len(rows), has_target=bool(duration_ms))
            if not rows:
                return None
            target = _to_seconds(duration_ms) if duration_ms else None
            if target:
                window = max(7, int(target * 0.10))
                close = []
                for r in rows:
                    d = _to_seconds(r.get("duration"))
                    if d is None:
                        continue
                    if abs(d - target) <= window:
                        ch = (r.get("channel") or r.get("uploader") or "").lower()
                        score = 0
                        if any(k in ch for k in ("vevo", "topic", "official")):
                            score += 3
                        if "lyrics" in (r.get("title") or "").lower():
                            score -= 1
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

    query = f"{name} - {artists}" if artists else name
    yt = _yt_first_match(query, duration_ms)
    if not yt:
        _log("Quickplay: no YouTube match", q=query)
        return _json_error("no_youtube_match", 404)

    bot = getattr(current_app, "bot", None)
    if not bot:
        _log("Quickplay: bot unavailable")
        return _json_error("bot_unavailable", 500)
    music_cog = bot.get_cog("Music")
    if not music_cog:
        _log("Quickplay: music cog missing")
        return _json_error("music_cog_missing", 500)

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
        msg = str(e).lower()
        if "voice" in msg or "vocal" in msg:
            _log("Quickplay: user not in voice", error=str(e))
            return jsonify(ok=False, error="Tu dois être en salon vocal.", error_code="USER_NOT_IN_VOICE"), 409
        _log("Quickplay: playback error", error=str(e))
        return _json_error(str(e), 500)

    _log("Quickplay: enqueued OK", guild_id=guild_id, title=name)
    return jsonify(ok=True, resolved=item,
                   youtube={"title": yt.get("title"), "url": yt.get("webpage_url") or yt.get("url")})


@bp.post("/spotify/logout")
@login_required
def api_spotify_logout():
    _log("Route /spotify/logout")
    u = current_user()
    _del_user_tokens(u["id"])
    _log("Unlinked Spotify", uid=u["id"])
    return jsonify(ok=True)


@bp.post("/spotify/playlist_delete")
@login_required
def api_spotify_playlist_delete():
    _log("Route /spotify/playlist_delete")
    u = current_user()
    data = request.get_json(force=True) or {}
    pid = (data.get("playlist_id") or "").strip()
    if not pid:
        return _json_error("missing playlist_id", 400)
    try:
        access, _ = _ensure_access_token(u["id"])
        _unfollow_playlist(access, pid)
        _log("Unfollowed playlist", pid=pid)
        return jsonify(ok=True)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("playlist_delete error", status=status)
        return _json_error(f"http_{status}", status)
    except Exception as e:
        _log("playlist_delete error", error=str(e))
        return _json_error(str(e), 400)


@bp.post("/spotify/playlist_remove_tracks")
@login_required
def api_spotify_playlist_remove_tracks():
    _log("Route /spotify/playlist_remove_tracks")
    u = current_user()
    data = request.get_json(force=True) or {}

    pid = (data.get("playlist_id") or "").strip()
    uris = list(data.get("track_uris") or [])
    ids = list(data.get("track_ids") or [])

    uri_single = (data.get("track_uri") or "").strip()
    id_single = (data.get("track_id") or "").strip()
    if uri_single:
        uris.append(uri_single)
    if id_single:
        ids.append(id_single)

    if not pid or (not uris and not ids):
        return _json_error("missing playlist_id/track_uris|track_ids", 400)

    norm_uris = []
    for s in uris:
        s = str(s or "").strip()
        if s:
            norm_uris.append(s)
    for s in ids:
        s = str(s or "").strip()
        if s:
            norm_uris.append(f"spotify:track:{s}")

    if not norm_uris:
        return _json_error("no_valid_uris", 400)

    try:
        access, _ = _ensure_access_token(u["id"])
        me = _me(access)
        # Vérifie possibilité d'édition (owner/collaborative)
        info = _sp_get(access, f"/playlists/{pid}", params={"fields": "owner(id),collaborative"})
        owner_id = ((info or {}).get("owner") or {}).get("id")
        is_collab = bool((info or {}).get("collaborative"))
        if not (owner_id == me["id"] or is_collab):
            return _json_error("Tu ne peux pas modifier cette playlist.", 403, code="NOT_OWNER")

        res = _remove_tracks_from_playlist(access, pid, norm_uris)
        return jsonify(ok=True, removed=len(norm_uris), snapshot_id=res.get("snapshot_id"))
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("playlist_remove_tracks error", status=status)
        return _json_error(f"http_{status}", status)
    except Exception as e:
        _log("playlist_remove_tracks error", error=str(e))
        return _json_error(str(e), 400)


@bp.post("/spotify/playlist_clear")
@login_required
def api_spotify_playlist_clear():
    _log("Route /spotify/playlist_clear")
    u = current_user()
    data = request.get_json(force=True) or {}
    pid = (data.get("playlist_id") or "").strip()
    if not pid:
        return _json_error("missing playlist_id", 400)

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
        _log("Playlist cleared", pid=pid, removed=len(uris))
        return jsonify(ok=True, removed=len(uris), snapshot_id=res.get("snapshot_id"))
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        _log("playlist_clear error", status=status)
        return _json_error(f"http_{status}", status)
    except Exception as e:
        _log("playlist_clear error", error=str(e))
        return _json_error(str(e), 400)
