import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { buildGeometry, GEO, PANE_A0, PANE_STEP, clipPoly, inPoly, circlePoly } = await loadTs('../src/lib/rose/geometry.ts');

const g = buildGeometry();
const kinds = (k) => g.filter((o) => o.kind === k);

test('ouvertures : 48 panneaux, 16 lancettes, 16 quadrilobes, 8 rondels, 1 cœur', () => {
  assert.equal(kinds('ring').length, GEO.panes);
  assert.equal(kinds('lancet').length, 16);
  assert.equal(kinds('foil').length, 16);
  assert.equal(kinds('roundel').length, 8);
  assert.equal(kinds('heart').length, 1);
});

test('géométrie identique au prototype (la pierre Blender a été calculée dessus)', () => {
  let s = 0, n = 0;
  for (const o of g) for (const c of [...o.cells, ...(o.med ? o.med.cells : [])]) for (const [x, y] of c.poly) { s += x + 2 * y; n++; }
  assert.equal(n, 8342);
  assert.ok(Math.abs(s - -2.374039) < 1e-6, `somme de contrôle ${s}`);
  const cells = g.reduce((t, o) => t + o.cells.length + (o.med ? o.med.cells.length : 0), 0);
  assert.equal(cells, 979);
});

test('déterministe pour une graine, différent pour une autre', () => {
  assert.deepEqual(buildGeometry(23), g);
  assert.notDeepEqual(buildGeometry(7), g);
});

test('le panneau 0 de l’horloge est centré en haut, les panneaux tournent dans le sens horaire', () => {
  const [p0, p1] = kinds('ring');
  assert.ok(Math.abs(((p0.t1 + p0.t2) / 2) + Math.PI / 2) < 1e-12);
  assert.ok(Math.abs(p1.t1 - p0.t1 - PANE_STEP) < 1e-12);
  assert.equal(p0.t1, PANE_A0);
});

test('constantes du prototype, y compris celles que seule la pierre utilise (paint.ts les cale dessus)', () => {
  assert.deepEqual(GEO, {
    extent: 1.06, stone: 1.045, ringIn: 0.892, ringOut: 0.958, panes: 48, paneGap: 0.0105, beadR: 0.8755, beads: 96,
    lanIn: 0.33, lanH: 0.655, lanTip: 0.845, lanGap: 0.038, medR: 0.565, medRad: 0.092, qfR: 0.8, qfLobe: 0.026,
    rosR: 0.235, rosRad: 0.066, heart: 0.13,
  });
});

test('tout le verre tient dans l’anneau extérieur, chaque pièce a au moins 3 sommets', () => {
  const inside = ([x, y]) => Math.hypot(x, y) <= GEO.ringOut + 1e-9;
  for (const o of g) {
    assert.ok(o.poly.every(inside), o.kind);
    for (const c of [...o.cells, ...(o.med ? o.med.cells : [])]) {
      assert.ok(c.poly.length >= 3, o.kind);
      assert.ok(c.poly.every(inside), o.kind);
    }
  }
});

test('mosaïque : 34 à 36 pièces par lancette, un médaillon peint dans chacune', () => {
  for (const l of kinds('lancet')) {
    assert.ok(l.cells.length >= 34 && l.cells.length <= 36, String(l.cells.length));
    assert.equal(l.med.cells.filter((c) => c.paint).length, 2);
  }
  assert.deepEqual(kinds('lancet').slice(0, 4).map((l) => l.med.motif), ['crown', 'fleur', 'rose', 'fleur']);
});

test('clipPoly et inPoly', () => {
  const sq = [[0, 0], [2, 0], [2, 2], [0, 2]];
  const half = clipPoly(sq, (x) => x - 1);   // garde x ≤ 1
  assert.ok(half.every(([x]) => x <= 1 + 1e-12));
  assert.ok(inPoly([0.5, 0.5], half) && !inPoly([1.5, 0.5], half));
  assert.equal(circlePoly(0, 0, 1, 12).length, 12);
});
