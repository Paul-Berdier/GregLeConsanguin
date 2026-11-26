// next.config.js : aucune page du site ne s'affiche dans un cadre d'un autre site (clickjacking de /lier), et le
// relais vers l'API (rewrites, socket.io sans redirection du slash final) reste tel quel.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const config = require('../next.config.js');

test('toutes les routes refusent d’être encadrées : frame-ancestors \'none\' et X-Frame-Options DENY', async () => {
  assert.equal(typeof config.headers, 'function');
  const rules = await config.headers();
  const all = rules.find((r) => r.source === '/:path*');
  assert.ok(all, 'une règle sur /:path*');
  const got = Object.fromEntries(all.headers.map(({ key, value }) => [key, value]));
  assert.deepEqual(got, { 'Content-Security-Policy': "frame-ancestors 'none'", 'X-Frame-Options': 'DENY' });
});

test('rewrites vers l’API et skipTrailingSlashRedirect intacts', async () => {
  const before = process.env.API_URL;
  process.env.API_URL = 'http://api.test:3000';
  const log = console.log;
  console.log = () => {};
  try {
    assert.deepEqual(await config.rewrites(), [
      { source: '/api/:path*', destination: 'http://api.test:3000/api/:path*' },
      { source: '/socket.io', destination: 'http://api.test:3000/socket.io/' },
      { source: '/socket.io/:path*', destination: 'http://api.test:3000/socket.io/:path*' },
    ]);
  } finally {
    console.log = log;
    if (before === undefined) delete process.env.API_URL; else process.env.API_URL = before;
  }
  assert.equal(config.skipTrailingSlashRedirect, true);
});
