# Utilise une image Python récente et compatible avec GLIBC 2.38
FROM python:3.12-slim

# Installe ffmpeg et ses dépendances
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Définit le répertoire de travail
WORKDIR /app

# Copie les fichiers du projet
COPY . .

# Installe les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Définit la commande de lancement
CMD ["python", "main.py"]
