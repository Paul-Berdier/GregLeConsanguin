// Chansonnier du Roi (spec 2026-11-23 §3) : la place que ses boutons prennent aux lignes qu'ils rejoignent.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';

const css = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '');
/** Corps de la première règle `sel { … }` (sélecteur exact) d'une feuille. */
const rule = (src, sel) => {
  const i = src.indexOf(`${sel} {`);
  assert.ok(i >= 0, `règle ${sel}`);
  return src.slice(i + sel.length + 2, src.indexOf('}', i));
};

test('titre en cours : le demandeur cède avec l’artiste (le cœur et « Ajouter à une playlist » lui prennent 70 px)', () => {
  const now = css('src/components/Stage/now.css');
  const by = rule(now, '.meta-slot .by');
  assert.match(by, /flex: 0 4 auto;/, 'le demandeur cède d’abord, comme dans la file');
  assert.match(by, /min-width: 0;/);
  assert.ok(!/flex: none/.test(by), 'un demandeur rigide laissait une lettre à l’artiste');
  assert.match(rule(now, '.meta-slot .by-txt'), /overflow: hidden; text-overflow: ellipsis;/);
  assert.match(rule(now, '.meta-slot .artist'), /min-width: 0;/);
  assert.match(read('src/components/Stage/NowPlaying.tsx'), /<span className="by-txt">\{t\(keys\.plain, vars\)\}<\/span>/);
  // « Ajouter à une playlist » désactivé (chansonnier pas encore lu) : il le paraît
  assert.match(rule(now, '.nbtn:disabled'), /opacity: \.4;/);
});
