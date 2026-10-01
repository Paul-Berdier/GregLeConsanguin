"""Player routes — contrôle du lecteur de musique via Redis bridge."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from api.services.authz import require_session_user, session_user_id
from api.services.bot_bridge import send_command
from api.services.relay_clock import now_ms, with_relay_at

bp = Blueprint("player", __name__)

# play_for_user : le bot répond en < 20 s (contrat C2) ; marge pour Redis,
# et on reste sous le proxyTimeout de 30 s du front Next. Si la commande attend
# derrière un autre play_for_user de la même guild, c'est au bot de compter son
# budget depuis la réception (champs `timeout`/`deadline` posés par send_command).
PLAY_FOR_USER_TIMEOUT = 25
MSG_PLAY_TIMEOUT = (
    "Greg met trop de temps à répondre… La demande est peut-être encore en cours : "
    "vérifie la file avant de réessayer."
)
# Commandes qui modifient l'état (skip, stop, pause, move…) : le bot les exécute
# une par une par guild (contrat C3), donc un skip peut attendre derrière un
# play_for_user. On attend autant que lui, sinon on répondrait TIMEOUT pour une
# commande que le bot exécute quand même juste après (→ double skip au 2e clic).
MUTATING_TIMEOUT = PLAY_FOR_USER_TIMEOUT


def _body(req) -> dict:
    """Corps JSON de la requête — toujours un dict (un JSON non-objet est ignoré)."""
    data = req.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _int(v) -> int | None:
    """int() tolérant : None si la valeur n'est pas un entier valide."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _gid(req, data=None) -> int:
    if not isinstance(data, dict):
        data = _body(req)
    v = req.args.get("guild_id") or req.headers.get("X-Guild-ID") or data.get("guild_id")
    return _int(v) or 0


def _uid() -> int:
    """Utilisateur de la session Discord (SEC-C1) — le user_id du corps / X-User-ID est ignoré."""
    return session_user_id() or 0


def error_status(res: dict[str, Any], default: int = 409) -> int:
    """Code HTTP d'une réponse non-ok du bot ou du pont Redis."""
    err = str(res.get("error") or "")
    if err == "TIMEOUT":
        return 504
    if err == "BOT_OFFLINE":
        return 503
    if err == "PRIORITY_FORBIDDEN":
        return 403
    if err == "NOT_AUTHENTICATED":
        return 401
    if err == "NOT_GUILD_MEMBER":
        return 403
    return default


def _stamped(res: dict[str, Any], at_ms: int) -> dict[str, Any]:
    """relay_at_ms (synchro son/vidéo) là où le site lit `clock` : dans `state`, sinon à la racine."""
    st = res.get("state")
    return {**res, "state": with_relay_at(st, at_ms)} if isinstance(st, dict) else with_relay_at(res, at_ms)


def play_for_user_response(gid: int, uid: int, item: dict[str, Any]):
    """Envoie play_for_user au bot et construit la réponse HTTP (contrats C2/C3).

    Succès → 200 avec le résultat du bot tel quel (added/requested/truncated/…).
    Échec → 409 (403 PRIORITY_FORBIDDEN, 503 BOT_OFFLINE, 504 TIMEOUT), `message` FR transmis.
    """
    res = send_command("play_for_user", gid, uid, data={"item": item}, timeout=PLAY_FOR_USER_TIMEOUT)
    if res.get("ok"):
        return jsonify(res), 200
    if res.get("error") == "TIMEOUT":
        res = {**res, "message": MSG_PLAY_TIMEOUT}
    return jsonify(res), error_status(res)


@bp.get("/player/state")
@require_session_user
def get_state():
    gid = _gid(request)
    if not gid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400

    res = send_command("get_state", gid, _uid(), timeout=8)
    at_ms = now_ms()  # réception de la réponse du bot

    if res.get("ok"):
        return jsonify(_stamped(res, at_ms)), 200

    # Accès refusé (SEC-C1/C2) : pas un état « périmé », une vraie erreur 401/403.
    if res.get("error") in ("NOT_AUTHENTICATED", "NOT_GUILD_MEMBER"):
        return jsonify(res), error_status(res)

    # Contrat C3 : état « périmé », SANS faux current/queue vides — le front
    # garde son état précédent au lieu d'effacer la lecture en cours.
    out = {
        "ok": False,
        "stale": True,
        "backend_error": res.get("error", "unknown"),
    }
    if res.get("message"):
        out["message"] = res["message"]
    return jsonify(out), 200


@bp.post("/player/enqueue")
@require_session_user
def enqueue():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400

    query = str(data.get("query") or data.get("url") or data.get("title") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "missing query"}), 400

    item = {
        "url": data.get("url") or query,
        "title": data.get("title") or query,
        "artist": data.get("artist"),
        "duration": data.get("duration"),
        "thumb": data.get("thumb") or data.get("thumbnail"),
        "provider": data.get("provider"),
    }

    return play_for_user_response(gid, uid, item)


@bp.post("/player/skip")
@require_session_user
def skip():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("skip", gid, uid, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res, 500)
    return jsonify(res), code


@bp.post("/player/stop")
@require_session_user
def stop():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("stop", gid, uid, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res, 500)
    return jsonify(res), code


@bp.post("/player/pause")
@require_session_user
def toggle_pause():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("toggle_pause", gid, uid, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res)
    return jsonify(res), code


@bp.post("/player/repeat")
@require_session_user
def repeat():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    mode = str(data.get("mode", "toggle")).strip().lower()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("repeat", gid, uid, data={"mode": mode}, timeout=MUTATING_TIMEOUT)
    return jsonify(res), 200 if res.get("ok") else error_status(res)


@bp.post("/player/move")
@require_session_user
def move():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    src = data.get("src")
    dst = data.get("dst")
    if not gid or not uid or src is None or dst is None:
        return jsonify({"ok": False, "error": "missing params"}), 400
    src, dst = _int(src), _int(dst)
    if src is None or dst is None:
        return jsonify({"ok": False, "error": "invalid src/dst"}), 400
    res = send_command("move", gid, uid, data={"src": src, "dst": dst}, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res)
    return jsonify(res), code


@bp.delete("/player/queue/<int:index>")
@require_session_user
def remove_at(index: int):
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("remove", gid, uid, data={"index": index}, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res)
    return jsonify(res), code


# ── Compat routes (ancien front player.js) ──

@bp.post("/queue/add")
@require_session_user
def queue_add_compat():
    return enqueue()


@bp.post("/queue/skip")
@require_session_user
def queue_skip_compat():
    return skip()


@bp.post("/queue/stop")
@require_session_user
def queue_stop_compat():
    return stop()


@bp.post("/queue/remove")
@require_session_user
def queue_remove_compat():
    data = _body(request)
    idx = _int(data.get("index", 0))
    if idx is None or idx < 0:
        return jsonify({"ok": False, "error": "invalid index"}), 400
    return remove_at(idx)


@bp.get("/playlist")
@require_session_user
def playlist_state_compat():
    return get_state()


@bp.post("/playlist/toggle_pause")
@require_session_user
def playlist_pause_compat():
    return toggle_pause()


@bp.post("/playlist/repeat")
@require_session_user
def playlist_repeat_compat():
    return repeat()


@bp.post("/playlist/play_at")
@require_session_user
def playlist_play_at():
    """Joue le morceau à l'index donné dans la queue."""
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    index = _int(data.get("index", 0))
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    if index is None or index < 0:
        return jsonify({"ok": False, "error": "invalid index"}), 400
    res = send_command("play_at", gid, uid, data={"index": index}, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res)
    return jsonify(res), code


@bp.post("/playlist/restart")
@require_session_user
def playlist_restart():
    """Redémarre le morceau en cours."""
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("restart", gid, uid, timeout=MUTATING_TIMEOUT)
    code = 200 if res.get("ok") else error_status(res)
    return jsonify(res), code


@bp.post("/voice/join")
@require_session_user
def voice_join():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("join", gid, uid, timeout=MUTATING_TIMEOUT)
    return jsonify(res), 200 if res.get("ok") else error_status(res)
