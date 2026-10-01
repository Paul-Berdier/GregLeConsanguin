/**
 * État de la scène et textes qui en découlent (spec §4 « Nuit », casting du Roi).
 * Pur, sans import runtime (tests/scene.test.mjs) : les composants passent les clés rendues à `t()`.
 */

/** Jour : un titre joue (ou est en pause). Nuit : rien en lecture, chargement, ou déconnecté. */
export type Scene = 'day' | 'empty' | 'loading' | 'out';
export type NightKind = Exclude<Scene, 'day'>;

export function stageScene(s: { booted: boolean; loggedIn: boolean; hasCurrent: boolean }): Scene {
  if (!s.booted) return 'loading';
  if (!s.loggedIn) return 'out';
  return s.hasCurrent ? 'day' : 'empty';
}

/** Surtitre au-dessus du titre : état de lecture seulement (les répliques vont à côté). */
export function kickerKey(s: { paused: boolean; repeat: boolean }): 'now.kicker' | 'now.state.paused' | 'now.state.looping' {
  if (s.paused) return 'now.state.paused';
  return s.repeat ? 'now.state.looping' : 'now.kicker';
}

/** Qui a demandé le titre : le Roi lui-même (l'utilisateur), un courtisan, ou inconnu. */
export type Requester = { kind: 'mine' } | { kind: 'other'; name: string } | { kind: 'unknown' };

export function requesterOf(addedBy: { id?: string; name?: string } | null | undefined, meId: string | null | undefined): Requester {
  if (addedBy?.id && meId && String(addedBy.id) === String(meId)) return { kind: 'mine' };
  const name = (addedBy?.name || '').trim();
  return name ? { kind: 'other', name } : { kind: 'unknown' };
}

/** Clé du deck pour la ligne « Demandé par… » et, s'il y en a, pour la réplique du surtitre. */
export function requesterKeys(r: Requester): { plain: string; quips: string | null } {
  if (r.kind === 'mine') return { plain: 'now.order.mine.plain', quips: 'now.order.mine' };
  if (r.kind === 'other') return { plain: 'now.order.other.plain', quips: 'now.order.other' };
  return { plain: 'now.order.unknown.plain', quips: null };
}

/** Lettres latines que NFD ne décompose pas, ramenées à leur lettre de base (Øyvind → O, Łukasz → L). */
const FOLD: Record<string, string> = { Ø: 'O', Ł: 'L', Æ: 'A', Œ: 'O', Đ: 'D', Ð: 'D', Þ: 'T', Ħ: 'H', Ŧ: 'T', Ŋ: 'N' };

/**
 * Initiale du sceau du Roi : 1re lettre A–Z du pseudo, accents retirés (règle du deck `_meta.tokens.kingInitial`).
 * NFKD ramène aussi les lettres stylisées des pseudos Discord (𝓟, Ｐ) à leur lettre latine.
 * Sans lettre A–Z, la fleur de lys (`king-seal-fleur.webp`, public/licenses/LICENSES.md) remplace le repli « R »
 * de cette note du deck : un R serait l'initiale d'un autre.
 */
export function sealInitial(name: string | null | undefined): string {
  const m = (name || '').normalize('NFKD').toUpperCase().replace(/[ØŁÆŒĐÐÞĦŦŊ]/g, (ch) => FOLD[ch]).match(/[A-Z]/);
  return m ? m[0] : 'fleur';
}
export const kingSealSrc = (name: string | null | undefined): string => `/gothique/seals/king-seal-${sealInitial(name)}.webp`;

/** Graine stable d'une réplique (FNV-1a 32 bits) : la même pour un même titre, d'un rendu à l'autre. */
export function seedOf(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}
