/**
 * Palette du vitrail, tirée de la miniature du morceau (DESIGN §4 et §12.2).
 * Repris de proto-gothique/work/refine/rose-worker.js (lignes 194–272). L'analyse des pixels est
 * pure (`paletteFromPixels`) ; la lecture de la miniature (fetch, OffscreenCanvas) reste dans le worker.
 * Pur, sans import runtime (tests/palette.test.mjs).
 */
import type { GlassRole } from './geometry';

export type HSL = [number, number, number];
export type RGB = [number, number, number];
export type PaletteMode = 'color' | 'grisaille' | 'moon';
export type Palette = { mode: PaletteMode; hues?: number[]; lum: RGB; glassA: RGB; glassB: RGB } & Record<GlassRole, HSL>;

const clamp = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));

/** Couleur CSS d'un verre, avec décalages de teinte, de luminosité et de saturation. */
export function hslCss([h, s, l]: HSL, dh = 0, dl = 0, ds = 0): string {
  return `hsl(${Math.round(h + dh)} ${Math.round(clamp(s + ds, 0, 1) * 100)}% ${Math.round(clamp(l + dl, 0.04, 0.96) * 100)}%)`;
}
export function hsl2rgb(h: number, s: number, l: number): RGB {
  const k = (n: number) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}
export function rgb2hsv(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) {
    if (mx === r) h = ((g - b) / d) % 6; else if (mx === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
    h *= 60; if (h < 0) h += 360;
  }
  return [h, mx ? d / mx : 0, mx];
}
export const hueDist = (a: number, b: number): number => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

/** Luminosité « joyau » par teinte : cobalt et rubis profonds, jaune d'argent plus clair pour ne pas virer au brun. */
export function jewelL(h: number): number {
  h = ((h % 360) + 360) % 360;
  if (h >= 200 && h < 262) return 0.31;   // cobalt
  if (h >= 330 || h < 12) return 0.33;    // rubis
  if (h >= 12 && h < 38) return 0.33;     // vermillon, ambre
  if (h >= 38 && h < 70) return 0.45;     // jaune d'argent
  if (h >= 70 && h < 170) return 0.29;    // vert (seulement si le morceau en a)
  if (h >= 170 && h < 200) return 0.31;   // sarcelle
  return 0.3;                             // pourpre, violet
}
export const GLAZIER = { cobalt: 222, ruby: 352, gold: 44, murrey: 322 } as const;
/** Teintes de repli, prises chez le verrier médiéval selon l'harmonie avec la teinte principale ; jamais de vert. */
export function harmony(main: number): [number, number] {
  if (main >= 180 && main < 262) return [GLAZIER.ruby, GLAZIER.gold];
  if (main >= 262 && main < 330) return [GLAZIER.gold, GLAZIER.cobalt];
  if (main >= 70 && main < 180) return [GLAZIER.ruby, GLAZIER.gold];
  if (main >= 38 && main < 70) return [GLAZIER.cobalt, GLAZIER.ruby];
  return [GLAZIER.cobalt, GLAZIER.gold];
}
/** La lumière du morceau (--lumiere) : ≥ 6:1 sur --nef quelle que soit la teinte (DESIGN §7). */
export function lumiereOf(h: number): RGB {
  const l = h >= 190 && h < 280 ? 0.74 : h > 40 && h < 75 ? 0.64 : 0.69;
  return hsl2rgb(h, 0.78, l);
}
export function buildPalette(hues: number[]): Palette {
  const main = hues[0];
  const [f2, f3] = harmony(main);
  const second = hues[1] ?? f2;
  let third = hues[2] ?? (hueDist(f3, second) > 40 ? f3 : f2);
  if (hueDist(third, main) < 30) {
    third = [GLAZIER.gold, GLAZIER.ruby, GLAZIER.cobalt].find((h) => hueDist(h, main) > 40 && hueDist(h, second) > 40) ?? GLAZIER.gold;
  }
  const J = (h: number, s: number, dl = 0): HSL => [h, s, jewelL(h) + dl];
  return {
    mode: 'color', hues: [main, second, third],
    ground: J(main, 0.8), border: J(second, 0.78), figure: J(third, 0.76, 0.06), accent: J(main, 0.6, 0.1),
    pale: [44, 0.42, 0.58], ringA: J(second, 0.8), ringB: J(main, 0.84),
    lum: lumiereOf(main), glassA: hsl2rgb(main, 0.7, 0.45), glassB: hsl2rgb(second, 0.7, 0.45),
  };
}
/** Vidéo en noir et blanc : grisaille verdâtre chaude, feuillages peints, un seul accent jaune d'argent. */
export const GRISAILLE: Palette = {
  mode: 'grisaille', ground: [64, 0.09, 0.35], border: [54, 0.1, 0.39], figure: [44, 0.66, 0.5], accent: [66, 0.07, 0.44],
  pale: [56, 0.14, 0.55], ringA: [54, 0.1, 0.4], ringB: [64, 0.09, 0.36], lum: [222, 212, 178], glassA: [120, 116, 96], glassB: [150, 140, 110],
};
/** Rien en lecture : clair de lune à travers le verre clair et le jaune d'argent. */
export const MOONLIGHT: Palette = {
  mode: 'moon', ground: [218, 0.3, 0.37], border: [40, 0.2, 0.42], figure: [46, 0.46, 0.53], accent: [214, 0.16, 0.5],
  pale: [50, 0.2, 0.62], ringA: [40, 0.2, 0.42], ringB: [218, 0.3, 0.38], lum: [180, 196, 226], glassA: [110, 128, 170], glassB: [150, 150, 130],
};

/** Taille de l'échantillon : le milieu 16:9 de hqdefault réduit à 48 × 27. */
export const SAMPLE_W = 48, SAMPLE_H = 27;
/** URL de la miniature lue par le worker (i.ytimg.com répond `Access-Control-Allow-Origin: *`). */
export const thumbUrl = (id: string): string => `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;

/**
 * Pics de teinte d'un histogramme pondéré par la saturation (24 cases de 15°), trois au plus, écartés de 30°.
 * Pas de teinte exploitable (chroma moyen < 0,02) : grisaille. Le seuil est celui du code du prototype et de
 * DESIGN §12.2 ; le 0,012 de DESIGN §4 date du tour 2 et a été remonté depuis.
 */
export function paletteFromPixels(d: ArrayLike<number>): Palette {
  const bins = Array.from({ length: 24 }, () => ({ w: 0, sx: 0, sy: 0 }));
  let chroma = 0, n = 0;
  for (let i = 0; i + 3 < d.length; i += 4) {
    const [h, s, v] = rgb2hsv(d[i], d[i + 1], d[i + 2]);
    n++;
    if (v < 0.16 || s < 0.22) continue;
    const w = Math.pow(s, 1.5) * v;
    chroma += w;
    const b = bins[Math.floor(h / 15) % 24];
    b.w += w; b.sx += Math.cos((h * Math.PI) / 180) * w; b.sy += Math.sin((h * Math.PI) / 180) * w;
  }
  if (!n || chroma / n < 0.02) return GRISAILLE;
  const peaks: { w: number; h: number }[] = [];
  bins.forEach((b, i) => {
    if (b.w) peaks.push({ w: b.w + (bins[(i + 23) % 24].w + bins[(i + 1) % 24].w) * 0.5, h: ((Math.atan2(b.sy, b.sx) * 180) / Math.PI + 360) % 360 });
  });
  peaks.sort((a, b) => b.w - a.w);
  const hues: number[] = [];
  for (const p of peaks) {
    if (hues.length >= 3) break;
    if (p.w < peaks[0].w * 0.12) break;
    if (hues.every((h) => hueDist(h, p.h) > 30)) hues.push(p.h);
  }
  return hues.length ? buildPalette(hues) : GRISAILLE;
}
