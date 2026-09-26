// Tests de la résolution de la base API côté navigateur (node:test, sans réseau).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadTs } from './_loadTs.mjs';

const { resolveApiBase, isBrowserReachable, isNotAuthenticated, onAuthLost, api } = await loadTs('../src/lib/api.ts');

// ── compose-build-time-config : plus de repli implicite vers la prod ──
test('resolveApiBase : NEXT_PUBLIC_API_URL (build) utilisée en local, /api/v1 ajouté', () => {
  assert.equal(resolveApiBase({ pageHost: 'localhost', envUrl: 'http://localhost:3000' }), 'http://localhost:3000/api/v1');
  assert.equal(resolveApiBase({ pageHost: 'localhost', envUrl: 'http://localhost:3000/' }), 'http://localhost:3000/api/v1');
  assert.equal(resolveApiBase({ pageHost: '127.0.0.1', envUrl: ' http://localhost:3000/api/v1/ ' }), 'http://localhost:3000/api/v1');
});

test('resolveApiBase : sans configuration → /api/v1 relatif sur tout hôte (jamais la prod en dur)', () => {
  for (const pageHost of ['localhost', '192.168.1.20', 'greg.example.fr', 'gregleconsanguin.up.railway.app']) {
    assert.equal(resolveApiBase({ pageHost }), '/api/v1', pageHost);
    assert.equal(resolveApiBase({ pageHost, envUrl: '' }), '/api/v1', pageHost);
  }
});

test('resolveApiBase : front de prod (*.railway.app) → toujours /api/v1 relatif (inchangé)', () => {
  assert.equal(resolveApiBase({ pageHost: 'gregleconsanguin.up.railway.app', envUrl: 'https://autre.example.com' }), '/api/v1');
});

test('resolveApiBase : NEXT_PUBLIC_API_URL injoignable par le navigateur → ignorée', () => {
  // nom de service Docker / réseau privé Railway
  assert.equal(resolveApiBase({ pageHost: 'localhost', envUrl: 'http://api:3000' }), '/api/v1');
  assert.equal(resolveApiBase({ pageHost: 'greg.example.fr', envUrl: 'http://api.railway.internal:3000' }), '/api/v1');
  // localhost figé dans un build servi depuis une autre machine
  assert.equal(resolveApiBase({ pageHost: 'greg.example.fr', envUrl: 'http://localhost:3000' }), '/api/v1');
  assert.equal(resolveApiBase({ pageHost: '192.168.1.20', envUrl: 'http://localhost:3000' }), '/api/v1');
  // valeur invalide
  assert.equal(resolveApiBase({ pageHost: 'localhost', envUrl: 'pas une url' }), '/api/v1');
});

test('resolveApiBase : NEXT_PUBLIC_API_URL publique utilisée hors railway.app', () => {
  assert.equal(resolveApiBase({ pageHost: 'localhost', envUrl: 'https://gregleconsanguin.up.railway.app' }),
    'https://gregleconsanguin.up.railway.app/api/v1');
  assert.equal(resolveApiBase({ pageHost: 'greg.example.fr', envUrl: '/greg/api/v1/' }), '/greg/api/v1');
});

test('resolveApiBase : window.GREG_API_BASE reste prioritaire', () => {
  assert.equal(resolveApiBase({ pageHost: 'localhost', override: 'https://x.example/api/v1/', envUrl: 'http://localhost:3000' }),
    'https://x.example/api/v1');
  assert.equal(resolveApiBase({ pageHost: 'localhost', override: '/custom/', envUrl: 'http://localhost:3000' }), '/custom');
  assert.equal(resolveApiBase({ pageHost: 'gregleconsanguin.up.railway.app', override: '/custom/' }), '/custom');
  assert.equal(resolveApiBase({ pageHost: 'localhost', override: '   ' }), '/api/v1');
});

test('isBrowserReachable : services internes et localhost vu depuis un autre hôte', () => {
  assert.equal(isBrowserReachable('http://localhost:3000', 'localhost'), true);
  assert.equal(isBrowserReachable('http://127.0.0.1:3000', 'localhost'), true);
  assert.equal(isBrowserReachable('http://[::1]:3000', '127.0.0.1'), true);
  assert.equal(isBrowserReachable('https://gregleconsanguin.up.railway.app', 'greg.example.fr'), true);
  assert.equal(isBrowserReachable('http://192.168.1.20:3000', '192.168.1.20'), true);
  assert.equal(isBrowserReachable('http://api:3000', 'localhost'), false);
  assert.equal(isBrowserReachable('http://api.railway.internal:3000', 'x.up.railway.app'), false);
  assert.equal(isBrowserReachable('http://localhost:3000', 'gregleconsanguin.up.railway.app'), false);
  assert.equal(isBrowserReachable('not a url', 'localhost'), false);
});

// ── SEC-C7 : 401 NOT_AUTHENTICATED sur n'importe quel appel → déconnecté ──
test('isNotAuthenticated : seul un 401 NOT_AUTHENTICATED (toute casse) compte', () => {
  assert.equal(isNotAuthenticated(401, { ok: false, error: 'NOT_AUTHENTICATED', message: 'Connecte-toi…' }), true);
  assert.equal(isNotAuthenticated(401, { ok: false, error: 'not_authenticated' }), true); // /users/me, /guilds
  assert.equal(isNotAuthenticated(401, { ok: false, error: 'not_linked' }), false); // autre 401 ≠ session Discord
  assert.equal(isNotAuthenticated(401, { ok: false, error: 'unauthorized' }), false);
  assert.equal(isNotAuthenticated(403, { ok: false, error: 'NOT_AUTHENTICATED' }), false);
  assert.equal(isNotAuthenticated(401, null), false);
  assert.equal(isNotAuthenticated(401, 'Unauthorized'), false);
});

test('onAuthLost : prévenu à chaque 401 NOT_AUTHENTICATED, jamais pour un autre refus', async () => {
  const realFetch = globalThis.fetch;
  const reply = (status, body) => async () => new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  });
  const seen = [];
  const off = onAuthLost((e) => seen.push(e));
  try {
    globalThis.fetch = reply(401, { ok: false, error: 'NOT_AUTHENTICATED', message: 'Connecte-toi avec Discord pour contrôler Greg.' });
    await assert.rejects(api.queueSkip('42', '1'), (e) => e.status === 401);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].status, 401);
    assert.equal(seen[0].payload.error, 'NOT_AUTHENTICATED');

    globalThis.fetch = reply(401, { ok: false, error: 'not_linked' });
    await assert.rejects(api.getHistory('42'));
    globalThis.fetch = reply(403, { ok: false, error: 'NOT_GUILD_MEMBER' });
    await assert.rejects(api.queueSkip('42', '1'));
    assert.equal(seen.length, 1);

    off();
    globalThis.fetch = reply(401, { ok: false, error: 'NOT_AUTHENTICATED' });
    await assert.rejects(api.queueSkip('42', '1'));
    assert.equal(seen.length, 1);
  } finally {
    off();
    globalThis.fetch = realFetch;
  }
});
