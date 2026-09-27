/**
 * Mise en page de la scène : tout découle d'un nombre, R, le rayon du vitrail (DESIGN §12.4).
 * Repris de `layout()` (proto-gothique/work/refine/src/app.js, lignes 364–406) : même algorithme,
 * mêmes constantes. Pur, sans import runtime (tests/stageLayout.test.mjs).
 *
 * 1. Couronne pleine (c = 0,3 : 70 % du rayon visible) aussi grande que possible.
 * 2. Si la vidéo passerait sous 560 px : on abaisse d'abord la couronne (c jusqu'à 0,64).
 * 3. Seulement ensuite, on réduit la vidéo.
 */

export const EXT = 1.06;          // demi-côté du carré peint (disque de pierre + moulure), en R
export const RHO = 0.52;          // R = RHO × largeur de la vidéo : la base de la rose touche le linteau
export const RING_TO = -0.2;      // bas du recadrage de l'anneau des panneaux (en R, depuis le centre)
export const C_FULL = 0.3;        // corde de coupe : 70 % du rayon visible
export const C_MAX = 0.64;        // couronne la plus basse avant de réduire la vidéo
export const C_MOBILE = 0.42;
export const VIDEO_PREF = 560;    // largeur de vidéo sous laquelle on abaisse d'abord la couronne
export const SPRING_ROOM = 72;    // place d'un libellé de temps à chaque naissance de l'arc
export const MOBILE_MAX = 900;    // une colonne (même seuil que la CSS)
export const R_MIN = 110;
export const R_MOBILE_MAX = 260;
export const BELOW_GAP = 6;

export type StageInput = {
  colW: number;       // largeur intérieure de la colonne de scène (clientWidth)
  colH: number;       // hauteur intérieure de la colonne de scène (clientHeight)
  belowH: number;     // hauteur du bloc sous le portail (titre, transport, note)
  viewportW: number;  // innerWidth
};
export type StageLayout = {
  mobile: boolean;
  R: number;          // rayon du vitrail (px)
  c: number;          // hauteur de la corde de coupe, en R au-dessus du centre
  vw: number;         // largeur de la vidéo (px)
  f: number;          // épaisseur des piédroits de pierre (px)
  crown: number;      // hauteur de rose visible au-dessus du linteau (px)
  cR: number;         // c·R arrondi (px)
  heart: number;      // diamètre de l'oculus (couronne, portrait) la nuit (px)
  ringH: number;      // hauteur du recadrage de l'anneau (px)
  clipDay: number;    // rognage bas du vitrail le jour (px)
  clipNight: number;  // rognage bas du vitrail la nuit (px)
  springs: 'spring' | 'row';  // temps aux naissances de l'arc, ou en ligne sous le portail
};

export const fOf = (R: number): number => Math.max(10, Math.round(0.05 * R));

export function solveStageLayout({ colW, colH, belowH, viewportW }: StageInput): StageLayout {
  const mobile = viewportW <= MOBILE_MAX;
  let R: number, c: number, vw: number;
  if (mobile) {
    c = C_MOBILE;
    R = Math.floor(Math.min(colW / 2.12, R_MOBILE_MAX));
    vw = Math.round(colW - 2 * fOf(R));
  } else {
    const H = colH - belowH - BELOW_GAP;
    const total = (r: number, cc: number) => r * (EXT - cc) + 2 * fOf(r) + ((r / RHO) * 9) / 16;
    const solveR = (cc: number) => {
      let lo = 80, hi = 1200;
      for (let i = 0; i < 32; i++) { const m = (lo + hi) / 2; if (total(m, cc) <= H) lo = m; else hi = m; }
      return lo;
    };
    const Rw = (colW - 2 * SPRING_ROOM) / 2.12;   // la rose et la place des deux libellés de temps
    c = C_FULL;
    R = Math.min(solveR(C_FULL), Rw);
    const Rpref = VIDEO_PREF * RHO;
    if (R < Rpref && Rw > R) {
      R = Math.min(Rw, Rpref);
      c = EXT - (H - 2 * fOf(R) - ((R / RHO) * 9) / 16) / R;
      if (c > C_MAX) { c = C_MAX; R = solveR(C_MAX); }
      c = Math.max(C_FULL, c);
    }
    R = Math.max(R_MIN, Math.floor(R));
    vw = Math.round(R / RHO);
  }
  const f = fOf(R), crown = Math.round(R * (EXT - c));
  return {
    mobile, R, c, vw, f, crown,
    cR: Math.round(c * R),
    heart: Math.round(Math.max(84, Math.min(160, R * 0.46))),
    ringH: Number((R * (EXT + RING_TO)).toFixed(1)),
    clipDay: Number((2.12 * R - (crown + f * 0.5)).toFixed(1)),
    clipNight: Number((0.11 * R).toFixed(1)),
    springs: mobile || colW < 2.12 * R + 2 * SPRING_ROOM ? 'row' : 'spring',
  };
}

/** Variables CSS posées sur `.stage` (stage.css, rose.css, portal.css, now.css les lisent). */
export function stageCssVars(l: StageLayout): Record<string, string> {
  return {
    '--R': `${l.R}px`, '--vw': `${l.vw}px`, '--f': `${l.f}px`, '--crown': `${l.crown}px`, '--cR': `${l.cR}px`,
    '--heart': `${l.heart}px`, '--ring-h': `${l.ringH}px`, '--clip-day': `${l.clipDay}px`, '--clip-night': `${l.clipNight}px`,
  };
}

/** Même mise en page à l'écran ? (évite un rendu React quand l'observateur se réveille pour rien) */
export function sameLayout(a: StageLayout | null, b: StageLayout | null): boolean {
  return !!a && !!b && a.R === b.R && a.c === b.c && a.vw === b.vw && a.springs === b.springs && a.mobile === b.mobile;
}
