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
