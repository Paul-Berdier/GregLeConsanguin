// Focus des listes et du Héraut (revue B) : focus perdu rendu, ligne déplacée ramenée dans la vue, « Annuler »,
// annonces des Alt+↑↓ rapides. Calculs purs (lib/focus.ts) et contrats des composants qui s'en servent.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const F = await loadTs('../src/lib/focus.ts').catch(() => ({}));   // absent : chaque test le dit
const { createQueueEngine } = await loadTs('../src/lib/queue/optimistic.ts');
const { moveBefore } = await loadTs('../src/lib/keys.ts');

test('focus perdu : la même ligne si elle est là, sinon celle qui a pris sa place (bornée), sinon rien (C7, C8, C21)', () => {
  assert.equal(F.rescueKey(['a', 'c', 'd', 'b'], 'b', 1), 'b', 'ligne déplacée (Ctrl+Z, retour en arrière) : la même');
  assert.equal(F.rescueKey(['b', 'c'], 'a', 0), 'b', 'la tête part jouer : sa suivante');
  assert.equal(F.rescueKey(['a', 'b'], 'c', 2), 'b', 'la dernière retirée ailleurs : la nouvelle dernière');
  assert.equal(F.rescueKey(['a', 'c'], 'b', 1), 'c');
  assert.equal(F.rescueKey([], 'a', 0), null, 'liste vide : au volet (onglet)');
  assert.equal(F.rescueKey(['a'], 'x', -1), 'a');
});

test('ligne ramenée dans la vue au plus près (C20) : rien si visible, sinon le plus petit défilement', () => {
  assert.equal(F.revealDelta(100, 140, 0, 300), 0, 'visible');
  assert.equal(F.revealDelta(-200, -160, 0, 300), -200, 'au-dessus : on remonte jusqu’à son haut');
  assert.equal(F.revealDelta(320, 360, 0, 300), 60, 'au-dessous : on descend jusqu’à son bas');
  assert.equal(F.revealDelta(-10, 400, 0, 300), -10, 'plus haute que la vue : son haut d’abord');
  assert.equal(F.revealDelta(250, 600, 0, 300), 250, 'plus haute que la vue, en bas : son haut, pas plus');
});

test('« Annuler » ou Échap : l’« Annuler » d’une autre plaque, sinon la ligne active de la file, sinon l’onglet File (C9)', () => {
  const el = (name, attrs = {}) => ({ name, getAttribute: (a) => attrs[a] ?? null });
  const [u1, u2, row, tab] = [el('u1'), el('u2'), el('row'), el('tab')];
  const sel = '.toast:not([data-leaving]):not([data-hidden]) .undo';
  const section = (undos) => ({ querySelectorAll: (s) => (s === sel ? undos : []) });
  const cur = { contains: (b) => b === u1 };
  const doc = ({ hidden = 'false', withRow = true, withTab = true, panel = true } = {}) => ({
    getElementById: (id) => (id === 'pane-queue' ? (panel ? el('pane', { 'aria-hidden': hidden }) : null) : id === 'tab-queue' && withTab ? tab : null),
    querySelector: (s) => (s === '.qcontent > .qlist > .row[tabindex="0"]' && withRow ? row : null),
  });
  assert.equal(F.focusAfterToast(section([u1, u2]), cur, doc()), u2, 'une autre plaque attend');
  assert.equal(F.focusAfterToast(section([u1]), cur, doc()), row, 'seule : la ligne active de la file');
  assert.equal(F.focusAfterToast(section([u1]), cur, doc({ hidden: 'true' })), tab, 'volet Historique affiché : l’onglet File');
  assert.equal(F.focusAfterToast(section([u1]), cur, doc({ withRow: false })), tab, 'file vide : l’onglet File');
  assert.equal(F.focusAfterToast(section([u1]), cur, doc({ panel: false, withRow: false, withTab: false })), null, 'pas de panneau');
});

test('useRoving : focus perdu hors d’un geste clavier rendu sans défilement ; oublié quand il sort de la liste (C7, C8, C21)', () => {
  const rov = read('src/hooks/useRoving.ts');
  const effect = rov.slice(rov.indexOf('useLayoutEffect('), rov.indexOf('const onKeyDown'));
  assert.match(effect, /const lost = !at \|\| at === document\.body \|\| !!\(list\?\.contains\(at\) && at\.closest\('\[data-leaving\]'\)\)/,
    'perdu : sur <body>, ou sur une ligne qui sort');
  assert.match(effect, /rescueKey\(keys, l\.key, l\.index\)/);
  assert.match(effect, /\.focus\(\{ preventScroll: true \}\)/, 'sans faire sauter la vue');
  assert.match(effect, /document\.getElementById\(home\.current\)/, 'liste vide : l’onglet du volet');
  assert.ok(effect.indexOf('const l = last.current') > effect.indexOf('refocus.current = null;'), 'un refocus clavier passe d’abord');
  const focus = rov.slice(rov.indexOf('const onFocus'));
  assert.match(focus, /last\.current = \{ key: k, index: keys\.indexOf\(k\),/);
  assert.match(focus, /home\.current = listRef\.current\?\.closest\('\[role="tabpanel"\]'\)\?\.getAttribute\('aria-labelledby'\) \?\? null;/);
  // focus parti ailleurs (ou sur <body> d'un clic) : plus rien à rendre ; fenêtre quittée (activeElement inchangé) : gardé.
  // Décidé après coup (focusOutWatcher, une microtâche) : Chrome lance focusout pendant que React retire ou déplace la ligne.
  assert.match(rov, /document\.addEventListener\('focusout', out\)/);
  assert.match(rov, /const out = focusOutWatcher\(\{\s*list: \(\) => listRef\.current, active: \(\) => document\.activeElement,\s*defer: \(fn\) => queueMicrotask\(fn\), forget: \(\) => \{ last\.current = null; \},\s*\}\);/);
});

// Chrome lance blur/focusout de façon synchrone quand React retire (removeChild) ou déplace (insertBefore) la ligne focalisée :
// elle est encore dans la liste, activeElement est <body>, relatedTarget null. Décidé sur le coup, `last` était effacé et
// l'effet de rendu ne rendait jamais le focus (C7, C8). Firefox ne lance rien : déjà correct.
test('focus sorti de la liste : décidé après coup ; une ligne retirée ou déplacée par React ne l’efface pas (Chrome)', () => {
  const node = (name) => ({ name, isConnected: true });
  const [r1, r2, r3, outside, body] = [node('r1'), node('r2'), node('r3'), node('outside'), node('body')];
  const inList = new Set([r1, r2, r3]);
  const list = { contains: (n) => inList.has(n) };
  let active = r1, forgotten = 0;
  const tasks = [];
  const out = F.focusOutWatcher({ list: () => list, active: () => active, defer: (fn) => tasks.push(fn), forget: () => { forgotten++; } });
  const microtasks = () => { while (tasks.length) tasks.shift()(); };
  // React retire la ligne focalisée : focusout pendant removeChild, la ligne encore attachée, le focus sur <body>…
  active = body;
  out({ target: r1, relatedTarget: null });
  inList.delete(r1); r1.isConnected = false;
  active = r2;   // … puis l'effet de rendu (même commit, avant la microtâche) rend le focus à sa voisine
  microtasks();
  assert.equal(forgotten, 0, 'ligne retirée : le focus rendu reste suivi');
  // même cas, rendu remis au rendu suivant (voisine pas encore là) : rien d'oublié non plus
  active = body; out({ target: r2, relatedTarget: null }); inList.delete(r2); r2.isConnected = false; microtasks();
  assert.equal(forgotten, 0, 'ligne démontée, rien encore rendu : la place reste à rendre');
  // Alt+↓ : React déplace la ligne focalisée (focusout), puis lui rend le focus (restoreSelection)
  active = body; out({ target: r3, relatedTarget: null }); active = r3; microtasks();
  assert.equal(forgotten, 0, 'ligne déplacée : toujours suivie');
  // clic dans le vide : la ligne est toujours là, le focus reste sur <body>
  active = body; out({ target: r3, relatedTarget: null }); microtasks();
  assert.equal(forgotten, 1, 'focus parti sur <body> d’un clic : oublié');
  // Tab vers un autre contrôle
  active = outside; out({ target: r3, relatedTarget: outside }); microtasks();
  assert.equal(forgotten, 2);
  // vers une autre ligne de la liste, ou fenêtre quittée (activeElement inchangé) : rien à décider
  const r4 = node('r4'); inList.add(r4);
  out({ target: r3, relatedTarget: r4 });
  active = r3; out({ target: r3, relatedTarget: null });
  out({ target: outside, relatedTarget: null });   // hors de la liste
  assert.equal(tasks.length, 0);
  assert.equal(forgotten, 2);
});

// Chrome donne le focus au bouton cliqué (« Retirer », « Jouer maintenant », tabindex -1) : rendu à la voisine, il y
// gardait ses boutons affichés (:focus-within) et les raccourcis de la page (Espace, Maj+←/→, saisie) s'arrêtaient sur
// une ligne. Seul un focus venu du clavier (:focus-visible) est rendu ; au pointeur, il tombe comme avant.
test('focus perdu rendu seulement s’il venait du clavier (:focus-visible) ; au pointeur, il tombe', () => {
  assert.equal(F.keyboardFocus({ matches: (s) => s === ':focus-visible' }), true);
  assert.equal(F.keyboardFocus({ matches: () => false }), false, 'clic : pas de focus visible');
  assert.equal(F.keyboardFocus({ matches: () => { throw new SyntaxError(':focus-visible'); } }), true, 'navigateur sans :focus-visible : rendu comme avant');
  const rov = read('src/hooks/useRoving.ts');
  const focus = rov.slice(rov.indexOf('const onFocus'));
  assert.match(focus, /last\.current = \{ key: k, index: keys\.indexOf\(k\), kb: keyboardFocus\(e\.target as HTMLElement\) \};/);
  const effect = rov.slice(rov.indexOf('useLayoutEffect('), rov.indexOf('const onKeyDown'));
  const kb = effect.indexOf('if (!l.kb) { last.current = null; return; }');
  assert.ok(kb > effect.indexOf('if (!lost) return;') && kb < effect.indexOf('rescueKey('), 'au pointeur : rien de rendu, oublié');
  const h = read('src/components/Herald/Herald.tsx');
  const at = h.indexOf('const undo = '), undo = h.slice(at, h.indexOf('\n  };', at));
  assert.match(undo, /const to = had && e\.detail === 0 && cur && sec \? focusAfterToast\(sec, cur, document\) : null;/,
    '« Annuler » au clavier (Entrée, Espace : detail 0) seulement');
  assert.match(undo, /herald\.act\(id\);\s*if \(to\) to\.focus\(\);\s*else if \(had\) btn\.blur\(\);/, 'au pointeur : le bouton lâche le focus');
});

test('useRoving : la ligne refocalisée au clavier est ramenée dans la vue, à sa place d’arrivée (C20)', () => {
  const rov = read('src/hooks/useRoving.ts');
  const effect = rov.slice(rov.indexOf('useLayoutEffect('), rov.indexOf('const onKeyDown'));
  assert.match(effect, /if \(at !== el\) el\.focus\(\);\s*reveal\(el\);/, 'même quand elle a gardé le focus');
  assert.match(rov, /translateYOf\(getComputedStyle\(el\)\.transform\)/, 'sans la translation FLIP en cours');
  assert.match(rov, /revealDelta\(/);
  assert.match(rov, /behavior: reducedMotion\(\) \? 'auto' : 'smooth'/);
});

test('Héraut : « Annuler » rend le focus avant que sa plaque ne s’efface ; Échap passe par le même choix (C9)', () => {
  const h = read('src/components/Herald/Herald.tsx');
  assert.match(h, /className="undo" onClick=\{\(e\) => undo\(e, x\.id\)\}/);
  const at = h.indexOf('const undo = '), undo = h.slice(at, h.indexOf('\n  };', at));
  assert.ok(at > 0 && undo.length > 0);
  assert.match(undo, /focusAfterToast\(/);
  assert.ok(undo.indexOf('focusAfterToast(') < undo.indexOf('herald.act(id)'), 'cible choisie avant l’annulation');
  assert.match(undo, /herald\.act\(id\);\s*if \(to\) to\.focus\(\);/, 'au clavier : le focus suit (au pointeur, il ne part pas dans la file)');
  assert.match(undo, /const had = document\.activeElement === btn;/, 'seulement si le bouton avait le focus');
  const esc = h.slice(h.indexOf('const onKeyDown'), h.indexOf('const undo = '));
  assert.match(esc, /focusAfterToast\(e\.currentTarget, cur, document\)/);
});

test('Alt+↑↓ rapides : seul le dernier déplacement est annoncé, à sa vraie place (C22)', async () => {
  const T = (k) => ({ key: k, url: `https://youtu.be/${k}`, title: k, duration: 200 });
  const snap = (keys) => ({ player: { current: null, queue: keys.map(T), paused: false, repeat: false, position: 0, duration: 0 }, tickBase: { pos: 0, at: 0, dur: 0 } });
  const run = async (guard) => {
    const acks = [], spoken = [];
    const eng = createQueueEngine({ initial: snap(['a', 'b', 'c', 'd', 'e']), now: () => 0, onView: () => {},
      send: () => new Promise((r) => acks.push(r)) });
    let seq = 0;
    const press = () => {   // QueuePanel, Alt+↓ sur « a » : position annoncée i + 1 + dir
      const keys = eng.view().player.queue.map((x) => x.key), i = keys.indexOf('a'), n = ++seq;
      void eng.dispatch({ kind: 'move', key: 'a', beforeKey: moveBefore(keys, 'a', 1) })
        .then((ok) => { if (ok && (!guard || n === seq)) spoken.push(i + 2); });
    };
    press(); press(); press();
    await Promise.resolve();
    while (acks.length) { acks.shift()(); await new Promise((r) => setTimeout(r, 0)); }
    return { spoken, order: eng.view().player.queue.map((x) => x.key).join('') };
  };
  assert.deepEqual(await run(false), { spoken: [3, 2, 4], order: 'bcdae' }, 'sans garde : 3, puis 2, puis 4');
  assert.deepEqual(await run(true), { spoken: [4], order: 'bcdae' });
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /const n = \+\+moves\.current;/);
  assert.match(panel, /if \(ok && n === moves\.current\) speak\(t\('queue\.dnd\.liveMoved'/);
});
