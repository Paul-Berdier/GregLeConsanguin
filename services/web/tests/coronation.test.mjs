// Le Couronnement (étape 4) : jetons, courbe, vol, source visible, modes, plans, ordres du Roi.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const C = await loadTs('../src/lib/stage/coronation.ts');
const M = await loadTs('../src/lib/motion.ts');

test('jetons : vol 420 ms (= --dur-flight), Héraut 80 ms après, rafale 1,5 s, lune 240 ms', () => {
  assert.equal(C.FLIGHT_MS, M.DUR.flight);
  assert.equal(C.AFTER_CEREMONY_MS, M.DUR.flight + 80);
  assert.deepEqual([C.QUICK_WINDOW_MS, C.NIGHT_ROSE_FADE_MS, C.BUSY_MS], [1500, 240, 1300]);
});

test('bezier : bornes, monotone ; --ease-drawer à 95 % du trajet à mi-temps', () => {
  const f = C.easeDrawer;
  assert.deepEqual([f(0), f(1)], [0, 1]);
  let prev = 0;
  for (let i = 1; i <= 100; i++) { const v = f(i / 100); assert.ok(v >= prev - 1e-9, `${i}`); prev = v; }
  assert.ok(Math.abs(f(0.25) - 0.7791) < 1e-3 && Math.abs(f(0.5) - 0.9548) < 1e-3);
  assert.ok(Math.abs(C.bezier(0, 0, 1, 1)(0.3) - 0.3) < 1e-6);
});

test('vol : 13 images clés en transform seul, de la pochette à la scène, sans recul', () => {
  const kf = C.flightFrames({ left: 1000, top: 300, width: 72, height: 40.5 }, { left: 100, top: 200, width: 648, height: 364.5 });
  assert.equal(kf.length, 13);
  assert.deepEqual(Object.keys(kf[0]).sort(), ['offset', 'transform']);
  assert.deepEqual([kf[0].offset, kf[12].offset], [0, 1]);
  assert.equal(kf[0].transform, 'translate(1000px, 300px) scale(0.1111)');
  assert.equal(kf[12].transform, 'translate(100px, 200px) scale(1)');
  const xs = kf.map((k) => Number(/translate\(([-\d.]+)px/.exec(k.transform)[1]));
  for (let i = 1; i < xs.length; i++) assert.ok(xs[i] <= xs[i - 1], `${i}`);
});

test('source visible à moitié au moins ; une ligne repliée ne l’est pas', () => {
  const c = { left: 0, top: 100, width: 400, height: 500 }, r = (top, h = 40) => ({ left: 10, top, width: h ? 72 : 0, height: h });
  assert.deepEqual([120, 80, 70, 580, 590].map((y) => C.visibleIn(r(y), c)), [true, true, false, true, false]);
  assert.equal(C.visibleIn(r(120, 0), c), false);
});

test('mode : vol à la souris ; rapide au clavier, en rafale ou sans ordre ; repli si la nuit se lève', () => {
  const b = { via: 'pointer', sinceLast: 5000, reduced: false, canFly: true, fromNight: false };
  const m = (o) => C.crownMode({ ...b, ...o });
  assert.deepEqual([m({}), m({ canFly: false }), m({ via: 'key' }), m({ via: null }), m({ sinceLast: 900 }), m({ fromNight: true })],
    ['flight', 'fallback', 'quick', 'quick', 'quick', 'fallback']);
  assert.equal(m({ reduced: true, fromNight: true }), 'reduced');
});

test('plans de chaque mode (DESIGN §5, motion.md §6.10 et §8)', () => {
  const [f, b, q, r] = ['flight', 'fallback', 'quick', 'reduced'].map(C.crownPlan);
  assert.deepEqual([f.titleDelay, f.metaDelay, f.exitMs, f.enterMs, f.shift, f.roseAt, f.roseFade, f.glintAt], [160, 200, 180, 280, 8, 420, 900, 420]);
  assert.deepEqual([b.posterMs, b.roseAt, b.roseFade, b.glintAt], [420, 0, 900, 380]);
  assert.deepEqual([q.titleDelay, q.metaDelay, q.posterMs, q.roseFade, q.glintAt], [0, 40, 210, 450, null]);
  assert.deepEqual([r.shift, r.exitMs, r.enterMs, r.posterMs, r.roseFade, r.glintAt], [0, 150, 150, 200, 300, null]);
});

test('un plan rendu est à son appelant : le retoucher n’altère pas la cérémonie suivante', () => {
  const p = C.crownPlan('flight');
  p.titleDelay = 999; p.glintAt = null;
  assert.deepEqual([C.crownPlan('flight').titleDelay, C.crownPlan('flight').glintAt], [160, 420]);
  assert.notEqual(C.crownPlan('quick'), C.crownPlan('quick'));
});

test('ordres du Roi : clé précise ou « le suivant », 4 s, pris une fois', () => {
  const I = C.createOrders();
  I.mark('k3', 'pointer', 1000);
  assert.equal(I.take('k9', 'k1', 1100), null, 'un autre titre : l’ordre attend');
  assert.deepEqual(I.take('k3', 'k1', 1200), { target: 'k3', via: 'pointer', at: 1000 });
  assert.equal(I.take('k3', 'k1', 1300), null);
  I.mark(C.NEXT, 'key', 2000);
  assert.equal(I.take('k5', 'k4', 2100), null, 'k5 n’était pas le suivant');
  assert.equal(I.take('k4', 'k4', 2200)?.via, 'key');
  I.mark('k7', 'pointer', 3000);
  assert.equal(I.take('k7', null, 3000 + C.ORDER_TTL_MS + 1), null, 'périmé');
});

test('boxOf lit un rectangle du DOM', () => {
  assert.deepEqual(C.boxOf({ getBoundingClientRect: () => ({ left: 1, top: 2, width: 3, height: 4, right: 4, bottom: 6 }) }),
    { left: 1, top: 2, width: 3, height: 4 });
});
