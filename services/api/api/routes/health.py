"""Health check routes."""
from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    return jsonify({"ok": True, "service": "greg-api"}), 200


@bp.get("/healthz")
def healthz():
    return jsonify({"ok": True}), 200
