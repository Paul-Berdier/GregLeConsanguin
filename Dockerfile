# Image Python slim + ffmpeg + Playwright Chromium (headless)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OS deps (ffmpeg, playwright deps)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates gnupg wget \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libasound2 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
        libgtk-3-0 fonts-liberation && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt && \
    python -m playwright install --with-deps chromium

# Code
COPY . /app

# Expose (si Flask)
EXPOSE 8000

# Variables d'env utiles (adapter si besoin)
# YTDLP_COOKIES_BROWSER=chrome:Default
# YTDLP_COOKIES_B64=<netscape_cookie_file_base64>
# YT_PO_TOKEN=<fallback_token_si_auto_fetch_échoue>

# Commande (exemple Flask + eventlet). Adapte à ton entrypoint.
CMD ["python", "app.py"]
