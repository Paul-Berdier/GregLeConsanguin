// Régulateur de la vidéo (spec synchro son/vidéo §6.1) : seuils, hystérésis, attente, repli en sauts, démarrage gardé.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const {
  decide, afterDecision, whenHidden, nextHold, rateCheck, gateLoad, CTL_INIT, CTL_TICK_MS, HOLD_MS, SEEK_SETTLE_MS,
  NORATE_GAP_MS, COMPAT_GAP_MS, RATE_CONFIRM_MS,
} = await loadTs('../src/lib/sync/controller.ts');

const NOW = 100_000;
// cible 0 : écarts exacts en flottants (60 + 0.04 − 60 < 0.04)
const d = (err, o = {}) => decide({ target: 0, current: err, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW, ...o });

test('4 Hz', () => { assert.equal(CTL_TICK_MS, 250); });

test('seuils : zone morte < 40 ms, ×0,95 / ×1,05 jusqu’à 300 ms, ×0,90 / ×1,10 jusqu’à 2 s, saut au-delà', () => {
  assert.equal(d(0), null);
  assert.equal(d(0.039), null);
  assert.equal(d(-0.039), null);
  assert.deepEqual(d(0.04), { rate: 0.95 }, 'en avance : ralentit');
  assert.deepEqual(d(-0.04), { rate: 1.05 }, 'en retard : accélère');
  assert.deepEqual(d(0.3), { rate: 0.95 });
  assert.deepEqual(d(-0.31), { rate: 1.1 });
  assert.deepEqual(d(2), { rate: 0.9 });
  assert.deepEqual(d(2.01), { seek: 0 });
  assert.deepEqual(d(-5), { seek: 0 });
  assert.deepEqual(decide({ target: 60, current: 65, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), { seek: 60 }, 'saut à la cible');
  assert.deepEqual(decide({ target: -0.2, current: 5, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), { seek: 0 }, 'jamais négatif');
});

test('hystérésis : un recalage en cours continue jusqu’à 15 ms, puis ×1', () => {
  const nudging = { ...CTL_INIT, rate: 0.95 };
  assert.equal(d(0.02, { state: nudging }), null, 'garde ×0,95 dans la zone morte');
  assert.deepEqual(d(-0.02, { state: nudging }), { rate: 1.05 }, 'dépassé : sens inverse');
  assert.deepEqual(d(0.014, { state: nudging }), { rate: 1 });
  assert.deepEqual(d(0.1, { state: { ...CTL_INIT, rate: 0.9 } }), { rate: 0.95 }, 'sous 300 ms : petit pas');
  assert.equal(d(0.5, { state: { ...CTL_INIT, rate: 0.9 } }), null, 'déjà à la bonne vitesse');
});

test('attente : ×1 et rien d’autre pendant HOLD_MS (reprise, blocage, nouveau play_id)', () => {
  assert.equal(HOLD_MS, 3000);
  assert.equal(d(1, { holdUntil: NOW + 1 }), null);
  assert.equal(d(5, { holdUntil: NOW + 1 }), null, 'pas même un saut');
  assert.deepEqual(d(1, { holdUntil: NOW + 1, state: { ...CTL_INIT, rate: 1.1 } }), { rate: 1 });
  assert.deepEqual(d(1, { holdUntil: NOW }), { rate: 0.9 }, 'échue');
});

test('un saut à la fois : SEEK_SETTLE_MS entre deux sauts', () => {
  const justSeeked = { ...CTL_INIT, lastSeekAt: NOW - SEEK_SETTLE_MS + 1 };
  assert.equal(d(3, { state: justSeeked }), null);
  assert.deepEqual(d(3, { state: { ...CTL_INIT, lastSeekAt: NOW - SEEK_SETTLE_MS } }), { seek: 0 });
});

test('sans vitesse confirmée : sauts seuls, seuil 250 ms, 10 s entre deux sauts', () => {
  assert.equal(d(0.25, { rateOk: false }), null);
  assert.deepEqual(d(0.26, { rateOk: false }), { seek: 0 });
  assert.equal(d(0.5, { rateOk: false, state: { ...CTL_INIT, lastSeekAt: NOW - NORATE_GAP_MS + 1 } }), null);
  assert.deepEqual(d(0.5, { rateOk: false, state: { ...CTL_INIT, rate: 1.05 } }), { rate: 1 }, 'retour à ×1 d’abord');
});

test('ancien bot (sans clock) : l’ancien régime, 1,2 s et 15 s entre deux sauts', () => {
  assert.equal(d(1.2, { compat: true }), null);
  assert.deepEqual(d(-1.3, { compat: true }), { seek: 0 });
  assert.equal(d(3, { compat: true, state: { ...CTL_INIT, lastSeekAt: NOW - COMPAT_GAP_MS + 1 } }), null);
});

test('valeurs illisibles : rien', () => {
  assert.equal(decide({ target: Number.NaN, current: 1, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), null);
  assert.equal(decide({ target: 1, current: undefined, state: CTL_INIT, rateOk: true, holdUntil: 0, now: NOW }), null);
});

test('afterDecision : vitesse retenue, instant du saut noté', () => {
  assert.equal(afterDecision(CTL_INIT, null, NOW), CTL_INIT);
  assert.deepEqual(afterDecision(CTL_INIT, { rate: 1.05 }, NOW), { rate: 1.05, lastSeekAt: -Infinity });
  assert.deepEqual(afterDecision({ rate: 1.05, lastSeekAt: 0 }, { seek: 12 }, NOW), { rate: 1.05, lastSeekAt: NOW });
});

test('onglet caché : aucune correction, une vitesse ≠ ×1 revient à ×1 (l’écart ne se creuse pas jusqu’au retour)', () => {
  assert.equal(whenHidden(CTL_INIT), null);
  for (const rate of [0.9, 0.95, 1.05, 1.1]) assert.deepEqual(whenHidden({ ...CTL_INIT, rate }), { rate: 1 }, `×${rate}`);
  const s = { rate: 1.1, lastSeekAt: 7 };
  assert.equal(whenHidden(afterDecision(s, whenHidden(s), NOW)), null, 'une fois suffit');
  assert.equal(afterDecision(s, whenHidden(s), NOW).lastSeekAt, 7, 'aucun saut');
});

test('nextHold : à chaque entrée en lecture et à chaque nouveau play_id', () => {
  const P = (status, playId = 'p1') => ({ playId, status });
  assert.equal(nextHold(null, P('playing'), NOW, 0), NOW + HOLD_MS, 'premier état');
  assert.equal(nextHold(P('paused'), P('playing'), NOW, 0), NOW + HOLD_MS, 'reprise');
  assert.equal(nextHold(P('stalled'), P('playing'), NOW, 0), NOW + HOLD_MS, 'fin de blocage');
  assert.equal(nextHold(P('playing'), P('playing', 'p2'), NOW, 0), NOW + HOLD_MS, 'nouveau play_id');
  assert.equal(nextHold(P('playing'), P('playing'), NOW, 7), 7, 'rien de neuf');
  assert.equal(nextHold(P('playing'), P('stalled'), NOW, 7), 7, 'en blocage : la vidéo attend déjà');
});

test('rateCheck : attend RATE_CONFIRM_MS, puis compare à getPlaybackRate()', () => {
  const asked = { rate: 1.05, at: NOW };
  assert.equal(rateCheck(null, 1, NOW), 'ok');
  assert.equal(rateCheck(asked, 1, NOW + RATE_CONFIRM_MS - 1), 'wait');
  assert.equal(rateCheck(asked, 1.05, NOW + RATE_CONFIRM_MS), 'ok');
  assert.equal(rateCheck(asked, 1, NOW + RATE_CONFIRM_MS), 'failed', 'YouTube a arrondi à 1');
  assert.equal(rateCheck(asked, undefined, NOW + RATE_CONFIRM_MS), 'failed');
});

test('démarrage gardé : la vidéo attend que le bot joue ce titre sous un nouveau play_id', () => {
  const V = 'aaaaaaaaaaa', none = { id: null, playId: null };
  const C = (status, playId = 'p1') => ({ playId, status, compat: false });
  assert.equal(gateLoad(C('loading'), V, V, none), false, 'chargement : le poster reste');
  assert.equal(gateLoad(C('playing'), 'bbbbbbbbbbb', V, none), false, 'le bot joue encore l’ancien titre (saut optimiste)');
  assert.equal(gateLoad(C('playing'), null, V, none), false, 'lien du play_id inconnu');
  assert.equal(gateLoad(C('playing'), V, V, none), true);
  assert.equal(gateLoad(C('playing'), V, V, { id: V, playId: 'p1' }), false, 'déjà chargée');
  assert.equal(gateLoad(C('playing', 'p2'), V, V, { id: V, playId: 'p1' }), true, '« Depuis le début », boucle');
  assert.equal(gateLoad(C('playing'), V, null, none), false);
});

test('démarrage gardé, ancien bot ou aucun état : dès que le titre change, comme avant', () => {
  const V = 'aaaaaaaaaaa';
  assert.equal(gateLoad({ playId: null, status: 'playing', compat: true }, null, V, { id: null, playId: null }), true);
  assert.equal(gateLoad({ playId: null, status: 'playing', compat: true }, null, V, { id: V, playId: null }), false);
  assert.equal(gateLoad({ playId: null, status: null, compat: false }, null, V, { id: null, playId: null }), true);
});
