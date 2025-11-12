# Utilise une image Python récente
FROM python:3.12-slim

# Evite les .pyc et active stdout non bufferisé
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dépendances système (ffmpeg, curl, unzip pour Deno, libs audio/GUI, build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl unzip \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-6 libx11-xcb1 \
    libxcb-dri3-0 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxkbcommon0 libxrandr2 libxshmfence1 libpango-1.0-0 libxrender1 \
    git libffi-dev libsodium-dev build-essential \
  && rm -rf /var/lib/apt/lists/*

# Installe Deno (EJS yt-dlp) dans /usr/local/bin (pas besoin de modifier le PATH)
ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh -s -- -y && deno --version

# Copie l'app
COPY . .

# Dépendances Python
# - discord.py[voice] (dev) + requirements.txt
# - yt-dlp[default] pour activer le runtime JS (EJS/cipher) côté yt-dlp
RUN python -m pip install --upgrade pip && \
    pip install "discord.py[voice] @ git+https://github.com/Rapptz/discord.py@master" && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install -U "yt-dlp[default]"

# (Si tu utilises Playwright ailleurs) — sinon commente cette ligne
RUN python -m playwright install chromium || true

# Lancement
CMD ["python", "main.py"]
