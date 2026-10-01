// Réglage « Répliques de Greg » : <html data-quips> posé dès le <head>, connecté ou non (le menu du compte ne fait que basculer).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';
const P = await loadTs('../src/lib/prefs.ts');
const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8');

/** Le script du <head> exécuté sur un faux document : la valeur posée sur <html data-quips>. */
function run(getItem) {
  const dataset = {};
  new Function('document', 'localStorage', P.QUIPS_SCRIPT)({ documentElement: { dataset } }, { getItem });
  return dataset.quips;
}

test('répliques gardées par défaut, seul « off » les coupe', () => {
  assert.equal(P.QUIPS_STORAGE_KEY, 'greg.webplayer.quips');
  assert.deepEqual([null, undefined, 'on', 'off', ''].map((v) => P.quipsOn(v)), [true, true, true, false, true]);
});

test('script du <head> : lit le réglage, pose data-quips ; stockage absent ou bloqué : « on »', () => {
  const store = (v) => (k) => (k === P.QUIPS_STORAGE_KEY ? v : null);
  assert.deepEqual([run(store('off')), run(store('on')), run(store(null))], ['off', 'on', 'on']);
  assert.equal(run(() => { throw new Error('SecurityError'); }), 'on');
});

test('posé avant la première peinture, déconnecté ou en plein chargement : <head> du layout', () => {
  const layout = read('src/app/layout.tsx');
  assert.match(layout, /import \{ QUIPS_SCRIPT \} from '@\/lib\/prefs'/);
  const head = layout.indexOf('<head>'), script = layout.indexOf('<script dangerouslySetInnerHTML={{ __html: QUIPS_SCRIPT }}/>');
  assert.ok(head >= 0 && script > head && script < layout.indexOf('</head>') && layout.indexOf('</head>') < layout.indexOf('<body'),
    'script dans le <head>, avant le <body>');
  // l'attribut posé par le script n'est pas dans le rendu serveur : pas d'avertissement d'hydratation sur <html>
  assert.match(layout, /<html [^>]*suppressHydrationWarning/);
});

test('menu du compte : même clé, état lu dès le premier rendu (pas de « on » écrit par-dessus le « off » du <head>)', () => {
  const menu = read('src/components/Header/AccountMenu.tsx');
  assert.match(menu, /import \{[^}]*QUIPS_STORAGE_KEY[^}]*\} from '@\/lib\/prefs'/);
  assert.ok(!menu.includes("'greg.webplayer.quips'"), 'une seule copie de la clé (lib/prefs)');
  assert.match(menu, /useState\(readQuips\)/);
  assert.match(menu, /document\.documentElement\.dataset\.quips = quips \? 'on' : 'off'/);
});
