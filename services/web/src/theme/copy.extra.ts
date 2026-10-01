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
  queue: {
    list: 'Titres de la file',
    endsAt: 'fin vers {time}',
    etaNext: 'À suivre',
    eta: 'dans {n} min',
    more: { one: '…et 1 autre titre', other: '…et {n} autres titres' },
    rowAria: '{title}, {artist}, demandé par {name}',
    rowAriaMine: '{title}, {artist}, votre titre',
    rowAriaUnknown: '{title}, {artist}',
    keys: 'Flèches haut et bas : parcourir. Entrée : jouer maintenant. Suppr : retirer. Alt+flèches : déplacer. Alt+Début : jouer ensuite.',
  },
  often: {
    title: 'Souvent demandés ici',
  },
  history: {
    list: 'Titres joués sur ce serveur',
    keys: 'Flèches haut et bas : parcourir. Entrée : remettre le titre dans la file.',
    plays: { one: '1 écoute', other: '{n} écoutes' },
    ago: {
      now: 'à l’instant',
      min: 'il y a {n} min',
      h: 'il y a {n} h',
      yesterday: 'hier',
      d: 'il y a {n} j',
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
  a11y: { skipToQueue: 'Aller à la file', nowPlaying: 'En lecture : {title}', paused: 'En pause.', resumed: 'Lecture reprise.' },
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
  ['Alt+Début', 'Mettre en suivant'], ['Suppr', 'Retirer le titre'], ['Échap', 'Fermer'],
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
