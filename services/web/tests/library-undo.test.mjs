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
  assert.match(src, /const REREAD = new Set\(\['PLAYLIST_NOT_FOUND', 'STORAGE_UNAVAILABLE', 'STALE', 'INVALID_REQUEST', ''\]\);/);
  assert.match(body(src, 'function failed('), /if \(REREAD\.has\(code\)\) void load\(\);/);
  // les codes tels que libraryCode les lit : réseau et réponse illisible sans code
  const { libraryCode } = await loadTs('../src/lib/library.ts');
  assert.deepEqual([libraryCode({ payload: { error: 'storage_unavailable' } }), libraryCode(new TypeError('Failed to fetch')), libraryCode({ payload: 'Bad gateway' })],
    ['STORAGE_UNAVAILABLE', '', '']);
  // la relecture ne remplace pas une réponse acceptée entre-temps (plus récente qu'elle peut-être)
  const load = body(src, 'async function load(');
  assert.match(load, /const acks = engine\.acks\(\);[\s\S]*await api\.getLibrary\(\)[\s\S]*if \(engine\.acks\(\) === acks \|\| !engine\.view\(\)\) engine\.load\(lib\);/);
});

test('retour sur la fenêtre : relu (changé sur un autre appareil, Alt+↑ ↓ viserait un autre titre), sans excès', async () => {
  const { rereadOnFocus, REREAD_MIN_MS } = await loadTs('../src/lib/library.ts');
  assert.equal(REREAD_MIN_MS, 15000, 'comme la session (app/page.tsx)');
  const at = (o) => rereadOnFocus({ status: 'ready', pending: 0, now: 100_000, last: 100_000 - REREAD_MIN_MS, ...o });
  assert.equal(at({}), true);
  assert.equal(at({ last: 100_000 - REREAD_MIN_MS + 1 }), false, 'pas plus d’une fois par 15 s');
  assert.equal(at({ pending: 1 }), false, 'en attente : chaque accusé rend le chansonnier entier');
  for (const status of ['off', 'loading', 'error']) assert.equal(at({ status }), false, status);
  // branché sur le focus de la fenêtre, retiré au démontage ; espacé de toute lecture (connexion, échec, Réessayer)
  const src = read('src/hooks/useLibrary.ts');
  const init = body(src, 'export function useLibraryInit(');
  assert.match(init, /if \(rereadOnFocus\(\{ status: useLibrary\.getState\(\)\.status, pending: engine\.pending\(\), now: Date\.now\(\), last: _readAt \}\)\) void load\(\);/);
  assert.match(init, /window\.addEventListener\('focus', onFocus\);\s*return \(\) => window\.removeEventListener\('focus', onFocus\);/);
  assert.match(body(src, 'async function load('), /if \(!meId\) return;\s*_readAt = Date\.now\(\);/);
});

// ── Annulations à l'ancien rang et déplacements nommés : le moteur câblé comme useLibrary (send = sendOp(api, …)) ──
const L = await loadTs('../src/lib/library.ts');
const NOW = 1_700_000_000_000;
const T = (id, extra = {}) => ({ url: `https://youtu.be/${id.padEnd(11, '_')}`, title: id, artist: null, duration: 100, thumb: null, provider: 'youtube', added_at: 1, ...extra });
const PL = (id, tracks = [], name = id, created_at = 1, updated_at = 1) => ({ id, name, tracks, created_at, updated_at });
const LIB = (o = {}) => ({ likes: [], playlists: [], limits: { ...L.DEFAULT_LIMITS }, ...o });
const titles = (lib, i = 0) => lib.playlists[i].tracks.map((t) => t.title);

/** Client de l'API factice : chaque appel noté [route, ...arguments] ; `respond` rend sa réponse (null : accepté). */
function fakeApi(respond = () => Promise.resolve(null)) {
  const calls = [];
  const api = new Proxy({}, { get: (_, name) => (...args) => { calls.push([name, ...args]); return respond(name, args); } });
  return { api, calls };
}
const wired = (api, initial, fails = []) => {
  const engine = L.createLibraryEngine({ send: (op, base) => L.sendOp(api, op, base), now: () => NOW, onView: () => {}, onFail: (op, e) => fails.push({ op, e }) });
  engine.load(initial);
  return engine;
};

test('useLibrary : annulations préparées avant le geste (undoOf), rejouées par run ; send passe par sendOp(api, …)', () => {
  const src = read('src/hooks/useLibrary.ts');
  assert.match(src, /const send = \(op: LibraryOp, base: Library\): Promise<unknown> => sendOp\(api, op, base\);/);
  const un = body(src, 'function unlike(');
  assert.match(un, /const op: LibraryOp = \{ kind: 'unlike', url: track\.url \};\s*const undo = undoOf\(useLibrary\.getState\(\)\.lib, op\) \?\? \{ kind: 'like', track \};\s*const done = run\(op\);/);
  assert.match(un, /run: \(\) => \{ void run\(undo\); \}/);
  const del = body(src, 'function deletePlaylist(');
  assert.match(del, /const op: LibraryOp = \{ kind: 'delete', id: pl\.id \};\s*const undo = undoOf\(useLibrary\.getState\(\)\.lib, op\);\s*const done = run\(op\);/);
  assert.match(del, /run: \(\) => \{ if \(undo\) void run\(undo\); \}/);
  assert.ok(!/createPlaylist/.test(del), 'plus de recréation à la fin sous un nouvel id');
});

test('undoOf : le coup de cœur retiré revient à son rang, la playlist supprimée à sa place ; rien à défaire sinon', () => {
  const p2 = PL('p2', [T('x', { added_at: 77 })], 'Taverne', 10, 20);
  const lib = LIB({ likes: [T('a'), T('b')], playlists: [PL('p1'), p2] });
  assert.deepEqual(L.undoOf(lib, { kind: 'unlike', url: `https://www.youtube.com/watch?v=${'b'.padEnd(11, '_')}` }), { kind: 'like', track: T('b'), at: 1 }, 'par identité');
  assert.deepEqual(L.undoOf(lib, { kind: 'delete', id: 'p2' }),
    { kind: 'restore', id: 'p2', name: 'Taverne', tracks: p2.tracks, created_at: 10, updated_at: 20, at: 1 });
  assert.equal(L.undoOf(lib, { kind: 'unlike', url: T('z').url }), null);
  assert.equal(L.undoOf(lib, { kind: 'delete', id: 'nope' }), null);
  assert.equal(L.undoOf(lib, { kind: 'rename', id: 'p1', name: 'x' }), null);
  assert.equal(L.undoOf(null, { kind: 'delete', id: 'p2' }), null);
});

test('annuler le retrait d’un coup de cœur : POST /library/likes/add {track, index}, il revient à son rang', async () => {
  const { api, calls } = fakeApi();
  const engine = wired(api, LIB({ likes: [T('a'), T('b'), T('c')] }));
  const op = { kind: 'unlike', url: T('b').url };
  const undo = L.undoOf(engine.view(), op);
  assert.equal(await engine.dispatch(op), true);
  assert.equal(await engine.dispatch(undo), true);
  assert.deepEqual(calls, [['libraryUnlike', T('b').url], ['libraryLike', L.wireTrack(T('b')), 1]]);
  assert.deepEqual(engine.view().likes.map((t) => t.title), ['a', 'b', 'c'], 'à sa place, pas en tête');
  // un cœur ordinaire (bouton, J) ne dit pas de rang : en tête, comme avant
  await engine.dispatch({ kind: 'like', track: T('d') });
  assert.deepEqual(calls[2], ['libraryLike', L.wireTrack(T('d')), undefined]);
  assert.equal(engine.view().likes[0].title, 'd');
});

test('annuler la suppression d’une playlist : POST /library/playlists/restore, à sa place, sous son id et ses dates', async () => {
  const { api, calls } = fakeApi();
  const p2 = PL('p2', [T('x', { added_at: 77 }), T('y', { added_at: 78 })], 'Taverne', 10, 20);
  const engine = wired(api, LIB({ playlists: [PL('p1'), p2, PL('p3')] }));
  const op = { kind: 'delete', id: 'p2' };
  const undo = L.undoOf(engine.view(), op);
  assert.equal(await engine.dispatch(op), true);
  assert.deepEqual(engine.view().playlists.map((p) => p.id), ['p1', 'p3']);
  assert.equal(await engine.dispatch(undo), true);
  assert.deepEqual(calls, [
    ['playlistDelete', 'p2'],
    ['playlistRestore', { id: 'p2', name: 'Taverne', created_at: 10, updated_at: 20,
      tracks: [{ ...L.wireTrack(p2.tracks[0]), added_at: 77 }, { ...L.wireTrack(p2.tracks[1]), added_at: 78 }] }, 1],
  ]);
  assert.deepEqual(engine.view().playlists, [PL('p1'), p2, PL('p3')], 'à l’identique, à sa place');
});

test('restauration sur une API d’avant la route (404 sans code) : recréée par la création ; tout autre refus remonte', async () => {
  const notFound = Object.assign(new Error('not_found'), { status: 404, payload: { ok: false, error: 'not_found' } });
  assert.equal(L.routeMissing(notFound), true);
  assert.equal(L.routeMissing({ status: 404, payload: '<html>Not Found</html>' }), true, 'page du mandataire');
  assert.equal(L.routeMissing({ status: 404, payload: { error: 'playlist_not_found' } }), false, 'une playlist disparue');
  assert.equal(L.routeMissing({ status: 409, payload: { error: 'LIMIT_REACHED' } }), false);
  assert.equal(L.routeMissing(new TypeError('Failed to fetch')), false);
  assert.equal(L.routeMissing(null), false);
  const back = { kind: 'restore', id: 'p2', name: 'Taverne', tracks: [T('x')], created_at: 10, updated_at: 20, at: 1 };
  const old = fakeApi((name) => (name === 'playlistRestore' ? Promise.reject(notFound) : Promise.resolve({ ok: true, playlist_id: 'New42' })));
  assert.deepEqual(await L.sendOp(old.api, back, LIB()), { ok: true, playlist_id: 'New42' }, 'la réponse de la création : le moteur suit le nouvel id');
  assert.deepEqual(old.calls.map(([n]) => n), ['playlistRestore', 'playlistCreate']);
  assert.deepEqual(old.calls[1], ['playlistCreate', 'Taverne', [L.wireTrack(T('x'))]]);
  for (const e of [{ status: 404, payload: { error: 'PLAYLIST_NOT_FOUND' } }, { status: 409, payload: { error: 'LIMIT_REACHED', limit: 'playlists' } },
    { status: 503, payload: { error: 'STORAGE_UNAVAILABLE' } }, new TypeError('Failed to fetch')]) {
    const f = fakeApi(() => Promise.reject(e));
    await assert.rejects(L.sendOp(f.api, back, LIB()), (x) => x === e);
    assert.deepEqual(f.calls.map(([n]) => n), ['playlistRestore'], 'rien de recréé');
  }
});

test('déplacement : il nomme son titre ; 409 STALE (copie dépassée) → vue revenue, Héraut, chansonnier relu', async () => {
  const stale = Object.assign(new Error('STALE'), { status: 409, payload: { ok: false, error: 'STALE', message: 'Cette playlist a changé ailleurs.' } });
  const fails = [];
  const { api, calls } = fakeApi((name) => (name === 'playlistMove' ? Promise.reject(stale) : Promise.resolve(null)));
  const engine = wired(api, LIB({ playlists: [PL('p1', [T('a'), T('b'), T('c')])] }), fails);
  const done = engine.dispatch({ kind: 'move', id: 'p1', url: T('c').url, to: 0 });
  assert.deepEqual(titles(engine.view()), ['c', 'a', 'b'], 'optimiste');
  assert.equal(await done, false);
  assert.deepEqual(calls, [['playlistMove', 'p1', 2, 0, T('c').url]], 'rangs comptés sur le confirmé, titre nommé');
  assert.deepEqual(titles(engine.view()), ['a', 'b', 'c'], 'retour arrière');
  assert.equal(fails.length, 1);
  assert.equal(L.libraryCode(fails[0].e), 'STALE');
  assert.deepEqual(L.noticeOf(L.libraryCode(fails[0].e), fails[0].op, engine.view()), { key: 'library.error.STALE', kind: 'warn' });
  // useLibrary.failed : le Héraut le dit (noticeOf), puis le chansonnier est relu (REREAD)
  const src = read('src/hooks/useLibrary.ts');
  assert.match(src, /const REREAD = new Set\(\[[^\]]*'STALE'[^\]]*\]\);/);
  assert.match(body(src, 'function failed('), /if \(n\) say\(n\.key, \{ vars: n\.vars, kind: n\.kind \}\);\s*else sayError\(e\);\s*if \(REREAD\.has\(code\)\) void load\(\);/);
  const { tx } = await loadTs('../src/theme/copy.extra.ts');
  assert.equal(tx('library.error.STALE.text'), 'Cette playlist a changé ailleurs entre-temps : rien n’a bougé, elle vient d’être relue.');
});
