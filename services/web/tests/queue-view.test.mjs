// Vue de la file (étape 3) : heures estimées, fin de file, « Souvent demandés ici », historique, blasons, annulations.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const V = await loadTs('../src/lib/queue/view.ts');
const A = await loadTs('../src/lib/queue/arms.ts');
const U = await loadTs('../src/lib/queue/undo.ts');
const NB = ' ';
const T = (key, duration = 240, extra = {}) => ({ key, url: `https://www.youtube.com/watch?v=${key.padEnd(11, 'x')}`, duration, ...extra });

test('heure estimée : reste du titre en cours puis durées cumulées, « À suivre » pour le premier', () => {
  const etas = V.queueEtas([T('a', 300), T('b', 120), T('c')], 90);
  assert.deepEqual(etas.map((e) => [e.key, e.next, e.mins]), [['a', true, 2], ['b', false, 7], ['c', false, 9]]);
  assert.equal(V.queueEtas([T('a')], 0)[0].mins, 1, 'jamais « dans 0 min »');
  assert.deepEqual(V.queueEtas([T('a', null), T('b')], 60).map((e) => e.mins), [1, null], 'après un titre sans durée : inconnu');
});

test('durée longue et heure à la française (espaces insécables)', () => {
  assert.equal(V.fmtLong(47 * 60), `47${NB}min`);
  assert.equal(V.fmtLong(65 * 60), `1${NB}h${NB}05`);
  assert.equal(V.fmtLong(0), `0${NB}min`);
  assert.equal(V.clockText(new Date(2026, 8, 27, 22, 47)), `22${NB}h${NB}47`);
  assert.equal(V.clockText(new Date(2026, 8, 27, 9, 5)), `9${NB}h${NB}05`);
  const now = new Date(2026, 8, 27, 22, 0).getTime();
  assert.equal(V.clockText(V.endsAt(now, 120, [T('a', 1500), T('b', null), T('c', 1200)])), `22${NB}h${NB}47`);
  assert.equal(V.queueSeconds([T('a', 60), T('b', null)]), 60);
});

test('« Souvent demandés ici » : 3 au plus, ni en lecture ni dans la file (même vidéo sous une autre url)', () => {
  const H = (id, n) => ({ url: `https://www.youtube.com/watch?v=${id}`, title: id, play_count: n });
  const top = [H('aaaaaaaaaaa', 9), H('bbbbbbbbbbb', 8), H('ccccccccccc', 7), H('ddddddddddd', 6), H('eeeeeeeeeee', 5)];
  const queue = [{ url: 'https://youtu.be/bbbbbbbbbbb' }];
  assert.deepEqual(V.oftenAsked(top, queue, 'https://www.youtube.com/watch?v=aaaaaaaaaaa&list=RDx').map((h) => h.title),
    ['ccccccccccc', 'ddddddddddd', 'eeeeeeeeeee']);
  assert.deepEqual(V.oftenAsked([H('aaaaaaaaaaa', 2), H('aaaaaaaaaaa', 1), { title: 'sans url' }], [], null).length, 1, 'doublons et titres sans url écartés');
});

test('moment relatif de l’historique ; méta sans demandeur connu', () => {
  const now = Date.UTC(2026, 8, 27, 12) ;
  const at = (s) => V.agoOf(now / 1000 - s, now);
  assert.deepEqual(at(20), { unit: 'now', n: 0 });
  assert.deepEqual(at(5 * 60), { unit: 'min', n: 5 });
  assert.deepEqual(at(3 * 3600 + 10), { unit: 'h', n: 3 });
  assert.deepEqual(at(30 * 3600), { unit: 'yesterday', n: 1 });
  assert.deepEqual(at(4 * 86400), { unit: 'd', n: 4 });
  assert.equal(V.agoOf(undefined, now), null);
  assert.equal(V.dropEmptyTail('14 écoutes · '), '14 écoutes');
  assert.equal(V.dropEmptyTail('14 écoutes · Hugo'), '14 écoutes · Hugo');
});

test('blason : stable par personne, jamais de rouge, pièce lisible sur son champ, les six partitions servent', () => {
  assert.deepEqual(A.armsOf('101'), A.armsOf('101'));
  const seen = new Set();
  const hue = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    if (!d) return { h: 0, s: 0 };
    const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return { h: (h * 60 + 360) % 360, s: d / (1 - Math.abs(max + min - 1)) };
  };
  for (let i = 0; i < 400; i++) {
    const a = A.armsOf(String(100000 + i * 7919));
    seen.add(a.d);
    assert.notEqual(a.a, a.b);
    for (const c of [a.a, a.b]) { const { h, s } = hue(c); assert.ok(!(s > 0.35 && (h < 20 || h > 340)), `rouge : ${c}`); }
    if (a.a === '#c99a2e') assert.equal(a.b, A.DARK, 'sur l’or, une pièce sombre');
  }
  assert.equal(seen.size, A.DIVISIONS.length);
});

test('annuler l’ajout : les titres apparus, ceux du Roi seulement', () => {
  const before = ['a', 'b'];
  const after = [T('a'), T('b'), T('x', 1, { addedBy: { id: '101', name: 'Paul' } }), T('y', 1, { addedBy: { id: '102', name: 'Hugo' } }), T('z', 1, { addedBy: { id: '101', name: 'Paul' } })];
  assert.deepEqual(U.addedKeys(before, after, '101'), ['x', 'z']);
  assert.deepEqual(U.addedKeys(['a', 'b', 'x', 'y', 'z'], after, '101'), []);
});

test('annuler un retrait : la ligne revenue et le titre devant lequel la replacer', () => {
  const url = 'https://youtu.be/b';
  const after = [T('a'), T('c'), T('d'), { key: 'b2', url }];
  assert.deepEqual(U.restorePlan(['a', 'c', 'd'], after, url, 1), { key: 'b2', beforeKey: 'c' });
  assert.deepEqual(U.restorePlan(['a', 'c', 'd'], after, url, 3), { key: 'b2', beforeKey: null }, 'ancienne place en fin de file');
  assert.equal(U.restorePlan(['a', 'c', 'd'], [T('a'), T('c'), T('d')], url, 1), null, 'refusé (quota) : rien à déplacer');
  const twice = [{ key: 'b1', url }, T('a'), { key: 'b2', url }];
  assert.equal(U.restorePlan(['b1', 'a'], twice, url, 0).key, 'b2', 'la nouvelle, pas le doublon déjà là');
});
