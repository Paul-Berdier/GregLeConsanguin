import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { classifyLink, submitLabelKey, isBadLink } = await loadTs('../src/lib/links.ts');
const cases = [
  ['never gonna give you up', 'none'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'video'],
  ['youtu.be/dQw4w9WgXcQ', 'video'],
  ['https://www.youtube.com/shorts/dQw4w9WgXcQ', 'video'],
  ['https://m.youtube.com/playlist?list=PLabc', 'playlist'],
  ['https://music.youtube.com/playlist?list=OLAK5uy_x', 'playlist'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc', 'playlist'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ', 'mix'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&start_radio=1', 'mix'],
  ['https://www.youtube.com/@artiste', 'channel'],
  ['https://open.spotify.com/playlist/37i9', 'spotify'],
  ['https://soundcloud.com/x/y', 'unsupported'],
];
test('classifyLink', () => { for (const [i, k] of cases) assert.equal(classifyLink(i), k, i); });
test('classifyLink : hôtes, variantes et liens <…> de Discord', () => {
  assert.equal(classifyLink('<https://youtu.be/dQw4w9WgXcQ>'), 'video');
  assert.equal(classifyLink('https://youtu.be/dQw4w9WgXcQ?list=PLabc'), 'playlist');
  assert.equal(classifyLink('https://www.youtube.com/playlist'), 'playlist');
  assert.equal(classifyLink('https://www.youtube.com/channel/UC123'), 'channel');
  assert.equal(classifyLink('https://www.youtube.com/'), 'unsupported');
  assert.equal(classifyLink('spotify:track:abc'), 'spotify');
  assert.equal(classifyLink('https://spotify.link/xyz'), 'spotify');
  assert.equal(classifyLink('https://example.com/a'), 'unsupported');
  assert.equal(classifyLink('Mr.Brightside'), 'none');
  assert.equal(classifyLink(''), 'none');
});
// Mêmes règles que le bot (packages/shared/greg_shared/extractors/youtube.py) : la pastille
// décrit ce que l'ajout fera vraiment.
test('classifyLink suit le bot : formes de vidéo et hôtes YouTube (_YTID_RE, _is_youtube_host)', () => {
  for (const u of [
    'https://www.youtube.com/live/dQw4w9WgXcQ',
    'https://www.youtube.com/embed/dQw4w9WgXcQ',
    'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ',
    'https://www.youtube.com/v/dQw4w9WgXcQ',
    'https://music.youtube.com/watch?v=dQw4w9WgXcQ',
  ]) assert.equal(classifyLink(u), 'video', u);
});
test('classifyLink suit le bot : playlists YouTube Music et mix (RD, UL, PU, start_radio)', () => {
  assert.equal(classifyLink('https://music.youtube.com/browse/VLPLabc'), 'playlist');
  assert.equal(classifyLink('https://music.youtube.com/browse/MPREb_abc'), 'playlist');
  assert.equal(classifyLink('https://www.youtube-nocookie.com/embed/videoseries?list=PLabc'), 'playlist');
  assert.equal(classifyLink('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=ULdQw4w9WgXcQ'), 'mix');
  assert.equal(classifyLink('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PUabc'), 'mix');
  assert.equal(classifyLink('https://www.youtube.com/watch?v=dQw4w9WgXcQ&start_radio=true'), 'mix');
  // start_radio ne fait un mix qu'avec une vidéo, et ne l'emporte pas sur une vraie playlist
  assert.equal(classifyLink('https://www.youtube.com/watch?start_radio=1'), 'unsupported');
  assert.equal(classifyLink('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc&start_radio=1'), 'playlist');
});
test('chaîne : le bot en ajoute les derniers titres comme une playlist (_YT_TAB_PATH_RE)', () => {
  for (const u of [
    'https://www.youtube.com/@artiste/videos', 'https://www.youtube.com/channel/UC123/streams',
    'https://www.youtube.com/c/Nom', 'https://www.youtube.com/user/nom/', 'https://music.youtube.com/channel/UC123',
    'youtube.com/@artiste/shorts',
  ]) assert.equal(classifyLink(u), 'channel', u);
  // onglets que le bot ne déplie pas : non pris en charge
  for (const u of ['https://www.youtube.com/@artiste/playlists', 'https://www.youtube.com/@artiste/community', 'https://youtu.be/@artiste'])
    assert.equal(classifyLink(u), 'unsupported', u);
  assert.equal(submitLabelKey('channel'), 'search.submit.playlist');
  assert.equal(isBadLink('channel'), false);
});
test('isBadLink : pastille rouge pour Spotify et les liens non pris en charge seulement', () => {
  assert.equal(isBadLink('spotify'), true);
  assert.equal(isBadLink('unsupported'), true);
  for (const k of ['none', 'video', 'playlist', 'mix', 'channel']) assert.equal(isBadLink(k), false, k);
});
test('classifyLink et looksLikeUrl disent la même chose de ce qui est un lien', async () => {
  const { looksLikeUrl } = await loadTs('../src/lib/playerUtils.ts');
  const inputs = [...cases.map(([i]) => i), 'Mr.Brightside', 'www.youtube.com', 'on.soundcloud.com/x',
    'example.com/a', 'https://example.com', 'spotify:track:abc', '<youtu.be/dQw4w9WgXcQ>', 'a b', '',
    'youtube-nocookie.com/embed/dQw4w9WgXcQ', 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'];
  for (const i of inputs) assert.equal(classifyLink(i) !== 'none', looksLikeUrl(i), i);
});
test('submitLabelKey', () => {
  assert.equal(submitLabelKey('playlist'), 'search.submit.playlist');
  assert.equal(submitLabelKey('mix'), 'search.submit.mix');
  assert.equal(submitLabelKey('video'), 'search.submit.default');
});
