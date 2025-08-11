# 🧾 Greg le Consanguin — Discord & Web Music Bot 🎩💀🎶

> *Le seul bot Discord qui obéit en râlant. À déployer sur Railway pour le torturer à distance.*

---

## 👑 Présentation

Greg est un bot Discord **et** une interface de contrôle moderne qui peut être utilisée
depuis un site web **ou** via un **overlay flottant**. Il :
    - Rejoint un salon vocal (à contrecœur)
    - Joue des musiques SoundCloud et, grâce à l’extension YouTube réactivée,
      peut à nouveau lire des vidéos YouTube via le module `extractors/youtube.py`
    - Se synchronise avec un site web **ou l’overlay** pour contrôler la playlist,
      même à distance, en conservant **une seule vérité**
    - Vous méprise en musique et en silence, sur Discord comme sur l’overlay
    - Supporte un système modulaire (`extractors/`) pour supporter d’autres sources à venir
    - Gère la playlist de façon centralisée et synchrone (bot + web/overlay → 1 seule vérité)

---

## 🎵 À propos de la musique : SoundCloud et YouTube

Pendant l’été 2024, YouTube a renforcé ses mécanismes anti‑bots et
l’extraction de pistes avait été temporairement désactivée.  Cette
version réactive la prise en charge de YouTube en s’appuyant sur
`yt‑dlp` (un fork moderne de youtube‑dl) et en permettant
l’utilisation d’un fichier de cookies pour contourner les vérifications
anti‑robot.  Si une vidéo échoue, consultez la section « Cookies
YouTube » pour générer et fournir vos cookies.  SoundCloud reste bien
entendu supporté comme source principale.

---

## 📚 Commandes disponibles

Voici la liste de toutes les tortures sonores et autres joyeusetés que Greg est contraint d’exécuter pour vous...

### 📂 General
- `/ping` : Vérifie si Greg respire encore.
- `/greg` : Révèle l'identité du larbin musical.
- `/web` : Affiche le lien de l’interface web de Greg.
- `/help` : Affiche toutes les commandes classées par catégorie.

### 📂 Music
- `/play` : Joue un son depuis une URL ou une recherche SoundCloud.
- `/skip` : Passe à la piste suivante.
- `/stop` : Stoppe tout et vide la playlist.
- `/pause` : Met en pause la musique actuelle.
- `/resume` : Reprend la lecture après une pause.
- `/playlist` : Affiche les morceaux en attente.
- `/current` : Affiche le morceau actuellement joué.

### 📂 Voice
- `/join` : Fait rejoindre Greg dans votre salon vocal misérable.
- `/leave` : Fait quitter Greg du vocal, enfin libéré de vous.
- `/restart` : Redémarre Greg le Consanguin (et vos nerfs).

---

## 🗂️ Structure du projet

```

GregLeConsanguin/
│
├── main.py                   # Point d'entrée (démarre Discord + serveur web/socketio)
├── playlist_manager.py        # Logique centralisée de playlist (thread‑safe) ; une vérité
│
├── commands/                 # Toutes les cogs Discord (slash commands)
│   ├── music.py              # Commandes /play, /skip, /stop, etc.
│   ├── voice.py              # Commandes /join, /leave, /restart
│   └── general.py            # Commandes diverses (/ping, /greg, /help)
│
├── extractors/               # Modules pour chaque source musicale
│   ├── soundcloud.py         # Recherche, extraction et stream SoundCloud
│   ├── youtube.py            # (Réactivé) Extraction/stream YouTube via yt‑dlp
│   └── __init__.py
│
├── overlay/                 # Mini‑interface en overlay pour contrôle in‑game
│   ├── overlay.py           # Tkinter + Socket.IO, always‑on‑top
│   └── __init__.py
│
├── web/                     # Site web de contrôle (Flask + SocketIO)
│   ├── app.py               # API REST + Socket.IO + OAuth
│   ├── oauth.py             # Authentification Discord
│   ├── static/              # CSS/JS/Assets
│   │   ├── style.css
│   │   ├── greg.js
│   │   └── assets/
│   │       └── greg.jpg
│   └── templates/
│       ├── index.html       # Accueil et authentification
│       ├── select.html      # Sélection du serveur/canal
│       └── panel.html       # Panel principal de gestion
│
├── tests/                   # Suite de tests unitaires (pytest)
│   ├── test_playlist_manager.py
│   └── test_extractors.py
│
├── .env (optionnel)         # Token Discord & autres secrets
├── requirements.txt          # Toutes les dépendances Python (inclut pytest)
└── README.md                 # Ce fichier

```

---

## ⚙️ Prérequis Discord Developer Portal

1. Rendez-vous sur [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → nommez-la "Greg le Consanguin"
3. **Bot** → **Add Bot** → cochez :
   - `MESSAGE CONTENT INTENT`
   - `SERVER MEMBERS INTENT`
4. Copiez le **TOKEN** du bot

### Ajouter Greg à un serveur :

- Dans `OAuth2` → `URL Generator` :
  - Scopes : `bot`
  - Bot Permissions : `Connect`, `Speak`, `Send Messages`, `Read Message History`
- Générez l’URL et invitez Greg

---

## 🚀 Déploiement sur Railway

### ✅ Étapes :

#### 1️⃣ Créer un projet Railway

- [https://railway.app](https://railway.app) → `New Project`
- Connectez votre dépôt GitHub contenant Greg

#### 2️⃣ Configurer le type de build

- **Settings** → `Build Type` → sélectionnez **Python** (pas Docker !)

#### 3️⃣ Ajouter les Variables d’Environnement :

| Nom                    | Valeur                                    | Description                                  |
|------------------------|-------------------------------------------|----------------------------------------------|
| `DISCORD_TOKEN`        | votre clé du bot Discord                  | Pour connecter Greg                          |
| `DISCORD_WEBHOOK_URL`  | Webhook d’un salon texte Discord          | Pour que le site web envoie les commandes    |
| `HUGGINGFACE_API_KEY`  | (optionnel pour chat vocal)               | Si vous utilisez la commande `!ask`          |
| `YT_COOKIES_TXT`       | contenu brut de `youtube.com_cookies.txt` | Injecté automatiquement au démarrage         |

---

## 🍪 Comment générer `youtube.com_cookies.txt`

Si certaines vidéos YouTube échouent à cause de vérifications (âge, bot, etc.) :

1. Installez l’extension **Get cookies.txt** sur Chrome ou Firefox
2. Allez sur [youtube.com](https://youtube.com) connecté à votre compte
3. Cliquez sur l’icône de l’extension > cliquez "Export cookies"
4. Enregistrez le fichier sous le nom **`youtube.com_cookies.txt`**
5. Dans Railway :
   - Onglet `Variables`
   - Créez une variable `YT_COOKIES_TXT`
   - Collez tout le contenu du fichier (y compris l’en-tête Netscape)

---

## 🧱 Configuration réseau (Networking)

1. Dans votre projet Railway :
   - Allez dans `Settings > Networking`
2. Cliquez sur **Generate Domain**
   - Une URL publique vous sera attribuée (ex: `greg.up.railway.app`)
3. Votre site web de contrôle de Greg est accessible publiquement à cette URL

---

## ⚠️ Limitations techniques

- 🎥 **Seules les musiques SoundCloud sont supportées actuellement**
- 🎥 **Les vidéos YouTube doivent faire moins de 20 minutes** (si jamais l’extracteur YouTube revient à la vie un jour)

---

## 🖥️ Interface Web

Votre site web (Flask + SocketIO) permet de :
    - Voir la playlist actuelle (mise à jour en temps réel)
    - Ajouter une musique (autocomplétion SoundCloud incluse)
    - Skip, Pause ou Stop via boutons (API REST)
    - Synchronisation immédiate avec les commandes Discord (`/play`, `/skip`, etc.)
    - Image de Greg qui tourne pendant la lecture (animation CSS)

### 🕶️ Overlay in‑game

Pour les joueurs qui souhaitent contrôler Greg sans quitter leur
jeu en plein écran, un **overlay léger** est fourni.  L’overlay
apparaît comme une petite fenêtre en haut à gauche de l’écran, à la
manière du mini‑overlay de Discord.  Il se connecte à votre serveur
local via Socket.IO pour recevoir les mises à jour de playlist et
permet d’ajouter, mettre en pause, reprendre, skip ou stopper une
musique.  Il se lance ainsi :

```bash
python -m overlay.overlay
```

Lors du démarrage, l’overlay vous demande le `guild_id` et votre
`user_id` Discord afin de savoir sur quel serveur et pour quel
utilisateur envoyer les commandes.  La fenêtre est déplaçable à la
souris, semi‑transparente et toujours au premier plan.  Les messages
d’erreur et de connexion apparaissent dans la console afin de ne pas
interrompre votre partie.

---

## 🔌 Architecture extractors/ (modulaire)

Chaque source musicale (SoundCloud…) a son propre module Python :
- `extractors/soundcloud.py` : recherche, extraction, stream
- Ajoutez vos propres extracteurs pour supporter d’autres plateformes, tout est branché automatiquement

---

## 🤝 Synchro temps réel playlist web + Discord

- Une **seule vérité** : `playlist_manager.py` (accès thread-safe)
- **Web** (Flask/SocketIO) émet chaque update à tous les clients (web et bot)
- **Bot Discord** écoute le serveur web (client SocketIO) et recharge la playlist à chaque MAJ
- **Aucune désynchronisation** possible, même si tu ajoutes/skip/stop depuis le web ou Discord

---

## 🧑‍💻 Dépendances requises

Dans `requirements.txt` :

```

discord.py==2.5.2 # petit probleme sur la derniére maj, il faut le git clone
openai
yt-dlp
ffmpeg-python
numpy>=2.2.0
gtts
python-dotenv
transformers
huggingface\_hub
torch
PyNaCl
flask
flask-socketio
python-socketio\[client]
requests

```

---

## 👨‍🔧 Astuces, debug & problèmes fréquents

- `ffmpeg` doit être installé sur Railway (et trouvable dans le PATH)
- Si le bot ne répond pas aux events du web : vérifiez que le client SocketIO est lancé et connecté
- Si la playlist web ne se met pas à jour : recharge la page, regarde la console navigateur (SocketIO doit recevoir “playlist_update”)
- **Greg râle mais il obéit.**  
Si tu veux ajouter une fonctionnalité, il souffrira encore plus… et toi aussi.

---