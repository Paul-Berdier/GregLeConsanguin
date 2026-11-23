// Chansonnier du Roi (spec 2026-11-23 §3) : gestes répétés (Entrée maintenue, double-clic) et focus gardé.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const GUARD = 'onKeyDownCapture={(e) => { if (heldEnter(e)) e.preventDefault(); }}';

test('Entrée maintenue : « Ajouter à une playlist » et tout le volet n’agissent qu’une fois', () => {
  const add = read('src/components/Library/AddToPlaylist.tsx');
  // sur l'enveloppe : le bouton, les playlists, « Nouvelle playlist… » et le champ du nom ; Échap (wrapProps) intact
  assert.ok(add.includes(`<div className="ladd" {...pop.wrapProps} ${GUARD}>`), 'menu du titre en lecture');
  assert.match(add, /import \{ heldEnter \} from '@\/lib\/keys';/);
  const panel = read('src/components/Library/LibraryPanel.tsx');
  // « Tout jouer », « Ajouter le titre en cours », renommer, supprimer, retour, nouvelle playlist… : sous .lpane
  assert.ok(panel.includes(`<div className="lpane" ref={paneRef} ${GUARD}`), 'volet du chansonnier');
  assert.match(panel, /<PlaylistView key=/);
});

test('double-clic sur une carte : la vue ouverte ignore la suite (« Tout jouer », une ligne remise dans la file)', async () => {
  const panel = read('src/components/Library/LibraryPanel.tsx');
  assert.ok(panel.includes(`${GUARD}\n      onClickCapture={swallow} onDoubleClickCapture={swallow}>`), 'en capture, sur le volet qui garde les deux vues');
  assert.match(panel, /if \(!fsSwallowClick\(e\.detail, performance\.now\(\) - switchedAt\.current\)\) return;\s*e\.preventDefault\(\);\s*e\.stopPropagation\(\);/);
  // l'heure du changement de vue est prise au rendu qui l'affiche (aller comme retour)
  const effect = panel.slice(panel.indexOf('useLayoutEffect(() => {\n    const want'), panel.indexOf('}, [view]);'));
  assert.match(effect, /switchedAt\.current = performance\.now\(\);/);
  assert.ok(effect.indexOf('switchedAt.current') < effect.indexOf('if (!root) return;'));
  // la salve d'un double-clic (2e clic, dblclick : detail 2) tout juste après l'ouverture ; jamais un clic du clavier
  const { fsSwallowClick } = await loadTs('../src/lib/stage/fullscreen.ts');
  assert.deepEqual([fsSwallowClick(2, 120), fsSwallowClick(1, 0), fsSwallowClick(0, 0), fsSwallowClick(2, 900)], [true, false, false, false]);
});

test('« Ajouter le titre en cours » : le titre ajouté, il garde le focus (aria-disabled) ; dans les coups de cœur, annoncé', () => {
  const view = read('src/components/Library/PlaylistView.tsx');
  const i = view.indexOf("aria-label={tx('library.addCurrent')}");
  const btn = view.slice(view.lastIndexOf('<button', i), view.indexOf('>', i));
  assert.match(btn, /aria-disabled=\{!canAdd\}/);
  assert.ok(!/\sdisabled=/.test(btn), 'désactivé, il perdait le focus sur <body> (Espace : pause pour tout le salon)');
  assert.match(view, /const canAdd = !!current && !\(curKey && keys\.includes\(curKey\)\);/);
  assert.match(view, /onClick=\{\(\) => \{ if \(canAdd && current\) void libraryActions\.addTo\(id, current\); \}\}/, 'désactivé : le clic ne fait rien');
  const css = read('src/components/Library/library.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(css, /\.lbtn:is\(:disabled, \[aria-disabled=true\]\) \{ opacity: \.4; cursor: default; \}/);
  for (const sel of ['.lbtn:active', '.lbtn:not', '.lbtn.primary:not', '.lbtn.danger:not']) {
    for (const m of css.matchAll(new RegExp(`${sel.replace(/[.:]/g, '\\$&')}[^{]*\\{`, 'g'))) assert.match(m[0], /:not\(:disabled, \[aria-disabled=true\]\)/, m[0]);
  }
  const lib = read('src/hooks/useLibrary.ts');
  const add = lib.slice(lib.indexOf('function addTo('), lib.indexOf('\n}\n', lib.indexOf('function addTo(')));
  assert.match(add, /if \(refused\(lib, op\)\) return Promise\.resolve\(false\);[^\n]*\n\s*const done = engine\.dispatch\(op\);/);
  assert.match(add, /const toast = say\('library\.toast\.liked', \{ vars: \{ title: songOf\(tr\) \}, kind: 'ok' \}\);/);
  assert.match(add, /void done\.then\(\(ok\) => \{ if \(!ok\) herald\.retract\(toast\); \}\);/, 'refusé par l’API : l’annonce part, Ctrl+Z n’y est pas');
});
