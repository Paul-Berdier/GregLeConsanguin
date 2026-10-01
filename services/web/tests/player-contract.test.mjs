// Contrats de usePlayer (étape 3) : un seul chemin pour les états reçus, plus de barre de statut, le Héraut monté.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';

const { createQueueEngine, createStateOrder, viewOf, moveIndices, refusalOf } = await loadTs('../src/lib/queue/optimistic.ts');
const { addedKeys, afterDone, restorePlan } = await loadTs('../src/lib/queue/undo.ts');
const { requesterOf } = await loadTs('../src/lib/stage/scene.ts');
const { errorCopy, stateKind } = await loadTs('../src/lib/playerUtils.ts');

const read = (p) => readFileSync(fileURLToPath(new URL(`../${p}`, import.meta.url)), 'utf8');
/** Corps d'une fonction de haut niveau (jusqu'à l'accolade fermante en début de ligne). */
function body(src, head) {
  const i = src.indexOf(head);
  assert.ok(i >= 0, head);
  return src.slice(i, src.indexOf('\n}\n', i));
}

test('usePlayer : les états reçus passent par le moteur optimiste, jamais directement dans le store', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.ok(src.includes('createQueueEngine('), 'moteur optimiste');
  assert.ok(src.includes("socket.on('playlist_update', onPlaylistUpdate)"));
  assert.ok(src.includes('const onPlaylistUpdate = (payload: any) => { receive(payload); };'), 'socket → receive → moteur');
  assert.ok(src.includes('snapshotFromPayload(payload, engine.latest(), performance.now())'), 'un tick se calcule sur l’état gardé en tampon');
  assert.ok(!src.includes('engine.server()'), 'jamais sur le seul dernier état appliqué');
  assert.ok(!/\b(?:applyPlaylistPayload|setPlayer|setTickBase)\b/.test(src), 'plus d’écriture directe de player / tickBase');
});

test('barre de statut retirée : ni status ni setStatus, le Héraut parle à sa place', () => {
  for (const f of ['src/hooks/usePlayer.ts', 'src/app/page.tsx']) {
    assert.ok(!/\bsetStatus\b|status\.(?:text|kind)|status-ok|status-err/.test(read(f)), f);
  }
  const page = read('src/app/page.tsx');
  assert.ok(!page.includes('<footer'), 'plus de barre de statut');
  assert.ok(page.includes('<Herald dock='), 'le Héraut est monté');
  assert.ok(read('src/app/globals.css').includes("@import '../components/Herald/herald.css';"));
});

test('le clavier de la page passe par les actions optimistes, pas par l’API', () => {
  const page = read('src/app/page.tsx');
  assert.ok(!page.includes("from '@/lib/api'"), 'page.tsx n’appelle plus l’API');
  assert.ok(page.includes('playerActions.togglePause()'));
});

// « Annuler » pendant qu'une autre action est en vol (Espace, N, un autre retrait) : l'état relu après l'ajout
// attend en tampon (HOLD_MAX_MS) et la vue affichée ne montre pas encore le titre. Tout se calcule donc sur la
// vue à venir : viewOf(engine.latest(), engine.pending()).
const track = (key, url = `https://youtu.be/${key}`, by = 'k') => ({ key, url, title: key, duration: 200, addedBy: { id: by, name: by } });
const state = (queue) => ({
  player: { current: track('cur'), queue, paused: false, repeat: false, position: 0, duration: 200 },
  tickBase: { pos: 0, at: 0, dur: 200 },
});
const keysOf = (s) => s.player.queue.map((x) => x.key);
function rig(initial) {
  const sent = [];
  const engine = createQueueEngine({
    initial, now: () => 0, onView: () => {},
    send: (m, before) => {   // même garde que sendMutation : rien à envoyer si le titre n'est pas (encore) là
      const q = before.player.queue;
      if (m.kind === 'remove' && q.every((x) => x.key !== m.key)) return null;
      if (m.kind === 'move' && !moveIndices(q, m.key, m.beforeKey)) return null;
      let resolve, reject;
      const promise = new Promise((r, j) => { resolve = r; reject = j; });
      sent.push({ m, before, resolve, reject });
      return promise;
    },
  });
  return { engine, sent, upcoming: () => viewOf(engine.latest(), engine.pending()) };
}
const settle = () => new Promise((r) => setTimeout(r, 0));

test('« Annuler » un retrait pendant une action en vol : le titre remis retrouve sa place', async () => {
  const [a, c] = [track('a'), track('c')];
  const { engine, sent, upcoming } = rig(state([a, c]));          // « b » (place 1) vient d'être retiré
  const before = keysOf(upcoming());
  engine.dispatch({ kind: 'setPaused', paused: true });            // Espace : en vol
  engine.receive(state([a, c, track('b2', 'https://youtu.be/b')])); // relecture après le rajout : gardée en tampon
  assert.deepEqual(keysOf(engine.view()), ['a', 'c'], 'la vue affichée ne montre pas encore le titre');
  assert.equal(restorePlan(before, engine.view().player.queue, 'https://youtu.be/b', 1), null, 'sur la vue affichée : titre perdu');
  const plan = restorePlan(before, upcoming().player.queue, 'https://youtu.be/b', 1);
  assert.deepEqual(plan, { key: 'b2', beforeKey: 'c' });
  const moved = engine.dispatch({ kind: 'move', ...plan });
  assert.equal(sent.length, 1, 'une requête à la fois');
  sent[0].resolve({ ok: true });                                   // l'accusé libère le tampon, puis le déplacement part
  await settle();
  assert.equal(sent.length, 2);
  assert.deepEqual(moveIndices(sent[1].before.player.queue, 'b2', 'c'), { src: 2, dst: 1 });
  sent[1].resolve({ ok: true });
  assert.equal(await moved, true);
  assert.deepEqual(keysOf(engine.view()), ['a', 'b2', 'c']);
});

test('« Annuler » un ajout pendant une action en vol : les lignes du Roi sont trouvées, puis retirées par clé', async () => {
  const a = track('a');
  const { engine, sent, upcoming } = rig(state([a]));
  const before = keysOf(upcoming());
  engine.dispatch({ kind: 'setPaused', paused: true });
  engine.receive(state([a, track('n1'), track('x', undefined, 'lea')]));
  assert.deepEqual(addedKeys(before, engine.view().player.queue, 'k'), [], 'sur la vue affichée : aucun « Annuler »');
  const keys = addedKeys(before, upcoming().player.queue, 'k');
  assert.deepEqual(keys, ['n1'], 'seulement les titres du Roi');
  const undone = keys.map((key) => engine.dispatch({ kind: 'remove', key }));   // clic sur « Annuler », tampon encore plein
  sent[0].resolve({ ok: true });
  await settle();
  assert.equal(sent.length, 2);
  assert.equal(sent[1].m.kind, 'remove');
  assert.equal(sent[1].before.player.queue.findIndex((x) => x.key === 'n1'), 1, 'index calculé une fois le tampon appliqué');
  sent[1].resolve({ ok: true });
  assert.deepEqual(await Promise.all(undone), [true]);
  assert.deepEqual(keysOf(engine.view()), ['a', 'x']);
});

test('usePlayer : « Annuler » (ajout, retrait) lit la vue à venir, état gardé en tampon compris', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.ok(src.includes('const upcoming = (): Snapshot => viewOf(engine.latest(), engine.pending());'));
  const restore = body(src, 'async function restoreTrack(');
  assert.ok(restore.includes('const before = upcoming().player.queue.map('), 'restoreTrack : avant');
  assert.ok(restore.includes('restorePlan(before, upcoming().player.queue, x.url, index)'), 'restoreTrack : après');
  const add = body(src, 'async function enqueue(');
  assert.ok(add.includes('const before = upcoming().player.queue.map('), 'enqueue : avant');
  assert.ok(add.includes('addedKeys(before, upcoming().player.queue, meId)'), 'enqueue : après');
  for (const [name, f] of [['restoreTrack', restore], ['enqueue', add]]) assert.ok(!f.includes('engine.view()'), `${name} : vue affichée`);
  const remove = body(src, 'async function removeTrack(');
  assert.ok(remove.includes("if (o.silent) return engine.dispatch({ kind: 'remove', key });"),
    'annuler un ajout : retrait par clé, même si la ligne attend encore en tampon');
});

// Le bot refuse aussi un titre du Roi (zone prioritaire, validate_move ; scène d'un mieux placé, _ensure_can_control).
test('refus PRIORITY_FORBIDDEN : le Roi n’est jamais nommé comme le prioritaire, texte générique à sa place', () => {
  const fn = body(read('src/hooks/usePlayer.ts'), 'function requesterName(');
  assert.ok(fn.includes('requesterOf('), 'même règle que la scène : le Roi est reconnu à son id');
  assert.ok(fn.includes("r.kind === 'other' ? r.name : undefined"));
  const refused = { payload: { error: 'PRIORITY_FORBIDDEN' } };
  const name = (addedBy) => { const r = requesterOf(addedBy, '101'); return r.kind === 'other' ? r.name : undefined; };
  assert.equal(errorCopy(refused, { name: name({ id: '101', name: 'Paul' }) }).path, 'error.PRIORITY_FORBIDDEN.textGeneric');
  assert.equal(errorCopy(refused, { name: name(null) }).path, 'error.PRIORITY_FORBIDDEN.textGeneric');
  const other = errorCopy(refused, { name: name({ id: '102', name: 'Léa' }) });
  assert.equal(other.path, 'error.PRIORITY_FORBIDDEN.text');
  assert.deepEqual(other.vars, { name: 'Léa' });
});

// Le bot ne dit pas pourquoi (PRIORITY_FORBIDDEN, la raison est perdue) : rang du demandeur (can_edit_queue_item), zone
// prioritaire (validate_move), scène d'un mieux placé (_ensure_can_control). Les poids sont ceux de la file (item.priority).
test('refus PRIORITY_FORBIDDEN d’un déplacement ou de « Jouer maintenant » : la bonne cause, jamais un faux prioritaire', () => {
  const W = (key, by, priority) => ({ ...track(key, undefined, by), ...(priority === undefined ? {} : { raw: { priority } }) });
  const at = (queue, current = track('cur', undefined, 'cur')) => ({ ...state(queue), player: { ...state(queue).player, current } });
  const blamed = (r) => r.blame?.addedBy?.name;
  const modo = W('k0', 'Modo'), k1 = W('k1', 'Léa');
  // un titre du Roi passe toujours can_edit_queue_item : seule la zone le refuse
  assert.deepEqual(refusalOf({ kind: 'move', key: 'k2', beforeKey: 'k0' }, at([modo, k1, W('k2', '101')]), '101'), { key: 'error.MOVE_PROMOTE_PRIORITY' });
  assert.deepEqual(refusalOf({ kind: 'move', key: 'k0', beforeKey: null }, at([W('k0', '101'), k1]), '101'), { key: 'error.MOVE_DEMOTE_PRIORITY' });
  // le titre de Bob, poids inconnus : pas de « Bob, prioritaire »
  const bob = refusalOf({ kind: 'move', key: 'k2', beforeKey: 'k0' }, at([modo, k1, W('k2', 'Bob')]), '101');
  assert.deepEqual(bob, { key: 'error.MOVE_PROMOTE_PRIORITY' });
  // poids connus : Bob (10) devant le DJ (80), la zone ; le titre du DJ (80) devant Léa (10), la zone exclue : son rang
  assert.deepEqual(refusalOf({ kind: 'move', key: 'b', beforeKey: 'd' }, at([W('d', 'DJ', 80), W('b', 'Bob', 10)]), '101'), { key: 'error.MOVE_PROMOTE_PRIORITY' });
  assert.equal(blamed(refusalOf({ kind: 'move', key: 'd', beforeKey: 'l' }, at([W('l', 'Léa', 10), W('d', 'DJ', 80)]), '101')), 'DJ');
  // « Jouer maintenant » sur le titre de Bob en tête, le DJ sur la scène : la scène, pas Bob
  const dj = W('cur', 'DJ');
  assert.equal(blamed(refusalOf({ kind: 'playAt', key: 'b', fromKey: 'cur' }, at([W('b', 'Bob')], dj), '101')), 'DJ');
  assert.deepEqual(refusalOf({ kind: 'playAt', key: 'k2', fromKey: 'cur' }, at([modo, k1, W('k2', 'Bob')], dj), '101'), { key: 'error.MOVE_PROMOTE_PRIORITY' });
  // le titre visé pèse au moins la scène : son rang (vérifié avant la scène)
  assert.equal(blamed(refusalOf({ kind: 'playAt', key: 'b', fromKey: 'cur' }, at([W('b', 'Bob', 80)], W('cur', 'Léa', 10)), '101')), 'Bob');
  // un titre du Roi en tête, la scène d'un autre : la scène
  assert.equal(blamed(refusalOf({ kind: 'playAt', key: 'm', fromKey: 'cur' }, at([W('m', '101')], dj), '101')), 'DJ');
  // retrait : le demandeur du titre ; passer, pause : celui de la scène
  assert.equal(blamed(refusalOf({ kind: 'remove', key: 'k1' }, at([modo, k1]), '101')), 'Léa');
  assert.equal(blamed(refusalOf({ kind: 'skip', fromKey: 'cur' }, at([k1], dj), '101')), 'DJ');
  assert.equal(blamed(refusalOf({ kind: 'setPaused', paused: true }, at([k1], dj), '101')), 'DJ');
});

test('usePlayer : un refus PRIORITY_FORBIDDEN passe par refusalOf (zone : MOVE_PROMOTE / MOVE_DEMOTE du deck)', () => {
  const src = read('src/hooks/usePlayer.ts');
  const refused = src.slice(src.indexOf('onRefused:'), src.indexOf('\n});', src.indexOf('onRefused:')));
  assert.match(refused, /const r = refusalOf\(m, before, useStore\.getState\(\)\.me\?\.id\);/);
  assert.match(refused, /if \('key' in r && errorCode\(e\)\.toUpperCase\(\) === 'PRIORITY_FORBIDDEN'\) say\(r\.key\);/);
  assert.match(refused, /else sayError\(e, \{ name: 'blame' in r \? requesterName\(r\.blame\) : undefined,/);
});

// « Annuler » (ajout, retrait, jouer ensuite) : sur le serveur de l'action, jamais celui choisi depuis.
test('usePlayer : les « Annuler » sont liés au serveur de l’action', () => {
  const src = read('src/hooks/usePlayer.ts');
  const add = body(src, 'async function enqueue(');
  assert.match(add, /const gid = s\.guildId, meId = s\.me\.id;/, 'serveur pris au clic');
  assert.match(add, /api\.queueAdd\(gid, meId, payload\)/);
  assert.match(add, /run: boundUndo\(gid, guildNow, \(\) => \{ for \(const k of keys\) void removeTrack\(k, \{ silent: true \}\); \}\)/);
  assert.match(add, /const keys = fromHere && here\(\) \? addedKeys\(before, upcoming\(\)\.player\.queue, meId\) : \[\];/,
    'serveur changé pendant l’ajout : la file affichée n’est pas celle de l’ajout');
  const restore = body(src, 'async function restoreTrack(');
  assert.match(restore, /^async function restoreTrack\(x: Track, index: number, gid: string\)/);
  assert.match(restore, /if \(!s\.me \|\| s\.guildId !== gid\) return;/, 'autre serveur choisi depuis le retrait : rien');
  assert.match(restore, /api\.queueAdd\(gid, meId, trackPayload\(x\)\)/);
  const remove = body(src, 'async function removeTrack(');
  assert.match(remove, /run: boundUndo\(gid, guildNow, afterDone\(done, \(\) => \{ void restoreTrack\(x, i, gid\); \}\)\)/);
  assert.match(body(src, 'async function playNext('), /run: boundUndo\(gid, guildNow, \(\) => \{ void moveTrack\(key, back\); \}\)/);
});

// « Retiré : X — Annuler » paraît avant la réponse du bot (l'ordre peut aussi attendre derrière un autre) : le rajout
// attend l'issue du retrait. Refusé, X n'est jamais parti : le rajouter le doublerait.
test('usePlayer : « Annuler » un retrait attend son issue (refusé : pas de doublon)', async () => {
  const remove = body(read('src/hooks/usePlayer.ts'), 'async function removeTrack(');
  const done = remove.indexOf("const done = engine.dispatch({ kind: 'remove', key });");
  assert.ok(done > 0 && done < remove.indexOf("say('toast.removed'"), 'l’ordre part, puis le toast propose de l’annuler');
  assert.match(remove, /const ok = await done;\n\s+if \(!ok\) herald\.retract\(id\);/);
  // même enchaînement sur le moteur : le retrait du titre de Léa est en vol, le Roi clique « Annuler » tout de suite
  const { engine, sent } = rig(state([track('a'), track('x', undefined, 'lea')]));
  let restored = 0;
  const acked = engine.dispatch({ kind: 'remove', key: 'x' });
  afterDone(acked, () => { restored++; })();
  await settle();
  assert.equal(restored, 0, 'pas avant la réponse du bot');
  sent[0].resolve({ ok: true });
  assert.equal(await acked, true);
  await settle();
  assert.equal(restored, 1, 'retrait accusé : le titre est rajouté');
  const refused = rig(state([track('a'), track('x', undefined, 'lea')]));
  const refusedDone = refused.engine.dispatch({ kind: 'remove', key: 'x' });
  afterDone(refusedDone, () => { restored++; })();
  refused.sent[0].reject(Object.assign(new Error('refus'), { payload: { error: 'PRIORITY_FORBIDDEN' } }));
  assert.equal(await refusedDone, false);
  await settle();
  assert.equal(restored, 1, 'refusé : rien à rajouter');
  assert.deepEqual(keysOf(refused.engine.view()), ['a', 'x'], 'le titre n’a jamais quitté la file');
});

// Ajout lancé avant le premier état du serveur choisi (démarrage, changement de serveur, GET /playlist en vol) : la file
// « avant » est la vue vide du reset, tous les titres du Roi y passeraient pour « ajoutés » et « Annuler » les retirerait.
test('usePlayer : pas d’« Annuler » d’un ajout lancé avant que la file du serveur ne soit lue', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.match(src, /\nlet _queueOf = '';/, 'serveur dont la file affichée a été lue');
  const rec = body(src, 'function receive(');
  assert.ok(rec.indexOf("if (kind === 'full') _queueOf = useStore.getState().guildId;") > rec.indexOf('engine.receive(snap);'),
    'un état complet lit la file ; un tick ne la porte pas');
  assert.match(body(src, 'function resetPlayer('), /_queueOf = '';/);
  const add = body(src, 'async function enqueue(');
  assert.match(add, /const before = upcoming\(\)\.player\.queue\.map\(\(x\) => x\.key\);\n(?:\s*\/\/[^\n]*\n)*\s+const fromHere = here\(\) && _queueOf === gid;/,
    'file pas encore lue quand « avant » est pris : rien d’attribuable');
  const restore = body(src, 'async function restoreTrack(');
  assert.match(restore, /const before = upcoming\(\)\.player\.queue\.map\(\(q\) => q\.key\);\n\s+const known = _queueOf === gid;/);
  assert.match(restore, /return known \? restorePlan\(before, upcoming\(\)\.player\.queue, x\.url, index\) : null;/,
    'place inconnue : le titre revient en fin de file, aucune ligne déjà là n’est déplacée');
  // pourquoi : sur la vue vide du reset, tous les titres du Roi déjà là passent pour « ajoutés »
  const mine = (k) => track(k, undefined, '101');
  assert.deepEqual(addedKeys([], [mine('old1'), mine('old2'), mine('new')], '101'), ['old1', 'old2', 'new']);
});

// Le bot écrit guild_id en nombre (int Python) : un id Discord dépasse 2^53, la comparaison se fait sur les deux arrondis.
test('état reçu : d’un autre serveur, tick ou complet (guild_id du bot au-delà de 2^53)', () => {
  const big = '123456789012345678';
  assert.equal(stateKind(JSON.parse(`{"guild_id": ${big}, "queue": []}`), big), 'full', 'même serveur malgré l’arrondi');
  assert.equal(stateKind(JSON.parse(`{"state": {"guild_id": ${big}}}`), big), 'full');
  assert.equal(stateKind(JSON.parse('{"guild_id": 223456789012345678, "queue": []}'), big), 'other');
  assert.equal(stateKind({ guild_id: '9', queue: [] }, '9'), 'full');
  assert.equal(stateKind({ guild_id: '8', queue: [] }, '9'), 'other');
  assert.equal(stateKind({ pm: { guild_id: 8 } }, '9'), 'other');
  assert.equal(stateKind({ queue: [] }, '9'), 'full', 'sans guild_id : rien à dire, gardé');
  assert.equal(stateKind({ only_elapsed: true, position: 3 }, '9'), 'tick');
  assert.equal(stateKind({ data: { only_elapsed: true } }, '9'), 'tick');
  assert.equal(stateKind(null, '9'), 'full');
});

// setGuild(B) : la room de A n'est quittée qu'après le rendu ; un état de A émis juste avant arrive encore. Compté, il
// faisait écarter la réponse REST de B (C5), et la file de A restait affichée sous B (retraits et déplacements envoyés à B).
test('usePlayer : un état du socket d’un autre serveur n’est ni daté ni affiché', () => {
  const rec = body(read('src/hooks/usePlayer.ts'), 'function receive(');
  assert.match(rec, /^function receive\(payload: any, from: 'socket' \| 'rest' = 'socket'\): boolean \{\n\s+const kind = stateKind\(payload, useStore\.getState\(\)\.guildId\);\n\s+if \(from === 'socket' && kind === 'other'\) return false;/);
  assert.ok(rec.indexOf("kind === 'other'") < rec.indexOf('_order.socket()') && rec.indexOf("kind === 'other'") < rec.indexOf('engine.receive('));
  // même enchaînement : GET /playlist de B en vol, un état de A arrive par le socket
  const order = createStateOrder();
  const mark = order.mark();
  const fromA = JSON.parse('{"guild_id": 111111111111111111, "queue": [{"url": "u"}]}');
  if (stateKind(fromA, '222222222222222222') === 'full') order.socket();
  assert.equal(order.fresh(mark), true, 'la réponse REST de B est appliquée');
});

test('usePlayer : un ajout (ou un rajout) à la fois, chacun relit la file après le précédent', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.match(src, /const addTurn = createTurns\(\);/);
  assert.match(body(src, 'async function enqueue('), /const ok = await addTurn\(async \(\) => \{\n\s+const before = upcoming\(\)\.player\.queue\.map\(/);
  assert.match(body(src, 'async function restoreTrack('), /const plan = await addTurn\(async \(\) => \{\n\s+if \(!here\(\)\) return null;\n\s+const before = upcoming\(\)\.player\.queue\.map\(/);
});

test('usePlayer : l’historique (« Souvent demandés ici », Annales) est celui du serveur affiché', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.match(body(src, 'async function setGuild('), /if \(id !== oldGid\) \{ resetPlayer\(\); useStore\.getState\(\)\.setHistoryItems\(\[\]\); \}/,
    'changement de serveur : la liste de l’ancien part avant le premier await');
  const h = body(src, 'async function refreshHistory(');
  assert.match(h, /const gid = s\.guildId;/);
  assert.match(h, /api\.getHistory\(gid, 'top', 30\)/);
  assert.equal((h.match(/if \(useStore\.getState\(\)\.guildId !== gid\) return;/g) || []).length, 2, 'réponse et échec d’un autre serveur ignorés');
});

test('usePlayer : une réponse REST partie avant le dernier état complet du socket est écartée', () => {
  const src = read('src/hooks/usePlayer.ts');
  const rec = body(src, 'function receive(');
  assert.match(rec, /^function receive\(payload: any, from: 'socket' \| 'rest' = 'socket'\): boolean/);
  assert.match(rec, /if \(from === 'socket' && kind === 'full'\) _order\.socket\(\);/, 'un tick ne date rien (stateKind : « tick »)');
  const r = body(src, 'async function refreshPlaylist(');
  assert.ok(r.indexOf('const mark = _order.mark();') >= 0 && r.indexOf('const mark = _order.mark();') < r.indexOf('await api.getPlaylistState(gid)'), 'marque prise au départ');
  assert.match(r, /if \(_order\.fresh\(mark\) && !receive\(data, 'rest'\)\) throw/);
});
