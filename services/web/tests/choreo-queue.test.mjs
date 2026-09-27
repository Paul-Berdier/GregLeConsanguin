// La file de l'étape 4 : Le Sceau, sortie en cascade, clavier des listes, sceaux différés.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { animated, assertKeys, read } from './_contract.mjs';

test('Le Sceau : sur un ajout du Roi seulement ; ressort --spring-seal ; sceau posé de 1.35 et −14°', () => {
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /sealBook\.take\(\{ url: item\.url, mine \}, performance\.now\(\)\)/);
  assert.match(panel, /requesterOf\(item\.addedBy, meRef\.current\?\.id\)\.kind === 'mine'/);
  const seal = read('src/components/Queue/seal.ts');
  for (const re of [/SPRING\.seal/, /scale\(1\.35\) rotate\(-14deg\)/, /li\.dataset\.sealed = ''/]) assert.match(seal, re);
  assert.ok(!/crown|couronne|greg-face/i.test(seal), 'le sceau est au Roi, rien de Greg');
});

test('arrêt : sortie de la dernière ligne à la première ; ordres notés avant « jouer maintenant »', () => {
  const flip = read('src/hooks/useFlip.ts');
  assert.match(flip, /reverseStagger\(/);
  assert.match(flip, /onEnter\?\.\(key, el\)/);
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /exitStagger: shown\.length === 0/);
  assert.match(panel, /kingOrders\.mark\(key, via, performance\.now\(\)\)/);
});

test('tabindex itinérant : un arrêt de Tab par liste, touches décrites, Alt+↑↓ annoncé', () => {
  assert.match(read('src/hooks/useRoving.ts'), /listKey\(e, i, keys\.length\)/);
  const panel = read('src/components/Queue/QueuePanel.tsx');
  for (const re of [/aria-describedby=\{keysId\}/, /tx\('queue\.keys'\)/, /moveBefore\(qKeys, key, act\.dir\)/, /speak\(t\('queue\.dnd\.liveMoved'/]) {
    assert.match(panel, re);
  }
  for (const f of ['Queue/QueueRow', 'History/HistoryRow']) {
    const row = read(`src/components/${f}.tsx`), n = (re) => (row.match(re) || []).length;
    assert.match(row, /tabIndex=\{tabIndex\}/, f);
    assert.ok(n(/<button /g) > 0 && n(/<button /g) === n(/<button type="button" tabIndex=\{-1\}/g), `${f} : bouton dans la tabulation`);
  }
  assert.match(read('src/components/History/useRequeue.ts'), /useRoving\(listRef, keys, 'url'/);
  for (const f of ['HistoryPanel', 'Suggestions']) assert.match(read(`src/components/History/${f}.tsx`), /tx\('history\.keys'\)/, f);
});

test('listes : Alt+Début et Alt+↑↓ retenus même sans effet ; un refocus en attente ne vole jamais le focus', () => {
  const rov = read('src/hooks/useRoving.ts');
  const hold = rov.indexOf('if (e.altKey && !e.ctrlKey && !e.metaKey && ALT_KEYS.has(e.key)) e.preventDefault();');
  assert.ok(hold > 0 && hold < rov.indexOf('if (!act) return;'), 'Alt+Début (page d’accueil de Chrome) retenu en première ligne et touche maintenue');
  assert.match(rov, /const ALT_KEYS = new Set\(\['Home', 'ArrowUp', 'ArrowDown'\]\);/);
  const effect = rov.slice(rov.indexOf('useLayoutEffect('), rov.indexOf('const onKeyDown'));
  assert.match(effect, /!keys\.includes\(k\)/, 'ligne partie de la liste : refocus abandonné');
  assert.match(effect, /at !== document\.body && !list\.contains\(at\)/, 'focus parti ailleurs : refocus abandonné');
  assert.match(rov, /if \(act\.kind === 'focus'\) \{ refocus\.current = null;/, 'les flèches effacent un refocus en attente');
  assert.match(rov, /if \(refocus\.current !== k\) refocus\.current = null;/, 'une autre ligne focalisée l’efface aussi');
  assert.match(rov, /refocus\.current = target;/, 'null : aucun refocus en attente');
  // historique : rien à refocaliser, sauf Entrée dans « Souvent demandés ici » (la ligne part : sa voisine)
  const rq = read('src/components/History/useRequeue.ts');
  assert.match(rq, /if \(!hit \|\| !add\(hit\)\) return null;/);
  assert.match(rq, /return leaves \? keys\[i \+ 1\] \?\? keys\[i - 1\] \?\? null : null;/);
  assert.match(read('src/components/History/Suggestions.tsx'), /useRequeueList\(pick, listRef, true\)/);
  assert.doesNotMatch(read('src/components/History/HistoryPanel.tsx'), /useRequeueList\(items, listRef, true\)/);
  // file : une Entrée dédoublonnée (rien de joué) ne déplace pas le focus
  assert.match(read('src/components/Queue/QueuePanel.tsx'), /if \(act\.kind === 'activate'\) return playNow\(key, 'key'\) \? near : null;/);
});

test('sceaux différés (loading="lazy") ; queue.css en transform et opacity ; fantôme fixe', () => {
  assert.match(read('src/components/Queue/QueueRow.tsx'), /<img src=\{sealSrc\} alt="" width=\{23\} height=\{23\} loading="lazy"/);
  const css = read('src/components/Queue/queue.css');
  for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), prop);
  assert.match(css, /\.seal-ghost\s*\{[^}]*position:\s*fixed/);
});

test('textes cités par la file et l’historique : chaque clé existe', () => {
  assert.ok(assertKeys(['Queue/QueuePanel.tsx', 'Queue/QueueRow.tsx', 'History/HistoryPanel.tsx', 'History/Suggestions.tsx']
    .map((f) => `src/components/${f}`)) >= 14);
});
