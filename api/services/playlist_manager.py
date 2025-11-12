# api/services/playlist_manager.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import abort, current_app


def _pm():
    pm = current_app.extensions.get("pm")
    if pm is None:
        abort(503, description="PlaylistManager not available.")
    return pm


def get_state() -> Dict[str, Any]:
    """
    Renvoie l'état de la lecture/queue depuis le PlaylistManager externe.
    """
    pm = _pm()
    try:
        return pm.get_state()
    except AttributeError:
        abort(501, description="PlaylistManager.get_state() not implemented.")


def enqueue(query: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    pm = _pm()
    try:
        return pm.enqueue(query=query, user_id=user_id)
    except AttributeError:
        abort(501, description="PlaylistManager.enqueue() not implemented.")


def skip() -> Dict[str, Any]:
    pm = _pm()
    try:
        return pm.skip()
    except AttributeError:
        abort(501, description="PlaylistManager.skip() not implemented.")


def stop() -> Dict[str, Any]:
    pm = _pm()
    try:
        return pm.stop()
    except AttributeError:
        abort(501, description="PlaylistManager.stop() not implemented.")
