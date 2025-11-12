# api/core/errors.py
from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http(e: HTTPException):
        payload: dict[str, Any] = {
            "ok": False,
            "status": e.code,
            "error": e.name,
            "message": e.description,
            "path": request.path,
        }
        return jsonify(payload), e.code

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        log.exception("Unhandled error: %s", e)
        payload = {
            "ok": False,
            "status": 500,
            "error": "InternalServerError",
            "message": "An unexpected error occurred.",
            "path": request.path,
        }
        return jsonify(payload), 500
