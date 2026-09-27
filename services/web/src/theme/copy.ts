/**
 * Textes « valet du Roi » : deck v2 (copy.v2.json, repris tel quel, ne pas éditer à la main).
 * Seule exception, validée par Paul (étape 4) : auth.kicker, formule de valet au lieu d'une formule royale.
 * Greg est le valet ; le Roi, c'est l'utilisateur connecté. Greg vouvoie le Roi.
 *
 * Formes du deck (voir `_meta.shape`) :
 * - chaîne à jetons `{clé}` ;
 * - message `{ text, quips?, kind?, action? }` : `text` est le fait, `null` = réplique seule ;
 * - pluriel `{ zero?, one, other }` piloté par `{n}` (ou `count`) ;
 * - renvoi `{ ref: 'section.cle' }`.
 *
 * Seul import runtime : le JSON du deck. Voir tests/copy.test.mjs.
 */
import deckJson from './copy.v2.json' with { type: 'json' };

export type CopyVars = {
  sire?: string;
  kingName?: string;
  theKing?: string;
  name?: string;
  q?: string;
  count?: number | string;
  [k: string]: unknown;
};

export const deck: Record<string, any> = deckJson;

export const SIRE_DEFAULT = 'Sire';

type Plural = { zero?: string; one?: string; other: string };

// Clés propres uniquement : un chemin ou un jeton « constructor » ne remonte pas au prototype.
function own(o: unknown, k: string): boolean {
  return o != null && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k);
}

// Renvoi = objet dont `ref` (chaîne) est la seule clé ; _meta.shape, qui documente cette forme
// sous une clé « ref » parmi d'autres, n'en est pas un.
function refOf(node: unknown): string | undefined {
  if (!own(node, 'ref') || Object.keys(node as object).length !== 1) return undefined;
  const ref = (node as { ref: unknown }).ref;
  return typeof ref === 'string' ? ref : undefined;
}

const MAX_REFS = 8;

// Chemin pointé ('search.submit.playlist', 'shortcuts.items.0.1'). Les renvois { ref } sont suivis
// à chaque segment ('loading.search.text'), MAX_REFS au plus par appel : un cycle rend undefined.
function resolve(path: string): unknown {
  let hops = 0;
  const deref = (node: unknown): unknown => {
    const ref = refOf(node);
    if (ref === undefined) return node;
    return ++hops > MAX_REFS ? undefined : walk(ref);
  };
  const walk = (p: string): unknown => {
    let node: unknown = deck;
    for (const key of p.split('.')) {
      node = deref(node);
      if (!own(node, key)) return undefined;
      node = (node as Record<string, unknown>)[key];
    }
    return deref(node);
  };
  return walk(path);
}

/**
 * Jetons d'adresse du Roi (sire, theKing, ofTheKing, REX, REGIS, yoElRey) pour un réglage
 * de « Greg vous appelle » (`address.king.options`) ; réglage inconnu → réglage par défaut.
 */
export function kingAddress(option?: string): CopyVars {
  const king = deck.address?.king;
  const options = king?.options;
  const key = option != null && own(options, option) ? option : king?.default;
  const picked = own(options, key) ? options[key] : {};
  const { label: _label, ...vars } = picked as Record<string, unknown>;
  return { sire: SIRE_DEFAULT, ...vars };
}

const DEFAULT_ADDRESS = kingAddress();

// Adresse par défaut sous les variables de l'appelant (une valeur undefined ne l'écrase pas) ;
// `count` sert de `{n}` quand `n` manque.
function withDefaults(vars?: CopyVars): CopyVars {
  const out: CopyVars = { ...DEFAULT_ADDRESS };
  for (const [k, v] of Object.entries(vars ?? {})) if (v !== undefined) out[k] = v;
  if (out.n === undefined && out.count !== undefined) out.n = out.count;
  return out;
}

// n = 0 → zero s'il existe, sinon one ; n = 1 → one ; n ≥ 2 → other (_meta.shape.plural).
// Exception : beaucoup de formes « one » écrivent « 1 » en dur (« 1 titre ») ; pour n = 0,
// on ne les prend que si elles portent {n}, sinon other (« 0 titres » plutôt que « 1 titre »).
function plural(p: Plural, n: unknown): string {
  const v = typeof n === 'number' ? n : typeof n === 'string' && n.trim() !== '' ? Number(n) : NaN;
  if (v === 0) return p.zero ?? (p.one?.includes('{n}') ? p.one : p.other);
  if (Math.abs(v) < 2) return p.one ?? p.other;
  return p.other;
}

function render(node: unknown, vars: CopyVars): string | undefined {
  if (typeof node === 'string') return fill(node, vars);
  if (typeof node === 'number') return String(node);
  if (node && typeof node === 'object' && !Array.isArray(node)) {
    if (own(node, 'text')) {
      const text = (node as { text: unknown }).text;
      return text === null ? '' : render(text, vars);
    }
    if (typeof (node as { other?: unknown }).other === 'string') return fill(plural(node as Plural, vars.n), vars);
  }
  return undefined;
}

/** Remplace chaque `{clé}` présente dans vars ; un jeton inconnu reste tel quel. */
export function fill(template: string, vars?: CopyVars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (m, k: string) => {
    const v = own(vars, k) ? vars[k] : undefined;
    return v == null ? m : String(v);
  });
}

/**
 * Texte au chemin donné, jetons remplis (adresse du Roi par défaut).
 * Clé absente ou qui n'est pas un texte (section, liste) → le chemin.
 */
export function t(path: string, vars?: CopyVars): string {
  return render(resolve(path), withDefaults(vars)) ?? path;
}

/**
 * Vrai si t(path) rend un texte du deck (renvois suivis) ; faux pour une clé absente, une section
 * ou une liste. Sert au motif `has(k) ? t(k) : repli`.
 */
export function has(path: string): boolean {
  return render(resolve(path), withDefaults()) !== undefined;
}

/**
 * Réplique déterministe : `list[seed % list.length]` dans `path.quips` (ou la liste au chemin
 * même, ex. 'quips.grumble'). null si aucune réplique. Le réglage « Répliques de Greg » est
 * appliqué par l'appelant.
 */
export function quip(path: string, seed: number, vars?: CopyVars): string | null {
  const node = resolve(path);
  const list: unknown = Array.isArray(node) ? node : own(node, 'quips') ? (node as { quips: unknown }).quips : null;
  const pool = Array.isArray(list) ? list.filter((q): q is string => typeof q === 'string') : [];
  if (!pool.length) return null;
  const s = Number.isFinite(seed) ? Math.floor(seed) : 0;
  return fill(pool[((s % pool.length) + pool.length) % pool.length], withDefaults(vars));
}
