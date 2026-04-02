"""Error handlers for the Flask app."""
from __future__ import annotations

import logging
from flask import jsonify

logger = logging.getLogger("greg.api.errors")


def register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"ok": False, "error": "bad_request", "message": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"ok": False, "error": "not_found"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("Internal server error: %s", e)
        return jsonify({"ok": False, "error": "internal_error"}), 500
