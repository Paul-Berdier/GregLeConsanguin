"""Web application package for Greg refonte.

This package exposes a factory function to create a Flask app and
associated SocketIO instance for the music bot's web interface.
"""

from .app import create_web_app  # noqa: F401
