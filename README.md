# 👑 Greg le Consanguin — v2

> *"Je suis pas grognon, je suis en mode économie d'empathie."*

Bot Discord musical avec interface web, thème médiéval, et architecture microservices.

## Architecture

```
┌──────────┐    Redis Pub/Sub     ┌──────────┐
│   Bot    │◄────────────────────►│   API    │
│ Discord  │  greg:commands       │  REST +  │
│ + Audio  │  greg:player:*       │   WS     │
└──────────┘                      └────┬─────┘
                                       │ HTTP + WS
                                  ┌────┴─────┐
                                  │   Web    │
                                  │ Next.js  │
                                  └──────────┘
```

**4 services Docker :**

| Service | Stack | Port | Rôle |
|---------|-------|------|------|
| `bot` | Python + discord.py + FFmpeg | — | Bot Discord, lecture audio, commandes slash |
| `api` | Python + Flask + Socket.IO | 3000 | API REST, WebSocket, OAuth Discord |
| `web` | Next.js + Tailwind | 3001 | Interface web player, DA médiévale |
| `redis` | Redis 7 | 6379 | Bus de messages entre services |

## Démarrage rapide

### Prérequis
- Docker + Docker Compose
- Un bot Discord créé sur [discord.com/developers](https://discord.com/developers)

### 1. Configuration
```bash
cp .env.example .env
# Éditer .env avec vos tokens Discord, etc.
```

### 2. Lancement
```bash
docker compose up --build
```

### 3. Accès
- **Web Player** : http://localhost:3001
- **API** : http://localhost:3000/api/v1/health

## Structure du projet

```
greg-le-consanguin/
├── docker-compose.yml
├── .env.example
├── packages/
│   └── shared/                 # Code partagé entre services
│       └── greg_shared/
│           ├── config.py       # Config centralisée (pydantic-settings)
│           ├── models.py       # Schémas Pydantic
│           ├── constants.py    # Personnalité de Greg (réponses)
│           ├── priority.py     # Système de priorité (v2)
│           └── extractors/     # YouTube, SoundCloud, Spotify
├── services/
│   ├── bot/                    # Discord Bot
│   │   └── bot/
│   │       ├── main.py
│   │       ├── greg_bot.py
│   │       ├── cogs/           # Commandes slash
│   │       └── services/       # PlayerService, PlaylistManager, Redis
│   ├── api/                    # REST API + WebSocket
│   │   └── api/
│   │       ├── main.py
│   │       ├── routes/         # Endpoints REST
│   │       ├── websocket/      # Socket.IO handlers
│   │       └── services/       # Bot bridge via Redis
│   ├── web/                    # Frontend Next.js
│   │   └── src/
│   │       ├── app/            # Pages (App Router)
│   │       ├── hooks/          # usePlayer, useAuth
│   │       ├── lib/            # API client, Socket.IO, types
│   │       └── theme/          # DA médiévale
│   └── voice-ai/              # IA conversationnelle (futur)
└── infra/
    └── railway.toml
```

## Système de priorité

Le système gère qui peut contrôler quoi dans la queue musicale :

| Poids | Source | Droits |
|-------|--------|--------|
| 10 000 | `__OWNER__` | Tout |
| 100 | `__ADMIN__` (permission Discord) | Tout, bypass quota |
| 90 | `__MANAGE_GUILD__` | Tout, bypass quota |
| 80 | Rôle `DJ` | Contrôle complet |
| 60 | Rôle `VIP` | Contrôle si poids ≥ owner du morceau |
| 45 | Rôle `Booster` | Prioritaire dans la queue |
| 10 | `__DEFAULT__` | FIFO normal, quota appliqué |

**Règles clés :**
- Poids ≥ owner du morceau → skip/pause/stop autorisé (même rang = OK)
- Ses propres morceaux → toujours modifiables/supprimables
- Seuil de priorité configurable (`PRIORITY_THRESHOLD=50`)
- Queue en 2 zones : prioritaire (poids > seuil) puis normale (FIFO)

## Personnalité de Greg

Greg est un gueux du Moyen Âge, mi-Jacquouille mi-serviteur râleur. Il **tutoie** et **parle directement** aux utilisateurs :

```
🎵 C'est bon @user, je te mets ça. T'as intérêt à écouter au moins.
⏭️ Skippé. Fallait le faire plus tôt si tu veux mon avis.
⛔ Toi ? Toucher à ça ? Avec ton rang ? Laisse-moi rire.
👑 Bon, j'arrive dans General. Faites-moi de la place, gueux.
```

## Commandes Discord

| Commande | Description |
|----------|-------------|
| `/play <query>` | Joue un morceau (recherche ou URL) |
| `/skip` | Passe au suivant |
| `/stop` | Stoppe et vide la file |
| `/pause` | Pause / reprend |
| `/playlist` | Affiche la file |
| `/repeat` | Active/désactive le repeat |
| `/join` | Rejoint le vocal |
| `/leave` | Quitte le vocal |
| `/ping` | Latence du bot |
| `/greg` | Qui est Greg ? |
| `/help` | Liste des commandes |
| `/roll <NdM>` | Lance des dés JDR |
| `/tarot` | Tire une carte |
| `/curse @user` | Malédiction RP |
| `/praise @user` | Compliment rare |
| `/shame @user` | 🔔 Shame! |
| `/priority weights` | (Owner) Voir les poids |
| `/priority setrole` | (Owner) Configurer un rôle |
| `/yt_cookies_update` | Mettre à jour les cookies YT |
| `/restart` | (Owner) Redémarrer Greg |

## Déploiement Railway

1. Créer un projet Railway
2. Ajouter le plugin Redis
3. Créer 3 services depuis le repo Git :
   - `bot` → Root directory: `services/bot`, Dockerfile
   - `api` → Root directory: `services/api`, Dockerfile
   - `web` → Root directory: `services/web`, Dockerfile
4. Configurer les variables d'env (copier `.env.example`)
5. Les `REDIS_URL` sont auto-configurées par le plugin

## Licence

Projet privé — Greg le Consanguin © 2024-2026
