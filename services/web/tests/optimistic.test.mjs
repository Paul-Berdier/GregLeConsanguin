// Actions optimistes (spec §5, tech.md §3) : réducteur par clé, rapprochement, moteur à une requête en vol.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const {
  moveIndices, applyMutation, viewOf, isSatisfied, reconcile, enqueueMutation, createQueueEngine, createStateOrder,
  ACK_GRACE_MS, HOLD_MAX_MS,
} = await loadTs('../src/lib/queue/optimistic.ts');

const T = (k, duration = 200) => ({ key: k, url: `https://youtu.be/${k}`, title: k.toUpperCase(), duration });
const snap = (queue, extra = {}) => ({
  player: { current: null, queue, paused: false, repeat: false, position: 0, duration: 0, ...extra },
  tickBase: { pos: 0, at: 0, dur: 0 },
});
const order = (s) => s.player.queue.map((t) => t.key).join(',');
let id = 0;
const mut = (o) => ({ id: ++id, at: 1000, status: 'sent', ...o });

test('moveIndices reproduit le bot : insert(dst, pop(src))', () => {
  const q = ['a', 'b', 'c', 'd'].map((k) => T(k));
  assert.deepEqual(moveIndices(q, 'd', 'a'), { src: 3, dst: 0 });   // en tête
  assert.deepEqual(moveIndices(q, 'a', null), { src: 0, dst: 3 });  // en fin
  assert.deepEqual(moveIndices(q, 'a', 'c'), { src: 0, dst: 1 });
  assert.equal(moveIndices(q, 'a', 'b'), null);                     // déjà à sa place
  assert.equal(moveIndices(q, 'x', 'a'), null);                     // titre absent
  assert.equal(moveIndices(q, 'a', 'zz'), null);                    // ancre disparue : rien, le titre garde sa place
  const bot = (arr, mv) => { const c = [...arr]; if (mv) c.splice(mv.dst, 0, c.splice(mv.src, 1)[0]); return c.map((t) => t.key).join(','); };
  for (const [key, before] of [['a', 'c'], ['d', 'b'], ['b', null], ['c', 'a'], ['b', 'zz']]) {
    const mv = moveIndices(q, key, before);
    assert.equal(bot(q, mv), order(applyMutation(snap(q), mut({ kind: 'move', key, beforeKey: before }))), `${key} avant ${before}`);
  }
});

test('déplacer : ancre disparue, titre disparu, même place', () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  const s = snap(q);
  assert.equal(order(applyMutation(s, mut({ kind: 'move', key: 'c', beforeKey: 'zz' }))), 'a,b,c');   // ancre partie : garde sa place
  assert.equal(applyMutation(s, mut({ kind: 'move', key: 'zz', beforeKey: 'a' })), s);                // titre parti : rien
  assert.equal(applyMutation(s, mut({ kind: 'move', key: 'a', beforeKey: 'b' })), s);                 // même objet
});

test('retirer, jouer maintenant, passer : conditionnels, jamais de double saut', () => {
  const [cur, n1, n2] = ['cur', 'n1', 'n2'].map((k) => T(k, 180));
  const s0 = snap([n1, n2], { current: cur, duration: 200 });
  assert.equal(order(applyMutation(s0, mut({ kind: 'remove', key: 'n1' }))), 'n2');
  const played = applyMutation(s0, mut({ kind: 'playAt', key: 'n2', fromKey: 'cur', at: 5000 }));
  assert.equal(played.player.current.key, 'n2');
  assert.equal(order(played), 'n1');
  assert.deepEqual(played.tickBase, { pos: 0, at: 5000, dur: 180, frozen: true }, 'figée jusqu’à ce que le bot le joue');
  assert.equal(played.player.paused, false);
  const skipped = applyMutation(s0, mut({ kind: 'skip', fromKey: 'cur' }));
  assert.equal(skipped.player.current.key, 'n1');
  // le bot a déjà avancé : rejouer le saut ne saute pas une deuxième fois
  const advanced = snap([n2], { current: n1 });
  assert.equal(viewOf(advanced, [mut({ kind: 'skip', fromKey: 'cur' })]).player.current.key, 'n1');
  // plus rien après : la scène se vide
  const last = applyMutation(snap([], { current: cur }), mut({ kind: 'skip', fromKey: 'cur' }));
  assert.equal(last.player.current, null);
  assert.equal(last.player.paused, true);
});

test('pause : l’horloge s’arrête à l’instant du clic, reprend de là', () => {
  const cur = T('cur', 100);
  const s0 = { player: { ...snap([], { current: cur }).player, paused: false }, tickBase: { pos: 10, at: 0, dur: 100 } };
  const p = applyMutation(s0, { id: 1, at: 5000, status: 'queued', kind: 'setPaused', paused: true });
  assert.equal(p.player.paused, true);
  assert.deepEqual(p.tickBase, { pos: 15, at: 5000, dur: 100 });
  const r = applyMutation(p, { id: 2, at: 9000, status: 'queued', kind: 'setPaused', paused: false });
  assert.deepEqual(r.tickBase, { pos: 15, at: 9000, dur: 100 });
  assert.equal(applyMutation(snap([]), { id: 3, at: 0, status: 'queued', kind: 'setPaused', paused: true }).player.paused, false, 'rien en lecture : rien à mettre en pause');
});

test('rapprochement : accusée et visible part, non accusée reste, accusée trop vieille part', () => {
  const q = ['a', 'b'].map((k) => T(k));
  const acked = { ...mut({ kind: 'remove', key: 'a' }), status: 'acked', ackedAt: 1000 };
  const sent = mut({ kind: 'remove', key: 'b' });
  assert.deepEqual(reconcile([acked, sent], snap([q[1]]), 1200).map((m) => m.id), [sent.id]);
  const notYet = { ...mut({ kind: 'move', key: 'b', beforeKey: 'a' }), status: 'acked', ackedAt: 1000 };
  assert.equal(reconcile([notYet], snap(q), 1000 + ACK_GRACE_MS - 1).length, 1);
  assert.equal(reconcile([notYet], snap(q), 1000 + ACK_GRACE_MS).length, 0);
  assert.ok(isSatisfied(notYet, snap([q[1], q[0]])));
});

test('regroupement : deux déplacements du même titre non envoyés, deux pauses : seul le dernier reste', () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  let p = enqueueMutation([], { ...mut({ kind: 'move', key: 'c', beforeKey: 'b' }), status: 'queued' });
  p = enqueueMutation(p, { ...mut({ kind: 'move', key: 'c', beforeKey: 'a' }), status: 'queued' });
  assert.equal(p.length, 1);
  assert.equal(order(viewOf(snap(q), p)), 'c,a,b');
  p = enqueueMutation(p, { ...mut({ kind: 'setPaused', paused: true }), status: 'queued' });
  p = enqueueMutation(p, { ...mut({ kind: 'setPaused', paused: false }), status: 'queued' });
  assert.deepEqual(p.map((m) => m.kind), ['move', 'setPaused']);
});

// ── Moteur ──
function deferred() {
  let resolve, reject;
  const promise = new Promise((r, j) => { resolve = r; reject = j; });
  return { promise, resolve, reject };
}
function rig(initial, { holdMaxMs } = {}) {
  let now = 0;
  const sent = [];
  const views = [];
  const refused = [];
  const engine = createQueueEngine({
    initial,
    now: () => now,
    holdMaxMs,
    send: (m, before) => {
      if (m.kind === 'remove' && before.player.queue.every((t) => t.key !== m.key)) return null;
      const d = deferred();
      sent.push({ m, before, ...d });
      return d.promise;
    },
    onView: (v) => views.push(v),
    onRefused: (m, e) => refused.push({ m, e }),
  });
  return { engine, sent, views, refused, tick: (ms) => { now += ms; } };
}
const flush = () => new Promise((r) => setTimeout(r, 0));

test('moteur : la vue change tout de suite ; sans ordre en attente, la vue est l’état reçu', async () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  const { engine, sent } = rig(snap(q));
  assert.equal(engine.view(), engine.server());
  const done = engine.dispatch({ kind: 'remove', key: 'b' });
  assert.equal(order(engine.view()), 'a,c');
  assert.equal(sent.length, 1);
  assert.equal(order(sent[0].before), 'a,b,c', 'indices calculés sur ce que le bot voit');
  sent[0].resolve({ ok: true });
  assert.equal(await done, true);
  engine.receive(snap([q[0], q[2]]));
  assert.equal(engine.pending().length, 0);
  assert.equal(engine.view(), engine.server());
});

test('moteur : refus de l’API = retour en arrière, onRefused appelé, promesse à false', async () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  const { engine, sent, refused } = rig(snap(q));
  const done = engine.dispatch({ kind: 'move', key: 'c', beforeKey: 'a' });
  assert.equal(order(engine.view()), 'c,a,b');
  sent[0].reject(Object.assign(new Error('403'), { status: 403, payload: { error: 'PRIORITY_FORBIDDEN' } }));
  assert.equal(await done, false);
  assert.equal(order(engine.view()), 'a,b,c');
  assert.equal(refused.length, 1);
  assert.equal(refused[0].m.kind, 'move');
});

test('moteur : une requête à la fois ; la suivante voit l’effet de la précédente', async () => {
  const q = ['a', 'b', 'c', 'd'].map((k) => T(k));
  const { engine, sent } = rig(snap(q));
  engine.dispatch({ kind: 'remove', key: 'b' });
  engine.dispatch({ kind: 'remove', key: 'd' });
  assert.equal(order(engine.view()), 'a,c');
  assert.equal(sent.length, 1, 'la deuxième attend');
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(sent.length, 2);
  assert.equal(order(sent[1].before), 'a,c,d', 'index de d calculé après le retrait de b');
});

test('moteur : un état reçu pendant l’action en vol attend sa fin (pas de clignotement)', async () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  const { engine, sent, views } = rig(snap(q));
  engine.dispatch({ kind: 'move', key: 'c', beforeKey: 'a' });
  const n = views.length;
  engine.receive(snap([...q, T('x')]));        // quelqu'un ajoute x ; le bot n'a pas encore déplacé c
  assert.equal(views.length, n, 'rien ne bouge pendant l’action');
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(order(engine.view()), 'c,a,b,x', 'l’état gardé est appliqué, le déplacement rejoué dessus');
});

test('moteur : au-delà de HOLD_MAX_MS, les états reçus passent (bot lent)', () => {
  const q = ['a', 'b'].map((k) => T(k));
  const { engine, tick } = rig(snap(q));
  engine.dispatch({ kind: 'remove', key: 'a' });
  tick(HOLD_MAX_MS);
  engine.receive(snap([...q, T('x')]));
  assert.equal(order(engine.view()), 'b,x');
});

test('moteur : glisser = états gardés jusqu’au dépôt', () => {
  const q = ['a', 'b'].map((k) => T(k));
  const { engine } = rig(snap(q));
  engine.hold();
  engine.receive(snap([...q, T('x')]));
  assert.equal(order(engine.view()), 'a,b');
  engine.release();
  assert.equal(order(engine.view()), 'a,b,x');
});

test('moteur : latest() rend l’état gardé en tampon, base du tick suivant (rien ne se perd)', () => {
  const q = ['a', 'b'].map((k) => T(k));
  const { engine } = rig(snap(q));
  assert.equal(engine.latest(), engine.server(), 'rien en tampon : le dernier état appliqué');
  engine.hold();
  const withX = snap([...q, T('x')]);
  engine.receive(withX);                        // un courtisan ajoute x pendant le glisser : gardé
  assert.equal(engine.latest(), withX, 'un tick calculé sur server() remplacerait cet état et effacerait x');
  assert.equal(order(engine.server()), 'a,b');
  engine.receive({ ...withX, tickBase: { pos: 5, at: 1000, dur: 200 } });   // le tick, calculé sur latest()
  engine.release();
  assert.equal(order(engine.view()), 'a,b,x');
  assert.equal(engine.view().tickBase.pos, 5);
  assert.equal(engine.latest(), engine.server());
});

test('moteur : ordre devenu sans effet = pas de requête, promesse à true', async () => {
  const q = ['a', 'b'].map((k) => T(k));
  const { engine, sent } = rig(snap(q));
  engine.hold();
  engine.receive(snap([q[0]]));                // b retiré ailleurs, pas encore affiché
  engine.release();
  assert.equal(await engine.dispatch({ kind: 'remove', key: 'b' }), true);
  assert.equal(sent.length, 0);
});

// useQueueDrag : onDrop (dispatch, envoi) part AVANT onEnd (release) ; l'état reçu pendant le glisser est encore gardé.
test('moteur : un dépôt pendant le glisser calcule ses indices sur l’état gardé (le bot a avancé)', () => {
  const q = ['a', 'b', 'c', 'd', 'e'].map((k) => T(k));
  const { engine, sent } = rig(snap(q, { current: T('x') }));
  engine.hold();                                                    // saisie (onLift)
  engine.receive(snap(q.slice(1), { current: q[0] }));              // x fini : a passe sur la scène, état gardé
  engine.dispatch({ kind: 'move', key: 'd', beforeKey: 'b' });      // dépôt (onDrop)
  engine.release();                                                 // onEnd
  assert.equal(sent.length, 1);
  assert.equal(order(sent[0].before), 'b,c,d,e', 'indices calculés sur la file que le bot a');
  assert.deepEqual(moveIndices(sent[0].before.player.queue, 'd', 'b'), { src: 2, dst: 0 }, 'et non {3,1}, qui déplacerait e');
});

test('moteur : l’ordre envoyé à l’accusé du précédent, pendant un glisser, part lui aussi de l’état gardé', async () => {
  const q = ['a', 'b', 'c', 'd', 'e'].map((k) => T(k));
  const { engine, sent } = rig(snap(q));
  engine.dispatch({ kind: 'remove', key: 'e' });                    // en vol
  engine.hold();                                                    // saisie
  engine.receive(snap(q.slice(1)));                                 // a a joué : gardé (le retrait de e n'y est pas encore)
  engine.dispatch({ kind: 'move', key: 'd', beforeKey: 'b' });      // dépôt : attend l'accusé
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(sent.length, 2);
  assert.equal(order(sent[1].before), 'b,c,d', 'l’état gardé, le retrait de e rejoué dessus');
  assert.deepEqual(moveIndices(sent[1].before.player.queue, 'd', 'b'), { src: 2, dst: 0 });
  engine.release();
});

// Même condition que sendMutation : « Jouer maintenant » et « Suivant » ne partent que si la scène est celle du clic.
function stageRig(initial) {
  const sent = [];
  const engine = createQueueEngine({
    initial, now: () => 0, onView: () => {},
    send: (m, before) => {
      const cur = before.player.current?.key ?? null;
      if ((m.kind === 'playAt' || m.kind === 'skip') && cur !== m.fromKey) return null;
      if (m.kind === 'playAt' && before.player.queue.every((t) => t.key !== m.key)) return null;
      const d = deferred();
      sent.push({ m, before, ...d });
      return d.promise;
    },
  });
  return { engine, sent };
}

test('moteur : « Jouer maintenant » écarté parce que la scène a changé entre-temps, promesse à false (pas de faux succès)', async () => {
  const [A, X, Y] = ['A', 'X', 'Y'].map((k) => T(k));
  const { engine, sent } = stageRig(snap([Y, X], { current: A }));
  const paused = engine.dispatch({ kind: 'setPaused', paused: true });    // Espace : en vol
  const played = engine.dispatch({ kind: 'playAt', key: 'X', fromKey: 'A' });   // attend son tour
  engine.receive(snap([X], { current: Y }));                              // A fini, Y passe : gardé pendant l'action
  sent[0].resolve({ ok: true });
  assert.equal(await paused, true);
  assert.equal(await played, false, 'X n’a jamais été joué : ni « Lecture immédiate » ni salon vocal');
  assert.equal(sent.length, 1, 'rien envoyé');
  assert.equal(engine.view().player.current.key, 'Y');
  assert.equal(order(engine.view()), 'X');
});

test('moteur : « Suivant » refusé, le « Jouer maintenant » qui le suivait est écarté à false ; un saut déjà fait reste un succès', async () => {
  const [A, B, X] = ['A', 'B', 'X'].map((k) => T(k));
  const { engine, sent } = stageRig(snap([B, X], { current: A }));
  const skipped = engine.dispatch({ kind: 'skip', fromKey: 'A' });        // N : la vue montre B
  const played = engine.dispatch({ kind: 'playAt', key: 'X', fromKey: 'B' });
  sent[0].reject(Object.assign(new Error('403'), { status: 403, payload: { error: 'PRIORITY_FORBIDDEN' } }));
  assert.equal(await skipped, false);
  assert.equal(await played, false);
  assert.equal(engine.view().player.current.key, 'A');
  assert.equal(order(engine.view()), 'B,X');
  // A passé ailleurs (fin du titre, un courtisan) : « Suivant » sur A a déjà son effet
  const again = stageRig(snap([X], { current: B }));
  assert.equal(await again.engine.dispatch({ kind: 'skip', fromKey: 'A' }), true);
  // X déjà sur la scène (joué par un autre) : l'ordre a son effet
  const done = stageRig(snap([], { current: X }));
  assert.equal(await done.engine.dispatch({ kind: 'playAt', key: 'X', fromKey: 'A' }), true);
});

// REST et socket n'arrivent pas dans l'ordre où le bot les a écrits (chemins séparés).
test('ordre des états : une réponse REST partie avant le dernier état complet du socket est écartée', async () => {
  const st = createStateOrder();
  const m1 = st.mark();
  assert.equal(st.fresh(m1), true, 'aucun état du socket pendant la requête');
  // GET /playlist (relève de 5 s) en vol ; le Roi retire b ; l'état d'après le retrait arrive par le socket, puis la
  // réponse REST, lue par le bot avant le retrait.
  const [a, b, c, d] = ['a', 'b', 'c', 'd'].map((k) => T(k));
  const { engine, sent } = rig(snap([a, b, c, d]));
  const rest = st.mark();
  engine.dispatch({ kind: 'remove', key: 'b' });
  sent[0].resolve({ ok: true });
  await flush();
  st.socket();
  engine.receive(snap([a, c, d]));
  assert.equal(st.fresh(rest), false, 'la réponse REST est peut-être plus vieille : écartée');
  if (st.fresh(rest)) engine.receive(snap([a, b, c, d]));
  assert.equal(order(engine.view()), 'a,c,d', 'b ne revient pas');
  engine.dispatch({ kind: 'remove', key: 'c' });
  assert.equal(sent[1].before.player.queue.findIndex((t) => t.key === 'c'), 1, 'l’index de c sur la file du bot, pas d sur [a,b,c,d]');
  assert.equal(st.fresh(st.mark()), true, 'une requête partie après lui passe');
});

test('moteur : reset (autre serveur) vide l’attente et ignore les réponses en retard', async () => {
  const q = ['a', 'b'].map((k) => T(k));
  const { engine, sent } = rig(snap(q));
  const done = engine.dispatch({ kind: 'remove', key: 'a' });
  engine.reset(snap([T('z')]));
  assert.equal(await done, false);
  assert.equal(order(engine.view()), 'z');
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(engine.pending().length, 0);
  assert.equal(order(engine.view()), 'z');
});

test('moteur : « Annuler » de « Jouer ensuite », le premier déplacement accusé n’est pas rejoué par-dessus', async () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  const { engine, sent, tick } = rig(snap(q));
  engine.dispatch({ kind: 'move', key: 'c', beforeKey: 'a' });   // jouer ensuite
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(order(engine.view()), 'c,a,b');
  engine.dispatch({ kind: 'move', key: 'c', beforeKey: null });  // Annuler : retour en fin de file
  assert.equal(order(engine.view()), 'a,b,c');
  assert.equal(order(sent[1].before), 'c,a,b', 'indices calculés après le premier déplacement');
  sent[1].resolve({ ok: true });
  await flush();
  assert.equal(order(engine.view()), 'a,b,c', 'à l’accusé, sans état reçu entre les deux');
  tick(500);
  engine.receive(snap(q));                                       // le bot a fait les deux : c est de nouveau en fin
  assert.equal(order(engine.view()), 'a,b,c');
  assert.equal(engine.pending().length, 0);
});

test('moteur : pause puis reprise accusées sans état reçu entre les deux, la vue suit la dernière', async () => {
  const { engine, sent } = rig(snap([T('a')], { current: T('now') }));
  engine.dispatch({ kind: 'setPaused', paused: true });
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(engine.view().player.paused, true);
  engine.dispatch({ kind: 'setPaused', paused: false });
  sent[1].resolve({ ok: true });
  await flush();
  assert.equal(engine.view().player.paused, false, 'la pause accusée n’est pas rejouée par-dessus la reprise');
  assert.equal(engine.pending().length, 0);
});

test('synchro son/vidéo : le saut optimiste fige l’horloge à 0, une pause ne la fait pas avancer', () => {
  const cur = T('cur', 100), n1 = T('n1', 180);
  const s0 = { player: { ...snap([n1], { current: cur }).player, paused: false }, tickBase: { pos: 10, at: 0, dur: 100 } };
  const skipped = applyMutation(s0, mut({ kind: 'skip', fromKey: 'cur', at: 5000 }));
  assert.equal(skipped.player.paused, false, 'pas en pause : seulement en attente du bot');
  const p = applyMutation(skipped, { id: 9, at: 9000, status: 'queued', kind: 'setPaused', paused: true });
  assert.equal(p.tickBase.pos, 0, 'figée : 4 s plus tard, toujours 0');
});
