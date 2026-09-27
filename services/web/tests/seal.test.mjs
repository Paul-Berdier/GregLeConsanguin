// Le Sceau (étape 4) : l'ajout du Roi attendu, reconnu à l'entrée de sa ligne.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const S = await loadTs('../src/lib/queue/seal.ts');

test('la prochaine ligne du Roi, du même titre, dans les 10 s, une seule fois', () => {
  const b = S.createSealBook(), e = { url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', from: null, thumb: null, at: 1000 };
  b.expect(e);
  assert.equal(b.take({ url: 'https://youtu.be/dQw4w9WgXcQ', mine: false }, 1100), null, 'ligne d’un autre');
  assert.equal(b.take({ url: 'https://youtu.be/djV11Xbc914', mine: true }, 1100), null, 'autre vidéo');
  assert.equal(b.take({ url: 'https://youtu.be/dQw4w9WgXcQ?si=abc', mine: true }, 1200), e);
  assert.equal(b.take({ url: 'https://youtu.be/dQw4w9WgXcQ', mine: true }, 1300), null);
});

test('recherche tapée (url null) : la première ligne du Roi ; périmé après 10 s ; clear', () => {
  const b = S.createSealBook(), any = { url: null, from: null, thumb: null, at: 0 }, row = { url: 'https://soundcloud.com/a/b', mine: true };
  b.expect(any); assert.equal(b.take(row, S.SEAL_TTL_MS + 1), null);
  b.expect(any); assert.ok(b.take(row, 500));
  b.expect(any); b.clear(); assert.equal(b.take(row, 1), null);
});

test('même titre : ids YouTube comparés, sinon liens identiques ; délais', () => {
  assert.ok(S.sameTrack('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1', 'https://youtu.be/dQw4w9WgXcQ'));
  assert.ok(S.sameTrack('https://music.youtube.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ'));
  assert.ok(!S.sameTrack('https://youtu.be/dQw4w9WgXcQ', 'https://youtu.be/djV11Xbc914'));
  const bot = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';   // formes que links.ts classe « vidéo » (VIDEO_ID)
  for (const u of ['https://www.youtube.com/live/dQw4w9WgXcQ', 'https://www.youtube.com/embed/dQw4w9WgXcQ',
    'https://www.youtube.com/v/dQw4w9WgXcQ', 'https://www.youtube.com/e/dQw4w9WgXcQ', 'https://www.youtube.com/watch/dQw4w9WgXcQ']) {
    assert.ok(S.sameTrack(u, bot), u);
  }
  assert.ok(!S.sameTrack('https://www.youtube.com/embed/videoseries?list=PLx', 'https://www.youtube.com/embed/videoseries?list=PLy'),
    '« videoseries » n’est pas un id');
  assert.ok(S.sameTrack('https://soundcloud.com/a/b', 'https://soundcloud.com/a/b') && !S.sameTrack('https://soundcloud.com/a/b', undefined));
  assert.deepEqual([S.SEAL_STAMP_DELAY_MS, S.SEAL_FLIGHT_MS], [380, 460]);
});
