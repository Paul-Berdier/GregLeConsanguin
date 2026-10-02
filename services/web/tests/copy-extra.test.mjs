// Compléments au deck (étape 3) : typographie du deck, pas de doublon avec lui, casting.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';

const { EXTRA, KEYS, tx } = await loadTs('../src/theme/copy.extra.ts');
const deck = JSON.parse(readFileSync(new URL('../src/theme/copy.v2.json', import.meta.url), 'utf8'));

function* strings(node, path = '') {
  if (typeof node === 'string') { yield [path, node]; return; }
  for (const [k, v] of Object.entries(node)) yield* strings(v, path ? `${path}.${k}` : k);
}

test('tx remplit les jetons, choisit le pluriel, rend le chemin inconnu', () => {
  assert.equal(tx('queue.eta', { n: 9 }), 'dans 9 min');
  assert.equal(tx('queue.more', { n: 1 }), '…et 1 autre titre');
  assert.equal(tx('queue.more', { n: 94 }), '…et 94 autres titres');
  assert.equal(tx('queue.endsAt', {}), 'fin vers {time}');
  assert.equal(tx('queue.nope'), 'queue.nope');
  assert.equal(tx('queue'), 'queue', 'une section n’est pas un texte');
});

test('typographie du deck : U+00A0 avant « : », U+202F avant ; ! ?, apostrophe courbe', () => {
  for (const [path, s] of strings(EXTRA)) {
    assert.ok(!/ [:;!?]/.test(s), `${path} : espace ordinaire avant la ponctuation haute`);
    assert.ok(!/[^ \s]:(?!\d)/.test(s.replace(/\{\w+\}/g, '')), `${path} : « : » sans espace insécable`);
    assert.ok(!/[;!?]/.test(s.replace(/ [;!?]/g, '')), `${path} : ; ! ? sans U+202F`);
    assert.ok(!s.includes("'"), `${path} : apostrophe droite`);
  }
});

test('aucun complément ne double une clé du deck ; aucun ne couronne Greg', () => {
  const at = (p) => p.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);
  for (const [path, s] of strings(EXTRA)) {
    assert.equal(at(path), undefined, `${path} existe déjà dans le deck`);
    assert.ok(!/Greg[^.]*\b(roi|couronne|Rex)\b/i.test(s), `${path} : ${s}`);
  }
});

test('raccourcis de l’étape 4 : Espace, Maj+→, Maj+← ; ni N, ni P, ni R ; libellés au format du deck', () => {
  const keys = KEYS.map(([k]) => k);
  assert.deepEqual(keys.slice(0, 3), ['Espace', 'Maj+→', 'Maj+←']);
  for (const k of ['/', '?', 'Ctrl+Z', '↑ ↓', 'Entrée', 'Alt+↑ ↓', 'Alt+Début', 'Suppr', 'Échap']) assert.ok(keys.includes(k), k);
  for (const bad of ['N', 'P', 'R']) assert.ok(!keys.includes(bad), bad);
  for (const [, label] of KEYS) assert.ok(label && !/ [:;!?]/.test(label) && !label.includes("'"), label);
});

test('textes de l’étape 4 : interrupteur, bulles, lien d’évitement, annonces', () => {
  assert.equal(tx('keys.toggle'), 'Raccourcis clavier');
  assert.equal(tx('transport.skipTip'), 'Suivant (Maj+→)');
  assert.equal(tx('transport.restartTip'), 'Depuis le début (Maj+←)');
  assert.equal(tx('a11y.skipToQueue'), 'Aller à la file');
  assert.equal(tx('a11y.nowPlaying', { title: 'Africa' }), 'En lecture : Africa');
  for (const k of ['keys.toggleHelp', 'keys.on', 'keys.off', 'transport.repeatTip', 'a11y.paused', 'a11y.resumed']) assert.notEqual(tx(k), k, k);
});

test('Synchro vidéo : l’aide dit le sens du réglage', () => {
  const help = tx('sync.help');
  assert.match(help, /avance[^.]*−/);
  assert.match(help, /retard[^.]*\+/);
  assert.match(readFileSync(new URL('../src/components/Stage/SyncOffset.tsx', import.meta.url), 'utf8'), /\{tx\('sync\.help'\)\}/);
});
