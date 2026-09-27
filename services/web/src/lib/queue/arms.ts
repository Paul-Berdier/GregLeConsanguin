/**
 * Blason du demandeur (DESIGN §12.5) : 13 × 15 px, un champ et une pièce, jamais de rouge (le rouge veut dire
 * « retirer » dans cette interface). Tiré de l'id Discord, toujours le même pour une même personne.
 * Émaux repris de PEOPLE (proto-gothique/work/refine/src/app.js, lignes 56–65). Pur, sans import runtime.
 */
export type Division = 'pale' | 'chevron' | 'bend' | 'fess' | 'quarterly' | 'bordure';
export type Arms = { d: Division; a: string; b: string };

export const DIVISIONS: readonly Division[] = ['pale', 'chevron', 'bend', 'fess', 'quarterly', 'bordure'];
/** Champs : azur, bleu de mer, sinople, or, pourpre, sable. */
export const FIELDS = ['#3a63b8', '#2c6e86', '#2f7d46', '#c99a2e', '#7b3c8c', '#5b544b'] as const;
/** Pièces claires (sur champ sombre) ; sur l'or, la pièce est sombre. */
export const LIGHT = ['#d8b25e', '#e6dcc6', '#b8ad9b'] as const;
export const DARK = '#2a241d';

// FNV-1a 32 bits (même hachage que seedOf, lib/stage/scene.ts ; recopié : un module pur n'importe rien)
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}

export function armsOf(id: string | null | undefined): Arms {
  const h = hash(String(id || '?'));
  const a = FIELDS[h % FIELDS.length];
  const d = DIVISIONS[(h >>> 8) % DIVISIONS.length];
  const b = a === '#c99a2e' ? DARK : LIGHT[(h >>> 16) % LIGHT.length];
  return { d, a, b };
}

/** Contour de l'écu (viewBox 0 0 13 15) : sert aussi de clipPath. */
export const SHIELD_PATH = 'M1 1h11v6c0 3.5-2.7 5.8-5.5 7C3.7 12.8 1 10.5 1 7z';
