# Recherche des serveurs, vidéo en plein écran, chansonnier du Roi : conception

Date : 2026-11-23. Demande de Paul : « les gens peuvent avoir plusieurs centaines de serveurs, mets une barre de
recherche » ; « la vidéo en plein écran avec une UI pour voir la liste un peu transparente, fais correspondre la DA » ;
« création et gestion de ses propres playlists et des musiques qu'on aime, pour les mettre rapidement ».
La DA est laissée à notre main : les choix ci-dessous sont les nôtres, signalés comme tels dans la PR.

Rappels qui s'appliquent partout :
- Greg est le valet, l'utilisateur est le Roi (vouvoiement, sceau et couronne au Roi).
- Textes nouveaux : `EXTRA` de `services/web/src/theme/copy.extra.ts`, lus par `tx()`, typographie du deck
  (U+00A0 avant « : », U+202F avant ; ! ?, apostrophe courbe), sous des sections qui ne sont pas des sections du
  deck (`guildFilter`, `fullscreen`, `library`). Pas d'humour dans EXTRA (libellés et lecteurs d'écran).
- Aucun `transition: all`, aucune classe héritée (`btn`, `glass`…), mouvement réduit respecté.
- Les tests existants (web 402, API 392, bot 223) restent verts ; chaque morceau ajoute les siens.

## 1. Recherche dans le choix du serveur

Constat : `GuildPicker.tsx` rend tous les serveurs dans un listbox, sans tri, sans filtre, focus DOM sur les options,
icônes chargées d'emblée. Discord renvoie jusqu'à 200 serveurs par appel, assez pour la limite de Discord.

Conception :
- Logique pure dans `services/web/src/lib/guilds.ts` (testée) : `foldText(s)` (minuscules, sans accents NFD, espaces
  réduits) et `filterGuilds(guilds, q)`.
  - Sans requête : serveurs où Greg est présent d'abord, puis les autres, ordre de Discord gardé dans chaque groupe.
  - Avec requête : tous les mots de la requête doivent apparaître dans le nom ; rang exact > début du nom > début
    d'un mot > ailleurs ; à rang égal, Greg présent d'abord, puis l'ordre de Discord.
- Motif combobox (comme `SearchBar.tsx`) : un champ en tête du popover, hors du `role="listbox"`, focus gardé dans
  le champ, `aria-activedescendant` sur l'option active ; ↑ ↓ Début Fin parcourent, Entrée choisit, Échap vide le
  champ s'il contient du texte (sans fermer), sinon ferme et rend le focus au déclencheur.
- Le champ n'apparaît qu'à partir de 8 serveurs ; en dessous, le popover garde le même modèle clavier, focus sur le
  listbox lui-même.
- Intertitres « Greg présent » / « Sans Greg » quand la présence est connue et qu'aucune requête n'est tapée.
- Résultat vide : « Aucun serveur ne correspond à « {q} » » ; nombre de résultats annoncé (région `role="status"`).
- Icônes en `loading="lazy"` ; champ collant en haut du popover ; la règle `.top .pop` (max-height, overflow-y,
  overscroll-behavior) testée par keyboard-contract ne bouge pas.
- `usePopover` reste exporté (AccountMenu, prefs.test).

## 2. La vidéo en plein écran

Constat : déplacer l'iframe YouTube dans le DOM la recharge. Le régulateur de synchro (Portal.tsx) continue de tourner
en plein écran (visibilityState ne change pas). Tout ce qui est hors de l'élément en plein écran est invisible.

Conception :
- L'élément mis en plein écran est `.video` (Portal.tsx), qui contient déjà l'iframe, les posters, le voile et le
  badge. L'iframe ne bouge jamais. `requestFullscreen()` est appelé dans le gestionnaire du clic (activation
  utilisateur) ; l'état suit `fullscreenchange` (`document.fullscreenElement === el`). Préfixes `webkit` gérés.
- Sans API plein écran pour un élément (iPhone) : repli « pseudo » en CSS (`data-fs="pseudo"`, fixed, inset 0),
  Échap et le bouton le quittent.
- Hook `services/web/src/hooks/useFullscreen.ts` ; logique pure testable à part si utile.
- En plein écran : `.video` occupe l'écran, posters en `object-fit: contain`, fond noir.
- Une surcouche « La Grand-Salle » (`Stage/Theater.tsx`, `Stage/theater.css`), dernier enfant de `.video`, rendue
  seulement en plein écran :
  - en haut : surtitre, titre (Grenze), artiste ; bouton « Quitter le plein écran » ;
  - à droite : la file « À suivre » en plaque translucide (fond `rgb(11 9 8 / .6)`, filet `--hair`), titre en cours
    puis les prochains (pochette, titre nettoyé, artiste, durée), défilante ; « Jouer maintenant » et « Retirer » par
    ligne, via les actions optimistes existantes (`playerActions.playNow`, `removeTrack`) ; bouton pour masquer ou
    montrer la file, mémorisé (localStorage, clé `greg.webplayer.fsQueue`) ;
  - en bas : temps et barre de progression, puis le `Transport` existant.
  - Pas de `backdrop-filter` ni de `filter` au-dessus ou autour de l'iframe (tech.md §6.2 : une passe de rendu par
    image vidéo). La translucidité vient de la couleur seule.
  - Les commandes s'effacent après 3 s sans mouvement de souris, sans touche, sans focus qui change ; le curseur
    disparaît avec elles ; elles reviennent au moindre mouvement. Mouvement réduit : apparition sans fondu.
  - Focus : à l'entrée, sur le bouton de sortie ; Tab reste dans la surcouche ; à la sortie, retour au bouton
    d'entrée.
- Entrées : bouton « Plein écran » dans `.below-foot` (à côté de « Synchro vidéo », même style), et double-clic sur la
  vidéo (entrée comme sortie). Disponible dès qu'un titre joue (vidéo YouTube ou pochette).
- Fin de lecture : plus de titre pendant 1,5 s → sortie du plein écran.
- Clavier de la page (page.tsx) : en plein écran, `type`, `search` et `help` sont ignorés (le champ de recherche et
  l'aide sont hors de l'écran) ; Espace et Maj+← / Maj+→ marchent toujours. Pas de touche « F » (toute lettre tape
  dans la recherche).

## 3. Le chansonnier du Roi : playlists et coups de cœur

Constat : rien n'existe par utilisateur. Le disque du bot est perdu à chaque redéploiement sur Railway ; Redis,
lui, a son volume. L'API sait qui est connecté (session, SEC-C1) et parle déjà à Redis.

### Stockage (API, Redis)
- Une clé par Roi : `greg:library:{discord_id}` → JSON `{"v": 1, "likes": [Track], "playlists": [Playlist]}`.
- Modifications en lecture-écriture sous `WATCH` / `MULTI` / `EXEC`, 5 essais, sinon 503.
- `Track` stocké : `{url, title, artist, duration, thumb, provider, added_at}`.
  - `url` obligatoire, http(s), au plus 500 caractères ;
  - `title` au plus 200 (défaut : l'url) ; `artist` au plus 120 ou null ;
  - `duration` entier 0..86400 ou null ; `thumb` http(s), au plus 500, ou null ;
  - `provider` `youtube` | `soundcloud` | null (déduit de l'hôte si absent) ; `added_at` en secondes epoch.
- Identité d'un titre (doublons) : `yt:<id>` pour une vidéo YouTube (watch?v=, youtu.be/, shorts/, embed/,
  music.youtube.com), sinon `url:<url sans espaces ni / final>`. Le site calcule la même clé (`trackKey`).
- `Playlist` : `{id, name, tracks: [Track], created_at, updated_at}`. `id` : `secrets.token_urlsafe(8)`. `name` :
  1 à 60 caractères après nettoyage (espaces réduits, caractères de contrôle retirés).
- Plafonds : 500 coups de cœur, 50 playlists, 200 titres par playlist.

### Routes (préfixe /api/v1, toutes `@require_session_user`, identité de la session seule)
Toutes les mutations renvoient `{ok: true, library}` (la bibliothèque complète, petite) plus leurs champs propres.
- `GET /library` → `{ok, library: {likes, playlists, limits: {likes, playlists, tracks, name}}}`.
- `POST /library/likes/add` `{track}` : idempotent, le plus récent en tête.
- `POST /library/likes/remove` `{url}` : retrait par identité.
- `POST /library/playlists/create` `{name, tracks?}` → `+ playlist_id` (titres en double écartés, plafonnés à 200).
- `POST /library/playlists/rename` `{id, name}`.
- `POST /library/playlists/delete` `{id}`.
- `POST /library/playlists/add` `{id, tracks}` → `+ added, skipped` (doublons écartés ; ce qui dépasse 200 est
  compté dans `skipped`).
- `POST /library/playlists/remove` `{id, url}`.
- `POST /library/playlists/move` `{id, src, dst}`.
- Erreurs (avec `message` en français) : 400 `INVALID_TRACK` / `INVALID_NAME` / `INVALID_REQUEST`,
  404 `PLAYLIST_NOT_FOUND`, 409 `LIMIT_REACHED`, 503 `STORAGE_UNAVAILABLE`, 401 `NOT_AUTHENTICATED`.

### Jouer une playlist d'un geste
- `POST /queue/add_many` `{guild_id, items: [Track], label?}` : 1 à 100 titres (sinon 400), nettoyés comme
  ci-dessus, envoyés au bot par `play_for_user` avec `item = {"items": [...], "title": label}` et le même délai
  (`PLAY_FOR_USER_TIMEOUT`) et la même réponse HTTP que `/player/enqueue`.
- Bot (`PlayerService.play_for_user`) : quand `item["items"]` est une liste non vide, les entrées sont ces titres
  (normalisés, sans url écartés), plafonnées à `min(limite d'expansion, quota restant)` avec `truncated`,
  `requested = len(items)`, `playlist = True` ; mêmes contrôles qu'aujourd'hui avant (salon vocal, Greg ailleurs,
  quota, connexion) et même boucle d'ajout sous le verrou (un titre refusé est sauté et compté).
  Réponse : la forme actuelle `{ok, added, requested, truncated, playlist, title}`.

### Site
- Logique pure `services/web/src/lib/library.ts` (testée) : `trackKey`, `toLibraryTrack`, durée totale, recherche
  d'une playlist, application optimiste des mutations.
- Store `services/web/src/hooks/useLibrary.ts` (zustand) : chargé quand le Roi est connecté, vidé à la déconnexion ;
  actions optimistes avec retour arrière et annonce du Héraut en cas d'erreur ; `playAll(tracks, label)` passe par
  une nouvelle action `playerActions.enqueueMany` (toast « N titres ajoutés », annulable comme un ajout).
- Troisième onglet du panneau de droite : « Chansonnier » (titre en Grenze Gotisch « Chansonnier du Roi », sous-titre
  avec les compteurs). Les onglets passent de deux à trois (pilule glissante, flèches gauche/droite).
  - Vue d'ensemble : carte « Coups de cœur » puis les playlists (nom, nombre de titres, durée) avec « Tout jouer » ;
    « Nouvelle playlist » (nom en ligne) et « Enregistrer la file » (titre en cours + file).
  - Vue d'une playlist (ou des coups de cœur) : retour, nom modifiable, « Tout jouer », « Supprimer » (confirmation),
    « Ajouter le titre en cours » ; lignes au style de l'historique (pochette, titre nettoyé, artiste, durée) avec
    « + » (remettre dans la file avec Le Sceau, comme `requeue`) et « Retirer » ; clavier : ↑ ↓ Début Fin, Entrée
    ajoute à la file, Suppr retire, Alt+↑ / Alt+↓ déplacent.
- Cœur « J'aime » (bouton à bascule, `aria-pressed`) : sous le titre en cours (NowPlaying), dans les actions d'une
  ligne de la file et d'une ligne de l'historique. À côté du cœur du titre en cours, « Ajouter à une playlist »
  ouvre un petit menu des playlists (et « Nouvelle playlist… »).
- La surcouche plein écran reçoit le cœur du titre en cours à l'intégration.

## Hors champ
- Partage de playlists entre Rois, import d'une playlist YouTube dans le chansonnier, glisser-déposer dans une
  playlist (le clavier Alt+flèches suffit pour réordonner).
- Persistance de Redis sur Railway : à vérifier dans le tableau de bord (volume du service Redis).
