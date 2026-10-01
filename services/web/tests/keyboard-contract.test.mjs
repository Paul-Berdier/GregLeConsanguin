// Clavier de la page (étape 4) : un gestionnaire, interrupteur (WCAG 2.1.4), lien d'évitement, recherche.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
const css = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '');

test('page : un gestionnaire (shortcutFor) ; plus de N / P / R ; « / » et « ? » ne s’écoutent plus ailleurs', () => {
  const page = read('src/app/page.tsx');
  for (const re of [/if \(ev\.defaultPrevented\) return;/, /shortcutFor\(ev, \{/, /kingOrders\.mark\(NEXT, 'key', performance\.now\(\)\)/,
    /watchReducedMotion\(/, /getAttribute\('aria-hidden'\) !== 'true'/]) assert.match(page, re);
  assert.ok(page.includes('playerActions.togglePause()'));
  assert.ok(!/ev\.key === '[npr]'/.test(page));
  assert.ok(!read('src/components/Header/SearchBar.tsx').includes("e.key !== '/'"));
  assert.ok(!read('src/components/Header/AccountMenu.tsx').includes("e.key !== '?'"));
});

test('page : sans serveur, « / », « ? » et la saisie servent encore ; seules les commandes du lecteur attendent un serveur', () => {
  const page = read('src/app/page.tsx');
  assert.match(page, /loggedIn: !!s\.me,/);
  assert.ok(!page.includes('loggedIn: !!s.me && !!s.guildId'));
  assert.match(page, /const PLAYS: readonly Shortcut\[\] = \['togglePause', 'skip', 'restart'\];/);
  // avant preventDefault : sans serveur, Espace et Maj+→/← restent au navigateur
  const gate = page.indexOf('if (!s.guildId && PLAYS.includes(act)) return;');
  assert.ok(gate > 0 && gate < page.indexOf('ev.preventDefault();'));
});

test('saisie directe : la lettre s’ajoute au texte du champ (curseur en fin), comme le prototype', () => {
  assert.match(read('src/app/page.tsx'), /search\.focus\(\); const n = search\.value\.length; search\.setSelectionRange\(n, n\);/);
});

test('menus de l’en-tête : bornés à la fenêtre, défilent (« Se déconnecter » reste atteignable)', () => {
  assert.match(css('src/components/Header/header.css'),
    /\.top \.pop\s*\{[^}]*max-height:\s*calc\(100dvh[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;?\s*\}/);
});

test('interrupteur : role=switch, mémorisé, reflété sur <html data-keys>, annoncé ; liste KEYS', () => {
  const menu = read('src/components/Header/AccountMenu.tsx');
  for (const re of [/SHORTCUTS_STORAGE_KEY/, /document\.documentElement\.dataset\.keys = keys \? 'on' : 'off'/, /tx\('keys\.toggle'\)/,
    /speak\(tx\(next \? 'keys\.on' : 'keys\.off'\)\)/, /addEventListener\(HELP_EVENT/, /KEYS\.map\(/]) assert.match(menu, re);
  assert.match(read('src/app/page.tsx'), /dataset\.keys !== 'off'/);
  // indice « / » seulement quand la touche marche (compte monté, raccourcis actifs) : rien avant l'hydratation
  assert.match(css('src/components/Header/header.css'), /:root:not\(\[data-keys=on\]\) \.kbd\s*\{\s*display:\s*none;?\s*\}/);
});

test('« Aller à la file » avant l’en-tête, visible au focus, en transform', () => {
  const page = read('src/app/page.tsx'), at = page.indexOf('className="skip-link"');
  assert.ok(at > 0 && at < page.indexOf('<Header'));
  assert.match(page, /tx\('a11y\.skipToQueue'\)/);
  const g = css('src/app/globals.css');
  assert.match(g, /\.skip-link:focus-visible\s*\{\s*transform:/);
  assert.match(g, /\.skip-link\s*\{[^}]*transition:\s*transform/);
});

test('recherche : sceau attendu noté avant l’ajout, oublié sur échec, pochette source transmise', () => {
  const sb = read('src/components/Header/SearchBar.tsx');
  for (const re of [/sealBook\.expect\(/, /sealBook\.clear\(\)/, /pick\(s, e\.currentTarget\.querySelector\('\.th'\)\)/]) assert.match(sb, re);
});
