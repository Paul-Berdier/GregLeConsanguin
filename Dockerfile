# Utilise une image Python récente
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Déps système (ffmpeg + voice)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    libffi-dev \
    libsodium-dev \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copie *tout* le projet (incluant tests/, à condition qu'il ne soit pas ignoré)
COPY . .

# Déps Python
RUN pip install --upgrade pip && \
    pip install "discord.py[voice] @ git+https://github.com/Rapptz/discord.py@master" && \
    pip install --no-cache-dir -r requirements.txt

# -------- Étape tests (exécutée pendant le build) --------
# On peut l'ignorer avec: docker build --build-arg SKIP_TESTS=1 .
ARG SKIP_TESTS=0
RUN if [ "$SKIP_TESTS" != "1" ]; then \
 echo "== Lancer uniquement les tests YouTube ==" && \
      pip install --no-cache-dir pytest pytest-asyncio && \
      YTDBG=0 YTDBG_HTTP_PROBE=0 DISABLE_WEB=1 \
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
      python -m pytest -q tests/test_youtube_extractor.py || (echo 'Pytest a échoué'; exit 1); \
    else \
      echo 'SKIP_TESTS=1 -> tests sautés'; \
    fi

# Commande de démarrage du bot
CMD ["python", "main.py"]
