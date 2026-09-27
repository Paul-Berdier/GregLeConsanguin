/**
 * Le Couronnement (spec §5, DESIGN §5 et §12.6, motion.md §6.10) : calculs purs (tests/coronation.test.mjs).
 * La miniature vole de sa ligne à la scène (--ease-drawer échantillonnée en 13 images clés de transform).
 */
export type Box = { left: number; top: number; width: number; height: number };
export type Via = 'pointer' | 'key';
export type CrownMode = 'flight' | 'fallback' | 'quick' | 'reduced';
/** Délais et durées (ms) ; shift : translation des légendes (px, 0 = fondu) ; roseAt : rallumage de la rosace. */
export type CrownPlan = { titleDelay: number; metaDelay: number; exitMs: number; enterMs: number; shift: number;
  posterMs: number; roseAt: number; roseFade: number; glintAt: number | null };
export type Order = { target: string; via: Via; at: number };

export const FLIGHT_MS = 420;                    // --dur-flight
export const AFTER_CEREMONY_MS = FLIGHT_MS + 80; // le Héraut parle une fois la couronne posée
export const QUICK_WINDOW_MS = 1500;
export const ORDER_TTL_MS = 4000;
export const BUSY_MS = 1300;                     // la rosace ne peint rien d'avance pendant la cérémonie
export const NIGHT_ROSE_FADE_MS = 240;           // arrêt : la lune entre en 240 ms (DESIGN §12.6)
export const NEXT = '@next';                     // « le suivant » : sa clé n'est connue qu'au changement

/** Courbe de Bézier CSS → fonction du temps, par dichotomie. */
export function bezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const at = (t: number, a: number, b: number): number => 3 * (1 - t) * (1 - t) * t * a + 3 * (1 - t) * t * t * b + t * t * t;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0, hi = 1;
    for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; if (at(m, x1, x2) < x) lo = m; else hi = m; }
    return at((lo + hi) / 2, y1, y2);
  };
}
export const easeDrawer = bezier(0.32, 0.72, 0, 1);
const round = (v: number, d: number): number => Math.round(v * 10 ** d) / 10 ** d;

/** Fantôme de la taille de la scène (`to`, origine 0 0), réduit sur la pochette au départ : net à l'arrivée. Joué en `linear`. */
export function flightFrames(from: Box, to: Box, steps = 12): { transform: string; offset: number }[] {
  const s0 = from.width / to.width, out: { transform: string; offset: number }[] = [];
  for (let i = 0; i <= steps; i++) {
    const p = easeDrawer(i / steps);
    const x = from.left + (to.left - from.left) * p, y = from.top + (to.top - from.top) * p, s = s0 + (1 - s0) * p;
    out.push({ transform: `translate(${round(x, 2)}px, ${round(y, 2)}px) scale(${round(s, 4)})`, offset: round(i / steps, 4) });
  }
  return out;
}

/** Verticalement, au moins la moitié de `r` dans `c` (motion.md §6.10) ; l'axe horizontal est à l'appelant. */
export function visibleIn(r: Box, c: Box): boolean {
  return r.width > 0 && r.height > 0 && r.top >= c.top - r.height / 2 && r.top + r.height <= c.top + c.height + r.height / 2;
}
export const boxOf = (el: { getBoundingClientRect(): { left: number; top: number; width: number; height: number } }): Box => {
  const b = el.getBoundingClientRect();
  return { left: b.left, top: b.top, width: b.width, height: b.height };
};

export function crownMode(o: { via: Via | null; sinceLast: number; reduced: boolean; canFly: boolean; fromNight: boolean }): CrownMode {
  if (o.reduced) return 'reduced';
  if (o.fromNight) return 'fallback';
  if (o.sinceLast < QUICK_WINDOW_MS || o.via !== 'pointer') return 'quick';
  return o.canFly ? 'flight' : 'fallback';
}

const PLANS: Record<CrownMode, CrownPlan> = {
  flight: { titleDelay: 160, metaDelay: 200, exitMs: 180, enterMs: 280, shift: 8, posterMs: 0, roseAt: FLIGHT_MS, roseFade: 900, glintAt: FLIGHT_MS },
  fallback: { titleDelay: 160, metaDelay: 200, exitMs: 180, enterMs: 280, shift: 8, posterMs: 420, roseAt: 0, roseFade: 900, glintAt: 380 },
  quick: { titleDelay: 0, metaDelay: 40, exitMs: 180, enterMs: 280, shift: 8, posterMs: 210, roseAt: 0, roseFade: 450, glintAt: null },
  reduced: { titleDelay: 0, metaDelay: 0, exitMs: 150, enterMs: 150, shift: 0, posterMs: 200, roseAt: 0, roseFade: 300, glintAt: null },
};
/** Une copie : l'appelant peut la retoucher sans altérer les cérémonies suivantes. */
export const crownPlan = (m: CrownMode): CrownPlan => ({ ...PLANS[m] });

/** Le dernier ordre du Roi (un titre, ou NEXT), repris une fois par le changement qu'il annonçait. */
export function createOrders(ttl = ORDER_TTL_MS) {
  let last: Order | null = null;
  return {
    mark(target: string, via: Via, now: number): void { last = { target, via, at: now }; },
    take(key: string, prevNext: string | null, now: number): Order | null {
      const i = last;
      if (!i || now - i.at > ttl) { last = null; return null; }
      if (i.target !== key && !(i.target === NEXT && prevNext === key)) return null;
      last = null;
      return i;
    },
  };
}
export const kingOrders = createOrders();
