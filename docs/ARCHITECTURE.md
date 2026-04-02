# Greg le Consanguin — Architecture v2

## Diagnostic de l'existant

### Ce qui marche bien
- **PlayerService** bien découplé avec gestion de lecture audio propre
- **Extractors** modulaires (YouTube, SoundCloud, Spotify) avec pattern `get_extractor()`
- **API Flask** structurée en blueprints avec WebSocket (Socket.IO)
- **Cogs Discord** bien séparés par domaine (Music, Voice, General, Spook, EasterEggs)
- **Cookie Guardian** & système d'annonces intégré
- **Gestion des playlists/mix** YouTube avec expand_bundle

### Problèmes identifiés

| Problème | Impact | Priorité |
|----------|--------|----------|
| **Monolithe unique** — bot + API + front dans un seul process/Dockerfile | Scaling impossible, redéploiement tout-ou-rien | 🔴 Haute |
| **`main.py` god-file** — 230 lignes de wiring, bridge sync/async, threading | Maintenance cauchemardesque | 🔴 Haute |
| **Front en vanilla JS** — 2163 lignes de JS procédural, 996 lignes CSS | Impossible à étendre pour les futures features (chat vocal IA) | 🔴 Haute |
| **Couplage API ↔ Bot** — `PlayerAPIBridge` fait du `asyncio.run_coroutine_threadsafe` | Fragile, timeouts fréquents | 🟠 Moyenne |
| **Pas de DA cohérente** — le thème "gueux médiéval" est à peine effleuré | UX fade, pas d'identité | 🟠 Moyenne |
| **`__pycache__`, `.idea`, `downloads/`** dans le repo | Repo sale, image Docker lourde | 🟡 Basse |
| **Config dupliquée** — `config.py` + `api/core/config.py` + env vars | Confusion sur la source de vérité | 🟡 Basse |
| **Système de priorité cassé** — insertion buggée, `is_priority_item` toujours `True`, pas de tri garanti | Skip/move/enqueue incohérents | 🔴 Haute |
| **Pas de health check propre** pour Railway multi-service | Railway ne sait pas si le bot est up | 🟡 Basse |

---

## Architecture cible : 4 services Docker

```
greg-le-consanguin/
├── docker-compose.yml          # Orchestration locale
├── docker-compose.prod.yml     # Overrides Railway/prod
├── .env.example
├── .gitignore
│
├── packages/
│   └── shared/                 # Code partagé (types, constantes, DA)
│       ├── greg_shared/
│       │   ├── __init__.py
│       │   ├── config.py       # SOURCE UNIQUE de config (pydantic-settings)
│       │   ├── models.py       # Schemas Pydantic (Track, QueueState, User…)
│       │   ├── constants.py    # Réponses de Greg, quotes, DA
│       │   ├── extractors/     # YouTube, SoundCloud, Spotify extractors
│       │   └── priority.py     # Logique de priorité par rôle
│       ├── pyproject.toml
│       └── README.md
│
├── services/
│   ├── bot/                    # 🤖 SERVICE 1 — Discord Bot
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── bot/
│   │   │   ├── __init__.py
│   │   │   ├── main.py         # Entry point propre (~50 lignes)
│   │   │   ├── greg_bot.py     # Classe GregBot
│   │   │   ├── cogs/
│   │   │   │   ├── music.py
│   │   │   │   ├── voice.py
│   │   │   │   ├── general.py
│   │   │   │   ├── eastereggs.py
│   │   │   │   ├── spook.py
│   │   │   │   └── cookie_guardian.py
│   │   │   └── services/
│   │   │       ├── player_service.py
│   │   │       └── playlist_manager.py
│   │   └── assets/
│   │       └── sounds/         # SFX (intro, spook)
│   │
│   ├── api/                    # 🌐 SERVICE 2 — REST API + WebSocket
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── api/
│   │   │   ├── __init__.py     # create_app() factory
│   │   │   ├── main.py         # Entry point (uvicorn/gunicorn)
│   │   │   ├── routes/
│   │   │   │   ├── player.py   # /api/v1/player/*
│   │   │   │   ├── search.py   # /api/v1/search/*
│   │   │   │   ├── auth.py     # /api/v1/auth/*
│   │   │   │   ├── guilds.py   # /api/v1/guilds/*
│   │   │   │   ├── spotify.py  # /api/v1/spotify/*
│   │   │   │   └── health.py   # /healthz, /readyz
│   │   │   ├── websocket/
│   │   │   │   ├── events.py
│   │   │   │   └── presence.py
│   │   │   ├── middleware/
│   │   │   │   ├── auth.py     # Discord OAuth middleware
│   │   │   │   ├── cors.py
│   │   │   │   └── errors.py
│   │   │   └── services/
│   │   │       ├── bot_bridge.py   # Communication bot ↔ API via Redis pub/sub
│   │   │       └── search.py
│   │   └── tests/
│   │
│   ├── web/                    # 🎨 SERVICE 3 — Frontend Next.js
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   ├── next.config.js
│   │   ├── tailwind.config.js
│   │   ├── public/
│   │   │   ├── fonts/
│   │   │   │   └── MedievalSharp.woff2
│   │   │   ├── images/
│   │   │   │   ├── greg-avatar.webp
│   │   │   │   ├── parchment-bg.webp
│   │   │   │   └── favicon.ico
│   │   │   └── sounds/
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── layout.tsx
│   │   │   │   ├── page.tsx         # Player principal
│   │   │   │   └── globals.css
│   │   │   ├── components/
│   │   │   │   ├── Player/
│   │   │   │   │   ├── NowPlaying.tsx
│   │   │   │   │   ├── Queue.tsx
│   │   │   │   │   ├── Controls.tsx
│   │   │   │   │   ├── ProgressBar.tsx
│   │   │   │   │   └── SearchBar.tsx
│   │   │   │   ├── Layout/
│   │   │   │   │   ├── Header.tsx
│   │   │   │   │   ├── GregAvatar.tsx
│   │   │   │   │   └── Footer.tsx
│   │   │   │   ├── Auth/
│   │   │   │   │   ├── LoginButton.tsx
│   │   │   │   │   └── UserCard.tsx
│   │   │   │   └── UI/
│   │   │   │       ├── MedievalCard.tsx
│   │   │   │       ├── ParchmentButton.tsx
│   │   │   │       └── GregToast.tsx
│   │   │   ├── hooks/
│   │   │   │   ├── useSocket.ts
│   │   │   │   ├── usePlayer.ts
│   │   │   │   ├── useAuth.ts
│   │   │   │   └── useGuild.ts
│   │   │   ├── lib/
│   │   │   │   ├── api.ts       # Client API typé
│   │   │   │   ├── socket.ts    # Socket.IO singleton
│   │   │   │   └── types.ts     # Types TypeScript
│   │   │   └── theme/
│   │   │       ├── medieval.ts  # Tokens DA
│   │   │       └── greg-quotes.ts
│   │   └── tsconfig.json
│   │
│   └── voice-ai/               # 🧠 SERVICE 4 — IA Conversationnelle (futur)
│       ├── Dockerfile
│       ├── pyproject.toml
│       └── voice_ai/
│           ├── __init__.py
│           ├── main.py
│           ├── stt/             # Speech-to-Text
│           ├── tts/             # Text-to-Speech
│           ├── llm/             # LLM orchestration
│           └── personality/     # Prompts système "Greg le gueux"
│
└── infra/
    ├── railway.toml             # Config Railway multi-service
    └── nginx.conf               # Reverse proxy (optionnel)
```

---

## Détail des 4 services

### SERVICE 1 — Bot Discord (`services/bot/`)

**Responsabilité** : Se connecter à Discord, gérer les commandes slash, lire l'audio en vocal.

**Changements majeurs :**
- `main.py` réduit à ~50 lignes : instancier `GregBot`, charger les cogs, lancer `bot.run()`
- Plus de threading Flask — le bot ne sert plus l'API
- Communication avec l'API via **Redis Pub/Sub** (pas de bridge sync/async fragile)
- `PlayerService` reste dans le bot (c'est lui qui a `voice_client`)

**Communication Bot → API :**
```python
# bot publie sur Redis quand l'état change
redis.publish("greg:player:update", json.dumps({
    "guild_id": gid,
    "state": player.get_state(gid)
}))
```

**Communication API → Bot :**
```python
# L'API publie une commande, le bot écoute
redis.publish("greg:commands", json.dumps({
    "action": "enqueue",
    "guild_id": "123",
    "user_id": "456",
    "item": {"url": "...", "title": "..."}
}))
```

**Dockerfile (simplifié) :**
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsodium-dev libffi-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY packages/shared/ /shared/
RUN pip install /shared/
COPY services/bot/ .
RUN pip install -r requirements.txt
CMD ["python", "-m", "bot.main"]
```

### SERVICE 2 — API REST + WebSocket (`services/api/`)

**Responsabilité** : Servir l'API REST, gérer les WebSockets, OAuth Discord, proxy vers le bot.

**Changements majeurs :**
- **Migrer de Flask vers FastAPI** (ou garder Flask mais avec un vrai ASGI via `hypercorn`)
  - FastAPI est recommandé : async natif, validation Pydantic intégrée, OpenAPI auto
- Plus de `asyncio.run_coroutine_threadsafe` — tout passe par Redis
- Les routes deviennent des vrais controllers REST propres
- WebSocket propre avec rooms par `guild_id`

**Routes API restructurées :**

```
GET    /api/v1/health              → Health check
GET    /api/v1/player/state        → État du player (queue, current, progress)
POST   /api/v1/player/enqueue      → Ajouter un track
POST   /api/v1/player/skip         → Skip
POST   /api/v1/player/stop         → Stop
POST   /api/v1/player/pause        → Toggle pause
POST   /api/v1/player/repeat       → Toggle repeat
POST   /api/v1/player/move         → Réordonner la queue
DELETE /api/v1/player/queue/:index  → Supprimer un track
POST   /api/v1/player/restart      → Restart le track courant

GET    /api/v1/search/autocomplete  → Recherche YouTube
GET    /api/v1/auth/login           → Discord OAuth
GET    /api/v1/auth/callback        → OAuth callback
POST   /api/v1/auth/logout          → Logout
GET    /api/v1/auth/me              → User info

GET    /api/v1/guilds               → Guildes du user (filtrées par le bot)
GET    /api/v1/spotify/*            → Intégration Spotify
```

**Modèles Pydantic (dans `shared/`) :**

```python
from pydantic import BaseModel
from typing import Optional

class Track(BaseModel):
    url: str
    title: str
    artist: Optional[str] = None
    duration: Optional[int] = None  # secondes
    thumbnail: Optional[str] = None
    provider: Optional[str] = "youtube"
    added_by: Optional[str] = None
    priority: int = 0

class PlayerState(BaseModel):
    guild_id: int
    current: Optional[Track] = None
    queue: list[Track] = []
    paused: bool = False
    position: int = 0        # secondes écoulées
    duration: Optional[int] = None
    repeat_all: bool = False

class EnqueueRequest(BaseModel):
    query: str               # URL ou recherche texte
    guild_id: int
    user_id: int
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
```

### SERVICE 3 — Frontend Next.js (`services/web/`)

**Responsabilité** : Interface utilisateur, web player, DA médiévale.

**Pourquoi Next.js :**
- SSR/SSG pour le SEO et le temps de chargement initial
- React pour la réactivité (Socket.IO updates en temps réel)
- Tailwind CSS pour une DA cohérente et maintenable
- TypeScript pour la fiabilité
- Hot reload en dev

**Stack technique :**
- Next.js 14+ (App Router)
- Tailwind CSS + variables CSS custom pour le thème médiéval
- Socket.IO client pour les updates en temps réel
- SWR ou React Query pour le data fetching
- Zustand pour le state management global

### SERVICE 4 — Voice AI (futur) (`services/voice-ai/`)

**Responsabilité** : Recevoir l'audio du vocal Discord, le transcrire (STT), générer une réponse avec un LLM personnalisé "Greg", et la synthétiser (TTS).

**Architecture prévue :**
```
Discord Audio Stream
        ↓
   STT (Whisper / Deepgram)
        ↓
   LLM (Claude API / Local)
   avec system prompt "Greg le gueux"
        ↓
   TTS (ElevenLabs / Coqui / Bark)
        ↓
Discord Audio Playback
```

**Ce service est isolé** pour pouvoir être déployé sur un GPU si nécessaire, indépendamment du reste.

---

## Direction Artistique — Le Gueux Médiéval

### Palette de couleurs

```css
:root {
  /* Parchemin & pierre */
  --bg-parchment:    #1a1410;       /* Fond sombre "vieux parchemin brûlé" */
  --bg-card:         #221c15;       /* Cartes "bois vermoulu" */
  --bg-card-hover:   #2d2418;

  /* Accents royaux déchus */
  --gold:            #c9a84c;       /* Or terni */
  --gold-bright:     #e6c45c;       /* Or sur hover */
  --crimson:         #8b2e2e;       /* Rouge sang séché */
  --emerald:         #2e6b4f;       /* Vert forêt */

  /* Texte */
  --text-primary:    #d4c5a9;       /* Parchemin clair */
  --text-secondary:  #8b7d6b;       /* Pierre usée */
  --text-accent:     #c9a84c;       /* Or pour titres */

  /* Fonctionnel */
  --danger:          #a63d3d;
  --success:         #3d7a5a;
  --border:          rgba(201, 168, 76, 0.15);
}
```

### Typographie

```css
/* Titres : police médiévale */
@font-face {
  font-family: 'MedievalSharp';
  src: url('/fonts/MedievalSharp.woff2') format('woff2');
}

h1, h2, .brand-title {
  font-family: 'MedievalSharp', serif;
  color: var(--gold);
  text-shadow: 0 2px 8px rgba(201, 168, 76, 0.3);
}

/* Corps : police lisible avec un twist */
body {
  font-family: 'Crimson Text', Georgia, serif;
  color: var(--text-primary);
}
```

### Ton des réponses Discord

**Le personnage** : Greg est un gueux du Moyen Âge, mi-Jacquouille mi-serviteur râleur. Il s'adresse DIRECTEMENT aux gens — il les tutoie, les interpelle, les charrie. Pas de narration à la troisième personne. C'est un mec qui parle, pas un conteur.

**Règles de voix :**
- Greg tutoie toujours (sauf s'il ironise avec un "messire")
- Il parle AUX gens, pas DE lui-même
- Langage familier médiéval, pas du vieux français littéraire
- Il utilise `{user}` pour interpeller directement
- Court et percutant, pas de pavés

```python
# packages/shared/greg_shared/constants.py

GREG_RESPONSES = {
    "play_success": [
        "🎵 C'est bon {user}, je te mets ça. T'as intérêt à écouter au moins.",
        "🎶 Allez hop en file, {user}. Encore un de tes goûts douteux…",
        "🎵 Ajouté. Franchement {user}, t'aurais pu choisir pire. Enfin, à peine.",
        "🎶 Ouais ouais, c'est en file {user}. Me remercie pas surtout.",
    ],
    "play_not_found": [
        "❌ Eh {user}, ça existe pas ton truc. Même les bardes du village connaissent pas.",
        "❌ J'ai cherché partout {user}. Y'a rien. T'es sûr que c'est une vraie chanson ?",
        "❌ Connais pas, {user}. T'as inventé ça ou quoi ?",
    ],
    "skip": [
        "⏭️ Hop, suivant ! Merci {user}, celui-là me vrillait les oreilles.",
        "⏭️ Skippé. Fallait le faire plus tôt si tu veux mon avis, {user}.",
        "⏭️ Allez dégage ce morceau. Au suivant !",
    ],
    "stop": [
        "⏹️ Ah enfin le silence… Merci {user}, mes oreilles te sont redevables.",
        "⏹️ C'est fini, on arrête tout. Allez, rentrez chez vous.",
        "⏹️ Stop. J'en pouvais plus de toute façon.",
    ],
    "pause": [
        "⏸️ Pause, {user}. J'en profite pour respirer un coup.",
        "⏸️ OK on fait une pause. Revenez quand vous êtes prêts, bande de gueux.",
        "⏸️ Pausé. Prends ton temps {user}, moi j'ai que ça à faire. Ah bah oui en fait.",
    ],
    "resume": [
        "▶️ C'est reparti. Accrochez-vous les manants.",
        "▶️ On reprend {user}. T'étais parti faire quoi, piquer du blé ?",
        "▶️ Allez allez, la musique reprend. Bougez-vous !",
    ],
    "join_voice": [
        "👑 Bon, j'arrive dans **{channel}**. Faites-moi de la place, gueux.",
        "👑 **{channel}** ? Soit. Mais c'est bien parce que tu me le demandes, {user}.",
        "👑 Me voilà dans **{channel}**. Estimez-vous heureux, bande de manants.",
    ],
    "leave_voice": [
        "👋 Bon je me casse. Amusez-vous bien sans moi, si vous en êtes capables.",
        "👋 Adieu les gueux. Profitez du silence, il est gratuit.",
        "👋 Je quitte ce taudis. Si vous avez besoin, tapez plus fort la prochaine fois.",
    ],
    "empty_queue": [
        "📋 Y'a rien en file, {user}. Faut mettre de la musique si tu veux que je joue, malin.",
        "📋 La file est vide. Comme vos cerveaux, j'imagine.",
    ],
    "ping": [
        "🏓 {latency}ms. Ouais je suis là. Qu'est-ce tu veux encore ?",
        "🏓 {latency}ms. Plus rapide que toi pour te lever le matin, {user}.",
    ],
    "error_not_in_voice": [
        "❌ Euh {user}… t'es même pas en vocal là. Tu veux que je joue pour les murs ?",
        "❌ Rentre en vocal d'abord {user}, après on cause. Quelle audace quand même.",
    ],
    "error_priority": [
        "⛔ Oh oh, doucement {user}. T'as pas le rang pour faire ça ici. Va gagner tes galons d'abord.",
        "⛔ Toi ? Toucher à ça ? Avec ton rang ? Laisse-moi rire, {user}.",
        "⛔ Hé non {user}, les gueux de ton rang touchent pas à ça. C'est réservé aux gens importants.",
    ],
    "error_quota": [
        "⛔ T'as déjà {count} morceaux en file, {user}. Calme-toi. Laisse les autres respirer.",
        "⛔ Stop {user}, t'as atteint ta limite ({count}/{cap}). Tu monopolises là.",
    ],
    "already_playing": [
        "🎵 Ça joue déjà {user}. T'es sourd ou quoi ?",
    ],
    "nobody_listening": [
        "😤 Y'a plus personne… je me casse dans {delay}s si ça bouge pas.",
    ],
    "auto_leave": [
        "👋 Bon, tout le monde s'est barré. Moi aussi du coup. Bande d'ingrats.",
    ],
    "repeat_on": [
        "🔁 Repeat activé. Vous allez entendre ça en boucle. Bon courage.",
    ],
    "repeat_off": [
        "🔁 Repeat coupé. Enfin du changement.",
    ],
}

import random
def greg_says(key: str, **kwargs) -> str:
    """Retourne une réponse de Greg. Passe user=mention, channel=nom, etc."""
    templates = GREG_RESPONSES.get(key, ["❌ Euh… j'ai bugué. Tapez-moi dessus, ça repart parfois."])
    return random.choice(templates).format(**{k: v for k, v in kwargs.items() if v is not None})
```

**Utilisation dans les cogs :**
```python
# commands/music.py
from greg_shared.constants import greg_says

@app_commands.command(name="play", description="Joue un son.")
async def play(self, interaction: discord.Interaction, query_or_url: str):
    await interaction.response.defer()
    # ... logique d'enqueue ...
    if out.get("ok"):
        await interaction.followup.send(
            greg_says("play_success", user=interaction.user.mention)
        )
    else:
        await interaction.followup.send(
            greg_says("play_not_found", user=interaction.user.mention)
        )
```

### Éléments visuels du front

```
┌─────────────────────────────────────────────────────┐
│  [Blason Greg]  Greg le Consanguin — Web Player     │
│                 🔍 [Rechercher une complainte...]    │
│                                      [Avatar] User  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌───────────────────────────────────────────┐      │
│  │   🎵 NOW PLAYING                         │      │
│  │   ┌──────┐                               │      │
│  │   │thumb │  Titre du morceau             │      │
│  │   │ nail │  Artiste                      │      │
│  │   └──────┘                               │      │
│  │   ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬░░░░░  2:34 / 4:12   │      │
│  │           ⏮  ⏯  ⏭  ⏹  🔁               │      │
│  │   Demandé par: @user (Chevalier)          │      │
│  └───────────────────────────────────────────┘      │
│                                                     │
│  ┌───────────────────────────────────────────┐      │
│  │   📜 FILE D'ATTENTE (3 complaintes)       │      │
│  │   ┌──┬─────────────────────────┬────┬──┐ │      │
│  │   │1 │ Titre — Artiste         │3:45│🗑│ │      │
│  │   │2 │ Titre — Artiste         │2:30│🗑│ │      │
│  │   │3 │ Titre — Artiste         │5:12│🗑│ │      │
│  │   └──┴─────────────────────────┴────┴──┘ │      │
│  └───────────────────────────────────────────┘      │
│                                                     │
├─────────────────────────────────────────────────────┤
│  💬 "Je ne suis pas grognon, je suis en mode       │
│      économie d'empathie."  — Greg le Consanguin    │
└─────────────────────────────────────────────────────┘
```

**Éléments DA spécifiques :**
- Cartes avec bords "parchemin usé" (`border-image` ou SVG)
- Boutons de contrôle stylisés comme des sceaux royaux
- Queue avec numérotation en chiffres romains (I, II, III…)
- Barre de progression stylisée comme un chemin de terre
- Quotes aléatoires de Greg en footer
- Animations subtiles : torches qui scintillent, parchemin qui se déroule

---

## Communication inter-services

### Redis comme bus de messages

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  bot:
    build: ./services/bot
    depends_on: [redis]
    environment:
      - REDIS_URL=redis://redis:6379

  api:
    build: ./services/api
    depends_on: [redis]
    ports:
      - "3000:3000"
    environment:
      - REDIS_URL=redis://redis:6379

  web:
    build: ./services/web
    depends_on: [api]
    ports:
      - "3001:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://api:3000

volumes:
  redis-data:
```

### Pattern de communication

```
┌──────────┐    Redis Pub/Sub     ┌──────────┐
│   Bot    │◄────────────────────►│   API    │
│ Discord  │  "greg:commands"     │  REST +  │
│  + Audio │  "greg:player:*"     │   WS     │
└──────────┘                      └────┬─────┘
                                       │ HTTP + WS
                                  ┌────┴─────┐
                                  │   Web    │
                                  │ Next.js  │
                                  └──────────┘
```

**Channels Redis :**

| Channel | Direction | Payload |
|---------|-----------|---------|
| `greg:commands` | API → Bot | `{action, guild_id, user_id, data}` |
| `greg:player:state` | Bot → API | `PlayerState` complet |
| `greg:player:progress` | Bot → API | `{guild_id, position, duration, paused}` |
| `greg:voice:events` | Bot → API | `{guild_id, action, channel}` |

---

## Refonte du système de priorité

### Bugs actuels identifiés

**1. L'insertion par priorité dans `PlayerService.enqueue()` ne marche pas correctement :**

```python
# Code actuel (buggé) — services/api/services/player_service.py
for i, it in enumerate(new_queue):
    w = int(it.get("priority") or 0)
    if weight > w:
        target_idx = i    # ← problème : prend le PREMIER item plus faible
        break
    target_idx = i + 1    # ← dans la boucle, pas dans le else
```

Le problème : si l'utilisateur a un poids de 60 (VIP) et que la queue contient `[80, 80, 10, 10]`, la boucle s'arrête au premier `10` (index 2), mais `target_idx` devrait être 2 (juste après les 80). Or si les `priority` ne sont pas triées dans la queue (ce qui arrive après des `move()`), le résultat est imprévisible.

**2. `is_priority_item()` considère TOUT le monde comme prioritaire :**

```python
# __DEFAULT__ = 10, ce qui est truthy
def is_priority_item(item):
    return bool(item and (item.get("priority") or ...))
# → True pour TOUS les items, car priority=10 est truthy
```

Conséquence : `first_non_priority_index()` retourne toujours `len(queue)`, ce qui rend la "barrière de priorité" dans `move()` inutile.

**3. Priorité égale = bloqué :**

```python
def can_user_bump_over(bot, gid, requester_id, owner_weight):
    return req_w > owner_weight  # STRICTEMENT supérieur
```

Deux VIP (poids 60) ne peuvent pas skip le morceau de l'autre. Un DJ (80) ne peut pas skip un autre DJ. C'est frustrant et contre-intuitif.

**4. La queue n'est jamais re-triée :**

Après un `move()` manuel, l'ordre de priorité est cassé. Il n'y a aucun invariant maintenu.

**5. Le poids est stocké dans l'item au moment de l'ajout :**

Si un user gagne ou perd un rôle entre-temps, ses items en queue gardent l'ancien poids. Mineur, mais incohérent.

### Nouveau système de priorité

**Principes :**
- La queue a deux zones : **zone prioritaire** (poids > seuil) et **zone normale** (poids ≤ seuil)
- Au sein de chaque zone, c'est FIFO (premier arrivé, premier servi)
- Un nouvel item prioritaire est inséré à la FIN de la zone prioritaire (pas au début)
- Un utilisateur peut skip/pause/stop le morceau en cours si son poids est **≥** (pas strictement >) au poids du owner
- Un utilisateur peut supprimer/déplacer ses propres items sans condition de poids

**Seuil de priorité** : configurable, par défaut `PRIORITY_THRESHOLD = 50`. Tout poids > 50 est "prioritaire".

```python
# packages/shared/greg_shared/priority.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import os, json

# ─────────────────────────── Config ───────────────────────────

PRIORITY_THRESHOLD = int(os.getenv("PRIORITY_THRESHOLD", "50"))
OWNER_WEIGHT = 10_000

DEFAULT_WEIGHTS: Dict[str, int] = {
    "__OWNER__":        OWNER_WEIGHT,
    "__ADMIN__":        100,
    "__MANAGE_GUILD__": 90,
    "DJ":               80,
    "VIP":              60,
    "Booster":          45,
    "__DEFAULT__":      10,
}

# ─────────────────────────── Poids d'un membre ───────────────────────────

def get_member_weight(bot, guild_id: int, user_id: int) -> int:
    """Retourne le poids effectif d'un membre (max de ses rôles)."""
    if _is_owner(user_id):
        return OWNER_WEIGHT

    weights = _get_weights()
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return weights.get("__DEFAULT__", 10)

    # Admin / Manage Guild
    perms = member.guild_permissions
    if perms.administrator:
        return max(weights.get("__ADMIN__", 100), _best_role_weight(member, weights))
    if perms.manage_guild or perms.manage_channels:
        return max(weights.get("__MANAGE_GUILD__", 90), _best_role_weight(member, weights))

    return max(weights.get("__DEFAULT__", 10), _best_role_weight(member, weights))


def _best_role_weight(member, weights: Dict[str, int]) -> int:
    best = 0
    for role in getattr(member, "roles", []) or []:
        if role and role.name != "@everyone":
            w = weights.get(role.name, 0)
            if w > best:
                best = w
    return best

# ─────────────────────────── Droits d'action ───────────────────────────

@dataclass
class PermissionResult:
    allowed: bool
    reason: str  # "ok", "own_item", "higher_rank", "equal_rank", "insufficient_rank"

def can_control_playback(bot, guild_id: int, requester_id: int, current_owner_weight: int) -> PermissionResult:
    """Peut-on skip/pause/stop le morceau en cours ?
    
    Règle : poids du requester >= poids du owner du morceau.
    (Même rang = OK. C'est le changement clé par rapport à l'ancien système.)
    """
    if _is_owner(requester_id):
        return PermissionResult(True, "owner")
    
    req_weight = get_member_weight(bot, guild_id, requester_id)
    
    # Admins peuvent toujours contrôler
    if _is_admin(bot, guild_id, requester_id):
        return PermissionResult(True, "admin")
    
    if req_weight >= current_owner_weight:
        return PermissionResult(True, "equal_or_higher_rank")
    
    return PermissionResult(False, "insufficient_rank")


def can_edit_queue_item(bot, guild_id: int, requester_id: int, item: dict) -> PermissionResult:
    """Peut-on supprimer/déplacer cet item de la queue ?
    
    Règles :
    1. C'est ton propre item → toujours OK
    2. Admin/Owner → toujours OK
    3. Ton poids >= poids de l'item → OK
    """
    item_owner = str(item.get("added_by") or "")
    
    # Règle 1 : propre item
    if item_owner and item_owner == str(requester_id):
        return PermissionResult(True, "own_item")
    
    # Règle 2 : admin/owner
    if _is_owner(requester_id) or _is_admin(bot, guild_id, requester_id):
        return PermissionResult(True, "admin")
    
    # Règle 3 : poids
    req_weight = get_member_weight(bot, guild_id, requester_id)
    item_weight = int(item.get("priority") or 0)
    
    if req_weight >= item_weight:
        return PermissionResult(True, "equal_or_higher_rank")
    
    return PermissionResult(False, "insufficient_rank")

# ─────────────────────────── Insertion dans la queue ───────────────────────────

def find_insert_position(queue: List[dict], new_weight: int) -> int:
    """Trouve la position d'insertion pour un nouvel item.
    
    Logique :
    - Zone prioritaire = items avec priority > PRIORITY_THRESHOLD
    - Zone normale     = items avec priority <= PRIORITY_THRESHOLD
    - Un item prioritaire va à la FIN de la zone prioritaire
    - Un item normal va à la FIN de la queue (FIFO classique)
    
    Résultat : la queue reste toujours triée en deux blocs.
    """
    if new_weight > PRIORITY_THRESHOLD:
        # Trouver la fin de la zone prioritaire (= premier item normal)
        for i, item in enumerate(queue):
            item_weight = int(item.get("priority") or 0)
            if item_weight <= PRIORITY_THRESHOLD:
                return i  # Insérer juste avant le premier item normal
        return len(queue)  # Toute la queue est prioritaire → à la fin
    else:
        return len(queue)  # Item normal → fin de queue (FIFO)


def is_priority_item(item: dict) -> bool:
    """Un item est 'prioritaire' si son poids dépasse le seuil."""
    return int(item.get("priority") or 0) > PRIORITY_THRESHOLD


def validate_move(queue: List[dict], src: int, dst: int, requester_weight: int, is_admin: bool) -> PermissionResult:
    """Vérifie qu'un move ne casse pas l'invariant de zone.
    
    Interdit : déplacer un item normal dans la zone prioritaire (sauf admin).
    Interdit : déplacer un item prioritaire dans la zone normale (sauf admin).
    """
    if is_admin:
        return PermissionResult(True, "admin")
    
    if not (0 <= src < len(queue) and 0 <= dst < len(queue)):
        return PermissionResult(False, "out_of_bounds")
    
    src_item = queue[src]
    src_is_prio = is_priority_item(src_item)
    
    # Trouver la frontière
    boundary = _priority_boundary(queue)
    dst_is_prio_zone = dst < boundary
    
    # Un item normal ne peut pas aller en zone prio
    if not src_is_prio and dst_is_prio_zone:
        return PermissionResult(False, "cannot_promote_to_priority_zone")
    
    # Un item prio ne peut pas être relégué en zone normale
    if src_is_prio and not dst_is_prio_zone and dst != boundary:
        return PermissionResult(False, "cannot_demote_from_priority_zone")
    
    return PermissionResult(True, "ok")


def _priority_boundary(queue: List[dict]) -> int:
    """Index du premier item non-prioritaire."""
    for i, item in enumerate(queue):
        if not is_priority_item(item):
            return i
    return len(queue)

# ─────────────────────────── Quota ───────────────────────────

PER_USER_CAP = int(os.getenv("QUEUE_PER_USER_CAP", "10") or 10)

def check_quota(queue: List[dict], user_id: int, bot, guild_id: int) -> PermissionResult:
    """Vérifie le quota de l'utilisateur."""
    if _is_owner(user_id) or _is_admin(bot, guild_id, user_id):
        return PermissionResult(True, "bypass")
    
    count = sum(1 for item in queue if str(item.get("added_by")) == str(user_id))
    if count >= PER_USER_CAP:
        return PermissionResult(False, f"quota_exceeded:{count}/{PER_USER_CAP}")
    
    return PermissionResult(True, "ok")

# ─────────────────────────── Helpers privés ───────────────────────────

def _is_owner(user_id) -> bool:
    oid = os.getenv("GREG_OWNER_ID", "")
    try:
        return bool(oid) and int(user_id) == int(oid)
    except Exception:
        return False

def _is_admin(bot, guild_id: int, user_id: int) -> bool:
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return False
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild

def _get_weights() -> Dict[str, int]:
    """Charge les poids (défauts + overrides env/fichier)."""
    w = DEFAULT_WEIGHTS.copy()
    # Overrides env
    raw = os.getenv("PRIORITY_ROLE_WEIGHTS", "").strip()
    if raw:
        try:
            w.update({str(k): int(v) for k, v in json.loads(raw).items()})
        except Exception:
            pass
    return w
```

### Résumé des changements de priorité

| Avant (cassé) | Après (corrigé) |
|----------------|-----------------|
| `is_priority_item` = `True` pour tous (poids 10 = truthy) | `is_priority_item` = poids > seuil configurable (défaut 50) |
| Insertion par boucle buggée qui ne trie pas | Insertion en 2 zones : prio à la fin du bloc prio, normal à la fin |
| Skip/stop si poids **strictement >** owner | Skip/stop si poids **≥** owner (même rang = OK) |
| Peut déplacer n'importe quoi n'importe où | Move protégé par validation de zone |
| Toujours toucher aux items des autres si poids > | Ses propres items = toujours modifiables, peu importe le poids |
| Quota bypass seulement admin/manage_guild | Quota bypass pour owner + admin |
| Pas de retour structuré sur les refus | `PermissionResult(allowed, reason)` pour des messages ciblés |

---

## Plan de migration (par phases)

### Phase 1 — Nettoyage, shared package & priorité (2-3 jours)

1. Nettoyer le `.gitignore` (ajouter `__pycache__/`, `.idea/`, `downloads/`, `*.pyc`, `.data/`)
2. Créer `packages/shared/` avec :
   - `config.py` unifié (pydantic-settings)
   - `models.py` (schemas Pydantic)
   - `constants.py` (réponses de Greg en tutoiement direct)
   - Déplacer `extractors/` et refactorer `utils/priority_rules.py`
3. **Refactorer le système de priorité** (cf. section dédiée) :
   - Remplacer `is_priority_item()` par le seuil configurable
   - Corriger `find_insert_position()` en 2 zones
   - Passer les checks de `>` strict à `>=`
   - Ajouter `PermissionResult` pour des messages Greg ciblés
   - Permettre l'édition de ses propres items sans condition de rang
4. Brancher `greg_says()` dans tous les cogs pour le nouveau ton de Greg

### Phase 2 — Séparer Bot et API (2-3 jours)

1. Ajouter Redis au stack (docker-compose)
2. Créer `BotBridge` dans l'API (publie des commandes sur Redis)
3. Créer un listener Redis dans le bot (écoute les commandes)
4. Le bot publie ses state updates sur Redis
5. Retirer `PlayerAPIBridge` et le threading dans `main.py`
6. Créer les 2 Dockerfiles séparés

### Phase 3 — Frontend Next.js (3-5 jours)

1. `npx create-next-app@latest` avec TypeScript + Tailwind
2. Créer le client API typé (`lib/api.ts`)
3. Implémenter `useSocket` hook (Socket.IO)
4. Migrer le player (NowPlaying, Queue, Controls, Search)
5. Appliquer la DA médiévale complète
6. Ajouter les animations et le polish

### Phase 4 — Déploiement Railway multi-service (1 jour)

1. Configurer Railway avec 4 services
2. Redis managé via Railway plugin
3. Variables d'environnement par service
4. Health checks par service

### Phase 5 — Voice AI (futur)

1. Capturer l'audio du voice channel Discord (PCM)
2. STT avec Whisper (local) ou Deepgram (API)
3. LLM avec system prompt "Greg le gueux médiéval"
4. TTS avec une voix grave/rocailleuse
5. Renvoyer l'audio dans le voice channel

---

## Fichiers de configuration Railway

```toml
# infra/railway.toml

[build]
builder = "DOCKERFILE"

[[services]]
name = "greg-bot"
rootDirectory = "services/bot"
startCommand = "python -m bot.main"

[services.healthcheck]
path = "/health"
timeout = 10

[[services]]
name = "greg-api"
rootDirectory = "services/api"
startCommand = "uvicorn api.main:app --host 0.0.0.0 --port $PORT"

[services.healthcheck]
path = "/api/v1/health"
timeout = 5

[[services]]
name = "greg-web"
rootDirectory = "services/web"
startCommand = "npm start"

[services.healthcheck]
path = "/"
timeout = 5
```

---

## Résumé des décisions techniques

| Décision | Choix | Raison |
|----------|-------|--------|
| Communication inter-services | Redis Pub/Sub | Simple, fiable, Railway le supporte nativement |
| Framework API | FastAPI (ou Flask + hypercorn) | Async natif, Pydantic intégré, auto-documentation |
| Framework front | Next.js 14 (App Router) | SSR, React, TypeScript, écosystème mature |
| CSS | Tailwind CSS | Cohérent, maintenable, thémable |
| State management front | Zustand | Léger, simple, pas de boilerplate |
| Realtime | Socket.IO | Déjà en place, mature, rooms par guild |
| Config | pydantic-settings | Validation, .env, types, une seule source |
| Tests | pytest (back) + Vitest (front) | Standards de l'industrie |
| CI/CD | GitHub Actions → Railway | Simple, intégration native |

---

*Document généré pour le projet Greg le Consanguin — Architecture v2*
*Objectif : passer d'un monolithe fonctionnel à une architecture microservices professionnelle, scalable, et prête pour l'IA conversationnelle.*
