// Garde `expected` (spec 2026-11-25 §3.6) : retirer, déplacer et jouer maintenant nomment le titre visé ; 409 STALE.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
import { capture } from './_capture.mjs';
import { read } from './_contract.mjs';

const { expectedOf, errorCopy } = await loadTs('../src/lib/playerUtils.ts');
const { api } = await loadTs('../src/lib/api.ts');
const { tx } = await loadTs('../src/theme/copy.extra.ts');
const E = { url: 'https://www.youtube.com/watch?v=aaaaaaaaaaa', added_by: '7', ts: 1700000000 };

test('expectedOf : url, added_by, ts du titre tel que le bot l’a', () => {
  assert.deepEqual(expectedOf({ key: 'k', url: 'x', title: 'T', raw: { ...E } }), E);
  assert.deepEqual(expectedOf({ key: 'k', url: 'x', title: 'T', raw: { url: null, requested_by: 7 } }), { url: 'x', added_by: '7', ts: null });
  assert.equal(expectedOf({ key: 'k', url: 'x', title: 'T' }), undefined); assert.equal(expectedOf(undefined), undefined);
});

test('api : expected envoyé seulement s’il est donné', async () => {
  for (const [fn, path, body] of [
    [() => api.queueRemove('42', '7', 2, E), '/api/v1/queue/remove', { index: 2, expected: E }],
    [() => api.move('42', '7', 3, 0, E), '/api/v1/player/move', { src: 3, dst: 0, expected: E }],
    [() => api.playAt('42', '7', 1, E), '/api/v1/playlist/play_at', { index: 1, expected: E }],
    [() => api.queueRemove('42', '7', 2), '/api/v1/queue/remove', { index: 2 }]]) {
    const { calls } = await capture(fn);
    assert.equal(calls[0].path, path); assert.deepEqual(calls[0].body, { ...body, guild_id: '42', user_id: '7' });
  }
});

test('409 STALE : « La file a bougé », texte typographié', () => {
  const e = { status: 409, payload: { ok: false, error: 'STALE', message: 'La file a bougé : réessayez.' } };
  assert.deepEqual(errorCopy(e, { action: 'move' }), { key: 'error.STALE', path: 'error.STALE.text' });
  assert.equal(tx('error.STALE.text'), 'La file a bougé entre-temps\u00a0: rien n’a changé. Réessayez.');
});

test('usePlayer : expected sur les trois mutations, relecture sur STALE', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.match(src, /api\.queueRemove\(gid, uid, i, expectedOf\(q\[i\]\)\)/);
  assert.match(src, /api\.move\(gid, uid, mv\.src, mv\.dst, expectedOf\(q\[mv\.src\]\)\)/);
  assert.match(src, /api\.playAt\(gid, uid, i, expectedOf\(q\[i\]\)\)/);
  const refused = src.slice(src.indexOf('onRefused:'), src.indexOf('\n});', src.indexOf('onRefused:')));
  assert.match(refused, /'STALE'/); assert.match(refused, /refreshPlaylist\(\{ quiet: true \}\)/);
});
