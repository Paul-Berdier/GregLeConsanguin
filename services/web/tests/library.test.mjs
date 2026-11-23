// Le chansonnier du Roi (spec 2026-11-23 §3) : identité d'un titre, nettoyage, plans, modifications optimistes, moteur.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const L = await loadTs('../src/lib/library.ts');
const {
  trackKey, youtubeId, providerOf, toLibraryTrack, wireTrack, cleanName, nameOk, totalSeconds, findPlaylist, tracksOf,
  likedKeys, addPlan, moveIndices, applyOp, checkOp, libraryCode, noticeOf, parseLibrary, createLibraryEngine,
  DEFAULT_LIMITS, LIKES, ADD_MANY_MAX,
} = L;

const NOW = 1_700_000_000_000;
const tr = (id, extra = {}) => ({ url: `https://youtu.be/${id.padEnd(11, '_')}`, title: id, artist: null, duration: 100, thumb: null, provider: 'youtube', added_at: 1, ...extra });
const pl = (id, tracks = [], name = id) => ({ id, name, tracks, created_at: 1, updated_at: 1 });
const lib = (o = {}) => ({ likes: [], playlists: [], limits: { ...DEFAULT_LIMITS }, ...o });
const urls = (list) => list.map((t) => t.title);

// ── identité d'un titre : la même clé que l'API ─────────────────────────────────────────────
test('trackKey : toutes les formes YouTube de la spec donnent yt:<id>', () => {
  const id = 'dQw4w9WgXcQ';
  for (const u of [
    `https://www.youtube.com/watch?v=${id}`,
    `https://youtube.com/watch?v=${id}&t=42s`,
    `https://m.youtube.com/watch?feature=share&v=${id}`,
    `https://music.youtube.com/watch?v=${id}&list=RDAMVM${id}`,
    `https://youtu.be/${id}`,
    `https://youtu.be/${id}?si=abc`,
    `https://www.youtube.com/shorts/${id}`,
    `https://www.youtube.com/embed/${id}?autoplay=1`,
    `HTTPS://WWW.YOUTUBE.COM/watch?v=${id}`,
    `  https://youtu.be/${id}/  `,
  ]) assert.equal(trackKey(u), `yt:${id}`, u);
  assert.equal(youtubeId(`https://www.youtube.com/watch?v=${id}`), id);
});

test('trackKey : ailleurs que sur une vidéo YouTube, le lien sans espaces autour ni « / » final', () => {
  assert.equal(trackKey('https://soundcloud.com/artiste/titre'), 'url:https://soundcloud.com/artiste/titre');
  assert.equal(trackKey(' https://soundcloud.com/artiste/titre/ '), 'url:https://soundcloud.com/artiste/titre', 'espaces et « / » final');
  assert.equal(trackKey('https://soundcloud.com/artiste/titre//'), 'url:https://soundcloud.com/artiste/titre');
  assert.equal(trackKey('https://soundcloud.com/a/t?si=x'), 'url:https://soundcloud.com/a/t?si=x', 'la requête reste');
  // pas une vidéo : une playlist YouTube, « videoseries », un autre hôte qui porte v=
  assert.equal(trackKey('https://www.youtube.com/playlist?list=PL123'), 'url:https://www.youtube.com/playlist?list=PL123');
  assert.equal(trackKey('https://www.youtube.com/embed/videoseries?list=PL1'), 'url:https://www.youtube.com/embed/videoseries?list=PL1');
  assert.equal(trackKey('https://example.com/watch?v=dQw4w9WgXcQ'), 'url:https://example.com/watch?v=dQw4w9WgXcQ');
  assert.equal(trackKey('https://notyoutube.com/watch?v=dQw4w9WgXcQ'), 'url:https://notyoutube.com/watch?v=dQw4w9WgXcQ');
  assert.equal(trackKey(''), '');
  assert.equal(trackKey(null), '');
  assert.equal(trackKey('   '), '');
});

test('trackKey : deux formes de la même vidéo sont un doublon', () => {
  assert.equal(trackKey('https://youtu.be/dQw4w9WgXcQ'), trackKey('https://music.youtube.com/watch?v=dQw4w9WgXcQ'));
  assert.notEqual(trackKey('https://youtu.be/dQw4w9WgXcQ'), trackKey('https://youtu.be/aaaaaaaaaaa'));
});

test('providerOf : déduit de l’hôte', () => {
  assert.equal(providerOf('https://music.youtube.com/watch?v=dQw4w9WgXcQ'), 'youtube');
  assert.equal(providerOf('https://youtu.be/dQw4w9WgXcQ'), 'youtube');
  assert.equal(providerOf('https://m.soundcloud.com/a/b'), 'soundcloud');
  assert.equal(providerOf('https://example.com/a.mp3'), null);
});

// ── nettoyage d'un titre, comme l'API le stocke ───────────────────────────────────────────────
test('toLibraryTrack : lien http(s) obligatoire, au plus 500 caractères', () => {
  assert.equal(toLibraryTrack({ url: 'youtu.be/dQw4w9WgXcQ' }, NOW), null, 'sans schéma');
  assert.equal(toLibraryTrack({ url: 'ftp://x.org/a' }, NOW), null);
  assert.equal(toLibraryTrack({ url: `https://x.org/${'a'.repeat(490)}` }, NOW), null, '> 500');
  assert.equal(toLibraryTrack({ title: 'sans lien' }, NOW), null);
  assert.equal(toLibraryTrack(null, NOW), null);
  assert.equal(toLibraryTrack({ webpage_url: 'https://youtu.be/dQw4w9WgXcQ' }, NOW)?.url, 'https://youtu.be/dQw4w9WgXcQ', 'repli : webpage_url');
});

test('toLibraryTrack : titre (le lien à défaut, 200), artiste (120 ou null), durée, pochette, source, date', () => {
  const t = toLibraryTrack({ url: ' https://youtu.be/dQw4w9WgXcQ ', title: '  Never   gonna ', artist: '', duration: 212.9,
    thumbnail: 'https://i.ytimg.com/vi/x/hq.jpg' }, NOW);
  assert.deepEqual(t, { url: 'https://youtu.be/dQw4w9WgXcQ', title: 'Never gonna', artist: null, duration: 212,
    thumb: 'https://i.ytimg.com/vi/x/hq.jpg', provider: 'youtube', added_at: NOW / 1000 });
  assert.equal(toLibraryTrack({ url: 'https://x.org/a' }, NOW).title, 'https://x.org/a', 'le lien à défaut');
  const long = toLibraryTrack({ url: 'https://x.org/a', title: '😀'.repeat(250), artist: 'é'.repeat(130) }, NOW);
  assert.equal([...long.title].length, 200, 'en caractères, pas en unités UTF-16');
  assert.equal(long.artist.length, 120);
  for (const [d, want] of [[-1, null], [86401, null], [86400, 86400], [0, 0], [NaN, null], [null, null], ['12', null]]) {
    assert.equal(toLibraryTrack({ url: 'https://x.org/a', duration: d }, NOW).duration, want, String(d));
  }
  assert.equal(toLibraryTrack({ url: 'https://x.org/a', thumb: 'data:image/png;base64,xx' }, NOW).thumb, null);
  assert.equal(toLibraryTrack({ url: 'https://soundcloud.com/a/b', provider: 'mixcloud' }, NOW).provider, 'soundcloud', 'déduite');
  assert.equal(toLibraryTrack({ url: 'https://x.org/a', provider: 'soundcloud' }, NOW).provider, 'soundcloud', 'donnée');
  assert.equal(toLibraryTrack({ url: 'https://x.org/a', added_at: 1234.5 }, NOW).added_at, 1234, 'date de l’API gardée');
});

test('wireTrack : ce que l’API reçoit (sans date) ; plafond de POST /queue/add_many', () => {
  assert.deepEqual(wireTrack(tr('a')), { url: tr('a').url, title: 'a', artist: null, duration: 100, thumb: null, provider: 'youtube' });
  assert.equal(ADD_MANY_MAX, 100);
});

test('cleanName / nameOk : espaces réduits, contrôles retirés, 1 à 60 caractères', () => {
  assert.equal(cleanName('  Soirée \t  taverne\n '), 'Soirée taverne');
  assert.equal(cleanName('Bal\u0007 des\u0000 gueux'), 'Bal des gueux');
  assert.equal(cleanName(42), '');
  assert.equal(nameOk(''), false);
  assert.equal(nameOk('a'), true);
  assert.equal(nameOk('a'.repeat(60)), true);
  assert.equal(nameOk('a'.repeat(61)), false);
  assert.equal(nameOk('🎻'.repeat(60)), true, 'en caractères');
  assert.equal(nameOk('abc', 2), false, 'plafond de l’API');
});

test('durées et recherches', () => {
  assert.equal(totalSeconds([{ duration: 60 }, { duration: null }, { duration: 30 }, { duration: -5 }]), 90);
  assert.equal(totalSeconds([]), 0);
  const l = lib({ likes: [tr('a')], playlists: [pl('p1', [tr('b')])] });
  assert.equal(findPlaylist(l, 'p1').name, 'p1');
  assert.equal(findPlaylist(l, 'nope'), null);
  assert.equal(findPlaylist(null, 'p1'), null);
  assert.deepEqual(urls(tracksOf(l, LIKES)), ['a']);
  assert.deepEqual(urls(tracksOf(l, 'p1')), ['b']);
  assert.equal(tracksOf(l, 'nope'), null);
  assert.ok(likedKeys(l.likes).has(trackKey(tr('a').url)));
});

// ── plans et modifications ────────────────────────────────────────────────────────────────────
test('addPlan : doublons écartés (entre eux et avec la playlist), place restante', () => {
  const twin = { ...tr('a'), url: `https://www.youtube.com/watch?v=${'a'.padEnd(11, '_')}` };
  assert.deepEqual(urls(addPlan([tr('a')], [twin, tr('b'), tr('b'), tr('c')], 200).added), ['b', 'c']);
  assert.equal(addPlan([tr('a')], [twin, tr('b'), tr('b'), tr('c')], 200).skipped, 2);
  const p = addPlan([tr('a'), tr('b')], [tr('c'), tr('d'), tr('e')], 3);
  assert.deepEqual(urls(p.added), ['c']);
  assert.equal(p.skipped, 2, 'ce qui dépasse compte dans skipped');
  assert.deepEqual(addPlan([], [{ ...tr('x'), url: '' }], 5).added, [], 'sans lien : écarté');
});

test('moveIndices : tracks.insert(dst, tracks.pop(src)) amène le titre au rang voulu', () => {
  const list = [tr('a'), tr('b'), tr('c'), tr('d')];
  const apply = ({ src, dst }) => { const x = list.slice(); x.splice(dst, 0, ...x.splice(src, 1)); return urls(x); };
  assert.deepEqual(moveIndices(list, tr('b').url, 0), { src: 1, dst: 0 });
  assert.deepEqual(apply(moveIndices(list, tr('b').url, 2)), ['a', 'c', 'b', 'd']);
  assert.deepEqual(apply(moveIndices(list, tr('a').url, 99)), ['b', 'c', 'd', 'a'], 'borné à la fin');
  assert.equal(moveIndices(list, tr('a').url, -3), null, 'déjà en tête');
  assert.equal(moveIndices(list, tr('z').url, 0), null);
  assert.equal(moveIndices(list, tr('a').url, NaN), null);
});

test('applyOp : coups de cœur en tête, sans doublon, plafonnés ; retrait par identité', () => {
  const base = lib({ likes: [tr('a')] });
  assert.deepEqual(urls(applyOp(base, { kind: 'like', track: tr('b') }, NOW).likes), ['b', 'a']);
  assert.equal(applyOp(base, { kind: 'like', track: { ...tr('a'), url: `https://music.youtube.com/watch?v=${'a'.padEnd(11, '_')}` } }, NOW), base,
    'idempotent : même vidéo, autre forme');
  const full = lib({ likes: [tr('a')], limits: { ...DEFAULT_LIMITS, likes: 1 } });
  assert.equal(applyOp(full, { kind: 'like', track: tr('b') }, NOW), full, 'plafond');
  assert.deepEqual(applyOp(base, { kind: 'unlike', url: `https://www.youtube.com/watch?v=${'a'.padEnd(11, '_')}` }, NOW).likes, []);
  assert.equal(applyOp(base, { kind: 'unlike', url: tr('z').url }, NOW), base);
});

test('applyOp : playlists créées à la fin (dédoublonnées, plafonnées), renommées, supprimées', () => {
  const base = lib({ playlists: [pl('p1')], limits: { ...DEFAULT_LIMITS, tracks: 2, playlists: 2 } });
  const c = applyOp(base, { kind: 'create', id: 'tmp:1', name: 'Taverne', tracks: [tr('a'), tr('a'), tr('b'), tr('c')] }, NOW);
  assert.deepEqual(c.playlists.map((p) => p.id), ['p1', 'tmp:1']);
  assert.deepEqual(urls(c.playlists[1].tracks), ['a', 'b']);
  assert.equal(c.playlists[1].created_at, NOW / 1000);
  assert.equal(c.playlists[0], base.playlists[0], 'les autres gardent leur référence');
  assert.equal(applyOp(c, { kind: 'create', id: 'tmp:2', name: 'x', tracks: [] }, NOW), c, 'plafond de playlists');
  assert.equal(applyOp(c, { kind: 'create', id: 'tmp:1', name: 'x', tracks: [] }, NOW), c, 'rejouée : rien de plus');
  const r = applyOp(base, { kind: 'rename', id: 'p1', name: 'Veillée' }, NOW);
  assert.equal(r.playlists[0].name, 'Veillée');
  assert.equal(r.playlists[0].updated_at, NOW / 1000);
  assert.equal(applyOp(base, { kind: 'rename', id: 'p1', name: 'p1' }, NOW), base);
  assert.deepEqual(applyOp(base, { kind: 'delete', id: 'p1' }, NOW).playlists, []);
  assert.equal(applyOp(base, { kind: 'delete', id: 'nope' }, NOW), base);
});

test('applyOp : ajout à la fin (doublons écartés, plafond), retrait, déplacement', () => {
  const base = lib({ likes: [tr('z')], playlists: [pl('p1', [tr('a'), tr('b')])], limits: { ...DEFAULT_LIMITS, tracks: 3 } });
  const a = applyOp(base, { kind: 'add', id: 'p1', tracks: [tr('b'), tr('c'), tr('d')] }, NOW);
  assert.deepEqual(urls(a.playlists[0].tracks), ['a', 'b', 'c']);
  assert.equal(a.likes, base.likes, 'les coups de cœur gardent leur référence');
  assert.equal(applyOp(base, { kind: 'add', id: 'p1', tracks: [tr('a')] }, NOW), base, 'doublon seul : rien');
  assert.equal(applyOp(base, { kind: 'add', id: 'nope', tracks: [tr('c')] }, NOW), base);
  assert.deepEqual(urls(applyOp(base, { kind: 'remove', id: 'p1', url: tr('a').url }, NOW).playlists[0].tracks), ['b']);
  assert.equal(applyOp(base, { kind: 'remove', id: 'p1', url: tr('q').url }, NOW), base);
  assert.deepEqual(urls(applyOp(base, { kind: 'move', id: 'p1', url: tr('b').url, to: 0 }, NOW).playlists[0].tracks), ['b', 'a']);
  assert.equal(applyOp(base, { kind: 'move', id: 'p1', url: tr('a').url, to: 0 }, NOW), base);
});

test('checkOp : refus prévus sans appeler l’API', () => {
  const base = lib({ likes: [tr('a')], playlists: [pl('p1', [tr('a')])], limits: { likes: 1, playlists: 1, tracks: 1, name: 10 } });
  assert.deepEqual(checkOp(base, { kind: 'like', track: tr('b') }), { code: 'LIMIT_REACHED', limit: 'likes' });
  assert.deepEqual(checkOp(base, { kind: 'like', track: tr('a') }), { code: 'NOOP' });
  assert.deepEqual(checkOp(base, { kind: 'like', track: { ...tr('a'), url: '' } }), { code: 'INVALID_TRACK' });
  assert.equal(checkOp(base, { kind: 'unlike', url: tr('a').url }), null);
  assert.deepEqual(checkOp(base, { kind: 'unlike', url: tr('b').url }), { code: 'NOOP' });
  assert.deepEqual(checkOp(base, { kind: 'create', id: 'tmp:1', name: '', tracks: [] }), { code: 'INVALID_NAME' });
  assert.deepEqual(checkOp(base, { kind: 'create', id: 'tmp:1', name: 'x'.repeat(11), tracks: [] }), { code: 'INVALID_NAME' }, 'plafond de l’API');
  assert.deepEqual(checkOp(base, { kind: 'create', id: 'tmp:1', name: 'ok', tracks: [] }), { code: 'LIMIT_REACHED', limit: 'playlists' });
  assert.deepEqual(checkOp(base, { kind: 'rename', id: 'nope', name: 'ok' }), { code: 'PLAYLIST_NOT_FOUND' });
  assert.deepEqual(checkOp(base, { kind: 'rename', id: 'p1', name: 'p1' }), { code: 'NOOP' });
  assert.deepEqual(checkOp(base, { kind: 'rename', id: 'p1', name: '' }), { code: 'INVALID_NAME' });
  assert.equal(checkOp(base, { kind: 'delete', id: 'p1' }), null);
  assert.deepEqual(checkOp(base, { kind: 'add', id: 'p1', tracks: [tr('a')] }), { code: 'DUPLICATE' });
  assert.deepEqual(checkOp(base, { kind: 'add', id: 'p1', tracks: [tr('b')] }), { code: 'LIMIT_REACHED', limit: 'tracks' });
  assert.deepEqual(checkOp(base, { kind: 'add', id: 'p1', tracks: [{ ...tr('b'), url: '' }] }), { code: 'INVALID_TRACK' });
  assert.deepEqual(checkOp(base, { kind: 'remove', id: 'p1', url: tr('b').url }), { code: 'NOOP' });
  assert.deepEqual(checkOp(base, { kind: 'move', id: 'p1', url: tr('a').url, to: 0 }), { code: 'NOOP' });
  const roomy = lib({ playlists: [pl('p1', [tr('a')])] });
  assert.equal(checkOp(roomy, { kind: 'create', id: 'tmp:1', name: 'Taverne', tracks: [] }), null);
  assert.equal(checkOp(roomy, { kind: 'add', id: 'p1', tracks: [tr('a'), tr('b')] }), null, 'un titre nouveau suffit');
});

test('libraryCode / noticeOf : le Héraut dit le plafond touché, le nom, l’indisponibilité', () => {
  assert.equal(libraryCode({ status: 409, payload: { error: 'limit_reached' } }), 'LIMIT_REACHED');
  assert.equal(libraryCode(new TypeError('fetch failed')), '');
  assert.equal(libraryCode(null), '');
  const base = lib({ playlists: [pl('p1', [], 'Taverne')] });
  assert.deepEqual(noticeOf('LIMIT_REACHED', { kind: 'like', track: tr('a') }, base), { key: 'library.error.limitLikes', vars: { n: 500 }, kind: 'warn' });
  assert.deepEqual(noticeOf('LIMIT_REACHED', { kind: 'create', id: 'tmp:1', name: 'x', tracks: [] }, base),
    { key: 'library.error.limitPlaylists', vars: { n: 50 }, kind: 'warn' });
  assert.deepEqual(noticeOf('LIMIT_REACHED', { kind: 'add', id: 'p1', tracks: [] }, base),
    { key: 'library.error.limitTracks', vars: { n: 200, name: 'Taverne' }, kind: 'warn' });
  assert.deepEqual(noticeOf('INVALID_NAME', { kind: 'rename', id: 'p1', name: '' }, base), { key: 'library.error.INVALID_NAME', vars: { n: 60 }, kind: 'warn' });
  assert.equal(noticeOf('STORAGE_UNAVAILABLE', { kind: 'unlike', url: 'x' }, null).kind, 'err');
  assert.equal(noticeOf('PLAYLIST_NOT_FOUND', { kind: 'delete', id: 'p1' }, base).key, 'library.error.PLAYLIST_NOT_FOUND');
  assert.equal(noticeOf('NOT_AUTHENTICATED', { kind: 'delete', id: 'p1' }, base), null, 'la perte de session parle seule');
  assert.equal(noticeOf('', { kind: 'delete', id: 'p1' }, base), null);
});

test('parseLibrary : réponse de l’API ({ok, library} ou nue), titres nettoyés, plafonds gardés', () => {
  const res = { ok: true, library: {
    likes: [{ url: 'https://youtu.be/dQw4w9WgXcQ', title: 'R', added_at: 5 }, { url: 'pas un lien' }],
    playlists: [{ id: 'Ab3_x', name: 'Taverne', tracks: [{ url: 'https://soundcloud.com/a/b' }], created_at: 7, updated_at: 8 }, { name: 'sans id' }],
    limits: { likes: 300, playlists: 20, tracks: 100, name: 40 },
  } };
  const l = parseLibrary(res);
  assert.equal(l.likes.length, 1);
  assert.equal(l.likes[0].added_at, 5);
  assert.deepEqual(l.playlists.map((p) => [p.id, p.name, p.tracks.length, p.created_at, p.updated_at]), [['Ab3_x', 'Taverne', 1, 7, 8]]);
  assert.deepEqual(l.limits, { likes: 300, playlists: 20, tracks: 100, name: 40 });
  const after = parseLibrary({ ok: true, library: { likes: [], playlists: [] } }, l.limits);
  assert.deepEqual(after.limits, l.limits, 'réponse d’une modification sans plafonds : ceux d’avant');
  assert.deepEqual(parseLibrary({ likes: [] }).limits, DEFAULT_LIMITS);
  assert.equal(parseLibrary(null), null);
  assert.equal(parseLibrary({ ok: true }), null);
  assert.equal(parseLibrary('x'), null);
});

// ── moteur : optimiste, une requête à la fois, retour arrière ─────────────────────────────────
function harness(initial = lib()) {
  const sent = [], views = [], fails = [], aliases = [];
  const engine = createLibraryEngine({
    now: () => NOW,
    send: (op, base) => new Promise((resolve, reject) => sent.push({ op, base, resolve, reject })),
    onView: (v) => views.push(v),
    onFail: (op, e) => fails.push({ op, e }),
    onAlias: (tmp, id) => aliases.push([tmp, id]),
  });
  if (initial) engine.load(initial);
  return { engine, sent, views, fails, aliases };
}
const settle = () => new Promise((r) => setTimeout(r, 0));
const reply = (l) => ({ ok: true, library: l });

test('moteur : rien avant le chargement ; une modification se voit tout de suite, part seule, la réponse fait foi', async () => {
  const empty = harness(null);
  assert.equal(await empty.engine.dispatch({ kind: 'like', track: tr('a') }), false, 'rien de chargé : rien d’envoyé');
  assert.equal(empty.sent.length, 0);

  const { engine, sent } = harness();
  const p1 = engine.dispatch({ kind: 'like', track: tr('a') });
  const p2 = engine.dispatch({ kind: 'like', track: tr('b') });
  assert.deepEqual(urls(engine.view().likes), ['b', 'a'], 'les deux visibles');
  await settle();
  assert.equal(sent.length, 1, 'une requête à la fois');
  assert.deepEqual(sent[0].base.likes, [], 'base : le chansonnier confirmé');
  sent[0].resolve(reply({ likes: [{ ...tr('a'), title: 'A (API)' }], playlists: [] }));
  assert.equal(await p1, true);
  await settle();
  assert.equal(sent.length, 2);
  assert.deepEqual(urls(sent[1].base.likes), ['A (API)'], 'la suivante part de la réponse');
  assert.deepEqual(urls(engine.view().likes), ['b', 'A (API)']);
  sent[1].resolve(reply({ likes: [tr('b'), tr('a')], playlists: [] }));
  assert.equal(await p2, true);
  assert.equal(engine.pending(), 0);
});

test('moteur : refus de l’API, la vue revient en arrière et le refus est remis à l’appelant', async () => {
  const { engine, sent, fails } = harness(lib({ likes: [tr('a')] }));
  const done = engine.dispatch({ kind: 'unlike', url: tr('a').url });
  assert.deepEqual(engine.view().likes, []);
  await settle();
  const err = Object.assign(new Error('x'), { status: 503, payload: { error: 'STORAGE_UNAVAILABLE' } });
  sent[0].reject(err);
  assert.equal(await done, false);
  assert.deepEqual(urls(engine.view().likes), ['a'], 'retour arrière');
  assert.equal(fails.length, 1);
  assert.equal(fails[0].e, err);
});

test('moteur : réponse sans chansonnier lisible, la modification devient l’état confirmé', async () => {
  const { engine, sent } = harness();
  const done = engine.dispatch({ kind: 'like', track: tr('a') });
  await settle();
  sent[0].resolve(null);
  assert.equal(await done, true);
  assert.deepEqual(urls(engine.view().likes), ['a']);
});

test('moteur : une playlist créée reçoit son id ; ce qui l’attendait part avec le vrai', async () => {
  const { engine, sent, aliases } = harness();
  const c = engine.dispatch({ kind: 'create', id: 'tmp:1', name: 'Taverne', tracks: [] });
  const a = engine.dispatch({ kind: 'add', id: 'tmp:1', tracks: [tr('a')] });
  assert.deepEqual(urls(findPlaylist(engine.view(), 'tmp:1').tracks), ['a']);
  await settle();
  sent[0].resolve({ ok: true, playlist_id: 'Real123', library: { likes: [], playlists: [pl('Real123', [], 'Taverne')] } });
  assert.equal(await c, true);
  assert.deepEqual(aliases, [['tmp:1', 'Real123']]);
  await settle();
  assert.equal(sent[1].op.id, 'Real123', 'l’ajout en attente vise le vrai id');
  assert.equal(engine.idOf('tmp:1'), 'Real123');
  assert.equal(engine.originOf('Real123'), 'tmp:1', 'clé React stable : la ligne créée reste montée');
  assert.equal(engine.originOf('other'), 'other');
  const later = engine.dispatch({ kind: 'rename', id: 'tmp:1', name: 'Veillée' });   // une vue restée sur l'id provisoire
  sent[1].resolve(reply({ likes: [], playlists: [pl('Real123', [tr('a')], 'Taverne')] }));
  assert.equal(await a, true);
  await settle();
  assert.equal(sent[2].op.id, 'Real123');
  sent[2].resolve(reply({ likes: [], playlists: [pl('Real123', [tr('a')], 'Veillée')] }));
  assert.equal(await later, true);
});

test('moteur : sans playlist_id, la création est reconnue à la playlist apparue', async () => {
  const { engine, sent, aliases } = harness(lib({ playlists: [pl('old')] }));
  const c = engine.dispatch({ kind: 'create', id: 'tmp:9', name: 'Neuve', tracks: [] });
  await settle();
  sent[0].resolve(reply({ likes: [], playlists: [pl('old'), pl('new42', [], 'Neuve')] }));
  assert.equal(await c, true);
  assert.deepEqual(aliases, [['tmp:9', 'new42']]);
});

test('moteur : création refusée, ce qui l’attendait tombe avec elle (un seul refus annoncé)', async () => {
  const { engine, sent, fails } = harness();
  const c = engine.dispatch({ kind: 'create', id: 'tmp:1', name: 'Taverne', tracks: [] });
  const a = engine.dispatch({ kind: 'add', id: 'tmp:1', tracks: [tr('a')] });
  const other = engine.dispatch({ kind: 'like', track: tr('z') });
  await settle();
  sent[0].reject(Object.assign(new Error('x'), { payload: { error: 'LIMIT_REACHED' } }));
  assert.equal(await c, false);
  assert.equal(await a, false);
  assert.equal(fails.length, 1);
  assert.equal(findPlaylist(engine.view(), 'tmp:1'), null);
  await settle();
  assert.equal(sent.length, 2);
  assert.equal(sent[1].op.kind, 'like', 'le reste continue');
  sent[1].resolve(reply({ likes: [tr('z')], playlists: [] }));
  assert.equal(await other, true);
});

test('moteur : reset (déconnexion) oublie tout ; une réponse arrivée après est ignorée', async () => {
  const { engine, sent, fails } = harness();
  const a = engine.dispatch({ kind: 'like', track: tr('a') });
  const b = engine.dispatch({ kind: 'like', track: tr('b') });
  await settle();
  engine.reset();
  assert.equal(engine.view(), null);
  assert.equal(await a, false);
  assert.equal(await b, false);
  sent[0].resolve(reply({ likes: [tr('a')], playlists: [] }));
  await settle();
  assert.equal(engine.view(), null, 'la réponse d’avant ne s’écrit pas');
  assert.equal(fails.length, 0, 'sans annonce');
  engine.load(lib());
  const c = engine.dispatch({ kind: 'like', track: tr('c') });
  await settle();
  assert.equal(sent.length, 2, 'le Roi suivant repart de zéro');
  sent[1].resolve(reply({ likes: [tr('c')], playlists: [] }));
  assert.equal(await c, true);
});
