// Contrats de usePlayer (étape 3) : un seul chemin pour les états reçus, plus de barre de statut, le Héraut monté.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';

const { createQueueEngine, viewOf, moveIndices } = await loadTs('../src/lib/queue/optimistic.ts');
const { addedKeys, restorePlan } = await loadTs('../src/lib/queue/undo.ts');
const { requesterOf } = await loadTs('../src/lib/stage/scene.ts');
const { errorCopy } = await loadTs('../src/lib/playerUtils.ts');

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
      let resolve;
      const promise = new Promise((r) => { resolve = r; });
      sent.push({ m, before, resolve });
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
