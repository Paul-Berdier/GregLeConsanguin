// Chansonnier du Roi (spec 2026-11-23 §3) : annulations (Héraut, Ctrl+Z) et état confirmé après un échec.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const body = (src, head) => { const i = src.indexOf(head); assert.ok(i >= 0, head); return src.slice(i, src.indexOf('\n}\n', i)); };

test('run : l’id provisoire devient le vrai avant la vérification (annulation d’un retrait fait pendant la création)', () => {
  const fn = body(read('src/hooks/useLibrary.ts'), 'function run(');
  assert.match(fn, /const real = engine\.resolve\(op\);\s*if \(!lib \|\| refused\(lib, real\)\) return Promise\.resolve\(false\);\s*return engine\.dispatch\(real\);/);
  // l'annulation d'un retrait passe par run (vérifiée, puis optimiste)
  assert.match(body(read('src/hooks/useLibrary.ts'), 'function removeFromPlaylist('),
    /run: \(\) => \{ void run\(\{ kind: 'add', id: pl\.id, tracks: \[track\] \}\); void run\(\{ kind: 'move', id: pl\.id, url: track\.url, to: at \}\); \}/);
});

test('échec à l’issue inconnue (503 « le site relit », réseau) : le chansonnier confirmé est relu', async () => {
  const src = read('src/hooks/useLibrary.ts');
  assert.match(src, /const REREAD = new Set\(\['PLAYLIST_NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INVALID_REQUEST', ''\]\);/);
  assert.match(body(src, 'function failed('), /if \(REREAD\.has\(code\)\) void load\(\);/);
  // les codes tels que libraryCode les lit : réseau et réponse illisible sans code
  const { libraryCode } = await loadTs('../src/lib/library.ts');
  assert.deepEqual([libraryCode({ payload: { error: 'storage_unavailable' } }), libraryCode(new TypeError('Failed to fetch')), libraryCode({ payload: 'Bad gateway' })],
    ['STORAGE_UNAVAILABLE', '', '']);
  // la relecture ne remplace pas une réponse acceptée entre-temps (plus récente qu'elle peut-être)
  const load = body(src, 'async function load(');
  assert.match(load, /const acks = engine\.acks\(\);[\s\S]*await api\.getLibrary\(\)[\s\S]*if \(engine\.acks\(\) === acks \|\| !engine\.view\(\)\) engine\.load\(lib\);/);
});
