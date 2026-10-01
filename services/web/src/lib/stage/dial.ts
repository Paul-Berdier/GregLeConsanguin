/**
 * L'horloge : l'anneau des 48 panneaux du vitrail, en lecture seule (le bot n'a pas de `seek`).
 * Seul l'arc visible au-dessus du linteau compte (19 panneaux à c = 0,3, 11 à c = 0,64). Le masque
 * change une fois par panneau (environ toutes les 11 s pour 3 min 30), jamais à chaque image.
 * Repris de `Dial` (proto-gothique/work/refine/src/app.js, lignes 309–337). Pur, sans import runtime
 * (tests/dial.test.mjs).
 */

export const PANES = 48;
export const PANE_DEG = 360 / PANES;   // 7,5°
export const RING_MID = 0.925;         // rayon médian de l'anneau, en R

export type DialGeometry = {
  K: number;   // panneaux de part et d'autre du panneau du haut
  n: number;   // panneaux visibles = 2K + 1
  a0: number;  // angle (degrés, 0 = en haut, sens horaire) du bord gauche du premier panneau visible
};

export function dialGeometry(c: number): DialGeometry {
  const phi = (Math.acos(Math.min(0.99, c / RING_MID)) * 180) / Math.PI;
  const K = Math.max(3, Math.floor((phi - 2) / PANE_DEG));
  return { K, n: 2 * K + 1, a0: -K * PANE_DEG - PANE_DEG / 2 };
}

/** Panneau courant (0…n−1) ; −1 sans durée connue. */
export function clockPane(pos: number, dur: number, n: number): number {
  if (!(dur > 0) || !Number.isFinite(pos)) return -1;
  const p = Math.min(0.9999, Math.max(0, pos / dur));
  return Math.floor(p * n);
}

/** Angles des masques coniques : `--p0` (panneaux déjà joués) et `--p1` (fin du panneau courant). */
export function paneMask(i: number): { p0: number; p1: number } {
  return { p0: Math.max(0, i) * PANE_DEG, p1: i < 0 ? 0 : (i + 1) * PANE_DEG };
}

/** Panneau sous le pointeur ; dx, dy : écart au centre de la rose (px, y vers le bas). */
export function paneAtPoint(dx: number, dy: number, dial: DialGeometry): number {
  const ang = (Math.atan2(dx, -dy) * 180) / Math.PI;
  return Math.max(0, Math.min(dial.n - 1, Math.floor((ang - dial.a0) / PANE_DEG)));
}

/** Temps (s) au début d'un panneau, pour l'info-bulle de survol. */
export function paneTime(i: number, n: number, dur: number): number {
  return dur > 0 ? (i / n) * dur : 0;
}

/** Tracé SVG de la zone de survol le long de l'arc visible (viewBox en unités R, centre 0,0). */
export function hitArcPath(dial: DialGeometry): string {
  const a1 = ((dial.a0 - 90) * Math.PI) / 180, a2 = ((dial.a0 + dial.n * PANE_DEG - 90) * Math.PI) / 180;
  const p = (a: number) => `${(Math.cos(a) * RING_MID).toFixed(4)} ${(Math.sin(a) * RING_MID).toFixed(4)}`;
  return `M${p(a1)}A${RING_MID} ${RING_MID} 0 0 1 ${p(a2)}`;
}

/** Durée dite (lecteurs d'écran) : « 45 s », « 1 min 32 », « 1 h 02 min 05 ». Vide si inconnue. */
export function fmtSpoken(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return '';
  const s = Math.floor(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const ss = String(r).padStart(2, '0');
  if (h) return `${h} h ${String(m).padStart(2, '0')} min ${ss}`;
  if (m) return `${m} min ${ss}`;
  return `${r} s`;
}
