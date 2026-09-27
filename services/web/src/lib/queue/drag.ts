/**
 * Glisser pour réordonner, accalmie et anti-doublon (DESIGN §12.5, motion.md §6.8) : calculs purs,
 * sans DOM (tests/motion.test.mjs). Le glisser lui-même : components/Queue/useQueueDrag.ts.
 */

/** Le glisser part de la poignée ou de la miniature, après 4 px (un clic reste un clic). */
export const DRAG_THRESHOLD = 4;
/** Défilement automatique : à moins de 50 px d'un bord, jusqu'à 25 px par image (quadratique). */
export const EDGE = 50;
export const MAX_SCROLL = 25;
/** Accalmie : 400 ms, ou le pointeur bouge de plus de 3 px. */
export const SETTLE_MS = 400;
export const SETTLE_PX = 3;
/** Un même titre n'est joué qu'une fois en 500 ms. */
export const DEDUPE_MS = 500;

/** Élastique au-delà des bords : r(x) = x·dim·c / (dim + c·x), au plus ~dim px. */
export function rubber(over: number, dim = 24, c = 0.55): number {
  return (over * dim * c) / (dim + c * over);
}

/** Décalage de la ligne saisie (px), borné à la liste avec l'élastique. `tops` : offsetTop des lignes. */
export function clampOffset(raw: number, tops: readonly number[], from: number): number {
  const minY = tops[0] - tops[from];
  const maxY = tops[tops.length - 1] - tops[from];
  if (raw < minY) return minY - rubber(minY - raw);
  if (raw > maxY) return maxY + rubber(raw - maxY);
  return raw;
}

/** Rang visé : là où tombe le centre de la ligne saisie, en pas de ligne. */
export function targetIndex(tops: readonly number[], from: number, y: number, step: number): number {
  const center = tops[from] - tops[0] + y + step / 2;
  return Math.max(0, Math.min(tops.length - 1, Math.floor(center / step)));
}

/** Les autres lignes s'écartent d'un pas pour faire la place. */
export function shiftFor(i: number, from: number, to: number, step: number): number {
  if (from < i && i <= to) return -step;
  if (to <= i && i < from) return step;
  return 0;
}

/** Vitesse du défilement automatique (px par image, négatif vers le haut). */
export function autoScrollSpeed(py: number, top: number, bottom: number, edge = EDGE, max = MAX_SCROLL): number {
  const t = py - top;
  const b = bottom - py;
  if (t < edge) return -Math.pow(1 - Math.max(0, t) / edge, 2) * max;
  if (b < edge) return Math.pow(1 - Math.max(0, b) / edge, 2) * max;
  return 0;
}

/** Durée du dépôt (react-beautiful-dnd) : 330 → 550 ms selon la distance ; ×0,6 pour une annulation. */
export function dropDuration(dist: number, cancel: boolean): number {
  return (0.33 + 0.22 * Math.min(1, Math.abs(dist) / 1500)) * 1000 * (cancel ? 0.6 : 1);
}

/** Ancre du déplacement : le titre qui suivra la ligne déposée au rang `to` (null : en fin de file). */
export function dropAnchor(keys: readonly string[], key: string, to: number): string | null {
  const rest = keys.filter((k) => k !== key);
  rest.splice(to, 0, key);
  return rest[to + 1] ?? null;
}

/**
 * Accalmie : après un changement qui fait glisser des lignes sous un pointeur immobile (retrait, jouer
 * maintenant, en suivant, dépôt), clics, doubles clics et puces attendent : 400 ms, ou que le pointeur
 * bouge de plus de 3 px.
 */
export function createSettle() {
  let until = 0;
  let origin: [number, number] | null = null;
  return {
    start(now: number): void { until = now + SETTLE_MS; origin = null; },
    /** Mouvement du pointeur ; vrai s'il met fin à l'accalmie. */
    move(x: number, y: number, now: number): boolean {
      if (now >= until) return false;
      if (!origin) { origin = [x, y]; return false; }
      if (Math.hypot(x - origin[0], y - origin[1]) <= SETTLE_PX) return false;
      until = 0;
      return true;
    },
    active: (now: number): boolean => now < until,
  };
}

/** Anti-doublon : vrai si ce titre vient d'être joué (double-clic suivi d'Entrée, triple clic). */
export function createDedupe(ms = DEDUPE_MS) {
  let last: { key: string; at: number } | null = null;
  return (key: string, now: number): boolean => {
    if (last && last.key === key && now - last.at < ms) return true;
    last = { key, at: now };
    return false;
  };
}
