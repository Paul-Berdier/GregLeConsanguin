# config.py
import os
from dotenv import load_dotenv

# Charger le fichier .env
load_dotenv()

# Token Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Clé API HuggingFace (si jamais tu ajoutes des fonctions IA plus tard)
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# Cookies YouTube (pour éviter la détection de bot)
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "youtube.com_cookies.txt")

# URL du serveur Flask/Socket.IO (pour overlay)
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:3000")
