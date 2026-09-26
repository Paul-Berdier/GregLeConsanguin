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
# - discord.py[voice] >= 2.7.1 : DAVE (E2EE vocal) obligatoire côté Discord
# - yt-dlp : plancher seulement, rafraîchi plus bas dans une couche dédiée
# - playwright + son binaire Chromium (PO tokens, auto-fetch opt-in)
# ─────────────────────────────────────────────────────────────
COPY services/bot/requirements.txt .
RUN pip install -r requirements.txt

# Installation Playwright + binaire Chromium + deps système.
# L'auto-fetch des PO tokens est opt-in (YT_PO_AUTOFETCH=1) : on garde
# Chromium dans l'image pour pouvoir l'activer sans rebuild.
RUN python -m playwright install --with-deps chromium \
 && find "${PLAYWRIGHT_BROWSERS_PATH:-/root/.cache/ms-playwright}" -type d | head -5

# Runtime JavaScript Deno — requis par yt-dlp ≥2025.11 (EJS) pour résoudre
# les signatures des flux YouTube sur les clients web (avec cookies).
# Sans lui: "Requested format is not available" même avec des cookies valides.
RUN curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip \
 && unzip -o /tmp/deno.zip -d /usr/local/bin \
 && rm /tmp/deno.zip \
 && chmod +x /usr/local/bin/deno \
 && deno --version

# ─────────────────────────────────────────────────────────────
# yt-dlp toujours à jour : couche séparée et tardive.
# YouTube casse régulièrement les vieux extracteurs/solveurs EJS, et le cache
# de layers (Railway/BuildKit) figerait sinon la version résolue au dernier
# changement de requirements.txt. Cette couche est invalidée :
#   - à chaque commit déployé (Railway injecte RAILWAY_GIT_COMMIT_SHA) ;
#   - à la demande via YTDLP_REFRESH (variable Railway ou build arg compose,
#     ex: la date du jour) — ou NO_CACHE=1 sur Railway pour tout reconstruire.
# Placée après Chromium/Deno pour ne pas les re-télécharger à chaque fois.
# ─────────────────────────────────────────────────────────────
ARG RAILWAY_GIT_COMMIT_SHA=""
ARG YTDLP_REFRESH=""
RUN echo "yt-dlp refresh (commit=${RAILWAY_GIT_COMMIT_SHA:-local}, refresh=${YTDLP_REFRESH:-none})" \
 && pip install -U "yt-dlp[default]" \
 && python -m yt_dlp --version

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
