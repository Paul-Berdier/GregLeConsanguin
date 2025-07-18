## 🧾 `README.md` — **Greg le Consanguin** 🎩💀🎶

> *Le seul bot Discord qui obéit en râlant. À déployer sur Railway pour le torturer à distance.*

---

## **👑 Présentation**

Greg est un bot Discord qui :

* Rejoint un salon vocal (à contrecœur)
* Joue des musiques YouTube avec `yt-dlp` et `ffmpeg`
* Se synchronise avec un site web pour le contrôler comme un esclave
* Vous méprise en musique et en silence
* Supporte **plusieurs sources musicales** : YouTube, SoundCloud… et d'autres à venir
* Utilise un système modulaire propre (`extractors/`) pour gérer chaque source individuellement

---

## **⚙️ Prérequis Discord Developer Portal**

1. Allez sur [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → nommez-la "Greg le Consanguin"
3. **Bot** → **Add Bot** → cochez :

   * `MESSAGE CONTENT INTENT`
   * `SERVER MEMBERS INTENT`
4. Copiez le **TOKEN** du bot

### Ajouter Greg à un serveur :

* Allez dans `OAuth2` → `URL Generator`

  * Scopes : `bot`
  * Bot Permissions : `Connect`, `Speak`, `Send Messages`, `Read Message History`
* Générez l’URL et invitez Greg

---

## **🚀 Déploiement sur Railway**

### ✅ Étapes :

#### 1️⃣ Créer un projet Railway

* [https://railway.app](https://railway.app) → `New Project`
* Connectez votre dépôt GitHub contenant Greg

#### 2️⃣ Configurer le type de build

* **Settings** → `Build Type` → sélectionnez **Python** (pas Docker)

#### 3️⃣ Ajouter les Variables d’Environnement (onglet `Variables`) :

| Nom                    | Valeur                           | Description                               |
| ---------------------- | -------------------------------- | ----------------------------------------- |
| `DISCORD_TOKEN`        | votre clé du bot Discord         | Pour connecter Greg                       |
| `DISCORD_WEBHOOK_URL`  | Webhook d’un salon texte Discord | Pour que le site web envoie les commandes |
| `HUGGINGFACE_API_KEY`  | (optionnel pour chat vocal)      | Si vous utilisez `!ask`                   |
| `YT_COOKIES_TXT`       | contenu brut de `youtube.com_cookies.txt` | Injecté automatiquement au démarrage |

---

## 🍪 Comment générer `youtube.com_cookies.txt`

Si certaines vidéos YouTube échouent à cause de vérifications (âge, bot, etc.) :

1. Installez l’extension **Get cookies.txt** sur Chrome ou Firefox
2. Allez sur [youtube.com](https://youtube.com) connecté à votre compte
3. Cliquez sur l’icône de l’extension > cliquez "Export cookies"
4. Enregistrez le fichier sous le nom **`youtube.com_cookies.txt`**
5. Dans Railway :

   * Ouvrez l’onglet `Variables`
   * Créez une variable nommée `YT_COOKIES_TXT`
   * Collez **tout le contenu du fichier**, y compris l’en-tête Netscape
   * Greg le convertira automatiquement en fichier local à chaque redémarrage

---

## 🧱 Configuration réseau (Networking)

1. Dans votre projet Railway :

   * Allez dans `Settings > Networking`
2. Cliquez sur **Generate Domain**

   * Une URL publique vous sera attribuée (ex: `greg.up.railway.app`)
3. Votre site web de contrôle de Greg est accessible publiquement à cette URL

---

## ⚠️ Limitations techniques

* 🎥 **Les vidéos YouTube doivent faire moins de 20 minutes**

  * Au-delà, Greg refuse de souffrir : cela provoque une erreur ou un plantage
  * Limite fixée dans `music.py` à 1200 secondes

---

## 🖥️ Interface Web

Votre site web (Flask) permet de :

* Voir la playlist actuelle
* Ajouter une musique
* Skip, Pause ou Stop via boutons
* Synchronisation avec les commandes Discord (`!play`, `!skip`, etc.)

---

## 🧪 Commandes Discord

| Commande      | Effet                                               |
| ------------- | --------------------------------------------------- |
| `!join`       | Greg rejoint le vocal (en râlant)                   |
| `!leave`      | Greg quitte le vocal (soulagé)                      |
| `!play <texte ou lien>` | Si lien → joue direct. Si texte → Greg vous demande YouTube ou SoundCloud |
| `!pause`      | Met en pause                                        |
| `!resume`     | Reprend                                             |
| `!skip`       | Passe à la suivante et retire de la playlist        |
| `!stop`       | Coupe tout et vide la file                          |
| `!playlist`   | Affiche la file d’attente                           |
| `!current`    | Affiche la musique en cours                         |
| `!ask`        | (optionnel) Greg répond en vocal via IA HuggingFace |

---

## 🔌 Architecture `extractors/` (système modulaire)

Chaque source musicale (YouTube, SoundCloud…) est gérée dans un module dédié :

