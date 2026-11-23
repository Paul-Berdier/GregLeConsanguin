/**
 * Compléments au deck v2 (copy.v2.json, repris tel quel, qu'on n'édite pas à la main) : les textes de la file,
 * de l'historique, du Héraut, du clavier, des lecteurs d'écran et deux erreurs que le deck n'a pas encore. À reverser au deck v3.
 * Même règles que le deck : vouvoiement du Roi, U+00A0 avant « : » et entre un nombre et son unité,
 * U+202F avant ; ! ?. Aucun humour ici : ce sont des libellés et des textes pour lecteurs d'écran.
 * Pur, sans import runtime (tests/copy-extra.test.mjs).
 */

type Plural = { one: string; other: string };
type Node = string | Plural | { [k: string]: Node };

export const EXTRA = {
  panel: {
    label: 'File d’attente et historique',
    tabs: 'Vues',
    queueTab: 'File',
  },
  // Choix du serveur (spec 2026-11-23 §1) : champ de recherche, intertitres, présence de Greg, état vide, décompte annoncé
  guildFilter: {
    label: 'Chercher un serveur',
    placeholder: 'Chercher un serveur…',
    present: 'Greg présent',
    absent: 'Greg absent',
    group: { present: 'Greg présent', absent: 'Sans Greg' },
    empty: 'Aucun serveur ne correspond à « {q} ».',
    count: { one: '1 serveur trouvé', other: '{n} serveurs trouvés' },
  },
  queue: {
    list: 'Titres de la file',
    endsAt: 'fin vers {time}',
    etaNext: 'À suivre',
    eta: 'dans {n} min',
    more: { one: '…et 1 autre titre', other: '…et {n} autres titres' },
    rowAria: '{title}, {artist}, demandé par {name}',
    rowAriaMine: '{title}, {artist}, votre titre',
    rowAriaUnknown: '{title}, {artist}',
    keys: 'Flèches haut et bas : parcourir. Entrée : jouer maintenant. Suppr : retirer. Alt+flèches : déplacer. Alt+Début : jouer ensuite. J : coup de cœur.',
  },
  often: {
    title: 'Souvent demandés ici',
  },
  history: {
    list: 'Titres joués sur ce serveur',
    keys: 'Flèches haut et bas : parcourir. Entrée : remettre le titre dans la file. J : coup de cœur.',
    plays: { one: '1 écoute', other: '{n} écoutes' },
    ago: {
      now: 'à l’instant',
      min: 'il y a {n} min',
      h: 'il y a {n} h',
      yesterday: 'hier',
      d: 'il y a {n} j',
    },
  },
  // Le chansonnier du Roi (spec 2026-11-23 §3) : troisième onglet du panneau, cœurs, menu « Ajouter à une playlist ».
  // Les annonces du Héraut sont des entrées { text } (say('library.toast.…')) ; les erreurs : noticeOf, lib/library.ts.
  library: {
    tab: 'Chansonnier',
    title: 'Chansonnier du Roi',
    panelLabel: 'File d’attente, historique et chansonnier',
    loading: 'Ouverture du chansonnier…',
    failed: 'Le chansonnier est indisponible pour l’instant.',
    retry: 'Réessayer',
    count: {
      likes: { one: '1 coup de cœur', other: '{n} coups de cœur' },
      likesNone: 'aucun coup de cœur',
      playlists: { one: '1 playlist', other: '{n} playlists' },
      playlistsNone: 'aucune playlist',
      tracks: { one: '1 titre', other: '{n} titres' },
      tracksNone: 'aucun titre',
    },
    likes: 'Coups de cœur',
    list: 'Coups de cœur et playlists',
    listKeys: 'Flèches haut et bas : parcourir. Entrée : ouvrir.',
    noPlaylists: 'Aucune playlist pour l’instant : créez-en une, ou enregistrez la file.',
    newPlaylist: 'Nouvelle playlist',
    newPlaylistMenu: 'Nouvelle playlist…',
    saveQueue: 'Enregistrer la file',
    saveQueueAria: 'Enregistrer le titre en cours et la file dans une nouvelle playlist',
    queueName: 'File du {date}',
    nameLabel: 'Nom de la playlist',
    create: 'Créer',
    createAria: 'Créer la playlist',
    save: 'Enregistrer',
    cancel: 'Annuler',
    playAll: 'Tout jouer',
    playAllAria: 'Tout jouer : {name}',
    back: 'Retour au chansonnier',
    rename: 'Renommer la playlist',
    addCurrent: 'Ajouter le titre en cours',
    tracks: 'Titres de « {name} »',
    keys: 'Flèches haut et bas : parcourir. Entrée : ajouter à la file. Suppr : retirer. Alt+flèches : déplacer.',
    keysLikes: 'Flèches haut et bas : parcourir. Entrée : ajouter à la file. Suppr : retirer des coups de cœur.',
    emptyPlaylist: 'Cette playlist est vide. Ajoutez-y le titre en cours, ou passez par « Ajouter à une playlist » sous le titre en lecture.',
    emptyLikes: 'Aucun coup de cœur pour l’instant. Le cœur sous le titre en lecture, dans la file ou dans l’historique les range ici.',
    requeue: 'Ajouter à la file',
    requeueAria: 'Ajouter à la file : {title}',
    remove: 'Retirer',
    removeAria: 'Retirer de la playlist : {title}',
    unlikeAria: 'Retirer des coups de cœur : {title}',
    delete: 'Supprimer',
    deleteAria: 'Supprimer la playlist « {name} »',
    confirm: {
      title: 'Supprimer « {name} » ?',
      body: { one: 'La playlist et son titre seront supprimés.', other: 'La playlist et ses {n} titres seront supprimés.' },
      bodyEmpty: 'La playlist vide sera supprimée.',
      yes: 'Supprimer',
      no: 'Garder',
    },
    like: {
      aria: 'Coup de cœur : {title}',
      // fin du nom d'une ligne de la file ou de l'historique dont le titre est un coup de cœur (son cœur n'a pas le focus)
      state: 'dans vos coups de cœur',
      add: 'Ajouter aux coups de cœur',
      remove: 'Retirer des coups de cœur',
    },
    addTo: {
      label: 'Ajouter à une playlist',
      aria: 'Ajouter à une playlist : {title}',
      already: 'déjà dedans',
      none: 'Aucune playlist pour l’instant.',
    },
    toast: {
      played: { text: { one: '1 titre ajouté depuis « {name} »', other: '{n} titres ajoutés depuis « {name} »' } },
      addedTo: { text: 'Ajouté à « {name} » : {title}' },
      already: { text: 'Déjà dans « {name} » : {title}' },
      created: { text: 'Playlist « {name} » créée' },
      createdWith: { text: 'Playlist « {name} » créée : {title}' },
      saved: { text: { one: 'File enregistrée dans « {name} » : 1 titre', other: 'File enregistrée dans « {name} » : {n} titres' } },
      nothingToSave: { text: 'Rien en lecture ni dans la file : rien à enregistrer.' },
      removed: { text: 'Retiré de « {name} » : {title}' },
      liked: { text: 'Ajouté aux coups de cœur : {title}' },
      unliked: { text: 'Retiré des coups de cœur : {title}' },
      deleted: { text: 'Playlist « {name} » supprimée' },
    },
    error: {
      STORAGE_UNAVAILABLE: { text: 'Le chansonnier est indisponible pour l’instant. Réessayez dans un instant.' },
      PLAYLIST_NOT_FOUND: { text: 'Cette playlist n’existe plus.' },
      INVALID_NAME: { text: 'Le nom d’une playlist compte de 1 à {n} caractères.' },
      INVALID_TRACK: { text: 'Ce titre n’a pas de lien que le chansonnier sache garder.' },
      limitLikes: { text: 'Vous avez atteint le plafond de {n} coups de cœur. Retirez-en un pour en garder un autre.' },
      limitPlaylists: { text: 'Vous avez atteint le plafond de {n} playlists. Supprimez-en une pour en créer une autre.' },
      limitTracks: { text: '« {name} » a atteint le plafond de {n} titres.' },
      notReady: { text: 'Le chansonnier s’ouvre encore. Réessayez dans un instant.' },
    },
  },
  herald: {
    region: 'Notifications',
    undoHint: '{label} avec Ctrl+Z.',
    dismiss: 'Fermer la notification',
  },
  keys: {
    toggle: 'Raccourcis clavier',
    toggleHelp: 'Désactivés : seules les touches des listes, Échap et Ctrl+Z restent actives.',
    on: 'Raccourcis clavier activés.',
    off: 'Raccourcis clavier désactivés.',
  },
  transport: { skipTip: 'Suivant (Maj+→)', restartTip: 'Depuis le début (Maj+←)', repeatTip: 'Boucle' },
  sync: {
    help: 'Compense le retard de Discord sur cet appareil. Image en avance sur le son\u00a0: glissez vers −. Image en retard\u00a0: vers +.',
  },
  a11y: { skipToQueue: 'Aller à la file', nowPlaying: 'En lecture : {title}', paused: 'En pause.', resumed: 'Lecture reprise.' },
  // Plein écran de la vidéo, « La Grand-Salle » (Stage.tsx, Stage/Theater.tsx ; conception du 2026-11-23, §2).
  fullscreen: {
    enter: 'Plein écran',
    enterTip: 'Plein écran (ou double-clic sur la vidéo)',
    exit: 'Quitter le plein écran',
    exitTip: 'Quitter le plein écran (Échap)',
    region: 'Lecture en plein écran',
    queue: 'À suivre',
    queueToggle: 'File à suivre',
    queueShow: 'Montrer la file',
    queueHide: 'Masquer la file',
    current: 'En cours',
    more: { one: '…et 1 autre titre', other: '…et {n} autres titres' },
  },
  // Erreurs d'ajout que le deck confond (errorCopy, lib/playerUtils.ts) ; le Héraut les lit après le deck (withExtras).
  error: {
    // NO_RESULTS transient : recherche trop lente ou bloquée, pas une absence de résultat
    SEARCH_FAILED: { text: 'La recherche YouTube n’a pas abouti. Réessayez dans un instant.' },
    // EXPAND_TIMEOUT d'une recherche ou d'une vidéo seule : l'attente derrière une autre demande
    BUSY: { text: 'Greg est déjà occupé avec une autre demande sur ce serveur. Réessayez dans un instant.' },
  },
} satisfies Record<string, Node>;

/** Raccourcis du menu du compte (DESIGN §12.7, body.html l. 54–63) : remplacent `shortcuts.items` du deck (N, P, R retirés). */
export const KEYS: readonly (readonly [string, string])[] = [
  ['Espace', 'Lecture / pause'], ['Maj+→', 'Titre suivant'], ['Maj+←', 'Recommencer le titre'], ['/', 'Rechercher'],
  ['A…Z', 'Chercher en tapant'], ['?', 'Afficher cette aide'], ['Ctrl+Z', 'Annuler la dernière action'],
  ['↑ ↓', 'Parcourir une liste'], ['Entrée', 'Jouer le titre maintenant'], ['Alt+↑ ↓', 'Déplacer le titre choisi'],
  ['Alt+Début', 'Mettre en suivant'], ['Suppr', 'Retirer le titre'], ['J', 'J’aime : coup de cœur du titre choisi'], ['Échap', 'Fermer'],
];

function at(path: string): Node | undefined {
  let node: Node | undefined = EXTRA as Node;
  for (const k of path.split('.')) {
    if (!node || typeof node !== 'object' || !Object.prototype.hasOwnProperty.call(node, k)) return undefined;
    node = (node as Record<string, Node>)[k];
  }
  return node;
}

/** Texte au chemin donné, `{clé}` remplis ; pluriel `{ one, other }` choisi par `n` (1 → one). Chemin absent → le chemin. */
export function tx(path: string, vars: Record<string, string | number> = {}): string {
  const node = at(path);
  const pl = node && typeof node === 'object' && 'other' in node && typeof node.other === 'string' ? (node as Plural) : null;
  const s = pl ? (Number(vars.n) === 1 ? pl.one : pl.other) : typeof node === 'string' ? node : null;
  if (s == null) return path;
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m));
}
