// Chansonnier du Roi : les appels à l'API (routes de la spec 2026-11-23 §3) et l'ajout d'un geste (POST /queue/add_many).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const { api, onAuthLost } = await loadTs('../src/lib/api.ts');
const { EXTRA, tx } = await loadTs('../src/theme/copy.extra.ts');
const { deckToast, withExtras } = await loadTs('../src/lib/herald.ts');

async function capture(fn, reply = { ok: true }, status = 200) {
  const realFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ path: new URL(String(url)).pathname, method: opts.method, body: opts.body ? JSON.parse(opts.body) : undefined, credentials: opts.credentials });
    return new Response(JSON.stringify(reply), { status, headers: { 'content-type': 'application/json' } });
  };
  try { return { calls, res: await fn() }; } finally { globalThis.fetch = realFetch; }
}

const T = { url: 'https://youtu.be/dQw4w9WgXcQ', title: 'R', artist: null, duration: 212, thumb: null, provider: 'youtube' };

test('chansonnier : chaque route, son corps, la session (credentials) et jamais d’identité envoyée', async () => {
  const cases = [
    [() => api.getLibrary(), 'GET', '/api/v1/library', undefined],
    [() => api.libraryLike(T), 'POST', '/api/v1/library/likes/add', { track: T }],
    [() => api.libraryUnlike(T.url), 'POST', '/api/v1/library/likes/remove', { url: T.url }],
    [() => api.playlistCreate('Taverne', [T]), 'POST', '/api/v1/library/playlists/create', { name: 'Taverne', tracks: [T] }],
    [() => api.playlistCreate('Vide'), 'POST', '/api/v1/library/playlists/create', { name: 'Vide', tracks: [] }],
    [() => api.playlistRename('p1', 'Veillée'), 'POST', '/api/v1/library/playlists/rename', { id: 'p1', name: 'Veillée' }],
    [() => api.playlistDelete('p1'), 'POST', '/api/v1/library/playlists/delete', { id: 'p1' }],
    [() => api.playlistAdd('p1', [T]), 'POST', '/api/v1/library/playlists/add', { id: 'p1', tracks: [T] }],
    [() => api.playlistRemove('p1', T.url), 'POST', '/api/v1/library/playlists/remove', { id: 'p1', url: T.url }],
    [() => api.playlistMove('p1', 3, 0), 'POST', '/api/v1/library/playlists/move', { id: 'p1', src: 3, dst: 0 }],
    // annulations à l'ancien rang, déplacement qui nomme son titre (copie dépassée : 409 STALE)
    [() => api.libraryLike(T, 2), 'POST', '/api/v1/library/likes/add', { track: T, index: 2 }],
    [() => api.libraryLike(T, 0), 'POST', '/api/v1/library/likes/add', { track: T, index: 0 }],
    [() => api.playlistRestore({ id: 'p1', name: 'Taverne', tracks: [T], created_at: 10, updated_at: 20 }, 3), 'POST',
      '/api/v1/library/playlists/restore', { playlist: { id: 'p1', name: 'Taverne', tracks: [T], created_at: 10, updated_at: 20 }, index: 3 }],
    [() => api.playlistMove('p1', 3, 0, T.url), 'POST', '/api/v1/library/playlists/move', { id: 'p1', src: 3, dst: 0, url: T.url }],
  ];
  for (const [fn, method, path, body] of cases) {
    const { calls } = await capture(fn);
    assert.equal(calls.length, 1, path);
    assert.deepEqual({ method: calls[0].method, path: calls[0].path, body: calls[0].body }, { method, path, body }, path);
    assert.equal(calls[0].credentials, 'include', `${path} : cookie de session`);
    assert.ok(!JSON.stringify(calls[0].body ?? {}).includes('user_id'), `${path} : l’identité vient de la session seule`);
  }
});

test('POST /queue/add_many : serveur, titres, libellé (comme /queue/add)', async () => {
  const { calls } = await capture(() => api.queueAddMany('42', '7', [T], 'Taverne'));
  assert.deepEqual(calls[0], { path: '/api/v1/queue/add_many', method: 'POST', credentials: 'include',
    body: { items: [T], label: 'Taverne', guild_id: '42', user_id: '7' } });
  const bare = await capture(() => api.queueAddMany('42', '7', [T]));
  assert.ok(!('label' in bare.calls[0].body), 'sans libellé : pas de champ vide');
});

test('chansonnier : un refus de l’API garde son code (LIMIT_REACHED, STORAGE_UNAVAILABLE) ; 401 : session perdue', async () => {
  const realFetch = globalThis.fetch;
  const seen = [];
  const off = onAuthLost((e) => seen.push(e));
  const reply = (status, body) => async () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  try {
    globalThis.fetch = reply(409, { ok: false, error: 'LIMIT_REACHED', message: 'Plafond atteint.' });
    await assert.rejects(api.libraryLike(T), (e) => e.status === 409 && e.payload.error === 'LIMIT_REACHED');
    globalThis.fetch = reply(503, { ok: false, error: 'STORAGE_UNAVAILABLE' });
    await assert.rejects(api.getLibrary(), (e) => e.status === 503 && e.payload.error === 'STORAGE_UNAVAILABLE');
    globalThis.fetch = reply(409, { ok: false, error: 'STALE', message: 'Cette playlist a changé ailleurs.' });
    await assert.rejects(api.playlistMove('p1', 1, 0, T.url), (e) => e.status === 409 && e.payload.error === 'STALE');
    // API d'avant la route de restauration : le 404 générique de Flask (errors.py), que sendOp distingue d'une playlist disparue
    globalThis.fetch = reply(404, { ok: false, error: 'not_found' });
    await assert.rejects(api.playlistRestore({ id: 'p1', name: 'X', tracks: [] }, 0), (e) => e.status === 404 && e.payload.error === 'not_found');
    assert.equal(seen.length, 0);
    globalThis.fetch = reply(401, { ok: false, error: 'NOT_AUTHENTICATED' });
    await assert.rejects(api.playlistDelete('p1'));
    assert.equal(seen.length, 1, 'le chemin habituel de la perte de session (usePlayer le vide, le Héraut le dit)');
  } finally {
    off();
    globalThis.fetch = realFetch;
  }
});

test('Héraut : les annonces du chansonnier sont des entrées { text } de copy.extra.ts, lues après le deck', () => {
  const deck = withExtras({ t: (p) => p, has: () => false, quip: () => null, seedOf: () => 0 }, tx);
  const say = (key, vars, kind) => deckToast(key, { vars, kind }, deck);
  assert.equal(say('library.toast.saved', { n: 3, name: 'Taverne' }, 'ok').fact, 'File enregistrée dans « Taverne » : 3 titres');
  assert.equal(say('library.toast.saved', { n: 1, name: 'Taverne' }, 'ok').fact, 'File enregistrée dans « Taverne » : 1 titre');
  assert.equal(say('library.toast.addedTo', { name: 'Taverne', title: 'Africa' }, 'ok').fact, 'Ajouté à « Taverne » : Africa');
  assert.equal(say('library.error.limitLikes', { n: 500 }, 'warn').fact, 'Vous avez atteint le plafond de 500 coups de cœur. Retirez-en un pour en garder un autre.');
  const err = say('library.error.STORAGE_UNAVAILABLE', {}, 'err');
  assert.equal(err.kind, 'err');
  assert.equal(err.quip, null, 'pas de réplique dans EXTRA');
  // 409 STALE d'un déplacement : typographie du deck (U+00A0 avant « : », apostrophe courbe)
  const stale = say('library.error.STALE', {}, 'warn');
  assert.equal(stale.fact, 'Cette playlist a changé ailleurs entre-temps : rien n’a bougé, elle vient d’être relue.');
  assert.equal(stale.kind, 'warn');
  // toast de « Tout jouer » (usePlayer.enqueueMany) : la clé du deck (toast.playlistAdded) pour la sorte, ce texte pour le fait
  assert.equal(tx('library.toast.played.text', { n: 12, name: 'Coups de cœur' }), '12 titres ajoutés depuis « Coups de cœur »');
  assert.equal(tx('library.toast.played.text', { n: 1, name: 'X' }), '1 titre ajouté depuis « X »');
  for (const k of Object.keys(EXTRA.library.error)) assert.equal(typeof EXTRA.library.error[k].text, 'string', k);
});
