# backend/api/blueprints/playlist.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth.session import require_login
from ..services import playlist_manager as PM
from ..services.search import autocomplete

bp = Blueprint("playlist", __name__)


@bp.get("/playlist")
def get_playlist_state():
    return jsonify({"ok": True, "state": PM.get_state()})


@bp.post("/playlist/enqueue")
@require_login
def enqueue():
    data = request.get_json(silent=True) or {}
    q = data.get("query")
    if not q:
        return jsonify({"ok": False, "error": "Missing 'query'"}), 400
    result = PM.enqueue(q)
    return jsonify({"ok": True, "result": result})


@bp.post("/playlist/skip")
@require_login
def skip():
    return jsonify({"ok": True, "result": PM.skip()})


@bp.post("/playlist/stop")
@require_login
def stop():
    return jsonify({"ok": True, "result": PM.stop()})


@bp.get("/autocomplete")
def auto():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", "8"))
    return jsonify({"ok": True, "items": autocomplete(q, limit=limit)})
