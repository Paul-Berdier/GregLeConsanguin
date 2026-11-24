// Chansonnier du Roi (spec 2026-11-23 §3) : le cœur des lignes de la file et de l'historique au clavier (J, « J’aime »).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const { KEYS, tx } = await loadTs('../src/theme/copy.extra.ts');
const body = (src, head) => { const i = src.indexOf(head); assert.ok(i >= 0, head); return src.slice(i, src.indexOf('\n}\n', i)); };

test('J sur une ligne de la file : le cœur basculé et dit, avant toute autre touche ; le focus reste', () => {
  const src = read('src/components/Queue/QueuePanel.tsx');
  const like = "if (act.kind === 'like') { const item = byKey.current.get(key); if (item) void libraryActions.toggleLike(item, { spoken: true }); return undefined; }";
  const at = src.indexOf(like), roving = src.indexOf("const roving = useRoving(listRef, shownKeys, 'key', (act, key, i) => {");
  assert.ok(roving > 0 && at > roving && at < src.indexOf('const near = ', roving), 'en tête du rappel de useRoving');
});

test('J sur une ligne de l’historique ou de « Souvent demandés ici » : le cœur basculé et dit ; la ligne reste', () => {
  const src = read('src/components/History/useRequeue.ts');
  const like = "if (act.kind === 'like') { const it = items.find((x) => x.url === url); if (it) void libraryActions.toggleLike(it, { spoken: true }); return undefined; }";
  const at = src.indexOf(like);
  assert.ok(at > src.indexOf("const roving = useRoving(listRef, keys, 'url',") && at < src.indexOf('const hit = '), 'avant Entrée');
  for (const f of ['HistoryPanel', 'Suggestions']) assert.match(read(`src/components/History/${f}.tsx`), /onKeyDown=\{list\.onKeyDown\}/, f);
});

test('toggleLike : la promesse de la modification ; au clavier, l’accusé dit sans notification visible', () => {
  const fn = body(read('src/hooks/useLibrary.ts'), 'function toggleLike(');
  assert.match(fn, /function toggleLike\(item: TrackLike, o: \{ spoken\?: boolean \} = \{\}\): Promise<boolean> \{/);
  assert.match(fn, /const done = run\(on \? \{ kind: 'like', track: tr \} : \{ kind: 'unlike', url: tr\.url \}\);/);
  // dit seulement s'il a pris (refusé : le Héraut dit pourquoi) ; speak, pas say : pas de toast au clic du cœur
  assert.match(fn, /if \(o\.spoken\) void done\.then\(\(ok\) => \{ if \(ok\) speak\(tx\(on \? 'library\.toast\.liked\.text' : 'library\.toast\.unliked\.text', \{ title: songOf\(tr\) \}\)\); \}\);/);
  assert.ok(!/say\('library\.toast\.(un)?liked'/.test(fn));
  assert.equal(tx('library.toast.liked.text', { title: 'Africa' }), 'Ajouté aux coups de cœur : Africa');
  assert.equal(tx('library.toast.unliked.text', { title: 'Africa' }), 'Retiré des coups de cœur : Africa');
});

test('nom d’une ligne : un coup de cœur le dit (son cœur, hors de la tabulation, n’a jamais le focus)', () => {
  const row = read('src/components/Queue/QueueRow.tsx');
  assert.match(row, /const said = liked \? `\$\{label\}, \$\{tx\('library\.like\.state'\)\}` : label;/);
  assert.match(row, /aria-label=\{said\} tabIndex=\{tabIndex\}/);
  assert.match(read('src/components/History/HistoryRow.tsx'), /aria-label=\{\[song, p\.artist, meta, liked && tx\('library\.like\.state'\)\]\.filter\(Boolean\)\.join\(', '\)\}/);
  assert.equal(`Wake Me Up, Avicii, votre titre, ${tx('library.like.state')}`, 'Wake Me Up, Avicii, votre titre, dans vos coups de cœur');
});

test('touches décrites : la file, l’historique et l’aide du compte disent J', () => {
  assert.ok(tx('queue.keys').endsWith('Alt+Début : jouer ensuite. J : coup de cœur.'), tx('queue.keys'));
  assert.ok(tx('history.keys').endsWith('Entrée : remettre le titre dans la file. J : coup de cœur.'), tx('history.keys'));
  const j = KEYS.find(([k]) => k === 'J');
  assert.ok(j, 'J dans l’aide des raccourcis');
  assert.equal(j[1], 'J’aime : coup de cœur du titre choisi');
  assert.ok(KEYS.findIndex(([k]) => k === 'J') > KEYS.findIndex(([k]) => k === 'Suppr'), 'avec les touches des listes');
});
