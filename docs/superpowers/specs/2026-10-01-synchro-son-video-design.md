# Synchro du son Discord et de la vidéo du site : design

Date : 2026-10-01 · Branche : `feat/synchro-son-video` (depuis `main`) · Approche retenue : **B, horloge fiable de bout en bout**.

## 1. Problème

Le site montre une vidéo YouTube **muette** du titre en cours ; le son sort dans Discord. Le Roi constate les quatre symptômes à la fois : retard constant, dérive au fil du titre, décalage après pause / « Suivant », décalage au lancement.

L'étude du 2026-10-01 (cartographie du code, simulation du vrai `AudioPlayer` de discord.py 2.7.1, sondes YouTube) attribue l'essentiel de l'écart à **l'horloge du bot**, que le site croit sur parole :

| Cause | Où | Effet sur la vidéo |
|---|---|---|
| `play_start = monotonic()` pris **avant** `vc.play()`, donc avant le premier son de ffmpeg | `player_service.py:1063-1068` | En avance de 0,2 à 0,6 s au lancement (mode direct) ; de **1 à 8 s pour tout le titre** en mode pipe (`-re`, `youtube.py:1356, 1373`) |
| Coupure vocale : discord.py attend jusqu'à 30 s, `play_start` continue de compter | `discord/player.py:812-824` | En avance de la durée de la coupure jusqu'à la fin du titre |
| Position en **secondes entières**, sans horodatage, ni identifiant de lecture | `player_service.py:551, 1626` ; `redis_bridge.py:501-508` | Erreur de 0 à 1 s, figée dans la vidéo à chaque pause / reprise ; sauts à chaque recalage REST |
| Fenêtre de chargement : le nouveau titre est publié avec la position de l'ancien | `player_service.py:895-898` | Sauts de 1 à 10 s après un « Suivant » |
| Le relais de l'API reconstruit le tick avec une liste fixe de champs | `api/services/redis_listener.py:77-90` | Tout nouveau champ est perdu |
| Côté site : correction par sauts seulement (seuil 1,2 s, +0,45 s de surcompensation, 15 s entre deux sauts) | `lib/stage/cover.ts:29-36, 77-88` ; `Portal.tsx` | Jusqu'à 1,2 s d'écart toléré indéfiniment, la vidéo atterrit 0,3 à 0,4 s en avance après chaque saut |
| Saut optimiste : la nouvelle vidéo démarre au clic, avant que le bot joue | `optimistic.ts` (crown) ; `Portal.tsx` | En avance de 1,5 à 6 s au début du titre |
| Retard propre à Discord (serveur vocal, tampon du client, casque) | invisible du bot | +80 à 250 ms filaire, jusqu'à 500 ms Bluetooth : **seul** ce terme relève d'un réglage manuel |

Mesures utiles :
- `getCurrentTime()` du lecteur YouTube est précis à ±2,4 ms.
- YouTube applique 0,90 / 0,95 / 1,05 / 1,10 sans voile ni mise en tampon.
- Les autres vitesses sont arrondies à une grille de 0,05.

## 2. Objectif et critères de réussite

- En régime établi, la vidéo reste à **±60 à 80 ms** du son entendu dans Discord, une fois le retard Discord réglé par appareil. C'est dans la tolérance de la recommandation ITU-R BT.1359, de +90 à −185 ms.
- **Démarrage :** aucune avance au lancement d'un titre, en mode direct comme en mode pipe. La vidéo démarre quand le bot joue vraiment.
- **Pause / reprise :** l'erreur ne s'accumule pas au fil des pauses.
- **Coupure vocale et blocage du flux :** la vidéo attend puis repart avec le son ; plus d'avance persistante.
- **Recalage :** il se fait sans saut visible quand l'écart est inférieur à 2 s.
- **Compatibilité :** un site sans ces changements continue de fonctionner, car le contrat est additif. Un bot sans ces changements aussi : le site retombe sur le comportement actuel si `clock` est absent.

Hors périmètre :
- le calibrage automatique (clics joués par le bot, micro) ;
- le réglage stocké par compte ;
- la détection des publicités ;
- le passage à `FFmpegOpusAudio`.

## 3. Contrat (additif)

Chaque état complet (`greg:player:state` → socket `playlist_update`, REST `/playlist` et `/player/state`) et chaque tick (`greg:player:progress`) porte en plus :

```jsonc
"clock": {
  "play_id": "a1b2c3d4",      // change à chaque vc.play() (nouveau titre, « Depuis le début », boucle, reprise après coupure)
  "status": "playing",        // idle | loading | playing | paused | stalled
  "position_ms": 83460.0,     // trames réellement lues par discord.py × 20 ms ; null si idle/loading sans son
  "sampled_at_ms": 1790846494123 // horloge murale du bot (epoch ms) au moment de l'échantillon
},
"relay_at_ms": 1790846494125  // ajouté par l'API : son horloge murale à la réception (Redis ou réponse RPC)
```

Règles :
- `position` et `progress.elapsed`, en secondes entières, restent publiés, maintenant dérivés de `position_ms`.
- **Le site se cale sur l'horloge de l'API.** Il utilise `relay_at_ms`, avec `sampled_at_ms` en repli. L'écart Redis entre les deux est de l'ordre de 1 à 5 ms. On évite ainsi tout décalage d'horloge entre les conteneurs bot et API.
- `status = stalled` : le flux est bloqué, plus de 250 ms sans lecture alors que rien n'est en pause. Le site fige alors sa référence.
- `loading` : un titre est choisi mais aucune trame n'est encore sortie. `position_ms` vaut `null` et le site garde le poster.

Synchro d'horloge :
- **Événement :** socket `time_sync`, avec accusé de réception. Requête `{t0}` (horloge du client), réponse `{t0, ts}`, où `ts` est l'horloge murale de l'API en ms.
- **Sécurité :** aucune donnée sensible, et aucune authentification au-delà de la connexion socket existante.

## 4. Bot

### 4.1 `CountingSource` (nouveau `services/bot/bot/services/audio_clock.py`)
`discord.AudioSource` enveloppant la source ffmpeg (`FFmpegPCMAudio`, PCM 48 kHz stéréo, 3840 octets par trame de 20 ms) :
- **Comptage :** `read()` lit la source interne et incrémente `frames` si la trame est non vide. Il note `first_read_at` et `last_read_at` (`time.monotonic()`).
- **Pré-lecture :** `preroll()` lit une trame en avance et la garde ; le premier `read()` la rend. Si cette première lecture renvoie `b''`, c'est un échec de démarrage, traité par le chemin d'échec existant.
- **Callbacks :** `on_first_frame` et `on_resume_after_stall`, appelés depuis le thread audio. Ils ne touchent jamais l'asyncio directement : ils passent par `loop.call_soon_threadsafe`.
- **Délégation :** `is_opus()` renvoie `False`. `cleanup()` délègue à la source interne. `__getattr__` délègue le reste, en particulier `_current_error`, lu par `AudioPlayer` (`player.py:806`), et `_ytdlp_proc` (`player_service.py:207-221`).
- **Position :** `position_ms()` vaut `frames × 20.0`. Elle ne bouge pas pendant une pause ni pendant une coupure, puisque discord.py n'appelle pas `read()`.

### 4.2 `PlayerService`
- **Création de la source :** elle est enveloppée dans `CountingSource` aux deux endroits où elle est créée pour la musique, mode direct et mode pipe. Le clip d'intro n'est pas compté.
- **Avant `vc.play()` :**
  - `await asyncio.to_thread(src.preroll)` ;
  - si une autre lecture a commencé entre-temps, on garde les vérifications de génération et de titre périmé ;
  - si l'échec vient de `b''`, nettoyage, puis chemin d'erreur actuel.
- **État par serveur :** `play_id[gid]` (8 caractères hexadécimaux, nouveau à chaque `vc.play`) et `source[gid]` (le `CountingSource` actif).
- **`get_state` et ticker :** ils calculent `clock` :
  - `idle` : aucun titre ;
  - `loading` : titre choisi mais pas de source, ou source sans trame ;
  - `paused` : en pause ;
  - `stalled` : `monotonic() - last_read_at > 0.25` hors pause ;
  - `playing` sinon.

  `position` et `progress.elapsed` valent `int(position_ms / 1000)`.
- **Fenêtre de chargement :** dès que `play_next` choisit un titre, `clock.status` passe à `loading` avec `position_ms` à `null`, et `play_start` est remis à zéro. Plus de position héritée de l'ancien titre.
- **Envois immédiats :** au premier son, à la pause, à la reprise, au début d'un blocage (détecté par le ticker) et à la fin d'un blocage. Pour ces deux derniers, un état complet est publié via `call_soon_threadsafe`.
- **Usages internes de `play_start` :** il reste utilisé en interne, par exemple pour le réessai sur coupure dans `_handle_track_end`, qui dépend du temps écoulé. Il est désormais posé **après** la pré-lecture.
- **Log `[SYNC]` par titre :** mode `direct` ou `pipe`, délai entre le choix du titre et la première trame, délai de pré-lecture, `vc.average_latency`.

### 4.3 `redis_bridge.py`
`publish_progress` transmet `clock`. Les champs existants ne changent pas.

## 5. API

- **`redis_listener.py` :** ajoute `relay_at_ms = int(time.time()*1000)` aux deux canaux, et transmet `clock` dans le tick reconstruit (liste de champs complétée).
- **`routes/player.py` :** `/player/state` et `/playlist` ajoutent `relay_at_ms`, pris à la réception de la réponse du bot.
- **`websocket/events.py` :** gestionnaire `time_sync` qui renvoie `{"t0": data.get("t0"), "ts": time.time()*1000}`. Une valeur `t0` non numérique est ignorée et renvoyée telle quelle.

## 6. Site

### 6.1 Modules purs (testés avec `node:test`, sans import à l'exécution)
- **`lib/sync/timesync.ts` :**
  - un échantillon `(t0, ts, t1)` donne `offset = ts − (t0+t1)/2` et `rtt = t1 − t0` ;
  - on garde les 8 derniers et on retient celui dont le `rtt` est le plus faible ;
  - un `rtt` supérieur à 2 s est rejeté ;
  - `serverNow(perfNow)` donne l'heure de l'API vue du client.
- **`lib/sync/refclock.ts`** — l'ancre vaut `{play_id, status, position_ms, at}` :
  - `ingest(sample)` :
    - ignore un échantillon plus ancien que l'ancre ;
    - recale l'ancre sur un changement de `play_id` ou de `status`, ou si la position prédite s'écarte de plus de 40 ms ;
  - `positionAt(serverNow)` vaut `position_ms + (serverNow − at)` si `playing`, et `position_ms` figée sinon ;
  - sans bloc `clock`, l'horloge passe en mode compatibilité : ancre à la réception, comme aujourd'hui.
- **`lib/sync/controller.ts`** — `decide({target, current, state, rateOk, holdUntil, now})` renvoie `{rate}`, `{seek}` ou rien :
  - **seuils** (écart = position vidéo − cible ; la vidéo ralentit quand elle est en avance et accélère quand elle est en retard) :

    | Écart | Action |
    |---|---|
    | moins de 40 ms (zone morte) | vitesse ×1 ; retour à ×1 sous 15 ms (hystérésis) |
    | jusqu'à 300 ms | ×0,95 ou ×1,05 |
    | jusqu'à 2 s | ×0,90 ou ×1,10 |
    | au-delà de 2 s | saut |
  - **saut :** sous le poster, sans surcompensation fixe. On vérifie après `PLAYING`, puis la vitesse corrige le reste ;
  - **attente :** 3 s après une reprise, un blocage ou un nouveau `play_id`, le temps que le client Discord se recale ;
  - **sans vitesse fiable :** si YouTube ne confirme pas la vitesse (`getPlaybackRate`), on passe en sauts seuls, avec un seuil de 250 ms et au moins 10 s entre deux sauts.

### 6.2 Branchements
- **`lib/socket.ts` et `usePlayer.ts` :**
  - `time_sync` : 5 mesures à la connexion, 1 s d'écart, puis une toutes les 30 s ;
  - chaque état ou tick reçu nourrit `refclock` ;
  - la barre de progression et les minutages lisent `refclock`.
- **`Portal.tsx` et `useYouTubePlayer.ts` :**
  - boucle à 4 Hz tant que la vidéo est `PLAYING` et l'onglet visible ;
  - la cible vaut `refclock.positionAt(serverNow) + réglage` ;
  - la décision de `controller` est appliquée ;
  - la vitesse est réappliquée après `loadVideoById` ;
  - recalage immédiat au retour de l'onglet ;
  - les anciens seuils de `cover.ts` (`DRIFT_*`, `SEEK_COMP_S`) sont remplacés.
- **Démarrage gardé :** un nouveau `videoId` est chargé et lancé seulement quand `clock.status = playing` pour un nouveau `play_id`. Le saut optimiste (crown) ne pose plus de position 0 au clic ; le poster reste affiché pendant `loading`.
- **« Synchro vidéo »** (`SyncOffset.tsx`, `useVideoOffset.ts`) :
  - pas de 50 ms, plage de ±3 s ;
  - une valeur déjà stockée est arrondie et bornée ;
  - texte d'aide sur le sens du réglage ;
  - l'aperçu passe par le même régulateur, sans saut brut ;
  - le réglage reste par appareil (`localStorage`).

## 7. Tests et vérification

- **Bot (pytest)** — fausse source interne scriptée (trames, `b''`, lectures lentes) :
  - comptage, pré-lecture, échec de démarrage, délégation de `_current_error` et de `cleanup` ;
  - `status` : loading → playing → paused → playing → stalled → playing ;
  - `play_id` change lors d'un « Depuis le début » ;
  - position nulle pendant le chargement.
- **API (pytest) :** `clock` et `relay_at_ms` passent sur les deux canaux et en REST ; `time_sync` répond bien et résiste à une entrée invalide.
- **Site (`node:test`) :**
  - `timesync` : filtre au plus faible aller-retour, rejet des valeurs aberrantes ;
  - `refclock` : ordre des échantillons, recalages, mode compatibilité ;
  - `controller` : seuils, hystérésis, attente, repli en sauts ;
  - tests de contrat sur le démarrage gardé.
- **Navigateur :**
  - l'API simulée (scratchpad) émet `clock` et `time_sync` ;
  - avec Playwright et le vrai lecteur YouTube, on mesure l'écart entre `getCurrentTime()` et la cible : régime établi, pause, saut, blocage simulé.
- **Après déploiement :** lire les logs `[SYNC]` sur Railway (part du mode pipe, délai jusqu'au premier son). Le Roi règle une fois « Synchro vidéo » sur son appareil.

## 8. Risques

- **Pré-lecture :** elle est sur le chemin critique de la lecture (générations, échecs ffmpeg, nettoyage des processus, intro). Elle est couverte par les tests et reste fidèle aux chemins d'échec existants.
- **Attributs privés de discord.py :** `CountingSource` délègue `_current_error`. Un test vérifie la délégation, pour détecter une rupture lors d'une montée de version.
- **Grille de vitesses YouTube :** elle n'est pas documentée. Le repli en sauts couvre ce cas.
- **Ordre de déploiement :** Railway déploie les trois services depuis `main`. Le contrat est additif et le site tolère l'absence de `clock`.
