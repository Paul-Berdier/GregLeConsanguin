// Compléments au deck (étape 3) : typographie du deck, pas de doublon avec lui, casting.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';

const { EXTRA, tx } = await loadTs('../src/theme/copy.extra.ts');
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
