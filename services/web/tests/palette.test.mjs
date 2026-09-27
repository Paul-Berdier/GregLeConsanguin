import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';
const P = await loadTs('../src/lib/rose/palette.ts');
const { contrast } = await loadTs('../src/lib/color.ts');
const { paletteFromPixels, buildPalette, lumiereOf, hueDist, hslCss, GRISAILLE, MOONLIGHT, SAMPLE_W, SAMPLE_H, thumbUrl } = P;

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

test('troisième teinte trop proche de la principale : remplacée', () => {
  assert.deepEqual(buildPalette([20, 222]).hues, [20, 222, 44]);
  for (let h = 0; h < 360; h += 5) {
    const [m, , t] = buildPalette([h]).hues;
    assert.ok(hueDist(m, t) >= 30 || t === 44, `${h}`);
  }
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
