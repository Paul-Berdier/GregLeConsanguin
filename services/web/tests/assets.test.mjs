import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const pub = (p) => fileURLToPath(new URL(`../public/${p}`, import.meta.url));
const REQUIRED = [
  'gothique/stone-rose-2048.webp', 'gothique/stone-frame-640.webp', 'gothique/crown-320.webp',
  'gothique/crown-turn-128.avif', 'gothique/crown-still-128.avif', 'gothique/crown-badge-64.webp',
  'gothique/crown-badge-128.webp', 'gothique/grain-256.webp', 'gothique/greg-face-96.webp',
  'gothique/greg-face-192.webp', 'gothique/minstrels-manesse-line.webp',
  'fonts/GrenzeGotisch-VF.woff2', 'fonts/Grenze-VF.woff2', 'fonts/AlegreyaSans-Regular.woff2',
  'fonts/AlegreyaSans-Medium.woff2', 'fonts/AlegreyaSans-Bold.woff2', 'fonts/AlegreyaSans-ExtraBold.woff2',
  'fonts/Alegreya-Italic-VF.woff2', 'licenses/LICENSES.md',
];
test('assets Nuit gothique présents et non vides', () => {
  for (const p of REQUIRED) {
    assert.ok(existsSync(pub(p)), `manquant : ${p}`);
    assert.ok(statSync(pub(p)).size > 0, `vide : ${p}`);
  }
});
test('un sceau royal par initiale A–Z', () => {
  for (const c of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') assert.ok(existsSync(pub(`gothique/seals/king-seal-${c}.webp`)), c);
});
test('poids total raisonnable (< 1,6 Mo hors sceaux)', () => {
  const total = REQUIRED.reduce((s, p) => s + statSync(pub(p)).size, 0);
  assert.ok(total < 1_600_000, `${total} octets`);
});
test('bonnet à grelots de Greg (portrait de la nuit « déconnecté »), avec sa licence', () => {
  for (const p of ['gothique/jester-cap-256.webp', 'gothique/jester-cap-512.webp']) {
    assert.ok(existsSync(pub(p)) && statSync(pub(p)).size > 0, p);
  }
  assert.match(readFileSync(pub('licenses/LICENSES.md'), 'utf8'), /jester-cap-256\.webp/);
});
