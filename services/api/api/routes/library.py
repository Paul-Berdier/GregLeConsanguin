"""Library routes — le chansonnier du Roi : coups de cœur et playlists (spec 2026-11-23 §3).

Identité : la session seule (SEC-C1), jamais le user_id du corps ni X-User-ID. Rien ne passe par le bot :
les données sont au Roi, pas à une guild (stockage : api.services.library_store).

Toutes les mutations sont des POST JSON (get_json silencieux : un formulaire inter-sites n'est pas lu) et
renvoient {ok: true, library} (la bibliothèque complète, en UTF-8 non échappé) plus leurs champs propres.
Les entrées sont validées AVANT tout accès à Redis : une requête invalide reçoit 400 même Redis coupé.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from api.services import library_store as store
from api.services.authz import require_session_user, session_user_id
from api.services.library_store import LibraryError

bp = Blueprint("library", __name__)


def _body() -> dict[str, Any]:
    """Corps JSON objet, sinon INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise LibraryError("INVALID_REQUEST", store.MSG_INVALID_REQUEST, 400)
    return data


def _error(e: LibraryError):
    return jsonify(e.body()), e.status


def _ok(body: dict[str, Any]):
    """200 {ok: true, …} en UTF-8 tel quel. jsonify échappe chaque caractère non ASCII (« é » → 6 octets, un emoji
    → 12) : la bibliothèque complète pèserait jusqu'à 3 fois sa valeur stockée (MAX_LIBRARY_BYTES)."""
    data = current_app.json.dumps({"ok": True, **body}, ensure_ascii=False, separators=(",", ":"))
    return current_app.response_class(f"{data}\n", mimetype="application/json"), 200


def _mutate(build: Callable[[dict[str, Any], int], store.Op]):
    """build(corps, maintenant) valide l'entrée et renvoie l'opération ; erreurs → réponse JSON codée."""
    try:
        op = build(_body(), int(time.time()))
        library, extra = store.mutate(session_user_id(), op)
    except LibraryError as e:
        return _error(e)
    return _ok({"library": library, **extra})


@bp.get("/library")
@require_session_user
def get_library():
    try:
        library = store.read_library(session_user_id())
    except LibraryError as e:
        return _error(e)
    return _ok({"library": library})


# ── Coups de cœur ──

@bp.post("/library/likes/add")
@require_session_user
def likes_add():
    # `index` facultatif (annulation d'un retrait : le titre revient à son rang) ; absent, en tête.
    return _mutate(lambda b, now: store.op_add_like(store.clean_track(b.get("track"), now),
                                                    store.clean_position(b.get("index"))))


@bp.post("/library/likes/remove")
@require_session_user
def likes_remove():
    return _mutate(lambda b, now: store.op_remove_like(store.clean_url_ref(b.get("url"))))


# ── Playlists ──

def _create(b: dict[str, Any], now: int) -> store.Op:
    name = store.clean_name(b.get("name"))
    tracks = b.get("tracks")
    tracks = [] if tracks is None else store.clean_tracks(tracks, now)
    return store.op_create_playlist(name, tracks, now)


@bp.post("/library/playlists/create")
@require_session_user
def playlists_create():
    return _mutate(_create)


def _restore(b: dict[str, Any], now: int) -> store.Op:
    return store.op_restore_playlist(store.clean_restored_playlist(b.get("playlist"), now),
                                     store.clean_position(b.get("index")))


@bp.post("/library/playlists/restore")
@require_session_user
def playlists_restore():
    """Annulation d'une suppression : {playlist: {id, name, tracks, created_at, updated_at}, index} la remet à
    son rang, sous son id ; déjà là → succès sans changement."""
    return _mutate(_restore)


@bp.post("/library/playlists/rename")
@require_session_user
def playlists_rename():
    return _mutate(lambda b, now: store.op_rename_playlist(
        store.clean_playlist_id(b.get("id")), store.clean_name(b.get("name")), now))


@bp.post("/library/playlists/delete")
@require_session_user
def playlists_delete():
    return _mutate(lambda b, now: store.op_delete_playlist(store.clean_playlist_id(b.get("id"))))


def _add(b: dict[str, Any], now: int) -> store.Op:
    pid = store.clean_playlist_id(b.get("id"))
    tracks = store.clean_tracks(b.get("tracks"), now)
    if not tracks:
        raise LibraryError("INVALID_REQUEST", store.MSG_INVALID_REQUEST, 400)
    return store.op_add_tracks(pid, tracks, now)


@bp.post("/library/playlists/add")
@require_session_user
def playlists_add():
    return _mutate(_add)


@bp.post("/library/playlists/remove")
@require_session_user
def playlists_remove():
    return _mutate(lambda b, now: store.op_remove_track(
        store.clean_playlist_id(b.get("id")), store.clean_url_ref(b.get("url")), now))


def _move(b: dict[str, Any], now: int) -> store.Op:
    # `url` facultatif : le titre attendu au rang src (409 STALE si la copie du site est dépassée).
    url = b.get("url")
    return store.op_move_track(
        store.clean_playlist_id(b.get("id")), store.clean_index(b.get("src")), store.clean_index(b.get("dst")),
        now, None if url is None else store.clean_url_ref(url))


@bp.post("/library/playlists/move")
@require_session_user
def playlists_move():
    return _mutate(_move)
