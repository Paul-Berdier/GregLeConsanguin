// Mouvement de liste (étape 3) : jetons JS = tokens.css ; présence et FLIP ; glisser, accalmie, anti-doublon.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';

const M = await loadTs('../src/lib/motion.ts');
const F = await loadTs('../src/lib/flip.ts');
const D = await loadTs('../src/lib/queue/drag.ts');

test('lib/motion.ts reprend à la lettre les jetons de tokens.css', () => {
  const css = readFileSync(new URL('../src/theme/tokens.css', import.meta.url), 'utf8');
  const root = css.slice(css.indexOf(':root{'), css.indexOf('}', css.indexOf(':root{')));
  const vars = Object.fromEntries([...root.matchAll(/--([\w-]+):([^;]+);/g)].map(([, k, v]) => [k, v.trim().replace(/\s+/g, '')]));
  const camel = (s) => s.replace(/-(\w)/g, (_, c) => c.toUpperCase());
  let n = 0;
  for (const [k, v] of Object.entries(vars)) {
    let m;
    if ((m = /^dur-(.+)$/.exec(k))) { assert.equal(`${M.DUR[camel(m[1])]}ms`, v, k); n++; }
    else if ((m = /^stagger$/.exec(k))) { assert.equal(`${M.DUR.stagger}ms`, v, k); n++; }
    else if ((m = /^ease-(.+)$/.exec(k))) { assert.equal(M.EASE[camel(m[1])], v, k); n++; }
    else if ((m = /^spring-(\w+)-dur$/.exec(k))) { assert.equal(`${M.SPRING[m[1]].dur}ms`, v, k); n++; }
    else if ((m = /^spring-(\w+)$/.exec(k))) { assert.equal(M.SPRING[m[1]].easing, v, k); n++; }
  }
  assert.ok(n >= 29, `${n} jetons comparés`);
});

const K = (k) => ({ k });
const keyOf = (x) => x.k;
const shape = (list) => list.map((p) => (p.leaving ? `(${p.key})` : p.key)).join(',');

test('présence : un titre parti reste le temps de sa sortie, après son ancien voisin', () => {
  const a = K('a'), b = K('b'), c = K('c'), d = K('d');
  const p0 = F.mergePresence([], [a, b, c, d], keyOf);
  assert.equal(shape(p0), 'a,b,c,d');
  const p1 = F.mergePresence(p0, [a, c, d], keyOf);
  assert.equal(shape(p1), 'a,(b),c,d');
  assert.equal(p1[0], p0[0], 'ligne inchangée : même objet');
  const p2 = F.mergePresence(p1, [c, d], keyOf);
  assert.equal(shape(p2), '(a),(b),c,d', 'deux sorties à la suite gardent leur ordre');
  const p3 = F.mergePresence(p2, [c, b, d], keyOf);
  assert.equal(shape(p3), '(a),c,b,d', 'revenu pendant sa sortie : présent de nouveau');
  assert.equal(shape(F.dropLeft(p3, 'a')), 'c,b,d');
  assert.equal(F.dropLeft(p3, 'b'), p3, 'on ne retire pas une ligne présente');
});

test('translateYOf lit matrix() et matrix3d() ; staggerDelay plafonne à 8', () => {
  assert.equal(F.translateYOf('none'), 0);
  assert.equal(F.translateYOf('matrix(1, 0, 0, 1, 0, -12.5)'), -12.5);
  assert.equal(F.translateYOf('matrix3d(1,0,0,0,0,1,0,0,0,0,1,0,0,30,0,1)'), 30);
  assert.equal(F.staggerDelay(3, 30), 90);
  assert.equal(F.staggerDelay(20, 30), 240);
});

test('glisser : rang visé, écart des voisins, élastique aux bords', () => {
  const tops = [0, 64, 128, 192, 256];
  const step = 64;
  assert.equal(D.targetIndex(tops, 1, 0, step), 1);
  assert.equal(D.targetIndex(tops, 1, 31, step), 1);
  assert.equal(D.targetIndex(tops, 1, 33, step), 2);
  assert.equal(D.targetIndex(tops, 4, -500, step), 0);
  assert.deepEqual([0, 1, 2, 3, 4].map((i) => D.shiftFor(i, 1, 3, step)), [0, 0, -64, -64, 0]);
  assert.deepEqual([0, 1, 2, 3, 4].map((i) => D.shiftFor(i, 3, 1, step)), [0, 64, 64, 0, 0]);
  assert.equal(D.clampOffset(50, tops, 1), 50);
  const over = D.clampOffset(-200, tops, 1);
  assert.ok(over < -64 && over > -64 - 24, `élastique : ${over}`);
  assert.ok(D.rubber(1e6) < 24, 'jamais plus de 24 px');
});

test('défilement automatique quadratique près des bords ; durée de dépôt 330 → 550 ms', () => {
  assert.equal(D.autoScrollSpeed(300, 0, 600), 0);
  assert.equal(D.autoScrollSpeed(0, 0, 600), -25);
  assert.equal(D.autoScrollSpeed(600, 0, 600), 25);
  assert.equal(D.autoScrollSpeed(25, 0, 600), -6.25);
  assert.equal(Math.round(D.dropDuration(0, false)), 330);
  assert.equal(Math.round(D.dropDuration(3000, false)), 550);
  assert.equal(Math.round(D.dropDuration(0, true)), 198);
});

test('ancre du dépôt : le titre qui suivra la ligne déposée', () => {
  const keys = ['a', 'b', 'c', 'd'];
  assert.equal(D.dropAnchor(keys, 'd', 0), 'a');
  assert.equal(D.dropAnchor(keys, 'a', 3), null);
  assert.equal(D.dropAnchor(keys, 'a', 2), 'd');
  assert.equal(D.dropAnchor(keys, 'c', 1), 'b');
});

test('accalmie : 400 ms, ou 3 px de mouvement ; anti-doublon 500 ms par titre', () => {
  const s = D.createSettle();
  s.start(1000);
  assert.ok(s.active(1399));
  assert.ok(!s.active(1400));
  s.start(2000);
  assert.equal(s.move(10, 10, 2010), false, 'premier mouvement : origine');
  assert.equal(s.move(12, 11, 2020), false);
  assert.equal(s.move(14, 10, 2030), true);
  assert.ok(!s.active(2031));
  const seen = D.createDedupe();
  assert.equal(seen('k1', 0), false);
  assert.equal(seen('k1', 499), true);
  assert.equal(seen('k2', 499), false);
  assert.equal(seen('k2', 1200), false);
});

test('mouvement réduit suivi en direct, jusqu’au désabonnement', () => {
  const ls = new Set(), mq = { matches: false, addEventListener: (_, fn) => ls.add(fn), removeEventListener: (_, fn) => ls.delete(fn) };
  const saved = globalThis.matchMedia;
  globalThis.matchMedia = () => mq;
  try {
    const seen = [], stop = M.watchReducedMotion((r) => seen.push(r));
    mq.matches = true; for (const fn of [...ls]) fn();
    stop();
    mq.matches = false; for (const fn of [...ls]) fn();
    assert.deepEqual(seen, [false, true]);
    assert.equal(ls.size, 0);
  } finally { globalThis.matchMedia = saved; }
});

test('sortie en cascade inversée : la dernière ligne d’abord, 20 ms, plafond 8', () => {
  assert.deepEqual([0, 1, 2].map((i) => F.reverseStagger(i, 3)), [40, 20, 0]);
  assert.deepEqual([F.reverseStagger(0, 12), F.reverseStagger(11, 12)], [140, 0]);
});
