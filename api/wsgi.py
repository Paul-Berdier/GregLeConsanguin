# api/wsgi.py
from __future__ import annotations

from . import create_app

# Gunicorn entrypoint: gunicorn -w 1 -k eventlet -b :8000 backend.api.wsgi:app
app = create_app()
