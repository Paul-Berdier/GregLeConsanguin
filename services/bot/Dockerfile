FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dépendances système (ffmpeg + audio + build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl unzip git \
    libffi-dev libsodium-dev build-essential \
  && rm -rf /var/lib/apt/lists/*

# Installe Deno (pour yt-dlp EJS)
ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh -s -- -y 2>/dev/null || true

# Shared package
COPY packages/shared/ /shared/
RUN pip install /shared/

# Bot dependencies
COPY services/bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install "discord.py[voice] @ git+https://github.com/Rapptz/discord.py@master" \
 && pip install -U "yt-dlp[default]"

# Bot code
COPY services/bot/ .

# Data directories
RUN mkdir -p /app/playlists /app/data

CMD ["python", "-m", "bot.main"]
