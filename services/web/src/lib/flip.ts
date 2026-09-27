/**
 * Présence et FLIP des listes (motion.md §6.6 et §6.7) : calculs purs de hooks/useFlip.ts.
 * Pur, sans import runtime (tests/motion.test.mjs).
 */

/** Une ligne affichée : présente, ou qui s'en va (gardée le temps de sa sortie, hors du flux). */
export type Presence<T> = { key: string; item: T; leaving: boolean };

/**
 * Lignes à afficher : les éléments de `next` dans leur ordre, plus ceux qui viennent de partir, gardés juste
 * après leur ancien voisin (ils sortent en position absolue : ils n'occupent plus de place, les autres
 * referment le vide tout de suite, comme « popLayout »). Un titre revenu pendant sa sortie redevient présent.
 * Une ligne inchangée garde son objet.
 */
export function mergePresence<T>(prev: readonly Presence<T>[], next: readonly T[], keyOf: (t: T) => string): Presence<T>[] {
  const before = new Map(prev.map((p) => [p.key, p]));
  const keys = new Set<string>();
  const out: Presence<T>[] = next.map((item) => {
    const key = keyOf(item);
    keys.add(key);
    const p = before.get(key);
    return p && !p.leaving && p.item === item ? p : { key, item, leaving: false };
  });
  let anchor: string | null = null;
  for (const p of prev) {
    if (!keys.has(p.key)) {
      const at = anchor == null ? 0 : out.findIndex((e) => e.key === anchor) + 1;
      out.splice(at, 0, p.leaving ? p : { ...p, leaving: true });
    }
    anchor = p.key;
  }
  return out;
}

/** Fin de la sortie d'une ligne : elle quitte la liste (si elle n'est pas revenue entre-temps). */
export function dropLeft<T>(list: readonly Presence<T>[], key: string): Presence<T>[] {
  const i = list.findIndex((p) => p.key === key && p.leaving);
  return i < 0 ? (list as Presence<T>[]) : [...list.slice(0, i), ...list.slice(i + 1)];
}

/** Translation verticale d'une valeur calculée de `transform` (« none », matrix(), matrix3d()). */
export function translateYOf(transform: string): number {
  const m = /^matrix(3d)?\(([^)]+)\)$/.exec((transform || '').trim());
  if (!m) return 0;
  const v = m[2].split(',').map(Number);
  const y = m[1] ? v[13] : v[5];
  return Number.isFinite(y) ? y : 0;
}

/** Délai de la i-ème entrée d'une cascade (pas de `step` ms, plafonnée à `cap` lignes). */
export function staggerDelay(i: number, step: number, cap = 8): number {
  return Math.min(Math.max(0, i), cap) * step;
}

/**
 * Sortie en cascade inversée (arrêt, DESIGN §5) : de la dernière ligne à la première, `step` ms. Ici `cap` compte les
 * rangs de la cascade (0 à cap - 1, soit 140 ms au plus par défaut), quand staggerDelay plafonne l'indice lui-même (0 à cap).
 */
export function reverseStagger(i: number, n: number, step = 20, cap = 8): number {
  return Math.min(Math.max(0, n - 1 - i), cap - 1) * step;
}
