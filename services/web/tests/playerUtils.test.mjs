// Tests unitaires des helpers purs du web player (node:test, sans réseau).
// Lancer : npm test   (Node >= 22.18 natif ; Node 20 : après `npm install`, voir _loadTs.mjs)
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadTs } from './_loadTs.mjs';

const {
  toSeconds,
  normalizeItem,
  buildUsersMap,
  isStalePayload,
  looksLikeUrl,
  describeError,
  errorCode,
  enqueueSuccessText,
  pickDefaultGuild,
  isShortcutIgnored,
  enterPicksSuggestion,
  createSeqGate,
  staleStateText,
  livePosition,
  recoveredStatusText,
} = await loadTs('../src/lib/playerUtils.ts');

// ── durations-over-10000-as-ms ──
test('toSeconds : une durée en secondes > 10000 reste en secondes', () => {
  assert.equal(toSeconds(10800), 10800); // mix de 3 h
  assert.equal(toSeconds('36000'), 36000);
  assert.equal(toSeconds(215.7), 215);
  assert.equal(toSeconds('1:02:03'), 3723);
  assert.equal(toSeconds('3:05'), 185);
  assert.equal(toSeconds(null), null);
  assert.equal(toSeconds(''), null);
  assert.equal(toSeconds('abc'), null);
});

test('toSeconds : seule l’unité ms explicite divise par 1000', () => {
  assert.equal(toSeconds(215000, 'ms'), 215);
  assert.equal(toSeconds('215000', 'ms'), 215);
});

test('normalizeItem : duration en secondes, duration_ms converti', () => {
  assert.equal(normalizeItem({ title: 'Mix', url: 'u', duration: 10800 }).duration, 10800);
  assert.equal(normalizeItem({ title: 'Sp', url: 'u', duration_ms: 215000 }).duration, 215);
  assert.equal(normalizeItem({ title: 'Sp', url: 'u', length_ms: 60000 }).duration, 60);
});

// ── added-by-contract-mismatch ──
test('normalizeItem : added_by (id string) résolu via queue_users', () => {
  const users = { '42': { id: '42', username: 'paul', display_name: 'Paulo' } };
  const t = normalizeItem({ title: 'T', url: 'u', added_by: '42', requested_by: '42' }, users);
  assert.deepEqual(t.addedBy, { id: '42', name: 'Paulo' });
});

test('normalizeItem : added_by inconnu → id conservé, pas de nom', () => {
  const t = normalizeItem({ title: 'T', url: 'u', added_by: '99' }, {});
  assert.deepEqual(t.addedBy, { id: '99', name: '' });
});

test('normalizeItem : added_by objet toujours supporté', () => {
  const t = normalizeItem({ title: 'T', url: 'u', requested_by: { id: 7, username: 'bob' } });
  assert.deepEqual(t.addedBy, { id: '7', name: 'bob' });
});

test('buildUsersMap : fusionne queue_users et requested_by_user', () => {
  const m = buildUsersMap({
    queue_users: { '1': { id: '1', display_name: 'A' } },
    requested_by_user: { id: '2', display_name: 'B' },
  });
  assert.equal(m['1'].display_name, 'A');
  assert.equal(m['2'].display_name, 'B');
  assert.deepEqual(buildUsersMap({}), {});
  assert.deepEqual(buildUsersMap(null), {});
});

// ── get-state-timeout-fake-empty ──
test('isStalePayload : état périmé / en échec détecté', () => {
  assert.equal(isStalePayload({ ok: false, stale: true, backend_error: 'TIMEOUT' }), true);
  // ancien format API : ok:true + faux état vide + backend_error
  assert.equal(isStalePayload({ ok: true, current: null, queue: [], backend_error: 'TIMEOUT' }), true);
  assert.equal(isStalePayload({ ok: false, error: 'TIMEOUT' }), true);
  assert.equal(isStalePayload({ ok: true, state: { current: null, queue: [] } }), false);
  assert.equal(isStalePayload({ only_elapsed: true, position: 3 }), false);
  assert.equal(isStalePayload(null), false);
});

// ── autocomplete-on-pasted-urls ──
test('looksLikeUrl : liens collés détectés (avec ou sans schéma)', () => {
  for (const s of [
    'https://www.youtube.com/playlist?list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG',
    '  https://youtu.be/dQw4w9WgXcQ?list=RDdQw4w9WgXcQ ',
    'http://example.com/a',
    'youtube.com/watch?v=dQw4w9WgXcQ&list=PL123',
    'www.youtube.com/playlist?list=PL1',
    'music.youtube.com/playlist?list=PL1',
    'm.youtube.com/watch?v=abc',
    'youtu.be/dQw4w9WgXcQ',
    'soundcloud.com/artist/sets/album',
    'on.soundcloud.com/abc',
    'open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M',
    'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M',
    '<https://www.youtube.com/watch?v=dQw4w9WgXcQ>',
  ]) assert.equal(looksLikeUrl(s), true, s);
});

test('looksLikeUrl : texte libre non détecté', () => {
  for (const s of ['daft punk', 'youtube.com is cool', 'rick astley never gonna', '', '   ', 'httpster'])
    assert.equal(looksLikeUrl(s), false, s);
});

// ── searchbar-stale-idx-submits-suggestion ──
test('enterPicksSuggestion : seulement liste ouverte + sélection clavier valide + pas une URL', () => {
  assert.equal(enterPicksSuggestion(true, 0, 3, 'daft punk'), true);
  assert.equal(enterPicksSuggestion(false, 0, 3, 'daft punk'), false); // Échap → liste fermée
  assert.equal(enterPicksSuggestion(true, -1, 3, 'daft punk'), false);
  assert.equal(enterPicksSuggestion(true, 5, 3, 'daft punk'), false); // index périmé
  assert.equal(enterPicksSuggestion(true, 0, 3, 'https://www.youtube.com/playlist?list=PL1'), false);
});

// ── C4 : messages d'erreur / toasts ──
const err = (payload, status = 409, message) =>
  Object.assign(new Error(message || payload?.error || `HTTP ${status}`), { status, payload });

test('describeError : payload.message prioritaire', () => {
  assert.equal(describeError(err({ ok: false, error: 'TIMEOUT', message: 'Greg met trop de temps à répondre…' }, 504)),
    'Greg met trop de temps à répondre…');
});

test('describeError : codes traduits en français', () => {
  const codes = ['TIMEOUT', 'BOT_OFFLINE', 'QUOTA_EXCEEDED', 'PLAYLIST_UNAVAILABLE', 'PLAYLIST_EMPTY',
    'SPOTIFY_UNSUPPORTED', 'UNSUPPORTED_SOURCE', 'NO_RESULTS', 'EXPAND_TIMEOUT', 'USER_NOT_IN_VOICE',
    'BOT_IN_OTHER_CHANNEL', 'GUILD_NOT_FOUND'];
  for (const c of codes) {
    const m = describeError(err({ ok: false, error: c }));
    assert.ok(m && m !== c && !/^[A-Z_]+$/.test(m), `${c} → ${m}`);
  }
  assert.match(describeError(err({ ok: false, error: 'GUILD_NOT_FOUND' })), /serveur/i);
  assert.match(describeError(err({ ok: false, error: 'USER_NOT_IN_VOICE' })), /vocal/i);
});

test('describeError : erreurs HTTP/proxy/réseau sans code', () => {
  assert.match(describeError(err('Internal Server Error', 500, 'HTTP 500')), /HTTP 500/);
  assert.notEqual(describeError(err('Internal Server Error', 500, 'HTTP 500')), 'HTTP 500');
  assert.match(describeError(new TypeError('Failed to fetch')), /serveur/i);
  assert.equal(describeError(err({ ok: false, error: 'UNKNOWN_THING' })), 'UNKNOWN_THING');
});

test('errorCode : extrait le code du payload', () => {
  assert.equal(errorCode(err({ ok: false, error: 'TIMEOUT' }, 504)), 'TIMEOUT');
  assert.equal(errorCode(new Error('x')), '');
  // état périmé (C3) : le code est dans backend_error
  assert.equal(errorCode(err({ ok: false, stale: true, backend_error: 'BOT_OFFLINE' }, 200)), 'BOT_OFFLINE');
});

// ── Bot hors ligne affiché « occupé » (état périmé C3) ──
const staleErr = (payload) => Object.assign(new Error('stale'), { payload });

test('staleStateText : TIMEOUT → « occupé »', () => {
  assert.match(staleStateText(staleErr({ ok: false, stale: true, backend_error: 'TIMEOUT' })), /occupé/);
});

test('staleStateText : BOT_OFFLINE → message de l’API, jamais « occupé »', () => {
  assert.equal(
    staleStateText(staleErr({ ok: false, stale: true, backend_error: 'BOT_OFFLINE', message: 'Greg est hors ligne pour le moment.' })),
    'Greg est hors ligne pour le moment.');
  const noMsg = staleStateText(staleErr({ ok: false, stale: true, backend_error: 'BOT_OFFLINE' }));
  assert.doesNotMatch(noMsg, /occupé/);
  assert.match(noMsg, /hors ligne/);
});

test('staleStateText : REDIS_UNAVAILABLE traduit, code inconnu → « occupé »', () => {
  const r = staleStateText(staleErr({ ok: false, stale: true, backend_error: 'REDIS_UNAVAILABLE' }));
  assert.doesNotMatch(r, /occupé/);
  assert.match(r, /injoignable/);
  assert.match(staleStateText(staleErr({ ok: false, stale: true, backend_error: 'unknown' })), /occupé/);
  // ancien format API (ok:true + backend_error)
  assert.match(staleStateText(staleErr({ ok: true, current: null, queue: [], backend_error: 'TIMEOUT' })), /occupé/);
});

test('staleStateText : échec HTTP / réseau (pas un état périmé) → describeError', () => {
  assert.match(staleStateText(err('Internal Server Error', 500, 'HTTP 500')), /HTTP 500/);
  assert.equal(staleStateText(new TypeError('Failed to fetch')), 'Connexion au serveur impossible.');
});

test('livePosition : position figée au moment de l’appel (bornée à la durée)', () => {
  assert.equal(livePosition({ pos: 30, at: 1000, dur: 200 }, false, 11000), 40);
  assert.equal(livePosition({ pos: 30, at: 1000, dur: 200 }, true, 11000), 30);
  assert.equal(livePosition({ pos: 190, at: 0, dur: 200 }, false, 60000), 200);
  assert.equal(livePosition({ pos: 5, at: 0, dur: 0 }, false, 2000), 7);
});

// ── refreshMe : un échec transitoire plus récent n'annule pas un succès plus ancien ──
test('createSeqGate : succès ancien appliqué si la requête plus récente a échoué (5xx)', () => {
  const g = createSeqGate();
  const boot = g.next();   // /users/me du boot (lent)
  const focus = g.next();  // /users/me du focus → 500 : rien d'appliqué
  assert.equal(g.tryApply(boot), true);
  assert.notEqual(focus, boot);
});

test('createSeqGate : une réponse plus ancienne ne remplace jamais une plus récente appliquée', () => {
  const g = createSeqGate();
  const a = g.next();
  const b = g.next();
  assert.equal(g.tryApply(b), true);
  assert.equal(g.tryApply(a), false);  // ex. 401 tardif d'une requête dépassée
  const c = g.next();
  assert.equal(g.tryApply(c), true);
  assert.equal(g.tryApply(c), false);
});

test('enqueueSuccessText : playlist / quota / limite / titre simple', () => {
  assert.equal(enqueueSuccessText({ ok: true, added: 12, requested: 12, truncated: null, playlist: true }),
    'Playlist ajoutée : 12 titres ✅');
  assert.equal(enqueueSuccessText({ ok: true, added: 1, requested: 1, truncated: null, playlist: true }),
    'Playlist ajoutée : 1 titre ✅');
  assert.match(enqueueSuccessText({ ok: true, added: 3, requested: 25, truncated: 'quota', playlist: true }),
    /^Playlist ajoutée : 3 titres.*limité par ton quota.*✅$/);
  assert.match(enqueueSuccessText({ ok: true, added: 25, requested: 25, truncated: 'limit', playlist: true }),
    /^Playlist ajoutée : 25 titres.*25 premiers.*✅$/);
  assert.match(enqueueSuccessText({ ok: true, added: 8, requested: 10, truncated: null, playlist: true }),
    /8 titres sur 10/);
  assert.equal(enqueueSuccessText({ ok: true, added: 1, requested: 1, playlist: false, title: 'Never Gonna Give You Up' }),
    'Ajouté : Never Gonna Give You Up ✅');
  // watch?v=…&list=… dont la playlist est illisible : la vidéo seule est ajoutée, on le dit
  assert.equal(enqueueSuccessText({ ok: true, added: 1, requested: 1, playlist: false, title: 'Titre',
    playlist_error: 'PLAYLIST_UNAVAILABLE',
    message: 'Playlist privée ou inaccessible : seule la vidéo demandée a été ajoutée.' }),
    '⚠️ Playlist privée ou inaccessible : seule la vidéo demandée a été ajoutée.');
  // ancien bot : réponse minimale
  assert.equal(enqueueSuccessText({ ok: true }), 'Ajouté à la file ✅');
  assert.equal(enqueueSuccessText(null), 'Ajouté à la file ✅');
});

// ── first-guild-auto-selected (C5) ──
test('pickDefaultGuild : garde un serveur sauvegardé présent dans la liste', () => {
  const g = [{ id: '1', name: 'A', bot_present: false }, { id: '2', name: 'B', bot_present: true }];
  assert.deepEqual(pickDefaultGuild(g, '1'), { guildId: '1', discarded: false });
});

test('pickDefaultGuild : sans sauvegarde → premier serveur où Greg est présent', () => {
  const g = [{ id: '1', name: 'A', bot_present: false }, { id: '2', name: 'B', bot_present: true }];
  assert.deepEqual(pickDefaultGuild(g, ''), { guildId: '2', discarded: false });
});

test('pickDefaultGuild : sauvegarde absente de la liste → écartée', () => {
  const g = [{ id: '1', name: 'A', bot_present: false }, { id: '2', name: 'B', bot_present: true }];
  assert.deepEqual(pickDefaultGuild(g, '999'), { guildId: '2', discarded: true });
});

test('pickDefaultGuild : bot_present inconnu → premier serveur (comportement historique)', () => {
  const g = [{ id: '1', name: 'A' }, { id: '2', name: 'B' }];
  assert.deepEqual(pickDefaultGuild(g, ''), { guildId: '1', discarded: false });
});

test('pickDefaultGuild : Greg absent partout → aucune sélection', () => {
  const g = [{ id: '1', name: 'A', bot_present: false }];
  assert.deepEqual(pickDefaultGuild(g, ''), { guildId: '', discarded: false });
});

test('pickDefaultGuild : liste vide (échec /guilds) → sauvegarde conservée', () => {
  assert.deepEqual(pickDefaultGuild([], '5'), { guildId: '5', discarded: false });
});

// ── keyboard-shortcuts-modifiers ──
test('isShortcutIgnored : modificateurs, répétition, champs de saisie', () => {
  const body = { tagName: 'BODY', closest: () => null };
  assert.equal(isShortcutIgnored({ key: 'r', ctrlKey: true, target: body }), true); // Ctrl+R
  assert.equal(isShortcutIgnored({ key: 'p', metaKey: true, target: body }), true); // Cmd+P
  assert.equal(isShortcutIgnored({ key: 'n', altKey: true, target: body }), true);
  assert.equal(isShortcutIgnored({ code: 'Space', key: ' ', repeat: true, target: body }), true);
  assert.equal(isShortcutIgnored({ key: 'n', target: { tagName: 'INPUT' } }), true);
  assert.equal(isShortcutIgnored({ key: 'r', target: { tagName: 'SELECT' } }), true);
  assert.equal(isShortcutIgnored({ key: 'r', target: { tagName: 'DIV', isContentEditable: true } }), true);
  const btn = { tagName: 'BUTTON', closest: () => ({}) };
  assert.equal(isShortcutIgnored({ code: 'Space', key: ' ', target: btn }), true);
  assert.equal(isShortcutIgnored({ key: 'n', target: btn }), false);
  assert.equal(isShortcutIgnored({ key: 'r', target: body }), false);
  assert.equal(isShortcutIgnored({ code: 'Space', key: ' ', target: body }), false);
});

// ── stale-warning-never-cleared ──
test("recoveredStatusText : efface l'avertissement « bot hors ligne » une fois l'état revenu", () => {
  const warn = 'Greg est hors ligne (redémarrage en cours ?)…';
  assert.equal(recoveredStatusText(warn, warn), 'Greg est de nouveau disponible ✅');
  // Un autre message a remplacé l'avertissement entre-temps : on n'y touche pas
  assert.equal(recoveredStatusText('Skip ✅', warn), null);
  // Aucun avertissement affiché par cette cause
  assert.equal(recoveredStatusText('', ''), null);
  assert.equal(recoveredStatusText(warn, ''), null);
});
