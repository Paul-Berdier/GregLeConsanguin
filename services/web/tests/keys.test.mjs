// Clavier (étape 4) : raccourcis de la page, interrupteur (WCAG 2.1.4), touches des listes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const K = await loadTs('../src/lib/keys.ts');
const ctx = { enabled: true, loggedIn: true, inField: false, inPopover: false, onRow: false, onControl: false, dragging: false };
const SPACE = { key: ' ', code: 'Space' }, NEXT = { key: 'ArrowRight', shiftKey: true };
const f = (ev, o = {}) => K.shortcutFor(ev, { ...ctx, ...o });

test('Espace, Maj+→, Maj+←, /, ? ; une lettre part dans la recherche (N ne saute plus)', () => {
  assert.deepEqual([f(SPACE), f(NEXT), f({ key: 'ArrowLeft', shiftKey: true }), f({ key: '/' }), f({ key: '?', shiftKey: true })],
    ['togglePause', 'skip', 'restart', 'search', 'help']);
  for (const key of ['n', 'p', 'r', 'N', 'é', '7']) assert.equal(f({ key }), 'type', key);
  for (const key of ['ArrowRight', 'Enter', 'Tab', 'Escape', 'F5']) assert.equal(f({ key }), null, key);
});

test('rien dans un champ, une fenêtre, un glisser, déconnecté, ou interrupteur coupé', () => {
  for (const off of [{ inField: true }, { inPopover: true }, { dragging: true }, { loggedIn: false }, { enabled: false }]) {
    for (const ev of [SPACE, NEXT, { key: '/' }, { key: '?' }, { key: 'a' }]) assert.equal(f(ev, off), null, `${JSON.stringify(off)} ${ev.key}`);
  }
});

test('Ctrl, Cmd, Alt et Espace maintenue restent au navigateur', () => {
  assert.deepEqual([f({ key: 'z', ctrlKey: true }), f({ key: 'r', metaKey: true }), f({ ...NEXT, altKey: true }), f({ ...SPACE, repeat: true })],
    [null, null, null, null]);
});

test('sur une ligne, les touches sont à la liste ; sur un bouton, Espace l’active', () => {
  assert.deepEqual([f(SPACE, { onRow: true }), f({ key: 'a' }, { onRow: true }), f({ key: '/' }, { onRow: true })], [null, null, 'search']);
  assert.deepEqual([f(SPACE, { onControl: true }), f(NEXT, { onControl: true }), f({ key: 'a' }, { onControl: true })], [null, 'skip', 'type']);
});

test('liste : flèches, Début, Fin, Entrée, Suppr, Alt+↑↓, Alt+Début', () => {
  const L = (key, i, o = {}) => K.listKey({ key, ...o }, i, 5);
  assert.deepEqual([L('ArrowDown', 2), L('ArrowDown', 4), L('ArrowUp', 0), L('Home', 3), L('End', 1)].map((a) => a.index), [3, 4, 0, 0, 4]);
  assert.deepEqual([L('Enter', 1), L('Delete', 1)], [{ kind: 'activate' }, { kind: 'remove' }]);
  const alt = { altKey: true };
  assert.deepEqual([L('ArrowUp', 1, alt), L('ArrowDown', 3, alt), L('Home', 3, alt)], [{ kind: 'move', dir: -1 }, { kind: 'move', dir: 1 }, { kind: 'next' }]);
  assert.deepEqual([L('ArrowUp', 0, alt), L('ArrowDown', 4, alt), L('Home', 0, alt), L('ArrowDown', 1, { ctrlKey: true }), L('a', 1)],
    [null, null, null, null, null]);
  assert.equal(K.listKey({ key: 'ArrowDown' }, 0, 0), null);
});

test('liste : une touche maintenue parcourt et déplace, mais ne joue ni ne retire en chaîne', () => {
  const R = (key, i, o = {}) => K.listKey({ key, repeat: true, ...o }, i, 5);
  assert.deepEqual([R('ArrowDown', 1), R('ArrowUp', 3), R('Home', 3), R('End', 1)].map((a) => a.index), [2, 2, 0, 4]);
  assert.deepEqual([R('ArrowUp', 2, { altKey: true }), R('ArrowDown', 2, { altKey: true })], [{ kind: 'move', dir: -1 }, { kind: 'move', dir: 1 }]);
  assert.deepEqual([R('Enter', 1), R('Delete', 1), R('Home', 3, { altKey: true })], [null, null, null]);
});

test('déplacer d’un rang : la clé devant laquelle déposer (null : fin de file)', () => {
  const k = ['a', 'b', 'c', 'd'];
  assert.deepEqual([K.moveBefore(k, 'c', -1), K.moveBefore(k, 'b', 1), K.moveBefore(k, 'c', 1)], ['b', 'd', null]);
  assert.deepEqual([K.moveBefore(k, 'a', -1), K.moveBefore(k, 'd', 1), K.moveBefore(k, 'x', 1)], [undefined, undefined, undefined]);
});

test('interrupteur allumé par défaut, seul « off » le coupe ; événement d’aide', () => {
  assert.deepEqual([K.SHORTCUTS_STORAGE_KEY, K.HELP_EVENT], ['greg.webplayer.keys', 'greg:help']);
  assert.deepEqual([null, undefined, 'on', 'off'].map((v) => K.shortcutsOn(v)), [true, true, true, false]);
});
