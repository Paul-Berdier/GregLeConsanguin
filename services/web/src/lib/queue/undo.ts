/**
 * Annuler un ajout ou un retrait (spec §2, non-objectifs : seuls ces deux-là). Le bot n'a pas de « remettre » :
 * - annuler l'ajout = retirer les titres apparus avec cet ajout, ceux du Roi ;
 * - annuler un retrait = rajouter le titre (il arrive en fin de file, ou à sa place de préséance), puis le
 *   déplacer à son ancienne place. Pur, sans import runtime (tests/queue-view.test.mjs).
 */
import type { Track } from '../types';

/** Clés apparues depuis `beforeKeys` et demandées par le Roi (`meId`), dans l'ordre de la file. */
export function addedKeys(beforeKeys: readonly string[], after: readonly Pick<Track, 'key' | 'addedBy'>[], meId: string): string[] {
  const before = new Set(beforeKeys);
  return after.filter((t) => !before.has(t.key) && (t.addedBy?.id ?? '') === meId).map((t) => t.key);
}

/**
 * Titre remis par « Annuler » d'un retrait : la dernière ligne nouvelle de même url, et la clé du titre devant
 * lequel la replacer (celui qui occupe son ancienne place `index` ; null : en fin de file). null si le titre
 * n'est pas revenu (refusé, quota).
 */
export function restorePlan(beforeKeys: readonly string[], after: readonly Pick<Track, 'key' | 'url'>[], url: string, index: number):
  { key: string; beforeKey: string | null } | null {
  const before = new Set(beforeKeys);
  const fresh = after.filter((t) => t.url === url && !before.has(t.key));
  const row = fresh[fresh.length - 1];
  if (!row) return null;
  const rest = after.filter((t) => t.key !== row.key);
  return { key: row.key, beforeKey: rest[Math.max(0, index)]?.key ?? null };
}
