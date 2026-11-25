# L'overlay Overwolf de Greg (League of Legends) : conception

Date : 2026-11-25.

Demande de Paul :
- « il va falloir revoir complètement l'overlay overwolf, pour le fonctionnement complet et que ça soit simple, avec la
  bonne DA et revoir l'ui » ;
- après les essais en jeu : « tout fonctionne, finis correctement le tout sachant que en bas à gauche il n'y a rien comme
  hud pour lol et qu'il le faut transparent à régler ».

Deux dépôts sont touchés :
- `greg-overlay-ow` : la nouvelle appli Overwolf, qui remplace l'ancienne GregLC ;
- `GregLeConsanguin` : l'API, le bot et le site, pour la connexion de l'appli et les données qui lui manquent.

Rappels qui s'appliquent partout :
- **Personnages.** Greg est le valet, l'utilisateur est le Roi. Greg vouvoie (« Sire ») ; la couronne et le sceau
  appartiennent au Roi, jamais à Greg.
- **Durcissement de 2026-09.** On ne revient sur aucun de ses points :
  - identité tirée du serveur (session ou jeton), jamais d'un `user_id` envoyé par le client ;
  - CORS sur liste blanche, sans joker ;
  - `state` OAuth à usage unique, pas de redirection ouverte ;
  - accès vérifié par serveur Discord.
  - Les vieux parcours permissifs de l'overlay (popup `?return=overlay`, abonnements sans session) ne reviennent pas.
    L'appli utilise `join_guild` / `leave_guild`, pas les noms `overlay_*` gardés pour le site.
- **Jeu.** Rien ne touche au processus du jeu en dehors des API d'Overwolf, et aucune donnée de partie n'est affichée.
- **Git.** Jamais de mention d'IA dans les commits ou les PR. `services/web/tsconfig.json` n'est jamais commité. Une PR
  par dépôt, et chaque fusion attend l'accord de Paul (la fusion déploie sur Railway).
- **Tests.** Les suites existantes restent vertes (API 722, web et bot actuels), et chaque morceau ajoute ses tests.

## 1. Ce qui est décidé, et pourquoi

**Plateforme : Overwolf (OW-native), pour Paul seul.** Voici ce que les essais du 2026-11-24/25 ont établi :
- **Appli Windows autonome (Electron), écartée :**
  - elle ne s'affiche qu'en Sans bordure ;
  - Paul joue en Plein écran ;
  - les raccourcis Windows classiques sont incertains en jeu.
- **Overwolf, validé en Plein écran dans l'outil d'entraînement** (journal de l'essai et journal de partie d'Overwolf) :
  - le bandeau est dessiné dans le jeu, et les clics le traversent ;
  - les quatre raccourcis arrivent pendant que LoL a le clavier, panneau ouvert ou fermé ;
  - le panneau prend le clavier grâce à `requestOverlayFocus` ;
  - à la fermeture du panneau, le clavier revient au jeu.
- **Limite assumée.** Les amis de Paul ne peuvent pas installer l'appli : Overwolf refuse les applis privées, et seul un
  compte développeur approuvé charge une appli non publiée. Ils continuent d'utiliser le site.
- **Vanguard.** Overwolf injecte son propre module dans LoL, et Paul a choisi Overwolf en connaissance de cause. Voir
  `Obsidian/ClaudeBrain/Research/riot-vanguard-overlays-lol.md`.

**Les maquettes de référence** sont dans `2026-11-25-overlay-overwolf-maquettes/`. Ce sont des modèles, reconstruits par
`build.py` en pages autonomes non commitées.
- **Maquette 1 (`1-en-jeu`) :** le bandeau et le panneau.
- **Maquette 2 (`2-hors-jeu`) :** la connexion, la fenêtre bureau, les réglages et les états du bandeau.
- **Maquette 3 (`3-dans-lol`) :** le placement dans LoL. Son emplacement « bord gauche au tiers » est remplacé par le bas à
  gauche (§6.4).
- Les maquettes 1 et 2 ont été validées par Paul. Elles font foi pour l'aspect et le contenu, avec l'apparence de l'essai.

**Ce que l'appli fait.** C'est la portée validée sur les maquettes 1 et 2.
- **Le bandeau**, toujours visible en jeu :
  - le titre en cours ;
  - qui l'a demandé ;
  - la progression ;
  - l'état (lecture, pause, rien en lecture, Greg hors ligne, refus) ;
  - une ligne fugace quand un ami agit.
  - **Nouveau :** il est ancré **en bas à gauche** (LoL n'y affiche rien) et sa **transparence se règle**.
- **Le panneau**, au raccourci :
  - le titre en cours avec la progression ;
  - pause/reprise, suivant, stop (confirmé si la file n'est pas vide), recommencer, boucle ;
  - la file, avec jouer maintenant, passer en tête, retirer et réordonner ;
  - la recherche avec suggestions, et l'ajout par titre ou par lien collé ;
  - le choix du serveur.
- **Les raccourcis**, panneau fermé comme ouvert :
  - Ctrl+F7 pause/reprise ;
  - Ctrl+F8 suivant ;
  - Ctrl+F10 panneau ;
  - Ctrl+F11 afficher ou cacher le bandeau.
  - Ils sont modifiables dans les réglages.
- **La fenêtre hors jeu** (Overwolf en exige une) :
  - la connexion par code ;
  - le même lecteur que le panneau ;
  - les réglages : raccourcis, bandeau (emplacement, taille, transparence, ligne des amis), répliques de Greg on/off, et
    « Délier cet appareil ».

**Hors périmètre :**
- Spotify ;
- la farce « jumpscare » ;
- les likes et playlists du chansonnier ;
- le volume (Greg ne le gère pas) ;
- l'avance dans le titre (le bot ne sait pas faire) ;
- la diffusion aux amis ;
- l'appli autonome.

**Anti-objectifs :**
- que le bandeau ou le panneau gardent le clavier, ou fassent rater un sort ;
- qu'une nouvelle porte d'entrée affaiblisse l'API (jeton sans révocation, CSRF, origine joker) ;
- tout ce qui ressemble à de la triche.

## 2. Approches considérées

**Plateforme :**
- **Overwolf OW-native, retenue.** C'est la seule à marcher en Plein écran, et elle est éprouvée en jeu.
- **Appli Electron autonome.** Elle serait pour tous et sans dépendance, mais seulement en Sans bordure. Ses raccourcis
  Windows sont incertains, et Vanguard la regarde moins qu'Overwolf.
- **Mini-lecteur du site.** Il ne demande rien à installer, mais il est invisible en Plein écran, sans raccourcis en jeu,
  et vole le focus.
- **Version ow-electron (branche `refunt`).** Écartée : elle exige l'installeur Overwolf et une approbation, et elle est
  dépassée par l'API.

**Connexion :**
- **Code d'appareil puis jeton porteur, retenue.** C'est le modèle des télés (RFC 8628) : l'appli affiche un code, Paul
  l'autorise sur le site où il est connecté, et l'appli reçoit un jeton aléatoire. Le serveur n'en garde que
  l'empreinte, et le jeton est révocable.
- **Cookie de session dans l'appli.** Écartée : l'origine `overwolf-extension://` est hors de la liste du site, le cookie
  est SameSite=None, et cette voie rouvrirait le popup supprimé.
- **Garder le jeton OAuth Discord côté serveur pour l'appli.** Écartée : ce jeton expire en environ 7 jours sans
  rafraîchissement, et il donnerait à l'appli plus que nécessaire.

## 3. Côté API (`services/api`)

### 3.1 Identité : session ou jeton porteur

- `authz.py` gagne :
  - `Identity {uid, via: "session"|"overlay", tid?}` ;
  - `current_identity()` / `current_user_id()` ;
  - le décorateur `require_identity`.
- Règles :
  - En-tête `Authorization` présent : il doit être `Bearer <jeton>` valide. Sinon, refus (401 `NOT_AUTHENTICATED`), sans
    jamais se rabattre sur le cookie.
  - Sinon, c'est la session (cookie), comme aujourd'hui.
  - Le résultat est mis en cache dans `flask.g`.
- Les routes du lecteur (`player.py`), de l'historique et des recherches passent à `require_identity`. Le chansonnier
  (`library.py`) reste en session seule, puisqu'il est hors périmètre.
- Le contrôle par serveur reste chez le bot (`_check_member`) et s'applique tel quel à une identité « overlay ».

### 3.2 Le défaut CSRF existant, corrigé avant d'ouvrir l'autorisation

Constat, vérifié par la lecture du 2026-11-25 :
- un formulaire HTML d'un site tiers peut faire `POST /player/skip?guild_id=…` (et stop, pause, play_at, repeat, voice/join,
  logout) avec le cookie ;
- la cause : SameSite=None, et le `guild_id` lu dans l'URL.

Correctif `csrf_ok()`, appliqué par `require_identity` / `require_session_user` aux méthodes non sûres authentifiées par
**session** :
- corps JSON obligatoire (`request.is_json`) ;
- `Origin`, s'il est présent, dans les origines du **site** (`WEB_ORIGINS`), jamais celles de l'appli ;
- sinon `Referer`, s'il est présent, dans ces mêmes origines.

Le reste de la règle :
- échec : 403 `CSRF_FAILED` ;
- les requêtes à jeton porteur en sont exemptées, car un navigateur ne joint jamais `Authorization` tout seul ;
- `POST /auth/logout` est couvert aussi.

Le site envoie déjà du JSON partout (`api.ts`). Le constructeur le vérifie, y compris pour `logout`.

### 3.3 Origines

- Nouvelle variable `OVERLAY_ORIGINS`, validée strictement par `overwolf-extension://[a-z]{20,64}` : pas de joker, pas de
  chemin, pas de métacaractère regex.
- `app.config["WEB_ORIGINS"]` vaut `cors_origins()` (inchangé).
- `ALLOWED_ORIGINS` vaut le site plus l'appli. Cette liste sert à CORS et à `cors_allowed_origins` de Socket.IO.
- L'UID est dérivé par Overwolf du `name` et de l'`author` du manifeste. On garde `name: "GregLC"` et
  `author: "Paul Berdier"` (voir §6), donc l'origine est
  `overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk`, l'UID de la carte GregLC actuelle. Le constructeur la
  confirme dans `overwolf://packages` avant de régler Railway.

### 3.4 Le parcours par code (nouveau blueprint `routes/overlay.py`, magasin `services/overlay_tokens.py`)

Le magasin Redis s'inspire de `library_store`, avec des délais courts. Clés :

| Clé | Contenu | Durée |
|---|---|---|
| `greg:overlay:device:{sha256(device_code)}` | `{user_code, status, client_name, created_at, interval, last_poll_at, uid?, user?, guild_id?}` | 600 s |
| `greg:overlay:user_code:{CODE}` | empreinte de l'appareil, écrite en SET NX | 600 s |
| `greg:overlay:token:{sha256(jeton)}` | `{tid, uid, label, created_at, last_used_at, expires_at, user, default_guild_id}` | durée du jeton |
| `greg:overlay:tokens:{uid}` | HASH `tid → empreinte`, pour lister et révoquer | — |
| `greg:ratelimit:{seau}:{sujet}` | INCR + EXPIRE | — |

Le format des codes :
- `user_code` : 8 caractères de `BCDFGHJKLMNPQRSTVWXZ`, affichés `XXXX-XXXX`. La saisie est normalisée (majuscules, sans
  séparateurs).
- `device_code` : `token_urlsafe(32)`.
- Jeton : `greg_ow_` + `token_urlsafe(32)`, conservé seulement sous forme d'empreinte sha256.

Routes (préfixe `/api/v1`) :

1. **Démarrer.** `POST /overlay/device`, sans authentification.
   - Limites : 30 par heure au total, et 5 par minute par IP au mieux.
   - Corps `{client_name?}` (≤ 40 caractères).
   - Réponse : `{device_code, user_code, verification_uri: WEB/lier, verification_uri_complete: WEB/lier?code=…, expires_in: 600, interval: 5}`.
2. **Consulter.** `GET /overlay/device/lookup?user_code=` (session, propriétaire). Renvoie `{client_name, created_at, expires_in}`,
   pour que /lier montre ce qu'on autorise.
3. **Autoriser ou refuser.** `POST /overlay/device/approve`.
   - Protections : session, `csrf_ok`, propriétaire seulement, 5 par minute par uid.
   - Corps `{user_code, decision: "approve"|"deny", guild_id?}`.
   - `guild_id` est le serveur par défaut. Il est validé par `get_state` (contrôle d'appartenance du bot).
   - L'identité et le portrait de l'utilisateur viennent de la session, jamais du corps.
   - Usage unique : GETDEL de l'index `user_code`.
   - Erreurs : 404 `CODE_EXPIRED`, 409 `ALREADY_USED`, 403 `NOT_OWNER` / `CSRF_FAILED`, 429 `RATE_LIMITED`.
4. **Récupérer le jeton.** `POST /overlay/token {device_code}`, sans authentification.
   - Erreurs au format RFC 8628 : `authorization_pending`, `slow_down` (+5 s), `access_denied`, `expired_token`.
   - Succès : `{access_token, token_type: "Bearer", expires_in, user: {id, username, global_name, avatar}, default_guild_id}`.
   - Le jeton est émis atomiquement : un second appel ne peut pas en frapper un deuxième.
5. **Gérer les jetons.**
   - `GET /overlay/me` (identité) renvoie le portrait enregistré.
   - `GET /overlay/tokens` (session ou jeton) liste `{id, label, created_at, last_used_at, expires_at, current}`, jamais
     d'empreinte.
   - `POST /overlay/tokens/revoke {id}` : session (avec CSRF et propriétaire), ou le jeton qui se révoque lui-même.
   - `POST /overlay/logout` révoque le jeton courant.
   - Toute révocation supprime les clés et déconnecte les sockets de ce jeton.
6. **Lister les serveurs.** `GET /overlay/guilds` (identité). Elle appelle l'action bot `user_guilds` (§4.1) et renvoie
   `{guilds: [{id, name, icon_url, greg_voice, user_voice, playing}]}`.

Autres décisions :
- **Propriétaire seulement.** Seul `GREG_OWNER_ID` peut autoriser un appareil.
  - L'appli ne sert qu'à Paul, et cela coupe court au hameçonnage par code.
  - Constat du 2026-11-25 (noms des variables seulement) : `GREG_OWNER_ID` est défini pour le service **BOT DISCORD**
    mais **pas pour le service API**. Il faut l'ajouter à l'API, avec la même valeur, en même temps
    qu'`OVERLAY_ORIGINS` et seulement avec l'accord de Paul.
  - Sans `GREG_OWNER_ID`, l'autorisation refuse tout (403 `NOT_OWNER`) : on ne passe jamais en mode « tout le monde ».
  - L'API publique est `https://greg-api.up.railway.app`. Le service API n'a pas de `CORS_ORIGINS`, donc les origines du
    site se limitent à `WEB_URL`.
- **Durée du jeton : 180 jours** (`OVERLAY_TOKEN_TTL_DAYS`, notre choix), révocable à tout moment. `last_used_at` est mis
  à jour au plus une fois toutes les 5 minutes.

### 3.5 Socket.IO

- `on_connect(auth=None)` :
  - si `auth.token` est présent, il est résolu ;
  - jeton invalide : `ConnectionRefusedError("NOT_AUTHENTICATED")` ;
  - jeton valide : l'identité est liée à la copie de session propre à ce socket (`session["_ident"]`, jamais réécrite dans
    un cookie), le sid est noté dans un registre `{tid: set(sid)}`, et le socket rejoint `authenticated`.
- `_subscribe` passe à `current_user_id()`. Pour un socket à jeton, il revérifie que le jeton existe encore avant
  `join_room`.
- `on_disconnect` nettoie le registre.
- La révocation déconnecte les sids du jeton.
- Le jeton voyage dans le paquet CONNECT (`io(url, {auth: {token}})`), jamais dans une URL.

### 3.6 Petits manques comblés

- **File qui a bougé (notre choix, plutôt que de recopier la faiblesse du site).**
  - Le problème aujourd'hui :
    - `remove`, `move` et `play_at` n'envoient qu'un index ;
    - le bot compare l'élément à sa propre file au moment de la commande ;
    - un index périmé mais encore dans les bornes agit donc sur un autre titre.
  - Le correctif :
    - ces routes acceptent un champ facultatif `expected: {url, added_by, ts}` ;
    - le bot le compare à `queue[index]` ;
    - en cas de différence, il refuse avec `{ok:false, error:"STALE"}`, que l'API renvoie en 409 `STALE`.
  - Sans `expected`, rien ne change. L'appli l'envoie toujours, et le site aussi (§5) : il a déjà ces trois champs pour
    ses clés de ligne.
- **Ticks.** Les ticks relayés (`redis_listener.py`) portent désormais `guild_id`, que le bot publie déjà. Le site
  l'ignore ; l'appli s'en sert pour écarter les ticks d'un autre serveur pendant un changement.
- **Activité des autres.** Après chaque commande réussie qui modifie l'état, le pont du bot publie
  `greg:player:event {guild_id, action, actor: {id, display_name}, title?}`.
  - Actions concernées : ajout, passage, stop, pause/reprise, retrait, déplacement, jouer maintenant, boucle.
  - L'API le relaie en `player_event` à la salle `guild:<id>`.
  - Les commandes slash Discord ne sont pas couvertes dans un premier temps. Leurs ajouts restent visibles par l'arrivée
    d'un titre `added_by` d'un autre.

## 4. Côté bot (`services/bot`)

### 4.1 Action `user_guilds` (lecture seule)

- Elle est calculée depuis le cache du bot (intents members et voice_states déjà actifs) : serveurs communs à Greg et à
  l'utilisateur.
- Chaque serveur donne `{id, name, icon_url, greg_voice: {id, name}|null, user_voice: {id, name}|null, playing: bool}`.
- Elle est ajoutée aux actions en lecture seule, et appelée avec `guild_id` 0, donc sans contrôle d'appartenance (elle ne
  renvoie que des serveurs où l'utilisateur est membre).
- L'uid vient uniquement de l'identité de l'API.

### 4.2 Événement d'activité

C'est la publication de §3.6, faite dans `redis_bridge._handle_command` après un résultat `ok` d'une action qui modifie
l'état.

### 4.3 Contrôle `expected`

`remove_at`, `move` et `play_at` (player_service) reçoivent l'élément attendu (§3.6). S'il est fourni et ne correspond
pas, ils renvoient `STALE`, sans rien modifier.

### 4.4 Hors de ce chantier

Les restes morts de l'ancien overlay (`spook_scare`, crochet `emit_fn`, modèles partagés avec `user_id`) ne sont pas
touchés. Ils sont notés pour plus tard.

## 5. Côté site (`services/web`) : la page /lier

- **Nouvelle route** `src/app/lier/page.tsx` (client), sans `usePlayerInit`.
- **Connecté et propriétaire :**
  - un champ code, prérempli par `?code=` mais jamais validé automatiquement ;
  - le nom de l'appareil et son âge (`lookup`) ;
  - le choix du serveur par défaut (serveurs où Greg est présent) ;
  - les boutons « Autoriser » (`.btn-solid`) et « Refuser » (`.btn-ghost`) ;
  - puis la confirmation « C'est fait, Sire. Retournez à votre jeu. »
- **Non connecté :**
  - le bouton « Se connecter avec Discord » ;
  - le code en attente est gardé en `sessionStorage` (`greg.lier.pending`, 10 min) ;
  - au retour sur « / », `boot()` renvoie vers /lier s'il en trouve un.
  - Le serveur ne reçoit aucune URL de retour.
- **Non propriétaire :** un message neutre, sans détail.
- **Appareils liés :** liste des jetons (nom, dernière utilisation, échéance) avec « Délier », confirmé par le motif de
  dialogue de `Transport.tsx`.
- **Accès :** une entrée « Appareils liés » dans `AccountMenu`, visible du seul propriétaire.
- **Textes :** une section `devices` dans `copy.extra.ts`, avec la typographie du deck (tests `copy-extra`).
- **API côté site :** de nouvelles méthodes `api.device*` dans le style du chansonnier (identité de session, JSON).
- **Logique pure :** normalisation du code, garde du code en attente, choix du serveur par défaut. Elle va dans
  `src/lib/devices.ts` et est testée.
- **Lecteur du site :**
  - `removeTrack`, `moveTrack` et `playNow` envoient `expected` (§3.6) ;
  - un 409 `STALE` reçoit le même traitement que le conflit de déplacement actuel : on resynchronise et on annonce
    « La file a bougé ».

## 6. L'appli Overwolf (`greg-overlay-ow`)

### 6.1 Dépôt et outillage

- **Branche `feat/overlay-v3`.** L'ancienne appli est retirée de l'arbre ; elle reste dans l'historique.
- **Pas de bundler :**
  - JavaScript simple en modules ES, chargés par `<script type="module">` ;
  - `socket.io.min.js` 4.7.5 copié dans le dépôt.
- **Logique pure** (normalisation de l'état, horloge, file, copie, placement, fusion des raccourcis) dans `lib/*.js`.
  Elle est testée avec `node --test`, avec un faux `overwolf` comme dans le banc de l'essai.
- **Script `scripts/sync-web.mjs`.** Il recopie depuis `../GregLeConsanguin/services/web` :
  - les polices et leurs licences ;
  - `greg-face-*.webp`, les sceaux, `crown-badge` ;
  - les jetons de `tokens.css` ;
  - les entrées utiles de `copy.v2.json`.
  - Le résultat est commité, pour que l'appli se charge sans le site.
- **README :**
  - charger l'appli (Load unpacked) ;
  - régler `OVERLAY_ORIGINS` sur Railway ;
  - délier ;
  - désactiver l'appli.

### 6.2 Manifeste

- **Identité :** `name: "GregLC"`, `author: "Paul Berdier"` (même UID, même origine), `version: "3.0.0"`.
- **Permissions :** `Hotkeys`, `GameInfo`. Pas de `FileSystem` : l'appli n'écrit plus de journal.
- **Jeu et lancement :** `game_targeting: dedicated [5426]` ; `launch_events: GameLaunch 5426` plus le lancement manuel.
- **Raccourcis :** `pause`, `suivant`, `panneau`, `bandeau` (Ctrl+F7, F8, F10, F11), en `custom`, `passthrough: false`.
- **Fenêtres :**
  - `fond` : page de fond, cerveau unique ;
  - `bureau` : fenêtre hors jeu (`desktop_only`, native) ;
  - `bandeau` : en jeu, transparent, `clickthrough`, `ignore_keyboard_events`, sans focus ;
  - `panneau` : en jeu, `grab_keyboard_focus`, plus `requestOverlayFocus` à l'ouverture.
- **CSP :** `default-src 'self'; connect-src https://greg-api.up.railway.app wss://greg-api.up.railway.app;
  img-src 'self' https://i.ytimg.com https://cdn.discordapp.com`.
  - L'appli parle directement à l'API publique, pas à travers les réécritures du site.
  - L'adresse de l'API est une constante de `lib/config.js`.

### 6.3 Le cerveau (`fond`)

- **Un seul détenteur.** Il détient le jeton, le socket, l'état du lecteur, le serveur choisi et les réglages. Les
  fenêtres s'abonnent via `getMainWindow().greg`, comme dans l'essai.
- **Jeton :**
  - rangé dans le `localStorage` de l'extension (origine propre à l'appli) ;
  - au démarrage, `GET /overlay/me` le valide ;
  - un 401 l'efface, et la fenêtre bureau repasse en connexion.
- **Socket :**
  - `io(api, {auth: {token}, transports: ['websocket']})` ;
  - `join_guild` du serveur choisi ;
  - écoute de `playlist_update` (état complet et ticks), `player_event` et `guild_join_error` ;
  - `time_sync` comme sur le site, pour l'horloge précise ;
  - repli : sondage REST toutes les 5 s tant que le socket est coupé.
- **Actions REST.** Elles envoient `Authorization: Bearer` et `guild_id` dans le corps, puis attendent `playlist_update`.
  - Les refus sont traduits par la table d'erreurs du site (portée en JS).
  - Retirer, déplacer et jouer maintenant envoient `expected` (§3.6).
  - Un 409 `STALE` ou hors bornes déclenche un `request_state`, puis l'annonce « La file a bougé, réessayez. »
- **Jeu.** La détection, la fermeture des fenêtres en fin de partie et le placement sont repris de l'essai :
  - `getRunningGameInfo2`, `onGameInfoUpdated`, et un contrôle toutes les 3 s ;
  - rien ne bouge si la fenêtre de LoL fait moins de 200 px (Plein écran hors focus = 1×1).
- **Raccourcis :**
  - fusion à 350 ms entre le raccourci Overwolf et la touche captée par le panneau ;
  - répétition ignorée sous 600 ms ;
  - pause et suivant passent par l'API ;
  - un appui sans serveur choisi ou sans connexion fait apparaître un message sur le bandeau.

### 6.4 Le bandeau

- **Contenu :** le médaillon de Greg, le surtitre (« Greg · en lecture / en pause / au repos »), le titre nettoyé
  (`parseTitle`), l'artiste et le demandeur (« par vous » avec le sceau du Roi, ou « par {nom} »), le temps et la barre
  dorée.
- **États :** rien en lecture ; Greg hors ligne ; pas connecté (« Liez l'appli depuis la fenêtre Greg ») ; serveur non
  choisi ; refus (le texte d'erreur, 6 s) ; ligne d'ami (« Kévin a ajouté « Thunderstruck » », 5 s, si l'option est
  active).
- **Ancrage, par défaut en bas à gauche :** `left = 16`, `top = hauteur logique − hauteur du bandeau − marge`.
  - Marge par défaut 24 px. Le constructeur l'ajuste sur une capture réelle, en évitant le chat de LoL s'il apparaît.
  - Autres choix dans les réglages : « Bord gauche, au tiers » (l'emplacement de l'essai) et « En haut à gauche ».
- **Taille :** « Compacte » (titre et temps, sans médaillon) ou « Normale ».
- **Transparence réglable** (curseur de 0 à 100 %, défaut 70 %) :
  - elle s'applique au fond seulement ;
  - le texte garde une ombre légère pour rester lisible sur la carte de jeu ;
  - à 0 %, il ne reste que le texte et la barre.
  - Le réglage est appliqué en direct, en jeu comme dans l'aperçu de la fenêtre bureau.
- **Jamais de focus, jamais de clic.** Il est caché pendant que le panneau est ouvert, puis revient à la première touche
  ou au bout de 3 s.

### 6.5 Le panneau

Il reprend l'essai, la DA du site et les composants du lecteur : `Transport`, `QueueRow`, `SearchBar`.
- **En-tête :** le médaillon, « Greg » (Grenze Gotisch), le nom du serveur (cliquable pour en changer) et « Échap ».
- **En cours :** le surtitre, le titre (Grenze 600), l'artiste et le demandeur, le temps et la barre.
- **Commandes :** stop (avec confirmation), recommencer, pause/lecture, suivant, boucle (`aria-pressed`).
- **Recherche :**
  - suggestions YouTube (280 ms, 2 caractères minimum, jamais pour un lien) ;
  - Entrée ajoute le premier choix, ou le texte tel quel ;
  - un lien collé est ajouté directement.
- **« À suivre » :** une ligne par titre (vignette, titre, artiste, demandeur, durée), et au survol jouer maintenant,
  en tête, retirer.
  - Le réordonnancement se fait par glisser-déposer, plus Alt+↑/↓ au clavier.
  - Au-delà de 60 titres : « …et N autres titres ».
- **Pied :** les raccourcis du moment.
- **Clavier :**
  - le panneau prend le clavier à l'ouverture (`requestOverlayFocus`, puis `bringToFront(focus)` en secours) ;
  - Échap, Ctrl+F10 ou un clic dans le jeu le ferment et rendent le clavier ;
  - Tab reste dans le panneau.
- **Annonces :** des messages courts dans le style du Héraut du site, plus une réplique de Greg au plus toutes les 30 s
  si les répliques sont actives.

### 6.6 La fenêtre bureau

- **Non lié :**
  - le code `XXXX-XXXX` en grand ;
  - le bouton « Ouvrir le site pour l'autoriser » (`openUrlInDefaultBrowser(verification_uri_complete)`) ;
  - l'appli interroge `/overlay/token` au rythme demandé ;
  - le code expire au bout de 10 min, avec un bouton « Nouveau code ».
- **Lié :**
  - le même lecteur que le panneau ;
  - un onglet « Réglages ».
- **Réglages :**
  - les raccourcis, affichés et modifiables (`hotkeys.assign` avec capture de la touche, refus des combinaisons déjà
    prises) ;
  - le bandeau : emplacement, taille, transparence (avec aperçu), ligne des amis ;
  - les répliques de Greg ;
  - « Délier cet appareil » (`/overlay/logout`).
- Les réglages sont dans le `localStorage` de l'appli.

### 6.7 La DA

- La « Nuit gothique » du site :
  - les jetons de `tokens.css` recopiés ;
  - les quatre polices ;
  - la plaque, l'anneau de focus doré et les icônes au trait.
- Les fonctions CSS récentes (`corner-shape`, `@starting-style`) se dégradent proprement : le CEF d'Overwolf n'est pas
  forcément à jour.
- Les textes viennent du deck du site (`copy.v2.json`, recopié), avec `t`/`fill`/`quip` portés en JS. Les textes propres à
  l'appli sont dans `copy.overlay.js`, avec la même typographie.

## 7. Vérification

- **API (pytest) :**
  - parcours complet du code ;
  - usage unique, expiration, `slow_down` ;
  - propriétaire seulement ;
  - CSRF (formulaire tiers refusé, JSON du site accepté) ;
  - porteur prioritaire sur le cookie, jeton invalide refusé sans repli ;
  - origine Overwolf acceptée, joker et origines invalides toujours refusés ;
  - socket à jeton accepté ou refusé, révocation qui déconnecte ;
  - `/overlay/guilds` ;
  - `guild_id` sur les ticks ;
  - `player_event` ;
  - `expected` : accepté s'il correspond, 409 `STALE` sinon, comportement inchangé sans lui.
  - Les gardes de 2026-09 (`test_auth`, `test_cors`, `test_socketio`, `test_authz`) restent vertes.
- **Bot :** `user_guilds` et la publication d'événements.
- **Site :** tests `node:test` de `lib/devices.ts`, `tsc --noEmit` et les tests du deck.
- **Appli :**
  - `node --test` sur `lib/` ;
  - un banc hors jeu avec un faux Overwolf et une fausse API (connexion, abonnement, actions, raccourcis, fusion,
    fermeture qui rend le clavier) ;
  - un aperçu des fenêtres dans un navigateur.
- **En jeu, par Paul :** un dernier passage dans l'outil d'entraînement, protocole court dans le README de la PR.
- **Relecture indépendante** de chaque PR avant de la proposer.

## 8. Laissé au constructeur

- Le découpage des fichiers et des fonctions, et les noms internes.
- Les marges exactes du bandeau en bas à gauche, ajustées sur une capture réelle de LoL.
- Les limites de débit exactes, si celles proposées gênent un usage normal.
- La forme des faux (Redis, Overwolf, API) pour les tests.
- Les textes d'erreur de détail, dans le ton du deck.
