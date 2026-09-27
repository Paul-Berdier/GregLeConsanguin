/**
 * Compléments au deck v2 (copy.v2.json, repris tel quel, qu'on n'édite pas à la main) : les textes de la file,
 * de l'historique et du Héraut que le deck n'a pas encore. À reverser au deck v3.
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
} satisfies Record<string, Node>;

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
