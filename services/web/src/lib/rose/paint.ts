/**
 * Peinture d'une fenêtre sur OffscreenCanvas (dans le worker). Repris de
 * proto-gothique/work/refine/rose-worker.js (lignes 274–494) sans changer une valeur.
 * Contextes 2D logiciels (`willReadFrequently`) : la peinture ne concurrence jamais le GPU du compositeur.
 */
import { buildGeometry, circlePoly, GEO, rng, TAU } from './geometry';
import type { BBox, Cell, Medallion, Motif, Opening, Poly } from './geometry';
import { hslCss } from './palette';
import type { Palette } from './palette';

type Ctx = OffscreenCanvasRenderingContext2D;
type PCell = Cell & { path: Path2D; bbp: BBox };
type PMed = Medallion & { px: number; py: number; pr: number; prIn: number; path: Path2D; cells: PCell[] };
type POpening = Omit<Opening, 'cells' | 'med'> & { path: Path2D; cells: PCell[]; med?: PMed };
type Resolved = { openings: POpening[]; all: Path2D; ring: Path2D };

function ctx(c: OffscreenCanvas): Ctx {
  const x = c.getContext('2d', { willReadFrequently: true });
  if (!x) throw new Error('OffscreenCanvas 2D indisponible');
  return x;
}

let TEX: OffscreenCanvas | null = null;
/** Verre « cylindre » : bruit flouté, stries, bulles d'air. Peint une fois. */
function glassTexture(): OffscreenCanvas {
  if (TEX) return TEX;
  const n = new OffscreenCanvas(64, 64), nx = ctx(n), id = nx.createImageData(64, 64);
  const r = rng(7);
  for (let i = 0; i < id.data.length; i += 4) { const v = 90 + r() * 110; id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 255; }
  nx.putImageData(id, 0, 0);
  const c = new OffscreenCanvas(512, 512), x = ctx(c);
  x.filter = 'blur(5px)'; x.drawImage(n, -16, -16, 544, 544); x.filter = 'none';
  x.globalAlpha = 0.09;
  for (let i = 0; i < 90; i++) {
    x.strokeStyle = r() > 0.5 ? '#fff' : '#000'; x.lineWidth = 1 + r() * 5; x.beginPath();
    const y = r() * 512;
    x.moveTo(0, y); x.bezierCurveTo(170, y + (r() - 0.5) * 60, 340, y + (r() - 0.5) * 60, 512, y + (r() - 0.5) * 40); x.stroke();
  }
  x.globalAlpha = 0.22; x.fillStyle = '#fff';
  for (let i = 0; i < 140; i++) { x.beginPath(); x.ellipse(r() * 512, r() * 512, 0.6 + r() * 1.4, 0.4 + r() * 0.8, r() * 3, 0, TAU); x.fill(); }
  x.globalAlpha = 1; TEX = c; return c;
}

function toPath(poly: Poly, S: number, cx: number, cy: number): Path2D {
  const p = new Path2D();
  poly.forEach(([x, y], i) => (i ? p.lineTo(cx + x * S, cy + y * S) : p.moveTo(cx + x * S, cy + y * S)));
  p.closePath();
  return p;
}
const resolveCell = (c: Cell, S: number, cx: number, cy: number): PCell =>
  ({ ...c, path: toPath(c.poly, S, cx, cy), bbp: [cx + c.bb[0] * S, cy + c.bb[1] * S, cx + c.bb[2] * S, cy + c.bb[3] * S] });

let BASE: Opening[] | null = null;
const GEOM_CACHE = new Map<string, Resolved>();
/** Géométrie résolue en Path2D pour une échelle de pixels (cache : R ne change qu'au redimensionnement). */
function geomAt(S: number, cx: number, cy: number): Resolved {
  const key = `${S.toFixed(2)}:${cx.toFixed(1)}:${cy.toFixed(1)}`;
  const hit = GEOM_CACHE.get(key);
  if (hit) return hit;
  BASE ??= buildGeometry();
  const all = new Path2D(), ring = new Path2D();
  const openings = BASE.map((o): POpening => {
    const path = toPath(o.poly, S, cx, cy);
    all.addPath(path);
    if (o.kind === 'ring') ring.addPath(path);
    const out: POpening = { ...o, path, cells: o.cells.map((c) => resolveCell(c, S, cx, cy)), med: undefined };
    if (o.med) {
      const m = o.med;
      out.med = { ...m, px: cx + m.x * S, py: cy + m.y * S, pr: m.r * S, prIn: m.rimIn * S,
        path: toPath(circlePoly(m.x, m.y, m.r, 48), S, cx, cy), cells: m.cells.map((c) => resolveCell(c, S, cx, cy)) };
    }
    return out;
  });
  const g = { openings, all, ring };
  GEOM_CACHE.set(key, g);
  if (GEOM_CACHE.size > 6) GEOM_CACHE.delete(GEOM_CACHE.keys().next().value as string);
  return g;
}

/** Figures peintes en grisaille (brun d'oxyde de fer) dans le cercle unité, « haut » = −y. */
function motif(x: Ctx, kind: Motif): void {
  x.beginPath();
  if (kind === 'crown') {
    x.moveTo(-0.62, 0.42); x.lineTo(-0.66, -0.18); x.lineTo(-0.36, 0.08); x.lineTo(0, -0.46); x.lineTo(0.36, 0.08); x.lineTo(0.66, -0.18); x.lineTo(0.62, 0.42); x.closePath();
    x.moveTo(-0.62, 0.28); x.lineTo(0.62, 0.28);
    for (const [px, py, r] of [[-0.66, -0.28, 0.09], [0, -0.58, 0.11], [0.66, -0.28, 0.09]]) { x.moveTo(px + r, py); x.arc(px, py, r, 0, TAU); }
  } else if (kind === 'fleur') {
    x.moveTo(0, -0.7); x.bezierCurveTo(0.3, -0.36, 0.22, -0.02, 0, 0.12); x.bezierCurveTo(-0.22, -0.02, -0.3, -0.36, 0, -0.7);
    x.moveTo(-0.08, 0.08); x.bezierCurveTo(-0.3, -0.26, -0.72, -0.22, -0.62, 0.08); x.bezierCurveTo(-0.56, 0.26, -0.34, 0.24, -0.3, 0.12);
    x.moveTo(0.08, 0.08); x.bezierCurveTo(0.3, -0.26, 0.72, -0.22, 0.62, 0.08); x.bezierCurveTo(0.56, 0.26, 0.34, 0.24, 0.3, 0.12);
    x.moveTo(-0.44, 0.16); x.lineTo(0.44, 0.16); x.moveTo(-0.44, 0.28); x.lineTo(0.44, 0.28);
    x.moveTo(-0.1, 0.28); x.bezierCurveTo(-0.12, 0.46, -0.28, 0.56, -0.38, 0.6); x.moveTo(0.1, 0.28); x.bezierCurveTo(0.12, 0.46, 0.28, 0.56, 0.38, 0.6); x.moveTo(0, 0.28); x.lineTo(0, 0.66);
  } else {
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + (i * TAU) / 5, px = Math.cos(a) * 0.36, py = Math.sin(a) * 0.36; x.moveTo(px + 0.3, py); x.arc(px, py, 0.3, 0, TAU); }
    x.moveTo(0.2, 0); x.arc(0, 0, 0.2, 0, TAU);
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + ((i + 0.5) * TAU) / 5; x.moveTo(Math.cos(a) * 0.5, Math.sin(a) * 0.5); x.lineTo(Math.cos(a) * 0.7, Math.sin(a) * 0.7); }
  }
}
function paintMotif(x: Ctx, m: PMed, ang: number, S: number): void {
  x.save(); x.beginPath(); x.arc(m.px, m.py, m.prIn, 0, TAU); x.clip();
  const g = x.createRadialGradient(m.px, m.py - m.prIn * 0.3, m.prIn * 0.1, m.px, m.py, m.prIn);
  g.addColorStop(0, 'rgb(40 26 14 / 0)'); g.addColorStop(0.7, 'rgb(40 26 14 / .22)'); g.addColorStop(1, 'rgb(30 18 10 / .5)');
  x.fillStyle = g; x.fillRect(m.px - m.prIn, m.py - m.prIn, m.prIn * 2, m.prIn * 2);
  x.translate(m.px, m.py); x.rotate(ang + Math.PI / 2);
  const s = m.prIn * 0.92; x.scale(s, s);
  motif(x, m.motif);
  x.lineJoin = 'round'; x.lineCap = 'round'; x.strokeStyle = 'rgb(34 20 10 / .82)'; x.lineWidth = Math.max(0.9, S * 0.0036) / s; x.stroke();
  x.fillStyle = 'rgb(34 20 10 / .18)'; x.fill('evenodd');
  x.restore();
}
/** Grisaille : un rinceau peint dans chaque lancette et des hachures croisées sur le fond. */
function paintFoliage(x: Ctx, o: POpening, S: number, cx: number, cy: number, alpha: number): void {
  x.save(); x.clip(o.path);
  const a = o.a ?? 0, ux = Math.cos(a), uy = Math.sin(a), vx = -uy, vy = ux;
  const P = (r: number, off: number): [number, number] => [cx + (ux * r + vx * off) * S, cy + (uy * r + vy * off) * S];
  x.strokeStyle = `rgb(38 26 14 / ${alpha})`; x.lineWidth = Math.max(0.8, S * 0.0028); x.lineCap = 'round';
  x.beginPath();
  for (let i = 0; i <= 40; i++) {
    const r = GEO.lanIn + 0.02 + ((GEO.lanTip - GEO.lanIn - 0.06) * i) / 40, off = Math.sin(i * 0.9) * 0.028;
    const [px, py] = P(r, off);
    if (i) x.lineTo(px, py); else x.moveTo(px, py);
  }
  x.stroke();
  for (let i = 2; i < 40; i += 4) {
    const r = GEO.lanIn + 0.02 + ((GEO.lanTip - GEO.lanIn - 0.06) * i) / 40, side = Math.sin(i * 0.9) > 0 ? 1 : -1;
    const [lx, ly] = P(r, Math.sin(i * 0.9) * 0.028 + side * 0.02);
    x.beginPath();
    for (let l = 0; l < 3; l++) { const t = a + (side * Math.PI) / 2 + (l - 1) * 0.9; x.moveTo(lx, ly); x.arc(lx + Math.cos(t) * S * 0.008, ly + Math.sin(t) * S * 0.008, S * 0.007, 0, TAU); }
    x.stroke();
  }
  x.globalAlpha = alpha * 0.45; x.lineWidth = Math.max(0.6, S * 0.0014); x.beginPath();
  const bb = o.cells.reduce<BBox>((b, c) => [Math.min(b[0], c.bbp[0]), Math.min(b[1], c.bbp[1]), Math.max(b[2], c.bbp[2]), Math.max(b[3], c.bbp[3])], [1e9, 1e9, -1e9, -1e9]);
  const sp = Math.max(3, S * 0.014);
  for (let t = bb[0] - (bb[3] - bb[1]); t < bb[2]; t += sp) { x.moveTo(t, bb[3]); x.lineTo(t + (bb[3] - bb[1]), bb[1]); }
  x.stroke(); x.restore();
}
function fillCells(x: Ctx, cells: PCell[], pal: Palette, S: number, { lit = false, dim = 0 } = {}): void {
  for (const c of cells) {
    const col = pal[c.role] || pal.ground;
    const u = c.v[0], dl = (u < 0.12 ? -0.09 : u > 0.9 ? 0.08 : (c.v[1] - 0.5) * 0.08) + (lit ? 0.2 : 0) - dim;
    x.fillStyle = hslCss(col, (c.v[2] - 0.5) * 10, dl, lit ? 0.06 : 0); x.fill(c.path);
    x.save(); x.clip(c.path);
    const bb = c.bbp, ang = c.v[3] * Math.PI;
    const mx = (bb[0] + bb[2]) / 2, my = (bb[1] + bb[3]) / 2, rad = Math.max(bb[2] - bb[0], bb[3] - bb[1]) * 0.62;
    const sg = x.createLinearGradient(mx - Math.cos(ang) * rad, my - Math.sin(ang) * rad, mx + Math.cos(ang) * rad, my + Math.sin(ang) * rad);
    sg.addColorStop(0, `rgb(255 248 230 / ${lit ? 0.3 : 0.13})`); sg.addColorStop(0.5, 'rgb(255 250 235 / 0)'); sg.addColorStop(1, 'rgb(0 0 0 / .2)');
    x.fillStyle = sg; x.fill(c.path);
    x.lineWidth = Math.max(2, S * 0.016); x.strokeStyle = 'rgb(12 7 4 / .32)'; x.stroke(c.path);
    x.restore();
  }
}
function leadCells(x: Ctx, cells: PCell[], base: number): void {
  for (const c of cells) { x.lineWidth = base * (0.72 + c.v[4] * 0.66); x.stroke(c.path); }
}

export type PaintInput = { R: number; dpr: number; pal: Palette; stone: ImageBitmap | null; ringTo: number };
export type PaintOutput = {
  win: ImageBitmap;           // verre, plombs, pierre, halo : carré de côté 2·1,06·R (résolution DPR)
  bloom: ImageBitmap;         // la lumière versée sur le mur : carré de côté 3R (DPR 1)
  ring: ImageBitmap | null;   // panneaux de l'horloge allumés (recadrage du haut) ; null au clair de lune
  head: ImageBitmap | null;   // les mêmes, plus lumineux : le panneau courant y est découpé par un masque CSS
  W: number; BW: number; RH: number;
};

/** Peint une fenêtre. Tous les canevas sont locaux : le résultat est transféré en ImageBitmap. */
export function paintWindow({ R, dpr, pal, stone, ringTo }: PaintInput): PaintOutput {
  const W = Math.round(2 * GEO.extent * R * dpr), S = R * dpr, cx = W / 2, cy = W / 2;
  const g = geomAt(S, cx, cy);
  const moon = pal.mode === 'moon', gris = pal.mode === 'grisaille';
  const base = Math.max(1.1, S * 0.0046);
  // 1. verre (les panneaux de l'horloge sont peints éteints ici ; les allumés forment leur propre calque)
  const A = new OffscreenCanvas(W, W), a = ctx(A);
  for (const o of g.openings) {
    a.save(); a.clip(o.path);
    fillCells(a, o.cells, pal, S, { dim: o.kind === 'ring' && !moon ? 0.16 : 0 });
    if (o.med) fillCells(a, o.med.cells, pal, S);
    if (o.kind === 'lancet' && (gris || moon)) paintFoliage(a, o, S, cx, cy, gris ? 0.5 : 0.28);
    a.restore();
  }
  for (const o of g.openings) if (o.med) paintMotif(a, o.med, o.a ?? 0, S);
  a.save(); a.globalCompositeOperation = 'overlay'; a.globalAlpha = 0.5; a.drawImage(glassTexture(), 0, 0, W, W); a.restore();
  a.save(); a.globalCompositeOperation = 'multiply';
  const fo = a.createRadialGradient(cx, cy, S * 0.2, cx, cy, S * 1.0);
  fo.addColorStop(0, 'rgb(242 240 236)'); fo.addColorStop(0.6, 'rgb(214 208 200)'); fo.addColorStop(1, 'rgb(140 130 120)');
  a.fillStyle = fo; a.fillRect(0, 0, W, W); a.restore();
  a.save(); a.globalCompositeOperation = 'screen';
  const hs = a.createRadialGradient(cx, cy - S * 0.95, S * 0.02, cx, cy - S * 0.6, S * 0.95);
  hs.addColorStop(0, moon ? 'rgb(200 214 240 / .3)' : 'rgb(255 238 210 / .34)'); hs.addColorStop(0.5, 'rgb(255 228 190 / .08)'); hs.addColorStop(1, 'rgb(255 230 200 / 0)');
  a.fillStyle = hs; a.fillRect(0, 0, W, W); a.restore();
  a.save(); a.globalCompositeOperation = 'destination-in'; a.fill(g.all); a.restore();
  // 2. plombs (1 à 2 px, jamais réguliers), anneaux des médaillons, barlotières
  const B = new OffscreenCanvas(W, W), b = ctx(B);
  b.drawImage(A, 0, 0);
  b.save(); b.lineJoin = 'round'; b.strokeStyle = 'rgb(10 7 5 / .96)';
  for (const o of g.openings) {
    b.save(); b.clip(o.path);
    if (o.cells.length > 1) leadCells(b, o.cells, base);
    if (o.med) {
      leadCells(b, o.med.cells, base);
      b.lineWidth = base * 1.9; b.stroke(o.med.path);
      b.beginPath(); b.arc(o.med.px, o.med.py, o.med.prIn, 0, TAU); b.lineWidth = base * 1.3; b.stroke();
    }
    b.restore();
    b.lineWidth = base * 2.2; b.stroke(o.path);
  }
  b.lineWidth = Math.max(1.8, S * 0.011); b.lineCap = 'butt';
  for (const o of g.openings) if (o.kind === 'lancet') for (const rr of [0.47, 0.75]) {
    const w = TAU / 16 / 2, oa = o.a ?? 0;
    b.beginPath();
    b.moveTo(cx + Math.cos(oa - w) * rr * S, cy + Math.sin(oa - w) * rr * S); b.lineTo(cx + Math.cos(oa + w) * rr * S, cy + Math.sin(oa + w) * rr * S); b.stroke();
  }
  b.restore();
  // 3. halo : le verre clair déborde sur le plomb sombre, dans les ouvertures
  b.save(); b.clip(g.all); b.globalCompositeOperation = 'lighter';
  b.filter = `blur(${(1.1 * dpr).toFixed(1)}px)`; b.globalAlpha = 0.26; b.drawImage(A, 0, 0); b.restore();
  // 4. la pierre (Blender), puis la lumière qui déborde sur ses arêtes (floutée à mi-taille)
  if (stone) b.drawImage(stone, 0, 0, W, W);
  const half = new OffscreenCanvas(Math.ceil(W / 2), Math.ceil(W / 2)), hx = ctx(half);
  hx.drawImage(A, 0, 0, half.width, half.height);
  b.save(); b.globalCompositeOperation = 'lighter';
  b.filter = `blur(${(1.2 * dpr).toFixed(1)}px)`; b.globalAlpha = moon ? 0.16 : 0.2; b.drawImage(half, 0, 0, W, W);
  b.filter = `blur(${(4.5 * dpr).toFixed(1)}px)`; b.globalAlpha = moon ? 0.1 : 0.13; b.drawImage(half, 0, 0, W, W);
  b.restore();
  const win = B.transferToImageBitmap();
  // la lumière sur le mur : DPR 1 (elle est floutée de toute façon), carré de côté 3R
  const BW = Math.round(3 * R), bc = BW / 2;
  const small = new OffscreenCanvas(Math.ceil(BW / 4), Math.ceil(BW / 4)), sx = ctx(small);
  sx.scale(0.25, 0.25);
  const gb = geomAt(R, bc, bc);
  for (const o of gb.openings) for (const c of o.cells) { sx.fillStyle = hslCss(pal[c.role] || pal.ground, 0, 0.1, -0.1); sx.fill(c.path); }
  const Bl = new OffscreenCanvas(BW, BW), bl = ctx(Bl);
  bl.globalCompositeOperation = 'lighter';
  bl.filter = `blur(${Math.round(R * 0.05)}px)`; bl.globalAlpha = 0.3; bl.drawImage(small, 0, 0, BW, BW);
  bl.filter = `blur(${Math.round(R * 0.14)}px)`; bl.globalAlpha = 0.4; bl.drawImage(small, 0, 0, BW, BW);
  bl.filter = `blur(${Math.round(R * 0.32)}px)`; bl.globalAlpha = 0.38; bl.drawImage(small, 0, 0, BW, BW);
  const bloom = Bl.transferToImageBitmap();
  // l'horloge : les panneaux de l'anneau allumés (recadrage du haut seulement), et les mêmes plus vifs
  let ring: ImageBitmap | null = null, head: ImageBitmap | null = null, RH = 0;
  if (!moon) {
    RH = Math.round((W * (GEO.extent + ringTo)) / (2 * GEO.extent));
    const rings = g.openings.filter((o) => o.kind === 'ring');
    const L = new OffscreenCanvas(W, RH), l = ctx(L);
    for (const o of rings) { l.save(); l.clip(o.path); fillCells(l, o.cells, pal, S, { lit: true }); l.restore(); }
    l.save(); l.globalCompositeOperation = 'overlay'; l.globalAlpha = 0.45; l.drawImage(glassTexture(), 0, 0, W, W); l.restore();
    l.save(); l.globalCompositeOperation = 'destination-in'; l.fill(g.ring); l.restore();
    const paintRing = (boost: boolean): ImageBitmap => {
      const Rg = new OffscreenCanvas(W, RH), r = ctx(Rg);
      if (boost) r.filter = 'brightness(1.6) saturate(1.2)';
      r.drawImage(L, 0, 0); r.filter = 'none';
      r.save(); r.strokeStyle = 'rgb(10 7 5 / .95)';
      for (const o of rings) { r.save(); r.clip(o.path); leadCells(r, o.cells, base); r.restore(); }
      r.restore();
      if (stone) r.drawImage(stone, 0, 0, W, W);
      r.save(); r.globalCompositeOperation = 'lighter';
      r.filter = `blur(${(1.2 * dpr).toFixed(1)}px)`; r.globalAlpha = boost ? 0.62 : 0.4; r.drawImage(L, 0, 0);
      r.filter = `blur(${(3 * dpr).toFixed(1)}px)`; r.globalAlpha = boost ? 0.56 : 0.3; r.drawImage(L, 0, 0);
      r.filter = `blur(${(10 * dpr).toFixed(1)}px)`; r.globalAlpha = boost ? 0.44 : 0.2; r.drawImage(L, 0, 0);
      r.restore();
      return Rg.transferToImageBitmap();
    };
    ring = paintRing(false); head = paintRing(true);
  }
  return { win, bloom, ring, head, W, BW, RH };
}
