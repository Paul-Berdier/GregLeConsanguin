# 🧾 Greg le Consanguin — Discord & Web Music Bot 🎩💀🎶

> *Le seul bot Discord qui obéit en râlant. À déployer sur Railway pour le torturer à distance.*

---

## 👑 Présentation

Greg est un bot Discord **et** une interface web moderne qui :
- Rejoint un salon vocal (à contrecœur)
- Joue des musiques SoundCloud (YouTube non supporté actuellement)
- Se synchronise avec un site web pour contrôler la playlist, même à distance
- Vous méprise en musique et en silence, sur Discord comme sur le web
- Supporte un système modulaire (`extractors/`) pour supporter d’autres sources à venir
- Gère la playlist de façon centralisée et synchrone (bot + web → 1 seule vérité)

---

## 🎵 À propos de la musique : SoundCloud only

**⚠️ La sécurité YouTube s’est renforcée mi-2024.**
- L’extraction via `yt-dlp` est instable, la plupart des morceaux ne fonctionnent plus correctement (restriction, cookies, login obligatoire…)
- **Greg ne supporte actuellement que SoundCloud pour la recherche et la lecture.**
- Dès que possible, l’extraction YouTube sera réactivée via une mise à jour d’extractors/youtube.py

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
├── main.py                   # Point d'entrée : lance Discord et le serveur web/SocketIO
├── playlist_manager.py       # Gestion centralisée de la playlist (thread‑safe)
│
├── commands/                 # Toutes les cogs Discord
│   ├── music.py
│   ├── voice.py
│   └── …
│
├── extractors/               # Modules pour chaque source musicale
│   ├── soundcloud.py
│   ├── youtube.py            # Peut être temporairement indisponible selon les restrictions YouTube
│   └── …
│
├── web/
│   ├── app.py                # Flask + SocketIO (API et interface web)
│   ├── oauth.py              # Authentification OAuth2 avec Discord
│   ├── static/
│   │   ├── style.css
│   │   ├── greg.js
│   │   └── assets/
│   │       └── greg.jpg
│   └── templates/
│       ├── index.html
│       ├── select.html
│       ├── panel.html
│       └── search_results.html
│
├── config.py                 # Charge les variables d’environnement (via dotenv)
├── requirements.txt          # Dépendances Python épinglées
├── youtube.com_cookies.txt   # (optionnel) Cookies bruts pour YouTube (voir section dédiée)
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

Le fichier `requirements.txt` contient des versions **épinglées** afin de garantir
une installation reproductible. Par exemple, au 4 mars 2025, `discord.py` en
version 2.5.2 est le dernier SDK stable publié sur PyPI et supporte la voix.

Pour installer toutes les dépendances, exécutez :

```bash
python -m pip install -r requirements.txt
```

Les principales dépendances sont :

- **`discord.py[voice]`** : wrapper Discord asynchrone utilisé par le bot ;
- **`flask`** et **`flask-socketio`** : API et interface web en temps réel ;
- **`python-socketio[client]`** : client Socket.IO du côté bot pour écouter les
  mises à jour du serveur web ;
- **`yt-dlp`** et **`ffmpeg-python`** : extraction et conversion des flux audio ;
- **`numpy`**, **`gtts`**, **`transformers`**, **`huggingface_hub`**, **`torch`** :
  dépendances pour les extensions IA et la commande vocale `!ask` (facultatif) ;
- **`python-dotenv`** : chargement des variables d’environnement à partir d’un
  fichier `.env` ;
- **`requests`** : requêtes HTTP pour l’authentification OAuth2 et les APIs.

Le fichier `requirements.txt` spécifie les versions recommandées de chaque
package. Pensez à le mettre à jour régulièrement et à tester après chaque
upgrade.

---

## 👨‍🔧 Astuces, debug & problèmes fréquents

- `ffmpeg` doit être installé sur Railway (et trouvable dans le PATH)
- Si le bot ne répond pas aux events du web : vérifiez que le client SocketIO est lancé et connecté
- Si la playlist web ne se met pas à jour : recharge la page, regarde la console navigateur (SocketIO doit recevoir “playlist_update”)
- **Greg râle mais il obéit.**  
Si tu veux ajouter une fonctionnalité, il souffrira encore plus… et toi aussi.

---