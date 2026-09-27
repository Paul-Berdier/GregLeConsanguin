import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { roseKey, keyFits, isMoonKey, evictable, KEEP_OTHERS, RoseClient } = await loadTs('../src/lib/rose/client.ts');

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
  assert.deepEqual(evictable(keys, ['t:a@1x1', 't:e@1x1']), ['t:b@1x1']);
  assert.deepEqual(evictable(['moon@1x1', 't:a@1x1'], ['t:a@1x1']), []);
});

/* ── Cycle de vie des fenêtres : un DOM et un worker factices ──────────────────────────────────────
   Le faux DOM reprend les règles des Web Animations relevées dans Chrome (review de la tâche 2) :
   - une animation finie en fill 'forwards' continue de s'appliquer, même après un détachement ;
   - une animation finie en fill 'backwards' ne s'applique plus ;
   - la dernière animation créée qui s'applique l'emporte, sinon le style en ligne ;
   - un élément détaché ne rend aucune animation par getAnimations(). */
const anims = [];
class FakeAnim {
  constructor(frames, opts) {
    this.to = Number(frames.at(-1).opacity);
    this.fill = opts.fill ?? 'none';
    this.state = 'running';
    this.finished = new Promise((res, rej) => { this.res = res; this.rej = rej; });
    this.finished.catch(() => {});
    anims.push(this);
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
}
globalThis.window = { devicePixelRatio: 1 };
globalThis.document = { createElement: (tag) => new El(tag), documentElement: new El('html', true) };

/** Opacité rendue d'une fenêtre, une fois tous les fondus terminés. */
function shownOpacity(el) {
  assert.ok(!el.anims.some((a) => a.state === 'running'), 'un fondu tourne encore');
  let v = el.style.opacity === '' ? 1 : Number(el.style.opacity);
  for (const a of el.anims) if (a.applies) v = a.to;
  return v;
}
const slotKey = (slot) => slot.children[0]?.bitmap?.key;
const wait = (ms = 0) => new Promise((r) => setTimeout(r, ms));
async function finishFades() { for (const a of anims) a.finish(); await wait(); }
async function until(cond, ms = 3000) {
  const t0 = Date.now();
  while (!cond()) { if (Date.now() - t0 > ms) assert.fail('délai dépassé'); await wait(5); }
}

function makeRose() {
  const layers = { bloom: new El('div', true), glass: new El('div', true) };
  const c = new RoseClient(layers);
  const posts = [];
  const bitmap = (key, w, h) => ({ key, width: w, height: h, close() {} });
  // start() sans vrai Worker : `new URL(…, import.meta.url)` n'a pas d'URL de fichier en mode transpilé
  c.worker = {
    postMessage(m) {
      if (m.type !== 'paint') return;
      posts.push(m.key);
      const moon = !m.id, W = Math.round(2.12 * m.R * m.dpr);
      setTimeout(() => c.onMessage({
        type: 'painted', key: m.key, pal: { mode: moon ? 'moon' : 'color', lum: moon ? [180, 196, 226] : [200, 100, 50] },
        win: bitmap(m.key, W, W), bloom: bitmap(m.key, W, W),
        ring: moon ? null : bitmap(m.key, W, 40), head: moon ? null : bitmap(m.key, W, 40), ms: [0, 0],
      }), 1);
    },
    terminate() {},
  };
  /** La fenêtre au premier plan (z-index 2) des deux calques : elle doit être celle voulue, et visible. */
  const front = () => {
    const pick = (layer) => {
      const top = layer.children.filter((s) => s.style.zIndex === '2');
      assert.equal(top.length, 1, 'une seule fenêtre au premier plan');
      return top[0];
    };
    const glass = pick(layers.glass), bloom = pick(layers.bloom);
    return { key: slotKey(glass), glass: shownOpacity(glass), bloom: shownOpacity(bloom) };
  };
  const glassOf = (prefix) => layers.glass.children.find((s) => slotKey(s)?.startsWith(prefix));
  return { c, layers, posts, front, glassOf };
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
  assert.equal(c.waits.size, 0);
});
