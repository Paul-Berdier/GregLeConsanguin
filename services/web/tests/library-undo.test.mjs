// Chansonnier du Roi (spec 2026-11-23 §3) : annulations (Héraut, Ctrl+Z) et état confirmé après un échec.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';

const body = (src, head) => { const i = src.indexOf(head); assert.ok(i >= 0, head); return src.slice(i, src.indexOf('\n}\n', i)); };

test('run : l’id provisoire devient le vrai avant la vérification (annulation d’un retrait fait pendant la création)', () => {
  const fn = body(read('src/hooks/useLibrary.ts'), 'function run(');
  assert.match(fn, /const real = engine\.resolve\(op\);\s*if \(!lib \|\| refused\(lib, real\)\) return Promise\.resolve\(false\);\s*return engine\.dispatch\(real\);/);
  // l'annulation d'un retrait passe par run (vérifiée, puis optimiste)
  assert.match(body(read('src/hooks/useLibrary.ts'), 'function removeFromPlaylist('),
    /run: \(\) => \{ void run\(\{ kind: 'add', id: pl\.id, tracks: \[track\] \}\); void run\(\{ kind: 'move', id: pl\.id, url: track\.url, to: at \}\); \}/);
});
