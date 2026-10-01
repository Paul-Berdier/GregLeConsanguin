// Mesure de l'horloge de l'API (spec synchro son/vidéo §6.1) : filtre au plus court aller-retour, rejet des aberrations.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const { createTimeSync, sampleOf, TS_KEEP, TS_MAX_RTT_MS } = await loadTs('../src/lib/sync/timesync.ts');

test('un échantillon : offset = ts − (t0 + t1) / 2, rtt = t1 − t0', () => {
  assert.deepEqual(sampleOf(1000, 1_790_000_000_050, 1100), { offset: 1_790_000_000_050 - 1050, rtt: 100 });
});

test('échantillons aberrants rejetés : aller-retour négatif, > 2 s, valeurs illisibles', () => {
  assert.equal(TS_MAX_RTT_MS, 2000);
  assert.equal(sampleOf(1000, 5, 900), null);
  assert.equal(sampleOf(0, 5, 2001), null);
  assert.notEqual(sampleOf(0, 5, 2000), null);
  for (const bad of [Number.NaN, Infinity, undefined, '12', null]) assert.equal(sampleOf(0, bad, 10), null, String(bad));
});

test('retient l’aller-retour le plus court ; serverNow suit son offset', () => {
  const ts = createTimeSync();
  assert.equal(ts.best(), null);
  assert.equal(ts.serverNow(5000), null);
  assert.equal(ts.add(0, 10_050, 100), true);    // rtt 100, offset 10 000
  assert.equal(ts.add(200, 10_230, 220), true);  // rtt 20, offset 10 020
  assert.equal(ts.add(300, 10_400, 500), true);  // rtt 200
  assert.deepEqual(ts.best(), { offset: 10_020, rtt: 20 });
  assert.equal(ts.serverNow(5000), 15_020);
  assert.equal(ts.add(0, 1, 5000), false, 'rejeté : rien ne change');
  assert.deepEqual(ts.best(), { offset: 10_020, rtt: 20 });
});

test('fenêtre des TS_KEEP dernières mesures : le meilleur ancien finit par sortir', () => {
  const ts = createTimeSync();
  assert.equal(TS_KEEP, 8);
  ts.add(0, 1000, 10);                                         // rtt 10, offset 995
  for (let i = 1; i <= 7; i++) ts.add(i * 100, 5000 + i * 100, i * 100 + 50);   // rtt 50
  assert.equal(ts.best().rtt, 10);
  ts.add(900, 6000, 950);                                      // 9e mesure : la première sort
  assert.equal(ts.best().rtt, 50);
  ts.reset();
  assert.equal(ts.best(), null);
});
