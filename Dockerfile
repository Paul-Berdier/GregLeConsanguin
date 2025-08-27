# Utilise une image Python récente
FROM python:3.12-slim
 
# Évite l'écriture de fichiers .pyc et active le mode verbeux
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Définit le répertoire de travail
WORKDIR /app

# Installe git, ffmpeg et les libs nécessaires à l'audio (PyNaCl)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    libffi-dev \
    libsodium-dev \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copie les fichiers de l'app
COPY . .

# Met à jour pip et installe la version dev de discord.py avec l'extra [voice]
RUN pip install --upgrade pip && \
    pip install "discord.py[voice] @ git+https://github.com/Rapptz/discord.py@master" && \
    pip install --no-cache-dir -r requirements.txt

# Commande de démarrage du bot
CMD ["python", "main.py"]
