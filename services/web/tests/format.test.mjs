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
// Mêmes formes que la pastille (links.ts) et le bot (_YTID_RE) : un lien /live/ collé doit avoir sa vidéo sur la scène
test('extractVideoId : /live/, /embed/, /shorts/ et anciennes formes /v/ /e/ /watch/', () => {
  const id = 'dQw4w9WgXcQ';
  for (const u of [
    `https://www.youtube.com/live/${id}?si=abc`, `https://www.youtube.com/embed/${id}`,
    `https://www.youtube-nocookie.com/embed/${id}`, `https://www.youtube.com/shorts/${id}`,
    `https://www.youtube.com/v/${id}`, `https://www.youtube.com/e/${id}`, `https://www.youtube.com/watch/${id}`,
    `https://www.youtube.com/watch?feature=share&v=${id}`,
  ]) assert.equal(extractVideoId(u), id, u);
  assert.equal(extractVideoId('https://www.youtube.com/embed/videoseries?list=PL1'), null);
});
test('extractVideoId : tout lien que la pastille dit « vidéo » a son identifiant', async () => {
  const { classifyLink } = await loadTs('../src/lib/links.ts');
  const id = 'dQw4w9WgXcQ';
  const urls = ['/watch?v=', '/shorts/', '/live/', '/embed/', '/v/', '/e/', '/watch/']
    .flatMap((p) => [`https://www.youtube.com${p}${id}`, `https://m.youtube.com${p}${id}`, `https://music.youtube.com${p}${id}`])
    .concat([`https://youtu.be/${id}`, `youtu.be/${id}`, `<https://youtu.be/${id}>`, `https://www.youtube-nocookie.com/embed/${id}`]);
  for (const u of urls) {
    assert.equal(classifyLink(u), 'video', u);
    assert.equal(extractVideoId(u), id, u);
  }
});
// Comme la pastille (YOUTUBE_HOST) et le bot (_is_youtube_host) : le même chemin sur un autre site n'est pas une vidéo
// (SoundCloud : un compte « watch » ou « live ») ; sinon la scène chargerait une fausse vidéo et la file une fausse pochette.
test('extractVideoId : hôtes YouTube seulement', () => {
  for (const u of [
    'https://soundcloud.com/watch/late-night-session', 'https://soundcloud.com/live/late-night-session',
    'https://example.com/embed/dQw4w9WgXcQ', 'https://example.com/v/dQw4w9WgXcQ', 'https://vimeo.com/x?v=dQw4w9WgXcQ',
    'https://notyoutube.com/watch?v=dQw4w9WgXcQ', 'https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ',
  ]) assert.equal(extractVideoId(u), null, u);
  assert.equal(extractVideoId('https://music.youtube.com/watch?v=dQw4w9WgXcQ'), 'dQw4w9WgXcQ', 'sous-domaine');
  assert.equal(extractVideoId('https://WWW.YouTube.com/watch?v=dQw4w9WgXcQ'), 'dQw4w9WgXcQ', 'hôte en capitales');
});
test('discordAvatar', () => {
  assert.equal(discordAvatar({ id: '1', avatar: 'abc' }, 96), 'https://cdn.discordapp.com/avatars/1/abc.png?size=96');
  assert.match(discordAvatar({ id: '175928847299117063' }), /embed\/avatars\/\d\.png$/);
  assert.equal(discordAvatar(null), null);
});
