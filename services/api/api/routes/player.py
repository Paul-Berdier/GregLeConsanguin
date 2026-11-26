"""Player routes — contrôle du lecteur de musique via Redis bridge."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from api.services.authz import current_user_id, require_identity
from api.services.bot_bridge import send_command
from api.services.library_store import (
    QUEUE_ITEM_KEYS,
    LibraryError,
    clean_label,
    clean_tracks,
)
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
# /queue/add_many (chansonnier du Roi) : une playlist d'un geste, 1 à ADD_MANY_MAX titres.
ADD_MANY_MAX = 100
MSG_ADD_MANY_COUNT = f"Envoyez entre 1 et {ADD_MANY_MAX} titres à la fois."
# remove / move / play_at : l'élément attendu (`expected`) n'est plus à l'index visé (spec §3.6).
MSG_STALE = "La file a bougé : réessayez."


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
    """Utilisateur de la session ou du jeton de l'appli (SEC-C1) — le user_id du corps / X-User-ID est ignoré."""
    return current_user_id() or 0


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
    if err == "STALE":
        return 409
    return default


def _expected_of(data: dict) -> dict | None:
    """Élément attendu `{url, added_by, ts}` de remove / move / play_at (spec §3.6), None s'il n'est pas fourni.

    `url` texte ou None, `added_by` texte, entier ou None, `ts` nombre (pas booléen) ou None ;
    toute autre forme → ValueError (400 « invalid expected », sans appel au bot).
    """
    expected = data.get("expected")
    if expected is None:
        return None
    if not isinstance(expected, dict):
        raise ValueError("expected n'est pas un objet")
    url, added_by, ts = expected.get("url"), expected.get("added_by"), expected.get("ts")
    if url is not None and not isinstance(url, str):
        raise ValueError("expected.url")
    if added_by is not None and (isinstance(added_by, bool) or not isinstance(added_by, (str, int))):
        raise ValueError("expected.added_by")
    if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
        raise ValueError("expected.ts")
    return {"url": url, "added_by": added_by, "ts": ts}


def _queue_edit(action: str, gid: int, uid: int, data: dict, cmd: dict[str, Any]):
    """remove / move / play_at : `expected` transmis au bot seulement s'il est fourni, STALE → 409 et MSG_STALE."""
    try:
        expected = _expected_of(data)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid expected"}), 400
    if expected is not None:
        cmd = {**cmd, "expected": expected}
    res = send_command(action, gid, uid, data=cmd, timeout=MUTATING_TIMEOUT)
    if res.get("ok"):
        return jsonify(res), 200
    if res.get("error") == "STALE":
        res = {**res, "message": MSG_STALE}
    return jsonify(res), error_status(res)


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
@require_identity
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
@require_identity
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


@bp.post("/queue/add_many")
@require_identity
def queue_add_many():
    """Ajoute une liste de titres connus (playlist ou coups de cœur du chansonnier) en UNE commande.

    Titres nettoyés comme ceux du chansonnier (library_store.clean_tracks : lien http(s) obligatoire), puis
    transmis au bot réduits aux 6 clés d'un item de file : item = {"items": [...], "title": label}.
    Même délai et même réponse HTTP que /player/enqueue (play_for_user_response).
    """
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    raw = data.get("items")
    if not isinstance(raw, list) or not 1 <= len(raw) <= ADD_MANY_MAX:
        return jsonify({"ok": False, "error": "INVALID_REQUEST", "message": MSG_ADD_MANY_COUNT}), 400
    try:
        tracks = clean_tracks(raw, max_items=ADD_MANY_MAX)
        label = clean_label(data.get("label"))
    except LibraryError as e:
        return jsonify(e.body()), e.status
    items = [{k: t[k] for k in QUEUE_ITEM_KEYS} for t in tracks]
    return play_for_user_response(gid, uid, {"items": items, "title": label})


@bp.post("/player/skip")
@require_identity
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
@require_identity
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
@require_identity
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
@require_identity
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
@require_identity
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
    return _queue_edit("move", gid, uid, data, {"src": src, "dst": dst})


@bp.delete("/player/queue/<int:index>")
@require_identity
def remove_at(index: int):
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    return _queue_edit("remove", gid, uid, data, {"index": index})


# ── Compat routes (ancien front player.js) ──

@bp.post("/queue/add")
@require_identity
def queue_add_compat():
    return enqueue()


@bp.post("/queue/skip")
@require_identity
def queue_skip_compat():
    return skip()


@bp.post("/queue/stop")
@require_identity
def queue_stop_compat():
    return stop()


@bp.post("/queue/remove")
@require_identity
def queue_remove_compat():
    data = _body(request)
    idx = _int(data.get("index", 0))
    if idx is None or idx < 0:
        return jsonify({"ok": False, "error": "invalid index"}), 400
    return remove_at(idx)


@bp.get("/playlist")
@require_identity
def playlist_state_compat():
    return get_state()


@bp.post("/playlist/toggle_pause")
@require_identity
def playlist_pause_compat():
    return toggle_pause()


@bp.post("/playlist/repeat")
@require_identity
def playlist_repeat_compat():
    return repeat()


@bp.post("/playlist/play_at")
@require_identity
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
    return _queue_edit("play_at", gid, uid, data, {"index": index})


@bp.post("/playlist/restart")
@require_identity
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
@require_identity
def voice_join():
    data = _body(request)
    gid = _gid(request, data)
    uid = _uid()
    if not gid or not uid:
        return jsonify({"ok": False, "error": "missing guild_id"}), 400
    res = send_command("join", gid, uid, timeout=MUTATING_TIMEOUT)
    return jsonify(res), 200 if res.get("ok") else error_status(res)
