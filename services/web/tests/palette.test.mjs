import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';
const P = await loadTs('../src/lib/rose/palette.ts');
const { contrast } = await loadTs('../src/lib/color.ts');
const { paletteFromPixels, buildPalette, lumiereOf, hueDist, hslCss, hsl2rgb, jewelL, GRISAILLE, MOONLIGHT, SAMPLE_W, SAMPLE_H, thumbUrl } = P;

const N = SAMPLE_W * SAMPLE_H;
function image(fill) {            // fill(i) → [r, g, b] pour le pixel i
  const d = new Uint8ClampedArray(N * 4);
  for (let i = 0; i < N; i++) { const [r, g, b] = fill(i); d.set([r, g, b, 255], i * 4); }
  return d;
}
const hex = ([r, g, b]) => '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');

test('vidéo sans teinte exploitable : grisaille', () => {
  assert.equal(paletteFromPixels(image(() => [128, 128, 128])), GRISAILLE);
  assert.equal(paletteFromPixels(image(() => [20, 5, 5])), GRISAILLE);                       // trop sombre
  assert.equal(paletteFromPixels(image((i) => (i < 20 ? [200, 30, 30] : [120, 120, 120]))), GRISAILLE); // chroma < 0,02
  assert.equal(paletteFromPixels(new Uint8ClampedArray(0)), GRISAILLE);
});

test('miniature rouge : fond rubis, compléments du verrier (cobalt, or)', () => {
  const p = paletteFromPixels(image(() => [200, 30, 30]));
  assert.equal(p.mode, 'color');
  assert.ok(hueDist(p.hues[0], 0) < 1, String(p.hues[0]));
  assert.deepEqual(p.hues.slice(1), [222, 44]);
  assert.equal(p.ground[0], p.hues[0]);
});

test('deux teintes présentes : les deux sont gardées, la dominante d’abord', () => {
  const p = paletteFromPixels(image((i) => (i % 3 === 0 ? [30, 60, 200] : [200, 30, 30])));
  assert.ok(hueDist(p.hues[0], 0) < 1);
  assert.ok(hueDist(p.hues[1], 229) < 2, String(p.hues[1]));
});

test('pas de vert ajouté si la miniature n’en a pas', () => {
  for (let h = 0; h < 360; h += 15) {
    const p = buildPalette([h]);
    for (const x of p.hues.slice(1)) assert.ok(!(x >= 70 && x < 170), `${h} → ${x}`);
  }
});

test('pics de teinte : écartés de plus de 30°, et au moins 12 % du plus fort', () => {
  const hue = (h) => hsl2rgb(h, 0.8, 0.45);
  // 10° et 20° : un seul pic, les deux autres teintes viennent du verrier
  assert.deepEqual(paletteFromPixels(image((i) => hue(i % 2 ? 10 : 20))).hues.slice(1), [222, 44]);
  // vert sur un pixel sur k, rouge ailleurs (même poids par pixel) : 1 sur 10 = 11 % du rouge, ignoré ; 1 sur 8 = 14 %, gardé
  const green = (k) => paletteFromPixels(image((i) => (i % k === 0 ? [30, 200, 30] : [200, 30, 30])));
  assert.deepEqual(green(10).hues.slice(1), [222, 44]);
  assert.ok(hueDist(green(8).hues[1], 120) < 1, String(green(8).hues));
});

test('troisième teinte trop proche de la principale : remplacée', () => {
  assert.deepEqual(buildPalette([70]).hues, [70, 352, 222]);        // l'or n'est qu'à 26° : cobalt
  assert.deepEqual(buildPalette([72, 200]).hues, [72, 200, 352]);   // l'or à 28°, le cobalt près de la 2e : rubis
  assert.deepEqual(buildPalette([20, 222]).hues, [20, 222, 44]);    // aucune teinte du verrier ne convient : l'or reste
  for (let h = 0; h < 360; h++) {
    const [m, , t] = buildPalette([h]).hues;
    if (h >= 15 && h <= 32) assert.equal(t, 44, `${h}`);          // vermillon, ambre : rubis et or trop proches, cobalt déjà pris
    else assert.ok(hueDist(m, t) >= 30, `${h} → ${t}`);
  }
});

test('valeurs du prototype : luminosités « joyau » et palettes de référence', () => {
  assert.deepEqual([0, 11.9, 12, 37.9, 38, 69.9, 70, 169.9, 170, 199.9, 200, 261.9, 262, 329.9, 330, -10, 370].map(jewelL),
    [0.33, 0.33, 0.33, 0.33, 0.45, 0.45, 0.29, 0.29, 0.31, 0.31, 0.31, 0.31, 0.3, 0.3, 0.33, 0.33, 0.33]);
  const r6 = (p) => JSON.parse(JSON.stringify(p, (_, v) => (typeof v === 'number' ? Math.round(v * 1e6) / 1e6 : v)));
  const pale = [44, 0.42, 0.58];
  assert.deepEqual(r6(buildPalette([0])), {
    mode: 'color', hues: [0, 222, 44], ground: [0, 0.8, 0.33], border: [222, 0.78, 0.31], figure: [44, 0.76, 0.51], accent: [0, 0.6, 0.43],
    pale, ringA: [222, 0.8, 0.31], ringB: [0, 0.84, 0.33], lum: [238, 114, 114], glassA: [195, 34, 34], glassB: [34, 83, 195],
  });
  assert.deepEqual(r6(buildPalette([222])), {
    mode: 'color', hues: [222, 352, 44], ground: [222, 0.8, 0.31], border: [352, 0.78, 0.33], figure: [44, 0.76, 0.51], accent: [222, 0.6, 0.41],
    pale, ringA: [352, 0.8, 0.33], ringB: [222, 0.84, 0.31], lum: [137, 168, 240], glassA: [34, 83, 195], glassB: [195, 34, 56],
  });
  assert.deepEqual(r6(buildPalette([300, 44])), {
    mode: 'color', hues: [300, 44, 222], ground: [300, 0.8, 0.3], border: [44, 0.78, 0.45], figure: [222, 0.76, 0.37], accent: [300, 0.6, 0.4],
    pale, ringA: [44, 0.8, 0.45], ringB: [300, 0.84, 0.3], lum: [238, 114, 238], glassA: [195, 34, 195], glassB: [195, 152, 34],
  });
  // la 2e teinte tombe sur l'or de repli : les figures prennent l'autre teinte de l'harmonie (rubis)
  assert.deepEqual(buildPalette([222, 50]).hues, [222, 50, 352]);
});

test('--lumiere lisible sur --nef pour toute teinte (≥ 6:1, DESIGN §7)', () => {
  for (let h = 0; h < 360; h += 5) assert.ok(contrast(hex(lumiereOf(h)), '#14110e') >= 6.0, `teinte ${h}`);
  assert.ok(contrast(hex(GRISAILLE.lum), '#14110e') >= 6.0);
});

test('clair de lune = valeur par défaut de --lumiere dans tokens.css', () => {
  const css = readFileSync(new URL('../src/theme/tokens.css', import.meta.url), 'utf8');
  assert.match(css, new RegExp(`--lumiere-rgb:${MOONLIGHT.lum.join(' ')};`));
});

test('hslCss borne saturation et luminosité', () => {
  assert.equal(hslCss([10, 0.8, 0.33]), 'hsl(10 80% 33%)');
  assert.equal(hslCss([10, 0.8, 0.33], 5, 1, 1), 'hsl(15 100% 96%)');
  assert.equal(thumbUrl('dQw4w9WgXcQ'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
});
