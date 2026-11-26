// Appareils liés (spec 2026-11-25 §5) : code de l'appli, code en attente, serveur par défaut, erreurs de /lier, appels /overlay.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
import { capture } from './_capture.mjs';

const D = await loadTs('../src/lib/devices.ts');
const { api } = await loadTs('../src/lib/api.ts');
const { tx } = await loadTs('../src/theme/copy.extra.ts');
const kv = () => { const m = new Map(); return { m, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }; };

test('normalizeUserCode / formatUserCode', () => {
  for (const [raw, code] of [['bcdf-ghjk', 'BCDFGHJK'], [' BCDF GHJK ', 'BCDFGHJK'], ['bcdf—ghjk', 'BCDFGHJK'],
    ['BCDF-GHJ', null], ['BCDF-GHJA', null], ['', null], [null, null], [12345678, null]]) assert.equal(D.normalizeUserCode(raw), code, String(raw));
  assert.equal(D.formatUserCode('BCDFGHJK'), 'BCDF-GHJK');
});

test('code en attente : 10 min, illisible retiré, stockage absent ou qui lève sans effet', () => {
  const s = kv(); D.savePendingCode(s, 'bcdf-ghjk', 0);
  assert.equal(D.peekPendingCode(s, 599_999), 'BCDFGHJK');
  assert.equal(D.peekPendingCode(s, 600_000), null); assert.equal(s.m.has(D.PENDING_KEY), false);
  s.setItem(D.PENDING_KEY, '{pas du json'); assert.equal(D.peekPendingCode(s, 0), null); assert.equal(s.m.size, 0);
  D.savePendingCode(s, 'nope', 0); assert.equal(s.m.size, 0);
  assert.equal(D.peekPendingCode(null, 0), null);
  const boom = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() { throw new Error('x'); } };
  assert.doesNotThrow(() => D.savePendingCode(boom, 'BCDFGHJK', 0)); assert.equal(D.peekPendingCode(boom, 0), null);
});

test('takePendingCode consomme le code (pas de seconde redirection)', () => {            // Review Focus 5
  const s = kv(); D.savePendingCode(s, 'BCDFGHJK', 0);
  assert.equal(D.takePendingCode(s, 1), 'BCDFGHJK'); assert.equal(D.peekPendingCode(s, 2), null);
});

test('pickDeviceGuild : enregistré, puis vocal, puis en lecture, puis le premier', () => {
  const g = (id, o = {}) => ({ id, name: id, icon_url: null, greg_voice: null, user_voice: null, playing: false, ...o });
  const all = [g('1'), g('2', { playing: true }), g('3', { user_voice: { id: '9', name: 'V' } })];
  assert.equal(D.pickDeviceGuild(all, '2'), '2'); assert.equal(D.pickDeviceGuild(all, '8'), '3');
  assert.equal(D.pickDeviceGuild(all.slice(0, 2), null), '2'); assert.equal(D.pickDeviceGuild([g('1')], null), '1');
  assert.equal(D.pickDeviceGuild([], '1'), null);
});

test('deviceErrorKey et textes', () => {
  for (const [code, key] of [['CODE_EXPIRED', 'devices.error.CODE_EXPIRED'], ['ALREADY_USED', 'devices.error.ALREADY_USED'],
    ['RATE_LIMITED', 'devices.error.RATE_LIMITED'], ['NOT_GUILD_MEMBER', 'devices.error.NOT_GUILD_MEMBER'],
    ['INVALID_REQUEST', 'devices.error.INVALID_CODE'], ['CSRF_FAILED', 'devices.error.generic'], [undefined, 'devices.error.generic']]) {
    assert.equal(D.deviceErrorKey({ payload: { error: code } }), key); assert.notEqual(tx(key), key);
  }
  assert.equal(D.ageMinutes(1000, 1000 * 1000 + 125_000), 2); assert.equal(D.ageMinutes(2000, 1000), 0);
  assert.equal(tx('devices.age', { n: 3 }), 'Demandé il y a 3\u00a0min');
  assert.equal(tx('devices.approved'), 'C’est fait, Sire. Retournez à votre jeu.');
  assert.equal(tx('devices.warning'), 'N’autorisez que l’appli que vous venez d’ouvrir vous-même.');
  assert.equal(tx('devices.notAllowed'), 'devices.notAllowed');                    // aucune vue « non autorisé »
});

test('api.device* : chemins, corps, session, jamais d’identité', async () => {
  for (const [fn, method, path, body] of [
    [() => api.deviceGuilds(), 'GET', '/api/v1/overlay/guilds', undefined],
    [() => api.deviceLookup('BCDFGHJK'), 'GET', '/api/v1/overlay/device/lookup', undefined],
    [() => api.deviceDecide('BCDFGHJK', 'approve', '42'), 'POST', '/api/v1/overlay/device/approve', { user_code: 'BCDFGHJK', decision: 'approve', guild_id: '42' }],
    [() => api.deviceDecide('BCDFGHJK', 'deny'), 'POST', '/api/v1/overlay/device/approve', { user_code: 'BCDFGHJK', decision: 'deny' }],
    [() => api.deviceTokens(), 'GET', '/api/v1/overlay/tokens', undefined],
    [() => api.deviceRevoke('t1'), 'POST', '/api/v1/overlay/tokens/revoke', { id: 't1' }]]) {
    const { calls } = await capture(fn);
    assert.deepEqual({ method: calls[0].method, path: calls[0].path, body: calls[0].body }, { method, path, body });
    assert.equal(calls[0].credentials, 'include'); assert.ok(!JSON.stringify(calls[0].body ?? {}).includes('user_id'));
  }
  assert.equal((await capture(() => api.deviceLookup('BCDFGHJK'))).calls[0].query, 'user_code=BCDFGHJK');
  assert.equal(api.deviceMe, undefined);                                           // le site ne lit pas /overlay/me
});
