/**
 * La rosace, en coordonnées unitaires (centre 0,0, y vers le bas, R = 1 = rayon du vitrail).
 * Repris de proto-gothique/work/refine/rose-worker.js (lignes 8–192) sans changer une valeur :
 * la pierre Blender (public/gothique/stone-rose-2048.webp) a été calculée depuis CETTE géométrie.
 * Pur, sans import runtime (tests/rose-geometry.test.mjs).
 */

export type Pt = [number, number];
export type Poly = Pt[];
export type BBox = [number, number, number, number];
export type GlassRole = 'ground' | 'border' | 'figure' | 'accent' | 'pale' | 'ringA' | 'ringB';
export type Cell = { poly: Poly; role: GlassRole; bb: BBox; v: [number, number, number, number, number]; edge?: boolean; paint?: boolean };
export type Motif = 'crown' | 'fleur' | 'rose';
export type Medallion = { x: number; y: number; r: number; rimIn: number; cells: Cell[]; motif: Motif };
export type OpeningKind = 'ring' | 'lancet' | 'foil' | 'roundel' | 'heart';
export type Opening = { poly: Poly; kind: OpeningKind; index?: number; t1?: number; t2?: number; a?: number; cells: Cell[]; med?: Medallion };

export const TAU = Math.PI * 2;
export const GEO = {
  extent: 1.06,                 // carré peint = [-extent, extent]² (disque de pierre + moulure)
  stone: 1.045,                 // bord extérieur du disque de pierre
  ringIn: 0.892, ringOut: 0.958, // anneau des 48 panneaux : l'horloge du morceau
  panes: 48, paneGap: 0.0105,   // meneau de pierre entre deux panneaux
  beadR: 0.8755, beads: 96,     // perles sculptées (pierre seule)
  lanIn: 0.33, lanH: 0.655, lanTip: 0.845, lanGap: 0.038,
  medR: 0.565, medRad: 0.092,   // médaillon peint dans chaque lancette
  qfR: 0.8, qfLobe: 0.026,      // quadrilobes des écoinçons
  rosR: 0.235, rosRad: 0.066,   // couronne intérieure de rondels
  heart: 0.13,
} as const;
export const PANE_STEP = TAU / GEO.panes;
export const PANE_A0 = -Math.PI / 2 - PANE_STEP / 2;   // un panneau centré en haut

export function rng(seed: number): () => number {
  let s = (seed >>> 0) % 2147483647 || 1;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}
export const clamp = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));

export function clipPoly(poly: Poly, f: (x: number, y: number) => number): Poly {
  const out: Poly = [];
  for (let k = 0; k < poly.length; k++) {
    const a = poly[k], b = poly[(k + 1) % poly.length], fa = f(a[0], a[1]), fb = f(b[0], b[1]);
    if (fa <= 0) out.push(a);
    if ((fa < 0) !== (fb < 0) && fa !== fb) { const t = fa / (fa - fb); out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]); }
  }
  return out;
}
export function inPoly(pt: Pt, poly: Poly): boolean {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}
function segDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy || 1;
  const t = clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2, 0, 1);
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}
function edgeDist(p: Pt, poly: Poly): number {
  let d = Infinity;
  for (let i = 0; i < poly.length; i++) d = Math.min(d, segDist(p, poly[i], poly[(i + 1) % poly.length]));
  return d;
}
function voronoi(seeds: Pt[], poly: Poly): Poly[] {
  return seeds.map((p, i) => {
    let cell = poly.slice();
    for (let j = 0; j < seeds.length && cell.length > 2; j++) {
      if (j === i) continue;
      const q = seeds[j];
      const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2, nx = q[0] - p[0], ny = q[1] - p[1];
      cell = clipPoly(cell, (x, y) => (x - mx) * nx + (y - my) * ny);
    }
    return cell;
  });
}
export function bbox(poly: Poly): BBox {
  const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
export function arcPts(cx: number, cy: number, r: number, t1: number, t2: number, n: number): Poly {
  const o: Poly = [];
  for (let i = 0; i <= n; i++) { const t = t1 + ((t2 - t1) * i) / n; o.push([cx + Math.cos(t) * r, cy + Math.sin(t) * r]); }
  return o;
}
export function circlePoly(cx: number, cy: number, r: number, n = 48): Poly { return arcPts(cx, cy, r, 0, TAU, n).slice(0, n); }

function lancetPoly(a: number, w: number): Poly {
  const { lanIn: r1, lanH: rh, lanTip: r2 } = GEO;
  const P = (r: number, t: number): Pt => [Math.cos(t) * r, Math.sin(t) * r];
  const q = (p0: Pt, c: Pt, p1: Pt, n: number): Poly => {
    const o: Poly = [];
    for (let i = 1; i <= n; i++) { const t = i / n, u = 1 - t; o.push([u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1]]); }
    return o;
  };
  const L0 = P(r1, a - w), L1 = P(rh, a - w), T = P(r2, a), R1 = P(rh, a + w);
  const cL = P(rh + (r2 - rh) * 0.62, a - w * 0.98), cR = P(rh + (r2 - rh) * 0.62, a + w * 0.98);
  const pts: Poly = [L0];
  for (let i = 1; i <= 6; i++) { const r = r1 + ((rh - r1) * i) / 6; pts.push(P(r, a - w)); }
  pts.push(...q(L1, cL, T, 12), ...q(T, cR, R1, 12));
  for (let i = 5; i >= 0; i--) { const r = r1 + ((rh - r1) * i) / 6; pts.push(P(r, a + w)); }
  pts.push(...arcPts(0, 0, r1, a + w, a - w, 6).slice(1, -1));
  return pts;
}
function quatrefoilPoly(cx: number, cy: number, rl: number, rot: number): Poly {
  const d = rl * 0.92, pts: Poly = [];
  const t = d * Math.SQRT1_2 + Math.sqrt(Math.max(0, rl * rl - d * d * 0.5));
  for (let i = 0; i < 4; i++) {
    const phi = rot + (i * Math.PI) / 2, lx = cx + Math.cos(phi) * d, ly = cy + Math.sin(phi) * d;
    const pa: Pt = [cx + Math.cos(phi - Math.PI / 4) * t, cy + Math.sin(phi - Math.PI / 4) * t];
    const pb: Pt = [cx + Math.cos(phi + Math.PI / 4) * t, cy + Math.sin(phi + Math.PI / 4) * t];
    const a1 = Math.atan2(pa[1] - ly, pa[0] - lx);
    let a2 = Math.atan2(pb[1] - ly, pb[0] - lx);
    while (a2 < a1) a2 += TAU;
    pts.push(...arcPts(lx, ly, rl, a1, a2, 14).slice(0, -1));
  }
  return pts;
}

/** Toutes les ouvertures et leurs pièces de verre (des rôles, pas des couleurs : une géométrie sert toutes les palettes). */
export function buildGeometry(seed = 23): Opening[] {
  const rnd = rng(seed);
  const openings: Opening[] = [];
  const cellOf = (poly: Poly, role: GlassRole, extra: Partial<Cell> = {}): Cell =>
    ({ poly, role, bb: bbox(poly), v: [rnd(), rnd(), rnd(), rnd(), rnd()], ...extra });
  // 1. l'horloge : 48 panneaux en dents de scie
  for (let i = 0; i < GEO.panes; i++) {
    const r1 = GEO.ringIn, r2 = GEO.ringOut;
    const t1 = PANE_A0 + i * PANE_STEP, t2 = t1 + PANE_STEP;
    const g1 = GEO.paneGap / 2 / r1, g2 = GEO.paneGap / 2 / r2;
    const outer = arcPts(0, 0, r2, t1 + g2, t2 - g2, 5), inner = arcPts(0, 0, r1, t2 - g1, t1 + g1, 5);
    const poly = [...outer, ...inner];
    const A: Poly = [inner[inner.length - 1], ...outer];
    const B: Poly = [inner[inner.length - 1], outer[outer.length - 1], ...inner.slice(0, -1)];
    openings.push({ poly, kind: 'ring', index: i, t1, t2, cells: [cellOf(A, 'ringA'), cellOf(B, i % 4 === 0 ? 'figure' : 'ringB')] });
  }
  // 2. seize lancettes en mosaïque : petites pièces de bordure, grandes pièces de fond, un médaillon
  const N = 16, step = TAU / N, a0 = -Math.PI / 2;
  const MOTIFS: Motif[] = ['crown', 'fleur', 'rose', 'fleur'];
  for (let k = 0; k < N; k++) {
    const a = a0 + k * step, w = step / 2 - (GEO.lanGap / 2 / GEO.lanIn) * 0.9;
    const poly = lancetPoly(a, w);
    const med: Pt = [Math.cos(a) * GEO.medR, Math.sin(a) * GEO.medR];
    const seeds: Pt[] = [], kinds: ('edge' | 'ground')[] = [];
    const far = (p: Pt, s: number) => seeds.every((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) > s);
    let perim = 0;
    const segs: [Pt, Pt, number][] = [];
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      const l = Math.hypot(q[0] - p[0], q[1] - p[1]);
      segs.push([p, q, l]); perim += l;
    }
    const nb = Math.round(perim / 0.034);
    let acc = 0, si = 0;
    for (let j = 0; j < nb; j++) {
      const target = ((j + 0.5) * perim) / nb;
      while (si < segs.length - 1 && acc + segs[si][2] < target) { acc += segs[si][2]; si++; }
      const [p, q, l] = segs[si], t = (target - acc) / l;
      const x = p[0] + (q[0] - p[0]) * t, y = p[1] + (q[1] - p[1]) * t;
      const nx = -(q[1] - p[1]) / l, ny = (q[0] - p[0]) / l;
      let s: Pt = [x + nx * 0.017, y + ny * 0.017];
      if (!inPoly(s, poly)) s = [x - nx * 0.017, y - ny * 0.017];
      if (inPoly(s, poly) && far(s, 0.02)) { seeds.push(s); kinds.push('edge'); }
    }
    const bb = bbox(poly);
    for (let tries = 0; tries < 2400; tries++) {
      const s: Pt = [bb[0] + rnd() * (bb[2] - bb[0]), bb[1] + rnd() * (bb[3] - bb[1])];
      if (!inPoly(s, poly)) continue;
      if (Math.hypot(s[0] - med[0], s[1] - med[1]) < GEO.medRad + 0.03) continue;
      if (edgeDist(s, poly) < 0.031) continue;
      const sp = 0.04 + rnd() * 0.024;
      if (far(s, sp)) { seeds.push(s); kinds.push('ground'); }
    }
    const polys = voronoi(seeds, poly);
    let edgeN = 0;
    const cells: Cell[] = [];
    polys.forEach((pl, i) => {
      if (pl.length < 3) return;
      let role: GlassRole;
      if (kinds[i] === 'edge') role = edgeN++ % 4 === 3 ? 'pale' : 'border';
      else { const u = rnd(); role = u < 0.16 ? 'accent' : u < 0.22 ? 'figure' : 'ground'; }
      cells.push(cellOf(pl, role, { edge: kinds[i] === 'edge' }));
    });
    const mcells: Cell[] = [];
    const mr = GEO.medRad, rimIn = mr * 0.78, nrim = 10;
    for (let j = 0; j < nrim; j++) {
      const t1 = (j * TAU) / nrim + a, t2 = ((j + 1) * TAU) / nrim + a;
      mcells.push(cellOf([...arcPts(med[0], med[1], mr, t1, t2, 4), ...arcPts(med[0], med[1], rimIn, t2, t1, 4)], j % 2 ? 'figure' : 'border'));
    }
    const inner = circlePoly(med[0], med[1], rimIn, 40);
    const half1 = clipPoly(inner, (x, y) => (x - med[0]) * Math.cos(a) + (y - med[1]) * Math.sin(a) - rimIn * 0.42);
    const half2 = clipPoly(inner, (x, y) => -((x - med[0]) * Math.cos(a) + (y - med[1]) * Math.sin(a) - rimIn * 0.42));
    mcells.push(cellOf(half2, 'figure', { paint: true }), cellOf(half1, k % 2 ? 'accent' : 'ground', { paint: true }));
    openings.push({ poly, kind: 'lancet', index: k, a, cells, med: { x: med[0], y: med[1], r: mr, rimIn, cells: mcells, motif: MOTIFS[k % 4] } });
    // 3. quadrilobe de l'écoinçon : lobes vitrés, plombs en croix
    const qa = a + step / 2, qx = Math.cos(qa) * GEO.qfR, qy = Math.sin(qa) * GEO.qfR;
    const qpoly = quatrefoilPoly(qx, qy, GEO.qfLobe, qa);
    const qcells = [0, 1, 2, 3].map((l) => {
      const d1 = qa + (l * Math.PI) / 2 - Math.PI / 4, d2 = d1 + Math.PI / 2;
      let pl = clipPoly(qpoly, (x, y) => -((x - qx) * -Math.sin(d1) + (y - qy) * Math.cos(d1)));
      pl = clipPoly(pl, (x, y) => (x - qx) * -Math.sin(d2) + (y - qy) * Math.cos(d2));
      return cellOf(pl, l % 2 ? 'figure' : 'border');
    });
    qcells.push(cellOf(circlePoly(qx, qy, GEO.qfLobe * 0.42, 16), 'pale'));
    openings.push({ poly: qpoly, kind: 'foil', cells: qcells });
  }
  // 4. rondels intérieurs et cœur
  for (let k = 0; k < 8; k++) {
    const a = -Math.PI / 2 + (k * Math.PI) / 4 + Math.PI / 8, x = Math.cos(a) * GEO.rosR, y = Math.sin(a) * GEO.rosR, rr = GEO.rosRad;
    const poly = circlePoly(x, y, rr, 40);
    const cells = [0, 1, 2, 3].map((l) => cellOf([[x, y], ...arcPts(x, y, rr, a + (l * Math.PI) / 2 + Math.PI / 4, a + ((l + 1) * Math.PI) / 2 + Math.PI / 4, 8)], l % 2 ? 'figure' : 'ground'));
    cells.push(cellOf(circlePoly(x, y, rr * 0.38, 20), k % 2 ? 'border' : 'pale'));
    openings.push({ poly, kind: 'roundel', cells });
  }
  {
    const r = GEO.heart, poly = circlePoly(0, 0, r, 64);
    const cells: Cell[] = [];
    for (let l = 0; l < 8; l++) cells.push(cellOf([[0, 0], ...arcPts(0, 0, r, (l * TAU) / 8 - Math.PI / 2, ((l + 1) * TAU) / 8 - Math.PI / 2, 8)], l % 2 ? 'border' : 'ground'));
    cells.push(cellOf(circlePoly(0, 0, r * 0.36, 24), 'figure'));
    openings.push({ poly, kind: 'heart', cells });
  }
  return openings;
}
