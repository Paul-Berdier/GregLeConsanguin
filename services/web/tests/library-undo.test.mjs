// Chansonnier du Roi (spec 2026-11-23 §3) : annulations (Héraut, Ctrl+Z) et état confirmé après un échec.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const body = (src, head) => { const i = src.indexOf(head); assert.ok(i >= 0, head); return src.slice(i, src.indexOf('\n}\n', i)); };

// Horloge et minuteurs factices du Héraut (comme tests/herald.test.mjs) : advance(ms) déclenche ce qui échoit.
function clock() {
  let now = 0, n = 0;
  const due = new Map();
  return {
    now: () => now,
    setTimer: (fn, ms) => { const h = ++n; due.set(h, { at: now + ms, fn }); return h; },
    clearTimer: (h) => { due.delete(h); },
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const next = [...due.entries()].filter(([, d]) => d.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        due.delete(next[0]);
        now = next[1].at;
        next[1].fn();
      }
      now = end;
    },
  };
}

test('Héraut : un changement de serveur ne désarme pas les annulations du Roi (chansonnier) ; sa déconnexion si', async () => {
  const { createHerald } = await loadTs('../src/lib/herald.ts');
  const c = clock();
  const h = createHerald(c);
  const runs = [];
  const queue = h.notify({ kind: 'info', fact: 'Retiré : X', action: { label: 'Annuler', run: () => runs.push('file') } });
  const deleted = h.notify({ kind: 'info', fact: 'Playlist « Taverne » supprimée', action: { label: 'Annuler', run: () => runs.push('chansonnier'), scope: 'king' } });
  const leaving = (id) => h.getSnapshot().find((t) => t.id === id).leaving;
  h.disarm();   // autre serveur (usePlayer.resetPlayer)
  assert.equal(leaving(queue), true, 'l’annulation de la file part');
  assert.equal(leaving(deleted), false, 'celle du chansonnier reste');
  assert.equal(h.undo(), true, 'Ctrl+Z la rejoue encore');
  assert.deepEqual(runs, ['chansonnier']);
  // déconnexion (useLibrary.clear) : celles du Roi aussi
  const again = h.notify({ kind: 'info', fact: 'Retiré des coups de cœur : Y', action: { label: 'Annuler', run: () => runs.push('cœur'), scope: 'king' } });
  h.disarm('king');
  assert.equal(leaving(again), true);
  assert.equal(h.undo(), false);
  h.act(again);
  assert.deepEqual(runs, ['chansonnier'], 'ni bouton ni Ctrl+Z');
  // l'inverse : désarmer le Roi laisse la file
  const q2 = h.notify({ kind: 'info', fact: 'Retiré : Z', action: { label: 'Annuler', run: () => runs.push('file 2') } });
  h.disarm('king');
  assert.equal(leaving(q2), false);
  assert.equal(h.undo(), true);
  assert.deepEqual(runs, ['chansonnier', 'file 2']);
});

test('chansonnier : ses annulations sont au Roi ; désarmées à sa déconnexion, pas au changement de serveur', () => {
  const src = read('src/hooks/useLibrary.ts');
  for (const head of ['function unlike(', 'function deletePlaylist(', 'function removeFromPlaylist(']) {
    assert.match(body(src, head), /action: \{ label: t\('toast\.undo'\), run: \(\) => \{[^\n]*\}, scope: 'king' \}/, head);
  }
  assert.match(body(src, 'function clear('), /engine\.reset\(\);\s*herald\.disarm\('king'\);/);
  // le lecteur garde son geste : autre serveur ou déconnexion, il désarme les siennes (portée par défaut)
  const player = read('src/hooks/usePlayer.ts');
  assert.match(body(player, 'function resetPlayer('), /herald\.disarm\(\);/);
  assert.ok(!/scope: 'king'/.test(player), 'les annulations de la file restent au serveur');
});

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
