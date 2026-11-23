// Chansonnier du Roi (spec 2026-11-23 §3) : gestes répétés (Entrée maintenue, double-clic) et focus gardé.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';

const GUARD = 'onKeyDownCapture={(e) => { if (heldEnter(e)) e.preventDefault(); }}';

test('Entrée maintenue : « Ajouter à une playlist » et tout le volet n’agissent qu’une fois', () => {
  const add = read('src/components/Library/AddToPlaylist.tsx');
  // sur l'enveloppe : le bouton, les playlists, « Nouvelle playlist… » et le champ du nom ; Échap (wrapProps) intact
  assert.ok(add.includes(`<div className="ladd" {...pop.wrapProps} ${GUARD}>`), 'menu du titre en lecture');
  assert.match(add, /import \{ heldEnter \} from '@\/lib\/keys';/);
  const panel = read('src/components/Library/LibraryPanel.tsx');
  // « Tout jouer », « Ajouter le titre en cours », renommer, supprimer, retour, nouvelle playlist… : sous .lpane
  assert.ok(panel.includes(`<div className="lpane" ref={paneRef} ${GUARD}>`), 'volet du chansonnier');
  assert.match(panel, /<PlaylistView key=/);
});
