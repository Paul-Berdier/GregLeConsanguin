// La file (étape 3, tâche 6) : mouvement de queue.css, casting du sceau, repli à 60 lignes, textes cités.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { animated, assertKeys, path, read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const QUEUE = readdirSync(path('src/components/Queue')).filter((f) => /\.tsx?$/.test(f)).map((f) => `src/components/Queue/${f}`);

test('queue.css : transform et opacity seulement, mouvement réduit prévu, importée', () => {
  const css = read('src/components/Queue/queue.css');
  for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), `anime « ${prop} »`);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.ok(read('src/app/globals.css').includes("@import '../components/Queue/queue.css';"));
});

test('casting : le sceau royal ne va que sur les titres du Roi ; aucune couronne dans la file', () => {
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /requesterOf\(item\.addedBy, me\?\.id\)\.kind === 'mine'/);
  assert.match(panel, /sealSrc=\{mine \? seal : null\}/);
  assert.match(panel, /kingSealSrc\(kingName\(me\)\)/);
  for (const f of QUEUE) assert.ok(!/crown|couronne|\bRex\b/i.test(read(f)), `${f} : couronne`);
});

test('file longue repliée à 60 lignes (tech.md §6.4) ; compat de l’ancien panneau retirée', () => {
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /export const MAX_ROWS = 60;/);
  // une tranche neuve à chaque rendu fait boucler useFlip (React #301 dès 61 titres)
  assert.ok(panel.includes('useMemo(() => (queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue), [queue])'), 'tranche mémoïsée');
  assert.ok(panel.includes('beforeKey ?? queue[MAX_ROWS]?.key ?? null'), 'dépôt sous la dernière ligne visible : devant le premier titre caché');
  assert.ok(!/removeFromQueue|playAt: \(i/.test(read('src/hooks/usePlayer.ts')), 'compat retirée');
});

test('libellé d’une ligne sans artiste : pas de « , , » lu à voix haute', async () => {
  // tx laisse « {artist} » tel quel quand la variable manque ; QueueRow retire alors le segment « , {artist} ».
  const { tx } = await loadTs('../src/theme/copy.extra.ts');
  assert.ok(read('src/components/Queue/QueueRow.tsx').includes("p.artist ? raw : raw.replace(', {artist}', '')"), 'segment retiré');
  const drop = (s) => s.replace(', {artist}', '');
  assert.equal(drop(tx('queue.rowAria', { title: 'Some random upload', name: 'Paul' })), 'Some random upload, demandé par Paul');
  assert.equal(drop(tx('queue.rowAriaMine', { title: 'Some random upload' })), 'Some random upload, votre titre');
  assert.equal(drop(tx('queue.rowAriaUnknown', { title: 'Some random upload' })), 'Some random upload');
  assert.equal(tx('queue.rowAria', { title: 'Song', artist: 'Band', name: 'Paul' }), 'Song, Band, demandé par Paul');
});

test('textes de la file : chaque clé citée existe', () => {
  assert.ok(assertKeys(QUEUE) >= 12);
});
