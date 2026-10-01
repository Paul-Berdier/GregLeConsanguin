import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';
const { stageScene, kickerKey, requesterOf, requesterKeys, sealInitial, kingSealSrc, seedOf } = await loadTs('../src/lib/stage/scene.ts');
// Deck lu directement (copy.ts importe son JSON : voir loadCopy dans copy.test.mjs).
const deck = JSON.parse(readFileSync(new URL('../src/theme/copy.v2.json', import.meta.url), 'utf8'));
const at = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);

test('scène : chargement, déconnecté, rien en lecture, jour', () => {
  assert.equal(stageScene({ booted: false, loggedIn: true, hasCurrent: true }), 'loading');
  assert.equal(stageScene({ booted: true, loggedIn: false, hasCurrent: false }), 'out');
  assert.equal(stageScene({ booted: true, loggedIn: true, hasCurrent: false }), 'empty');
  assert.equal(stageScene({ booted: true, loggedIn: true, hasCurrent: true }), 'day');
});

test('surtitre : en lecture, en pause, en boucle (textes du deck)', () => {
  assert.equal(at(kickerKey({ paused: false, repeat: false })), 'En lecture');
  assert.equal(at(kickerKey({ paused: true, repeat: true })), 'En pause');
  assert.equal(at(kickerKey({ paused: false, repeat: true })), 'En boucle');
});

test('demandeur : le Roi (l’utilisateur), un courtisan, inconnu', () => {
  assert.deepEqual(requesterOf({ id: '101', name: 'Paul' }, '101'), { kind: 'mine' });
  assert.deepEqual(requesterOf({ id: '102', name: ' Léa ' }, '101'), { kind: 'other', name: 'Léa' });
  assert.deepEqual(requesterOf({ id: '99', name: '' }, '101'), { kind: 'unknown' });
  assert.deepEqual(requesterOf(null, '101'), { kind: 'unknown' });
  assert.deepEqual(requesterOf({ id: '101', name: 'Paul' }, null), { kind: 'other', name: 'Paul' });
});

test('demandeur : clés du deck présentes', () => {
  assert.equal(at(requesterKeys({ kind: 'mine' }).plain), 'Demandé par vous');
  assert.equal(at(requesterKeys({ kind: 'other', name: 'Léa' }).plain), 'Demandé par {name}');
  assert.equal(at(requesterKeys({ kind: 'unknown' }).plain), 'Ajouté depuis Discord');
  assert.equal(requesterKeys({ kind: 'unknown' }).quips, null);
  for (const k of ['mine', 'other']) assert.ok(Array.isArray(at(`${requesterKeys({ kind: k, name: 'x' }).quips}.quips`)), k);
});

test('sceau du Roi : initiale A–Z sans accent, sinon fleur de lys ; le fichier existe', () => {
  assert.equal(sealInitial('Élodie'), 'E');
  assert.equal(sealInitial('paul'), 'P');
  assert.equal(sealInitial('42paul'), 'P');
  // lettres latines que NFD ne décompose pas : ramenées à leur lettre de base
  assert.equal(sealInitial('Øyvind'), 'O');
  assert.equal(sealInitial('łukasz'), 'L');
  assert.equal(sealInitial('Ærø'), 'A');
  assert.equal(sealInitial('Œdipe'), 'O');
  assert.equal(sealInitial('Đorđe'), 'D');
  assert.equal(sealInitial('Þór'), 'T');
  // lettres stylisées des pseudos Discord (mathématiques, pleine chasse) : leur lettre latine
  assert.equal(sealInitial('𝓹𝓪𝓾𝓵'), 'P');
  assert.equal(sealInitial('Ｌéa'), 'L');
  assert.equal(sealInitial('☆☆'), 'fleur');
  assert.equal(sealInitial(''), 'fleur');
  assert.equal(sealInitial(null), 'fleur');
  for (const n of ['Élodie', '☆']) {
    const f = fileURLToPath(new URL(`../public${kingSealSrc(n)}`, import.meta.url));
    assert.ok(existsSync(f), f);
  }
});

test('graine de réplique stable et répartie', () => {
  assert.equal(seedOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), seedOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ'));
  assert.notEqual(seedOf('a'), seedOf('b'));
  assert.ok(Number.isInteger(seedOf('x')) && seedOf('x') >= 0);
});
