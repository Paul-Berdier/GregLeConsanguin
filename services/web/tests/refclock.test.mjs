// Horloge de référence du son (spec synchro son/vidéo §6.1) : ordre des échantillons, recalages, mode compatibilité.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const { createRefClock, clockSampleOf, clockViewOf, predict, NO_CLOCK, REANCHOR_MS } = await loadTs('../src/lib/sync/refclock.ts');

const T = 1_790_846_494_000;
const S = (o = {}) => ({ play_id: 'p1', status: 'playing', position_ms: 10_000, at: T, compat: false, ...o });
const state = (clock, extra = {}) => ({ current: { url: 'https://youtu.be/aaaaaaaaaaa' }, position: 10, clock, ...extra });

test('échantillon d’un état : clock, relay_at_ms d’abord, sampled_at_ms en repli', () => {
  const clock = { play_id: 'a1b2c3d4', status: 'playing', position_ms: 83_460, sampled_at_ms: T };
  assert.deepEqual(clockSampleOf(state(clock, { relay_at_ms: T + 3 }), 0),
    { play_id: 'a1b2c3d4', status: 'playing', position_ms: 83_460, at: T + 3, compat: false });
  assert.equal(clockSampleOf(state(clock), 0).at, T);
  // REST : { ok, state: {…} } ; tick : only_elapsed
  assert.equal(clockSampleOf({ ok: true, state: state(clock, { relay_at_ms: T + 9 }) }, 0).at, T + 9);
  assert.equal(clockSampleOf({ only_elapsed: true, position: 83, clock, relay_at_ms: T + 1 }, 0).position_ms, 83_460);
  // chargement : position null
  assert.equal(clockSampleOf(state({ ...clock, status: 'loading', position_ms: null, play_id: null }), 0).position_ms, null);
});

test('échantillon : état périmé ou illisible → null ; sans clock → compatibilité, ancré à la réception', () => {
  assert.equal(clockSampleOf({ ok: false, stale: true, backend_error: 'TIMEOUT' }, 5), null);
  assert.equal(clockSampleOf(null, 5), null);
  assert.equal(clockSampleOf({ position: 'abc' }, 5), null);
  assert.deepEqual(clockSampleOf({ current: { title: 'A' }, position: 83, is_paused: false }, 5000),
    { play_id: null, status: 'playing', position_ms: 83_000, at: 5000, compat: true });
  assert.equal(clockSampleOf({ only_elapsed: true, position: 7, paused: true }, 1).status, 'paused');
  assert.equal(clockSampleOf({ current: null, queue: [], position: 0 }, 1).status, 'idle');
  // un statut inconnu : traité comme un ancien bot
  assert.equal(clockSampleOf(state({ status: 'bogus', sampled_at_ms: T }), 1).compat, true);
});

test('positionAt : avance en lecture, figée en pause, en blocage, en chargement', () => {
  const rc = createRefClock();
  assert.equal(rc.positionAt(T), null);
  assert.equal(rc.ingest(S()), 'anchored');
  assert.equal(rc.positionAt(T + 1500), 11_500);
  for (const status of ['paused', 'stalled']) {
    rc.ingest(S({ status, at: T + 2000, position_ms: 12_000 }));
    assert.equal(rc.positionAt(T + 60_000), 12_000, status);
  }
  rc.ingest(S({ play_id: 'p2', status: 'loading', position_ms: null, at: T + 3000 }));
  assert.equal(rc.positionAt(T + 9000), null);
  assert.equal(predict(S({ position_ms: 0, at: T }), T - 500), 0, 'jamais négative');
});

test('ticks conformes à la prédiction : l’ancre ne bouge pas (zone de 40 ms)', () => {
  const rc = createRefClock();
  rc.ingest(S());
  assert.equal(REANCHOR_MS, 40);
  assert.equal(rc.ingest(S({ at: T + 1000, position_ms: 11_020 })), 'kept');
  assert.equal(rc.ingest(S({ at: T + 2000, position_ms: 11_960 })), 'kept');
  assert.equal(rc.anchor().at, T, 'ancre d’origine');
  assert.equal(rc.ingest(S({ at: T + 3000, position_ms: 13_041 })), 'anchored', 'écart > 40 ms : recalée');
  assert.equal(rc.positionAt(T + 3000), 13_041);
});

test('recalage sur un changement de play_id ou de statut, même à position égale', () => {
  const rc = createRefClock();
  rc.ingest(S());
  assert.equal(rc.ingest(S({ at: T + 1000, position_ms: 11_000, status: 'paused' })), 'anchored');
  assert.equal(rc.ingest(S({ at: T + 5000, position_ms: 11_000, status: 'paused' })), 'kept');
  assert.equal(rc.ingest(S({ at: T + 6000, position_ms: 11_000 })), 'anchored', 'reprise');
  assert.equal(rc.ingest(S({ at: T + 7000, position_ms: 0, play_id: 'p2' })), 'anchored');
  assert.equal(rc.anchor().play_id, 'p2');
});

test('un échantillon plus ancien que l’ancre est ignoré (REST lente après un tick)', () => {
  const rc = createRefClock();
  rc.ingest(S({ at: T + 5000, position_ms: 15_000 }));
  assert.equal(rc.ingest(S({ at: T + 4000, position_ms: 10_000, play_id: 'old' })), 'stale');
  assert.equal(rc.anchor().play_id, 'p1');
  assert.equal(rc.positionAt(T + 6000), 16_000);
});

test('mode compatibilité : recalée à chaque état, comme avant ; passage au bot neuf sans blocage', () => {
  const rc = createRefClock();
  assert.equal(rc.ingest({ play_id: null, status: 'playing', position_ms: 83_000, at: 5000, compat: true }), 'anchored');
  assert.equal(rc.ingest({ play_id: null, status: 'playing', position_ms: 84_000, at: 6000, compat: true }), 'anchored');
  assert.equal(rc.positionAt(6500), 84_500);
  assert.equal(rc.ingest(S({ at: 10 })), 'anchored', 'un bloc clock, même daté « avant » l’ancre de réception');
  rc.reset();
  assert.equal(rc.anchor(), null);
});

test('vue de l’horloge : lien du play_id gardé par les ticks, même objet si rien ne change', () => {
  const a1 = S({ status: 'loading', position_ms: null });
  const v1 = clockViewOf(NO_CLOCK, a1, 'https://youtu.be/aaaaaaaaaaa');
  assert.deepEqual(v1, { playId: 'p1', status: 'loading', compat: false, url: 'https://youtu.be/aaaaaaaaaaa' });
  const v2 = clockViewOf(v1, S(), undefined);                     // tick : même play_id, lien gardé
  assert.deepEqual(v2, { ...v1, status: 'playing' });
  assert.equal(clockViewOf(v2, S(), undefined), v2, 'même objet');
  assert.equal(clockViewOf(v2, S({ play_id: 'p2' }), undefined).url, null, 'autre play_id : lien inconnu');
  assert.equal(clockViewOf(v2, null), NO_CLOCK);
});
