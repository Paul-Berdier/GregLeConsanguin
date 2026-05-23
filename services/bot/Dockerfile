# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ─────────────────────────────────────────────────────────────
# Dépendances système (FFmpeg + audio + libs Playwright/Chromium)
# `playwright install --with-deps chromium` ajoute le reste,
# on garde l'image lean en n'installant que le minimum vital ici.
# ─────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        unzip \
        git \
        libffi-dev \
        libsodium-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────────────────────
# Shared package (config, extractors, priority…)
# ─────────────────────────────────────────────────────────────
COPY packages/shared/ /shared/
RUN pip install /shared/

# ─────────────────────────────────────────────────────────────
# Dépendances Python du bot
# - yt-dlp est pinné à une version récente connue stable
# - discord.py 2.4 (release officielle, pas master) — voice OK
# - playwright + son binaire Chromium (CRITIQUE pour PO tokens)
# ─────────────────────────────────────────────────────────────
COPY services/bot/requirements.txt .
RUN pip install -r requirements.txt

# Installation Playwright + binaire Chromium + deps système
# C'EST LE FIX CENTRAL: sans cette étape, fetch_po_token() échoue
# silencieusement et yt-dlp se prend des 403 en boucle.
RUN python -m playwright install --with-deps chromium \
 && find "${PLAYWRIGHT_BROWSERS_PATH:-/root/.cache/ms-playwright}" -type d | head -5

# ─────────────────────────────────────────────────────────────
# Code du bot
# ─────────────────────────────────────────────────────────────
COPY services/bot/ .

# Répertoires persistants
RUN mkdir -p /app/playlists /app/data /app/history

# ─────────────────────────────────────────────────────────────
# Sanity check au build : vérifie que les browsers sont bien là.
# Si ce check casse, le build casse aussi → on ne déploie pas
# une image qui repartirait en boucle 403 en prod.
# ─────────────────────────────────────────────────────────────
RUN python - <<'PY'
import os, sys, pathlib
base = pathlib.Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright"))
hits = list(base.rglob("chrome")) + list(base.rglob("chrome-linux/chrome"))
if not any(p.is_file() and os.access(p, os.X_OK) for p in hits):
    sys.exit(f"FATAL: Playwright Chromium absent de {base}")
print("OK: Playwright Chromium présent.")
PY

CMD ["python", "-m", "bot.main"]
