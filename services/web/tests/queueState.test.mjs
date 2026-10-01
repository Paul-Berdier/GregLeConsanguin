// État reçu (étape 3) : clés stables, partage structurel, ticks, textes d'erreur du deck.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';

const { assignKeys, shareTracks, sameTrack, snapshotFromPayload, emptySnapshot, errorCopy } = await loadTs('../src/lib/playerUtils.ts');
const deck = JSON.parse(readFileSync(new URL('../src/theme/copy.v2.json', import.meta.url), 'utf8'));
const at = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);

const raw = (url, by = '101', ts = 100, extra = {}) => ({ url, title: url.toUpperCase(), added_by: by, ts, ...extra });
const tr = (r) => ({ key: '', url: r.url, title: r.title, artist: '', duration: null, thumb: null, provider: null, addedBy: { id: r.added_by, name: '' }, raw: r });
const state = (queue, current = null, extra = {}) => ({ ok: true, state: { queue, current, is_paused: false, repeat_all: false, position: 12, duration: 200, ...extra } });

test('assignKeys : stables quand un titre s’insère devant, uniques pour les doublons', () => {
  const a = assignKeys([raw('a'), raw('b'), raw('a')].map(tr));
  assert.equal(new Set(a.map((t) => t.key)).size, 3);
  const b = assignKeys([raw('x', '102', 200), raw('a'), raw('b'), raw('a')].map(tr));
  assert.deepEqual(b.slice(1).map((t) => t.key), a.map((t) => t.key));
  assert.equal(assignKeys([tr(raw('a', '1', 1, { qid: 'abc' }))])[0].key, 'q:abc#0');
  assert.notEqual(assignKeys([tr(raw('a', '1', 1, { repeat_tag: 'r1' }))])[0].key, assignKeys([tr(raw('a', '1', 1))])[0].key, 'la copie de boucle est un autre titre');
});

test('shareTracks : file inchangée = même tableau ; titre changé seul remplacé', () => {
  const q1 = assignKeys([raw('a'), raw('b')].map(tr));
  const q2 = assignKeys([raw('a'), raw('b')].map(tr));
  assert.equal(shareTracks(q1, q2), q1);
  const q3 = assignKeys([raw('a'), { ...raw('b'), title: 'B (live)' }].map(tr));
  const shared = shareTracks(q1, q3);
  assert.notEqual(shared, q1);
  assert.equal(shared[0], q1[0]);
  assert.equal(shared[1].title, 'B (live)');
  assert.ok(sameTrack(q1[0], q2[0]));
  assert.ok(!sameTrack(q1[0], null));
});

test('snapshotFromPayload : état complet, clés, demandeur résolu, horloge ancrée à la réception', () => {
  const p = state([raw('a', '102'), raw('b')], raw('cur'), { queue_users: { 102: { id: '102', display_name: 'Hugo' } } });
  const s = snapshotFromPayload(p, emptySnapshot(), 5000);
  assert.equal(s.player.current.url, 'cur');
  assert.ok(s.player.current.key.startsWith('f:cur|101|100|'));
  assert.deepEqual(s.player.queue.map((t) => t.url), ['a', 'b']);
  assert.deepEqual(s.player.queue[0].addedBy, { id: '102', name: 'Hugo' });
  assert.deepEqual(s.tickBase, { pos: 12, at: 5000, dur: 200 });
  assert.equal(snapshotFromPayload({ ok: false, stale: true }, s, 6000), null, 'état périmé : on garde le précédent');
});

test('snapshotFromPayload : même état reçu deux fois = mêmes objets (lignes mémoïsées)', () => {
  const p = state([raw('a'), raw('b')], raw('cur'));
  const s1 = snapshotFromPayload(p, emptySnapshot(), 1000);
  const s2 = snapshotFromPayload(state([raw('a'), raw('b')], raw('cur')), s1, 2000);
  assert.equal(s2.player.queue, s1.player.queue);
  assert.equal(s2.player.current, s1.player.current);
});

test('snapshotFromPayload : un tick ne touche ni au titre, ni à la file, ni à la boucle', () => {
  const s1 = snapshotFromPayload(state([raw('a')], raw('cur'), { repeat_all: true }), emptySnapshot(), 1000);
  const tick = { only_elapsed: true, paused: true, is_paused: true, position: 40, duration: 200, progress: { elapsed: 40, duration: 200 } };
  const s2 = snapshotFromPayload(tick, s1, 3000);
  assert.equal(s2.player.current, s1.player.current);
  assert.equal(s2.player.queue, s1.player.queue);
  assert.equal(s2.player.repeat, true);
  assert.equal(s2.player.paused, true);
  assert.deepEqual(s2.tickBase, { pos: 40, at: 3000, dur: 200 });
});

test('errorCopy : chaque code mène à un texte du deck, avec son contexte', () => {
  const err = (error, status = 409, extra = {}) => ({ status, payload: { ok: false, error, ...extra } });
  const cases = [
    [err('PRIORITY_FORBIDDEN', 403), { name: 'Hugo' }, 'error.PRIORITY_FORBIDDEN.text'],
    [err('PRIORITY_FORBIDDEN', 403), {}, 'error.PRIORITY_FORBIDDEN.textGeneric'],
    [err('QUOTA_EXCEEDED'), {}, 'error.QUOTA_EXCEEDED.textGeneric'],
    [err('NO_RESULTS'), { q: 'zzz' }, 'error.NO_RESULTS.text'],
    [err('TIMEOUT', 504), {}, 'error.TIMEOUT.text'],
    [err('USER_NOT_IN_VOICE'), {}, 'error.USER_NOT_IN_VOICE.text'],
    [err('UNKNOWN_ACTION:seek'), {}, 'error.UNKNOWN_ACTION.text'],
    [{ status: 409, payload: { ok: false } }, { action: 'move' }, 'error.MOVE_CONFLICT.text'],
    [{ status: 503, payload: null }, {}, 'error.HTTP_5XX.text'],
    [{ status: 401, payload: { error: 'session_revoked' } }, {}, 'error.HTTP_401.text'],
    [Object.assign(new TypeError('Failed to fetch')), {}, 'error.NETWORK.text'],
    [new Error('???'), {}, 'error.UNKNOWN.text'],
    [{ payload: { ok: false, stale: true, backend_error: 'TIMEOUT' } }, { action: 'state' }, 'toast.stale.text'],
    [{ payload: { ok: false, stale: true, backend_error: 'BOT_OFFLINE' } }, { action: 'state' }, 'error.BOT_OFFLINE.text'],
  ];
  for (const [e, ctx, path] of cases) {
    const c = errorCopy(e, ctx);
    assert.equal(c.path, path, JSON.stringify(e.payload ?? e.message));
    assert.equal(typeof at(path), 'string', `${path} absent du deck`);
    assert.ok(at(c.key) && typeof at(c.key) === 'object', `${c.key} : entrée du deck`);
  }
  assert.deepEqual(errorCopy(err('PRIORITY_FORBIDDEN', 403), { name: 'Hugo' }).vars, { name: 'Hugo' });
  // code inconnu mais message français de l'API : on le garde
  assert.deepEqual(errorCopy(err('WEIRD', 409, { message: 'Le bot refuse.' })), { key: 'error.UNKNOWN', text: 'Le bot refuse.' });
});

test('errorCopy : une recherche YouTube en échec passager (transient) ne met pas l’orthographe en cause', async () => {
  const { tx } = await loadTs('../src/theme/copy.extra.ts');
  const e = { status: 409, payload: { ok: false, error: 'NO_RESULTS', transient: true, message: 'La recherche YouTube met trop de temps, réessaie dans un instant.' } };
  for (const ctx of [{ q: 'africa toto' }, {}]) {
    const c = errorCopy(e, ctx);
    assert.notEqual(c.path, 'error.NO_RESULTS.text');
    assert.notEqual(c.path, 'error.NO_RESULTS.textGeneric');
    assert.deepEqual(c, { key: 'error.SEARCH_FAILED', path: 'error.SEARCH_FAILED.text' });
  }
  const text = tx('error.SEARCH_FAILED.text');
  assert.match(text, /Réessayez/);
  assert.doesNotMatch(text, /orthographe|Aucun résultat/);
  // une vraie absence de résultat garde le texte du deck
  assert.equal(errorCopy({ status: 409, payload: { ok: false, error: 'NO_RESULTS', message: 'Aucun résultat pour « x ».' } }, { q: 'x' }).path, 'error.NO_RESULTS.text');
});

test('errorCopy : EXPAND_TIMEOUT d’une recherche ou d’une vidéo seule, c’est Greg occupé, pas une playlist trop longue', async () => {
  const { tx } = await loadTs('../src/theme/copy.extra.ts');
  const busy = { status: 409, payload: { ok: false, error: 'EXPAND_TIMEOUT', message: 'Greg est déjà occupé avec une autre demande sur ce serveur : réessaie dans un instant.' } };
  for (const link of ['none', 'video']) assert.deepEqual(errorCopy(busy, { q: 'africa toto', link }), { key: 'error.BUSY', path: 'error.BUSY.text' }, link);
  // une playlist (ou un mix, une chaîne) peut vraiment être trop longue : le texte du deck
  for (const link of ['playlist', 'mix', 'channel', undefined]) assert.equal(errorCopy(busy, { link }).path, 'error.EXPAND_TIMEOUT.text', String(link));
  const text = tx('error.BUSY.text');
  assert.match(text, /occupé/);
  assert.match(text, /Réessayez/);
  assert.doesNotMatch(text, /playlist/i);
});

test('errorCopy : quota atteint avec ses nombres (count, cap de l’API), sinon le texte générique', () => {
  const quota = (extra) => errorCopy({ status: 409, payload: { ok: false, error: 'QUOTA_EXCEEDED', message: 'Quota atteint (10/10) : …', ...extra } });
  assert.deepEqual(quota({ count: 10, cap: 10 }), { key: 'error.QUOTA_EXCEEDED', path: 'error.QUOTA_EXCEEDED.text', vars: { k: '10', cap: '10' } });
  assert.match(at('error.QUOTA_EXCEEDED.text'), /\{k\}.*\{cap\}/);
  assert.equal(quota({}).path, 'error.QUOTA_EXCEEDED.textGeneric');
  assert.equal(quota({ count: 'dix', cap: null }).path, 'error.QUOTA_EXCEEDED.textGeneric');
  assert.equal(quota({ count: Infinity, cap: 10 }).path, 'error.QUOTA_EXCEEDED.textGeneric');
  assert.equal(quota({ count: 1, cap: 1 }).path, 'error.QUOTA_EXCEEDED.textGeneric', 'jamais « 1 titres »');
});

test('usePlayer : l’ajout dit la nature du lien (mix, et « occupé » d’une recherche ou d’une vidéo seule)', () => {
  const src = readFileSync(new URL('../src/hooks/usePlayer.ts', import.meta.url), 'utf8');
  const i = src.indexOf('async function enqueue(');
  const fn = src.slice(i, src.indexOf('\n}\n', i));
  assert.match(fn, /const link = classifyLink\(String\(payload\?\.url \|\| payload\?\.query \|\| ''\)\);/);
  assert.match(fn, /sayError\(e, \{ q: looksLikeUrl\(typed\) \? undefined : typed, link \}\)/);
  assert.match(fn, /addedCopy\(res, [^;]*, link\)/);
  const r = src.indexOf('async function restoreTrack(');
  assert.match(src.slice(r, src.indexOf('\n}\n', r)), /sayError\(e, \{ link: 'video' \}\)/, '« Annuler » d’un retrait : un seul titre');
});

test('addedCopy : un mix se dit « Mix ajouté », avec les compléments de la playlist', async () => {
  const { addedCopy } = await loadTs('../src/lib/playerUtils.ts');
  const { classifyLink } = await loadTs('../src/lib/links.ts');
  const url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ';
  assert.equal(classifyLink(url), 'mix');
  const c = addedCopy({ ok: true, playlist: true, added: 25, requested: 25 }, '', classifyLink(url));
  assert.deepEqual([c.key, c.path, c.suffix, c.action], ['toast.mixAdded', 'toast.mixAdded.text', null, 'toast.mixAdded.action']);
  assert.deepEqual(c.vars, { n: 25, m: 25 });
  // le deck n'a de compléments (sur m, quota, limite) que pour la playlist : un mix tronqué les garde
  assert.equal(addedCopy({ ok: true, playlist: true, added: 25, requested: 40, truncated: 'quota' }, '', 'mix').suffix, 'toast.playlistAdded.suffixQuota');
  assert.equal(addedCopy({ ok: true, playlist: true, added: 25, truncated: 'limit' }, '', 'mix').suffix, 'toast.playlistAdded.suffixLimit');
  assert.equal(addedCopy({ ok: true, playlist: true, added: 12 }, '', 'playlist').key, 'toast.playlistAdded');
  assert.equal(addedCopy({ ok: true, playlist: true, added: 12 }, '').key, 'toast.playlistAdded', 'sans nature : la playlist');
  assert.equal(addedCopy({ ok: true, added: 1, title: 'X' }, '', 'mix').key, 'toast.added', 'mix lu comme une vidéo seule');
  assert.equal(addedCopy({ ok: true, playlist_error: true, message: 'Playlist privée' }, 'x', 'mix').key, 'toast.playlistPartial');
  for (const path of [c.path, c.action]) {
    const node = at(path);
    assert.ok(typeof node === 'string' || typeof node?.other === 'string', `${path} absent du deck`);
  }
});

test('addedCopy : titre seul, playlist (complète, sur m, quota, limite), playlist illisible', async () => {
  const { addedCopy } = await loadTs('../src/lib/playerUtils.ts');
  const c1 = addedCopy({ ok: true, added: 1, title: 'Bohemian Rhapsody' }, 'x');
  assert.deepEqual([c1.path, c1.vars.title, c1.action], ['toast.added.text', 'Bohemian Rhapsody', 'toast.added.action']);
  assert.equal(addedCopy({ ok: true }, 'Tapé').vars.title, 'Tapé');
  const p = (extra) => addedCopy({ ok: true, playlist: true, added: 12, ...extra }, '');
  assert.equal(p({}).suffix, null);
  assert.equal(p({ requested: 20 }).suffix, 'toast.playlistAdded.suffixOf');
  assert.equal(p({ requested: 20, truncated: 'quota' }).suffix, 'toast.playlistAdded.suffixQuota');
  assert.equal(p({ truncated: 'limit' }).suffix, 'toast.playlistAdded.suffixLimit');
  assert.deepEqual(p({ requested: 20 }).vars, { n: 12, m: 20 });
  assert.equal(p({}).action, 'toast.playlistAdded.action');
  assert.equal(addedCopy({ ok: true, playlist_error: true, message: 'Playlist privée' }, 'x').path, 'toast.playlistPartial.text');
  for (const c of [c1, p({ requested: 20 }), p({ truncated: 'quota' })]) {
    for (const path of [c.path, c.suffix, c.action].filter(Boolean)) {
      const node = path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);
      assert.ok(typeof node === 'string' || typeof node?.other === 'string', `${path} absent du deck`);
    }
  }
});
