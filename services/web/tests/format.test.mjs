import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { fmt, extractVideoId, discordAvatar } = await loadTs('../src/lib/format.ts');
test('fmt', () => { assert.equal(fmt(213), '3:33'); assert.equal(fmt(null), '--:--'); assert.equal(fmt(-1), '--:--'); });
test('extractVideoId', () => {
  assert.equal(extractVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1'), 'dQw4w9WgXcQ');
  assert.equal(extractVideoId('https://youtu.be/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.equal(extractVideoId('nope'), null);
});
test('discordAvatar', () => {
  assert.equal(discordAvatar({ id: '1', avatar: 'abc' }, 96), 'https://cdn.discordapp.com/avatars/1/abc.png?size=96');
  assert.match(discordAvatar({ id: '175928847299117063' }), /embed\/avatars\/\d\.png$/);
  assert.equal(discordAvatar(null), null);
});
