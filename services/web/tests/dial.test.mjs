import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { dialGeometry, clockPane, paneMask, paneAtPoint, paneTime, hitArcPath, fmtSpoken, PANE_DEG } = await loadTs('../src/lib/stage/dial.ts');

test('arc visible selon la corde (valeurs du prototype)', () => {
  assert.deepEqual(dialGeometry(0.3), { K: 9, n: 19, a0: -71.25 });
  assert.deepEqual(dialGeometry(0.42), { K: 8, n: 17, a0: -63.75 });
  assert.deepEqual(dialGeometry(0.64), { K: 5, n: 11, a0: -41.25 });
  assert.equal(dialGeometry(0.95).K, 3);   // jamais moins de 7 panneaux
});

test('panneau courant : un par tranche de durée, −1 sans durée', () => {
  assert.equal(clockPane(0, 213, 19), 0);
  assert.equal(clockPane(41, 213, 19), 3);
  assert.equal(clockPane(213, 213, 19), 18);   // fin : dernier panneau, jamais n
  assert.equal(clockPane(500, 213, 19), 18);
  assert.equal(clockPane(10, 0, 19), -1);
  assert.equal(clockPane(Number.NaN, 213, 19), -1);
});

test('le masque ne change qu’au changement de panneau (≈ 11 s pour 3 min 30)', () => {
  const dur = 210, n = 19;
  let changes = 0, last = clockPane(0, dur, n);
  for (let t = 0; t <= dur; t += 0.25) { const i = clockPane(t, dur, n); if (i !== last) { changes++; last = i; } }
  assert.equal(changes, n - 1);
  assert.deepEqual(paneMask(3), { p0: 3 * PANE_DEG, p1: 4 * PANE_DEG });
  assert.deepEqual(paneMask(-1), { p0: 0, p1: 0 });
});

test('survol : panneau sous le pointeur et temps affiché', () => {
  const dial = dialGeometry(0.3);
  assert.equal(paneAtPoint(0, -100, dial), 9);          // en haut : le panneau du milieu
  assert.equal(paneAtPoint(-100, -30, dial), 0);        // loin à gauche : borné au premier
  assert.equal(paneAtPoint(100, -30, dial), 18);        // loin à droite : borné au dernier
  assert.equal(paneTime(9, 19, 190), 90);
  assert.equal(paneTime(3, 19, 0), 0);
});

test('zone de survol : un arc SVG le long des panneaux visibles', () => {
  assert.equal(hitArcPath(dialGeometry(0.3)), 'M-0.8759 -0.2973A0.925 0.925 0 0 1 0.8759 -0.2973');
});

test('durée dite pour les lecteurs d’écran', () => {
  assert.equal(fmtSpoken(45), '45 s');
  assert.equal(fmtSpoken(92), '1 min 32');
  assert.equal(fmtSpoken(3725), '1 h 02 min 05');
  assert.equal(fmtSpoken(null), '');
  assert.equal(fmtSpoken(-1), '');
});
