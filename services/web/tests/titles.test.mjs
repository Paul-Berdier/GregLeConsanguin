import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { cleanTitle, cleanArtist, parseTitle } = await loadTs('../src/lib/titles.ts');

test('cleanTitle retire les mentions entre parenthèses ou crochets', () => {
  assert.equal(cleanTitle('Bohemian Rhapsody (Official Video Remastered)'), 'Bohemian Rhapsody');
  assert.equal(cleanTitle('Take On Me (Official Video) [4K]'), 'Take On Me');
  assert.equal(cleanTitle('Alors on danse (Clip officiel)'), 'Alors on danse');
  assert.equal(cleanTitle('Papaoutai (Vidéo officielle)'), 'Papaoutai');
  assert.equal(cleanTitle('Formidable (Paroles)'), 'Formidable');
  assert.equal(cleanTitle('Song (feat. X)'), 'Song (feat. X)');   // rien à retirer
});

test('cleanArtist retire VEVO, « - Topic » et « Official »', () => {
  assert.equal(cleanArtist('RickAstleyVEVO'), 'RickAstley');
  assert.equal(cleanArtist('Queen - Topic'), 'Queen');
  assert.equal(cleanArtist('Queen Official'), 'Queen');
});

test('parseTitle : « Artiste – Titre » (DESIGN §6)', () => {
  assert.deepEqual(parseTitle('Queen – Bohemian Rhapsody (Official Video Remastered)', 'Queen Official'), { song: 'Bohemian Rhapsody', artist: 'Queen' });
  assert.deepEqual(parseTitle('Rick Astley - Never Gonna Give You Up (Official Music Video)', 'Rick Astley'), { song: 'Never Gonna Give You Up', artist: 'Rick Astley' });
  assert.deepEqual(parseTitle('a-ha - Take On Me (Official Video) [4K]', 'a-ha'), { song: 'Take On Me', artist: 'a-ha' });
});

test('parseTitle : « Titre – Artiste » reconnu grâce à la chaîne', () => {
  assert.deepEqual(parseTitle('Bohemian Rhapsody - Queen', 'Queen'), { song: 'Bohemian Rhapsody', artist: 'Queen' });
});

test('parseTitle : titres non latins (cyrillique, hangeul, kana), le titre n’est pas perdu', () => {
  assert.deepEqual(parseTitle('Кино - Группа крови', 'Кино'), { song: 'Группа крови', artist: 'Кино' });
  assert.deepEqual(parseTitle('Группа крови - Кино', 'Кино'), { song: 'Группа крови', artist: 'Кино' });
  assert.deepEqual(parseTitle('Кино - Кино - Группа крови', 'Кино'), { song: 'Группа крови', artist: 'Кино' });
  assert.deepEqual(parseTitle('아이유 - 좋은 날', 'IU'), { song: '좋은 날', artist: '아이유' });
  assert.deepEqual(parseTitle('ヨルシカ - ただ君に晴れ', 'ヨルシカ'), { song: 'ただ君に晴れ', artist: 'ヨルシカ' });
});

test('parseTitle : titre seul, doublons, vide', () => {
  assert.deepEqual(parseTitle('Never Gonna Give You Up', 'RickAstleyVEVO'), { song: 'Never Gonna Give You Up', artist: 'RickAstley' });
  assert.deepEqual(parseTitle('Nirvana - Nirvana - Smells Like Teen Spirit', 'Nirvana'), { song: 'Smells Like Teen Spirit', artist: 'Nirvana' });
  assert.deepEqual(parseTitle('', null), { song: '', artist: '' });
  assert.deepEqual(parseTitle(undefined, undefined), { song: '', artist: '' });
});
