import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { roseKey, keyFits, isMoonKey, evictable, KEEP_OTHERS, FADE_MS, RoseClient, afterFirstPaint, FIRST_PAINT_WAIT_MS, RESIZE_DEBOUNCE_MS, watchDpr } = await loadTs('../src/lib/rose/client.ts');

test('clé d’une fenêtre : titre ou lune, à une taille et une densité', () => {
  assert.equal(roseKey('dQw4w9WgXcQ', 349, 2), 't:dQw4w9WgXcQ@349x2');
  assert.equal(roseKey(null, 349, 1), 'moon@349x1');
  assert.ok(isMoonKey('moon@349x1') && !isMoonKey('t:moon@349x1'));
});

test('une peinture arrivée pour une ancienne taille est jetée', () => {
  assert.ok(keyFits('t:a@349x2', 349, 2));
  assert.ok(!keyFits('t:a@349x2', 291, 2));
  assert.ok(!keyFits('t:a@349x2', 349, 1));
});

test('fenêtres montées : on garde la lune, l’affichée, la nouvelle et les 2 plus récentes', () => {
  assert.equal(KEEP_OTHERS, 2);
  const keys = ['moon@1x1', 't:a@1x1', 't:b@1x1', 't:c@1x1', 't:d@1x1', 't:e@1x1'];
  assert.deepEqual(evictable(keys, ['t:a@1x1', 't:e@1x1'], 1, 1), ['t:b@1x1']);
  assert.deepEqual(evictable(['moon@1x1', 't:a@1x1'], ['t:a@1x1'], 1, 1), []);
});

test('fenêtres peintes pour une autre taille : évincées, la lune comprise, sauf celles à garder', () => {
  const keys = ['moon@300x2', 't:a@300x2', 'moon@310x2', 't:b@310x2', 't:c@300x2'];
  assert.deepEqual(evictable(keys, ['t:c@300x2', 't:b@310x2'], 310, 2), ['moon@300x2', 't:a@300x2']);
  assert.deepEqual(evictable(['moon@310x1', 'moon@310x2'], [], 310, 2), ['moon@310x1']);
});

/* ── Cycle de vie des fenêtres : un DOM et un worker factices ──────────────────────────────────────
   Le faux DOM reprend les règles des Web Animations relevées dans Chrome (review de la tâche 2) :
   - une animation finie en fill 'forwards' continue de s'appliquer, même après un détachement ;
   - une animation finie en fill 'backwards' ne s'applique plus ;
   - la dernière animation créée qui s'applique l'emporte, sinon le style en ligne ;
   - un élément détaché ne rend aucune animation par getAnimations(), et getComputedStyle n'y donne rien.
   Un fondu avance avec performance.now() (linéaire) : les tests à horloge simulée le font défiler. */
const anims = [];
class FakeAnim {
  constructor(frames, opts) {
    this.from = Number(frames[0].opacity);
    this.to = Number(frames.at(-1).opacity);
    this.duration = opts.duration;
    this.t0 = performance.now();
    this.fill = opts.fill ?? 'none';
    this.state = 'running';
    this.finished = new Promise((res, rej) => { this.res = res; this.rej = rej; });
    this.finished.catch(() => {});
    anims.push(this);
  }
  get value() {
    if (this.state !== 'running') return this.to;
    const p = Math.min(1, Math.max(0, (performance.now() - this.t0) / this.duration));
    return this.from + (this.to - this.from) * p;
  }
  finish() { if (this.state === 'running') { this.state = 'finished'; this.res(this); } }
  cancel() { if (this.state === 'running') this.rej(new Error('AbortError')); this.state = 'idle'; }
  get applies() { return this.state === 'running' || (this.state === 'finished' && (this.fill === 'forwards' || this.fill === 'both')); }
}
class El {
  constructor(tag, root = false) {
    this.tag = tag; this.root = root; this.parent = null; this.children = []; this.anims = [];
    this.className = ''; this.dataset = {}; this.width = 0; this.height = 0; this.bitmap = null;
    this.style = { opacity: '', zIndex: '', setProperty(k, v) { this[k] = v; } };
  }
  get isConnected() { return this.root || (this.parent?.isConnected ?? false); }
  appendChild(ch) { ch.remove(); ch.parent = this; this.children.push(ch); return ch; }
  append(...chs) { for (const ch of chs) this.appendChild(ch); }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  animate(frames, opts) { const a = new FakeAnim(frames, opts); this.anims.push(a); return a; }
  getAnimations() { return this.isConnected ? this.anims.filter((a) => a.applies) : []; }
  getContext(kind) { return kind === 'bitmaprenderer' ? { transferFromImageBitmap: (bm) => { this.bitmap = bm; } } : null; }
  /** Opacité rendue : la dernière animation qui s'applique, sinon le style en ligne. */
  rendered() {
    let v = this.style.opacity === '' ? 1 : Number(this.style.opacity);
    for (const a of this.anims) if (a.applies) v = a.value;
    return v;
  }
}
globalThis.window = { devicePixelRatio: 1 };
globalThis.location = { origin: 'http://localhost' };
globalThis.document = { createElement: (tag) => new El(tag), documentElement: new El('html', true) };
globalThis.getComputedStyle = (el) => ({ opacity: el.isConnected ? String(el.rendered()) : '' });

/** Opacité rendue d'une fenêtre, une fois tous les fondus terminés. */
function shownOpacity(el) {
  assert.ok(!el.anims.some((a) => a.state === 'running'), 'un fondu tourne encore');
  return el.rendered();
}
const slotKey = (slot) => slot.children[0]?.bitmap?.key;
const zOf = (slot) => Number(slot.style.zIndex || 0);
const wait = (ms = 0) => new Promise((r) => setTimeout(r, ms));
async function finishFades() { for (const a of anims) a.finish(); await wait(); }
async function until(cond, ms = 3000) {
  const t0 = Date.now();
  while (!cond()) { if (Date.now() - t0 > ms) assert.fail('délai dépassé'); await wait(5); }
}

/** Un client branché sur un worker factice (sans vrai Worker : `new URL(…, import.meta.url)` n'a pas d'URL de fichier ici). */
function makeRose({ paintMs = 1, autoStart = true } = {}) {
  anims.length = 0;
  const layers = { bloom: new El('div', true), glass: new El('div', true) };
  const posts = [];
  let fails = 0;
  const bitmap = (key, w, h) => ({ key, width: w, height: h, close() {} });
  const worker = {
    onmessage: null, onerror: null, onmessageerror: null, silent: false, terminated: false,
    postMessage(m) {
      if (m.type !== 'paint') return;
      posts.push(m.key);
      if (this.silent) return;
      const moon = !m.id, W = Math.round(2.12 * m.R * m.dpr);
      setTimeout(() => this.onmessage?.({ data: {
        type: 'painted', key: m.key, pal: { mode: moon ? 'moon' : 'color', lum: moon ? [180, 196, 226] : [200, 100, 50] },
        win: bitmap(m.key, W, W), bloom: bitmap(m.key, W, W),
        ring: moon ? null : bitmap(m.key, W, 40), head: moon ? null : bitmap(m.key, W, 40), ms: [0, 0],
      } }), paintMs);
    },
    terminate() { this.terminated = true; },
  };
  const c = new RoseClient(layers, { createWorker: () => worker, onFail: () => { fails++; } });
  if (autoStart) c.start();
  /** La fenêtre au premier plan des deux calques : elle doit être celle voulue, et visible. */
  const front = () => {
    const pick = (layer) => {
      const max = Math.max(...layer.children.map(zOf));
      const top = layer.children.filter((s) => zOf(s) === max);
      assert.equal(top.length, 1, 'une seule fenêtre au premier plan');
      return top[0];
    };
    const glass = pick(layers.glass), bloom = pick(layers.bloom);
    return { key: slotKey(glass), glass: shownOpacity(glass), bloom: shownOpacity(bloom) };
  };
  const glassOf = (prefix) => layers.glass.children.find((s) => slotKey(s)?.startsWith(prefix));
  const mounted = () => ({ glass: layers.glass.children.map(slotKey), bloom: layers.bloom.children.map(slotKey) });
  return { c, layers, posts, worker, front, glassOf, mounted, fails: () => fails };
}

test('une fenêtre remontrée reste visible : la lune au deuxième soir, un titre rejoué, un retour arrière', async () => {
  const { c, layers, front } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  await finishFades();
  assert.deepEqual(front(), { key: 'moon@100x1', glass: 1, bloom: 1 }, '1. premier soir');
  const steps = [['A', 't:A@100x1', '2. un titre'], [null, 'moon@100x1', '3. deuxième soir'], ['A', 't:A@100x1', '4. titre rejoué'],
    ['B', 't:B@100x1', '5. titre suivant'], ['A', 't:A@100x1', '6. retour arrière']];
  for (const [id, key, label] of steps) {
    await c.show(id);
    await finishFades();
    assert.deepEqual(front(), { key, glass: 1, bloom: 1 }, label);
  }
  c.destroy();
});

test('redimensionnement : aucune peinture pour une taille intermédiaire, le prochain titre préparé à la fin', async () => {
  const { c, posts } = makeRose();
  c.resize(300);
  await c.show('A');
  c.prepare('N');
  await until(() => posts.includes('t:N@300x1'));
  posts.length = 0;
  // une fenêtre qu'on tire : une taille par image, et l'effet de Rose.tsx rappelle prepare
  for (let r = 301; r <= 330; r++) { c.resize(r); c.prepare('N'); await wait(4); }
  await until(() => posts.includes('t:N@330x1'));
  assert.deepEqual(posts.filter((k) => !k.endsWith('@330x1')), [], 'peintures pour une taille intermédiaire');
  assert.deepEqual([...posts].sort(), ['moon@330x1', 't:A@330x1', 't:N@330x1']);
  c.destroy();
});

test('éviction : une fenêtre en plein fondu de sortie n’est pas coupée', async () => {
  const { c, layers, glassOf } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  for (const id of ['X', 'Y', 'Z', 'X']) { await c.show(id); await finishFades(); }
  await c.show('W');                     // X s'efface…
  const x = glassOf('t:X@');
  assert.ok(x?.isConnected);
  await c.show('V');                     // …pendant qu'une nouvelle fenêtre est construite
  assert.ok(x.isConnected, 'X retirée en plein fondu');
  await finishFades();
  assert.ok(!x.isConnected, 'X retirée à la fin de son fondu');
  c.destroy();
});

test('la fenêtre préparée n’est jamais évincée : le titre suivant s’affiche sans nouvelle peinture', async () => {
  const { c, posts, layers, front } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  c.prepare('N');
  await until(() => layers.glass.children.some((s) => s.style.opacity === '.001'));   // montée invisible
  for (const id of ['A', 'B', 'C', 'D']) { await c.show(id); await finishFades(); }
  await c.show('N');
  await finishFades();
  assert.equal(posts.filter((k) => k.startsWith('t:N@')).length, 1, 'N repeinte');
  assert.deepEqual(front(), { key: 't:N@100x1', glass: 1, bloom: 1 });
  assert.equal(layers.glass.children.length, 1, 'fenêtre orpheline restée montée');
  c.destroy();
});

test('après destroy, une préparation en attente ne laisse aucune promesse pendante', async () => {
  const { c, layers } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  c.prepare('N');                        // la peinture part au prochain temps mort…
  c.destroy();                           // …qui arrive après la destruction
  await wait(30);
  assert.equal(c.pending, 0);
});

test('worker hors service (module introuvable) : les attentes se résolvent, les calques se vident, la pierre prend le relais', async (t) => {
  const warn = t.mock.method(console, 'warn', () => {});
  const { c, layers, worker, fails } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  worker.silent = true;                  // plus aucune réponse…
  const shown = c.show('A');
  assert.equal(c.pending, 1);
  worker.onerror({ type: 'error', message: 'chunk introuvable' });   // …et le worker tombe
  const late = await Promise.race([shown.then(() => 'résolue'), wait(200).then(() => 'pendante')]);
  assert.equal(late, 'résolue');
  assert.equal(fails(), 1, 'Rose.tsx prévenue une fois');
  assert.equal(warn.mock.callCount(), 1);
  assert.equal(c.pending, 0);
  assert.ok(worker.terminated);
  assert.deepEqual([layers.glass.children.length, layers.bloom.children.length], [0, 0]);
  c.destroy();                           // l'effet de Rose.tsx détruit encore : sans effet
  assert.equal(fails(), 1);
});

/* ── Sans à-coup : horloge simulée et compositeur factice ────────────────────────────────────────── */

/**
 * Relève les à-coups de la rosace, image par image (toutes les 10 ms de temps simulé) :
 * - une opacité ne bouge jamais de plus de 0,1 d'une image à l'autre (un fondu de 220 ms bouge d'environ 0,05) ;
 * - une fenêtre n'apparaît qu'invisible, et ne quitte la scène qu'invisible : effacée, ou couverte par les
 *   fenêtres au-dessus (la lune couvre tout, un titre couvre un titre ; les blooms, des halos, ne se couvrent pas) ;
 * - deux verres visibles ne changent jamais d'ordre.
 */
function compositor(layers) {
  let prev = null;                       // premier appel : l'état de départ, rien à comparer
  const jolts = [];
  const snap = () => {
    const now = new Map();
    for (const [name, layer] of [['glass', layers.glass], ['bloom', layers.bloom]]) {
      const stack = layer.children.map((el, i) => ({ el, i, z: zOf(el), op: el.rendered() })).sort((a, b) => a.z - b.z || a.i - b.i);
      stack.forEach((s, rank) => {
        let w = s.op;
        if (name === 'glass') for (const up of stack.slice(rank + 1)) if (up.el.dataset.kind === 'moon' || s.el.dataset.kind === 'song') w *= 1 - up.op;
        now.set(s.el, { name, key: slotKey(s.el), op: s.op, w, rank });
      });
    }
    return now;
  };
  const check = (t = performance.now()) => {
    const now = snap();
    if (!prev) { prev = now; return; }
    const at = (p) => `${Math.round(t)} ms, ${p.name} ${p.key}`;
    for (const [el, p] of prev) {
      const n = now.get(el);
      if (!n) { if (p.w > 0.05) jolts.push(`${at(p)} : retirée visible (${p.w.toFixed(2)})`); continue; }
      if (Math.abs(n.op - p.op) > 0.1) jolts.push(`${at(p)} : saute de ${p.op.toFixed(2)} à ${n.op.toFixed(2)}`);
    }
    for (const [el, n] of now) if (!prev.has(el) && n.op > 0.1) jolts.push(`${at(n)} : apparaît à ${n.op.toFixed(2)}`);
    for (const [a, pa] of prev) {
      for (const [b, pb] of prev) {
        const na = now.get(a), nb = now.get(b);
        if (a === b || pa.name !== 'glass' || pb.name !== 'glass' || !na || !nb) continue;
        if (Math.min(pa.op, pb.op, na.op, nb.op) <= 0.05) continue;
        if (pa.rank < pb.rank && na.rank > nb.rank) jolts.push(`${at(pa)} : passe devant ${pb.key}`);
      }
    }
    prev = now;
  };
  return { check, jolts };
}

/** Horloge simulée (setTimeout, Date, performance.now) : `run` la fait avancer par images de 10 ms. */
function simulate(t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
  t.mock.method(performance, 'now', () => Date.now());
  const flush = () => new Promise((r) => setImmediate(r));
  return async function run(ms, each) {
    for (let i = 0; i < ms; i += 10) {
      t.mock.timers.tick(10);
      await flush();
      for (const a of [...anims]) if (a.state === 'running' && performance.now() - a.t0 >= a.duration) a.finish();
      await flush();
      each?.(performance.now());
    }
  };
}

test('jour → nuit quand R change avec la scène (1366 × 768 : 291 puis 274) : le titre s’efface jusqu’au bout, sans à-coup', async (t) => {
  const run = simulate(t);
  const { c, layers, front, glassOf, mounted } = makeRose();
  c.resize(291);
  await run(1000);                       // premier soir
  void c.show('A');
  await run(1200);
  const song = glassOf('t:A@291'), comp = compositor(layers);
  comp.check();
  const t0 = performance.now();
  let gone = null;
  void c.show(null);                     // Stage : la nuit…
  c.resize(274);                         // …puis, au rendu suivant, le R de la nuit
  await run(2500, (now) => { comp.check(now); if (gone === null && !song.isConnected) gone = now - t0; });
  assert.deepEqual(comp.jolts, []);
  assert.ok(gone >= FADE_MS, `titre retiré ${gone} ms après la tombée de la nuit`);
  assert.deepEqual(front(), { key: 'moon@274x1', glass: 1, bloom: 1 });
  assert.deepEqual(mounted(), { glass: ['moon@274x1'], bloom: ['moon@274x1'] }, 'fenêtres de l’ancienne taille restées montées');
  c.destroy();
});

test('nuit → jour quand R change avec la scène, peinture lente : la rosace se rallume en entier, sans à-coup', async (t) => {
  const run = simulate(t);
  const { c, layers, front, glassOf, mounted } = makeRose({ paintMs: 300 });
  c.resize(274);
  await run(1500);
  const comp = compositor(layers);
  comp.check();
  c.resize(291);                         // Rose.tsx : l'effet de R passe avant celui du titre
  void c.show('A');
  await run(2500, comp.check);
  assert.deepEqual(comp.jolts, []);
  assert.equal(glassOf('t:A@291').anims[0].duration, FADE_MS, 'fondu d’entrée écourté par la repeinte');
  assert.deepEqual(front(), { key: 't:A@291x1', glass: 1, bloom: 1 });
  assert.deepEqual(mounted(), { glass: ['t:A@291x1'], bloom: ['t:A@291x1'] });
  c.destroy();
});

test('titres qui se bousculent, retour arrière, nuit et jour en plein fondu : aucun à-coup', async (t) => {
  const run = simulate(t);
  const { c, layers, front, mounted } = makeRose();
  c.resize(100);
  void c.show('A');
  await run(1500);
  const comp = compositor(layers);
  comp.check();
  for (const [id, ms] of [['B', 300], ['C', 200], ['B', 300], ['A', 100], [null, 400], ['D', 300], [null, 150], ['D', 2000]]) {
    void c.show(id);
    await run(ms, comp.check);
  }
  assert.deepEqual(comp.jolts, []);
  assert.deepEqual(front(), { key: 't:D@100x1', glass: 1, bloom: 1 });
  assert.deepEqual(mounted(), { glass: ['t:D@100x1'], bloom: ['t:D@100x1'] });
  c.destroy();
});

test('hold : pendant une cérémonie, le prochain titre attend pour être peint', async () => {
  const { c, posts, layers } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  c.hold(150);
  c.prepare('N');
  await wait(60);
  assert.ok(!posts.some((k) => k.startsWith('t:N@')), 'peinte pendant la cérémonie');
  await until(() => posts.some((k) => k.startsWith('t:N@')), 1500);
  c.destroy();
});

test('démarrage différé : taille, titre et prochain titre demandés avant start() partent au démarrage', async () => {
  const { c, posts, layers, front } = makeRose({ autoStart: false });
  c.resize(100);
  await c.show('A');
  c.prepare('B');
  await wait(20);
  assert.deepEqual(posts, [], 'rien avant start()');
  c.start();
  await until(() => posts.includes('t:A@100x1') && posts.includes('moon@100x1') && posts.some((k) => k.startsWith('t:B@')));
  await until(() => layers.glass.children.some((s) => slotKey(s) === 't:A@100x1'));
  await finishFades();
  assert.equal(front().key, 't:A@100x1');
  c.destroy();
});

// Étape 4, vérification dans Chrome : sur un navigateur froid, le premier temps mort venait avant que la première image
// soit présentée (worker 335 ms, first-contentful-paint 340 ms). La pierre attend désormais l'image présentée.
function paintHost({ painted = false, observer = true } = {}) {
  const h = { idles: [], timers: [], watching: 0 };
  h.painted = () => painted;
  h.onPaint = (cb) => { if (!observer) return null; h.watching++; h.paint = () => { painted = true; cb(); }; return () => { h.watching--; }; };
  h.idle = (cb) => { const e = { cb, live: true }; h.idles.push(e); return () => { e.live = false; }; };
  h.later = (cb, ms) => { const e = { cb, ms, live: true }; h.timers.push(e); return () => { e.live = false; }; };
  h.fire = (list) => { for (const e of list.splice(0)) if (e.live) e.cb(); };
  return h;
}

test('pierre différée : la première image présentée (first-contentful-paint), puis le premier temps mort', () => {
  const runs = [], h = paintHost();
  afterFirstPaint(() => runs.push('start'), h);
  assert.equal(h.idles.length, 0, 'aucun temps mort guetté avant l’image présentée');
  assert.equal(h.watching, 1);
  h.paint();
  assert.equal(h.watching, 0, 'l’observateur est débranché');
  assert.equal(h.idles.length, 1);
  assert.deepEqual(runs, []);
  h.fire(h.idles);
  assert.deepEqual(runs, ['start']);
  h.fire(h.timers);
  assert.deepEqual(runs, ['start'], 'le filet ne relance pas');
});

test('pierre différée : déjà présentée, ou sans observateur, au premier temps mort ; onglet caché, filet de 3 s ; annulée, rien', () => {
  for (const o of [{ painted: true }, { observer: false }]) {
    const runs = [], h = paintHost(o);
    afterFirstPaint(() => runs.push('start'), h);
    assert.equal(h.watching, 0);
    assert.equal(h.idles.length, 1, JSON.stringify(o));
    h.fire(h.idles);
    assert.deepEqual(runs, ['start']);
  }
  const hidden = paintHost(), runs = [];
  afterFirstPaint(() => runs.push('start'), hidden);
  assert.deepEqual(hidden.timers.map((e) => e.ms), [FIRST_PAINT_WAIT_MS]);
  assert.equal(FIRST_PAINT_WAIT_MS, 3000);
  hidden.fire(hidden.timers);
  assert.equal(hidden.watching, 0);
  hidden.fire(hidden.idles);
  assert.deepEqual(runs, ['start']);
  const gone = paintHost(), none = [];
  const cancel = afterFirstPaint(() => none.push('start'), gone);
  cancel();
  assert.equal(gone.watching, 0);
  gone.fire(gone.timers); gone.fire(gone.idles);
  assert.deepEqual(none, [], 'démonté avant l’image : rien ne démarre');
  const late = paintHost({ painted: true }), after = [];
  afterFirstPaint(() => after.push('start'), late)();
  late.fire(late.idles);
  assert.deepEqual(after, [], 'démonté avant le temps mort : rien ne démarre');
});

// Revue C18 : la fenêtre tirée sur un écran plus dense (ou un zoom quand R est borné) garde R ; seule la densité change.
test('densité de pixels : un changement seul (même R) repeint à la nouvelle densité', async () => {
  const { c, posts } = makeRose();
  c.resize(100);
  await until(() => posts.includes('moon@100x1'));
  window.devicePixelRatio = 2;
  try {
    c.resize(100);                       // ce que l'abonnement de Rose.tsx (watchDpr) rappelle
    await wait(RESIZE_DEBOUNCE_MS + 20);
    await until(() => posts.includes('moon@100x2'));
  } finally { window.devicePixelRatio = 1; c.destroy(); }
});

test('watchDpr : prévenu quand la densité change, réarmé sur la nouvelle, désabonné à la fin', () => {
  const queries = [];
  const mm = (q) => {
    const mq = { q, ls: new Set(), addEventListener(_, fn) { this.ls.add(fn); }, removeEventListener(_, fn) { this.ls.delete(fn); } };
    queries.push(mq);
    return mq;
  };
  let calls = 0;
  try {
    const stop = watchDpr(() => { calls++; }, mm);
    const around = (d) => `(min-resolution: ${d - 0.001}dppx) and (max-resolution: ${d + 0.001}dppx)`;
    assert.deepEqual(queries.map((m) => m.q), [around(1)]);
    window.devicePixelRatio = 2;
    for (const fn of [...queries[0].ls]) fn();
    assert.equal(calls, 1);
    assert.deepEqual(queries.map((m) => m.q), [around(1), around(2)], 'réarmé sur la nouvelle densité');
    assert.equal(queries[0].ls.size, 0, 'l’ancienne requête n’écoute plus');
    stop();
    assert.equal(queries[1].ls.size, 0, 'désabonné');
  } finally { window.devicePixelRatio = 1; }
  assert.doesNotThrow(() => watchDpr(() => {}, undefined)(), 'sans matchMedia (Node) : rien');
});
