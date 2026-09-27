/**
 * Côté fil principal de la rosace : pilote le worker et échange des canevas `bitmaprenderer`.
 * Repris de l'objet `Rose` (proto-gothique/work/refine/src/app.js, lignes 181–307).
 * - Une fenêtre est peinte une fois par titre et par taille, dans le worker.
 * - La fenêtre du PROCHAIN titre est préparée pendant les temps morts, puis montée invisible
 *   (textures déjà envoyées au GPU le moment venu).
 * - Tant qu'une fenêtre n'est pas prête, l'ancienne reste affichée.
 * - Pendant un redimensionnement, rien n'est peint d'avance : la préparation attend la taille finale.
 * Sans import runtime : les fonctions exportées sont testées (tests/rose-client.test.mjs).
 */
import type { RoseIn, RoseOut } from './rose.worker';
import type { RGB } from './palette';

export const RING_TO = -0.2;          // bas du recadrage de l'anneau (même valeur que lib/stage/layout.ts)
export const READY_MAX = 3;           // fenêtres peintes pas encore montées
export const KEEP_OTHERS = 2;         // fenêtres montées gardées en plus de la lune et de l'affichée
export const STONE_URL = '/gothique/stone-rose-2048.webp';
export const FADE_MS = 900;           // --dur-ambient : la rosace se rallume
export const FIRST_FADE_MS = 700;
export const RESIZE_FADE_MS = 220;
export const RESIZE_DEBOUNCE_MS = 200;

export type Painted = Extract<RoseOut, { type: 'painted' }>;
// exit : le fondu de sortie en cours (null sinon) ; tant qu'il tourne, la fenêtre n'est jamais évincée
type Slot = { key: string; lum: RGB; bloom: HTMLDivElement; glass: HTMLDivElement; exit: Animation | null };
export type RoseLayers = { bloom: HTMLElement; glass: HTMLElement };

/** Clé d'une fenêtre : un titre (ou la lune) à une taille et une densité de pixels. */
export const roseKey = (id: string | null, R: number, dpr: number): string => `${id ? `t:${id}` : 'moon'}@${R}x${dpr}`;
export const keyFits = (key: string, R: number, dpr: number): boolean => key.endsWith(`@${R}x${dpr}`);
export const isMoonKey = (key: string): boolean => key.startsWith('moon@');

/** Fenêtres montées à retirer : ni la lune, ni celles à garder, au-delà des `max` plus récentes. */
export function evictable(keys: string[], keep: (string | null | undefined)[], max = KEEP_OTHERS): string[] {
  const others = keys.filter((k) => !isMoonKey(k) && !keep.includes(k));
  return others.slice(0, Math.max(0, others.length - max));
}

/** La lumière du morceau, posée sur :root (--lumiere et --lumiere-rgb, tokens.css). */
export function setLumiere([r, g, b]: RGB, el: HTMLElement = document.documentElement): void {
  el.style.setProperty('--lumiere-rgb', `${r} ${g} ${b}`);
  el.style.setProperty('--lumiere', `rgb(${r} ${g} ${b})`);
}

/** Moteur capable de peindre hors du fil principal ? Sinon, rosace statique (spec §7). */
export function roseSupported(): boolean {
  return typeof Worker !== 'undefined' && typeof OffscreenCanvas !== 'undefined' && typeof createImageBitmap === 'function';
}

const idle = (fn: () => void): void => {
  const ric = (globalThis as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
  if (ric) ric(fn, { timeout: 1500 }); else setTimeout(fn, 1);
};

export class RoseClient {
  private layers: RoseLayers;
  private worker: Worker | null = null;
  private R = 0;
  private dpr = 1;
  private gen = 0;
  private want: string | null = null;              // titre voulu à l'écran (null = clair de lune)
  private next: string | null = null;              // prochain titre, peint d'avance (prepare)
  private cur: Slot | null = null;
  private pre: Slot | null = null;
  private built = new Map<string, Slot>();
  private ready = new Map<string, Painted>();
  private waits = new Map<string, { p: Promise<Painted | null>; res: (d: Painted | null) => void }>();
  private busyUntil = 0;
  private resizeTimer: ReturnType<typeof setTimeout> | undefined;
  private resizing = false;
  private dead = false;

  constructor(layers: RoseLayers) { this.layers = layers; }

  start(): void {
    if (this.worker || this.dead) return;
    this.worker = new Worker(new URL('./rose.worker.ts', import.meta.url), { type: 'module' });
    this.worker.onmessage = (e: MessageEvent<RoseOut>) => this.onMessage(e.data);
    this.post({ type: 'init', stoneUrl: new URL(STONE_URL, location.origin).href });
  }

  destroy(): void {
    this.dead = true;
    clearTimeout(this.resizeTimer);
    this.worker?.terminate(); this.worker = null;
    for (const d of this.ready.values()) this.close(d);
    this.ready.clear();
    for (const w of this.waits.values()) w.res(null);
    this.waits.clear();
    for (const s of this.built.values()) this.unmount(s);
    this.built.clear(); this.cur = null; this.pre = null;
  }

  /**
   * Nouvelle taille : la fenêtre affichée est mise à l'échelle par la CSS jusqu'à la nouvelle peinture.
   * R change jusqu'à une fois par image quand on tire la fenêtre : la lune, l'affichée et le prochain titre
   * ne sont repeints qu'une fois la taille posée (comme le prototype).
   */
  resize(R: number): void {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (!R || (R === this.R && dpr === this.dpr)) return;
    const first = !this.R;
    this.R = R; this.dpr = dpr;
    for (const d of this.ready.values()) this.close(d);
    this.ready.clear();
    for (const [k, s] of this.built) if (s !== this.cur) { this.unmount(s); this.built.delete(k); }
    this.pre = null;
    this.resizing = true;
    clearTimeout(this.resizeTimer);
    this.resizeTimer = setTimeout(() => {
      this.resizing = false;
      void this.request(null).then((d) => { if (d) this.build(d); });   // la lune, prête d'avance
      void this.show(this.want, first ? 0 : RESIZE_FADE_MS);
      this.prepare(this.next);
    }, first ? 0 : RESIZE_DEBOUNCE_MS);
  }

  /** Affiche la fenêtre d'un titre (null = clair de lune). L'ancienne reste tant que la nouvelle n'est pas peinte. */
  async show(id: string | null, fade = FADE_MS): Promise<void> {
    this.want = id;
    if (!this.R || !this.worker) return;
    const key = roseKey(id, this.R, this.dpr), my = ++this.gen;
    if (this.cur?.key === key) { setLumiere(this.cur.lum); return; }
    let slot = this.built.get(key);
    if (!slot) {
      const d = await this.request(id);
      if (my !== this.gen || !d || this.dead) return;
      slot = this.build(d);
    }
    if (my !== this.gen) return;
    this.swap(slot, fade);
  }

  /**
   * Peint d'avance la fenêtre du prochain titre, jamais pendant une cérémonie ni un redimensionnement
   * (resize la prépare à la taille finale). Le titre est retenu même sans taille : la première mesure le prépare.
   */
  prepare(id: string | null): void {
    this.next = id;
    const go = (): void => {
      if (!id || this.next !== id || this.dead || this.resizing || !this.R || !this.worker) return;
      const key = roseKey(id, this.R, this.dpr);
      if (this.built.has(key) || this.ready.has(key) || this.waits.has(key)) return;
      const wait = this.busyUntil - performance.now();
      if (wait > 0) { setTimeout(go, wait + 30); return; }
      idle(() => { if (this.next === id && !this.dead && !this.resizing) void this.request(id); });
    };
    go();
  }

  private post(m: RoseIn): void { this.worker?.postMessage(m); }

  private request(id: string | null): Promise<Painted | null> {
    if (this.dead) return Promise.resolve(null);
    const key = roseKey(id, this.R, this.dpr);
    const ready = this.ready.get(key);
    if (ready) return Promise.resolve(ready);
    const waiting = this.waits.get(key);
    if (waiting) return waiting.p;
    let res!: (d: Painted | null) => void;
    const p = new Promise<Painted | null>((r) => { res = r; });
    this.waits.set(key, { p, res });
    this.post({ type: 'paint', key, id, R: this.R, dpr: this.dpr, ringTo: RING_TO });
    return p;
  }

  private onMessage(m: RoseOut): void {
    const w = this.waits.get(m.key);
    this.waits.delete(m.key);
    if (m.type === 'failed') { console.warn('rosace : peinture impossible', m.error); w?.res(null); return; }
    if (this.dead || !keyFits(m.key, this.R, this.dpr)) { this.close(m); w?.res(null); return; }   // peinte pour une ancienne taille
    this.ready.set(m.key, m);
    while (this.ready.size > READY_MAX) {
      const [k, d] = this.ready.entries().next().value as [string, Painted];
      this.ready.delete(k); this.close(d);
    }
    w?.res(m);
    if (!isMoonKey(m.key)) this.premount(m.key);
  }

  /** Monte une fenêtre prête, invisible, pendant un temps mort : ses textures partent au GPU avant la cérémonie. */
  private premount(key: string): void {
    idle(() => {
      const d = this.ready.get(key);
      if (!d || this.dead || this.cur?.key === key || performance.now() < this.busyUntil) return;
      const slot = this.build(d);
      if (this.pre && this.pre !== this.cur && this.pre !== slot) this.unmount(this.pre);
      this.pre = slot;
      for (const el of [slot.bloom, slot.glass]) { el.style.opacity = '.001'; el.style.zIndex = '0'; }
      this.layers.bloom.appendChild(slot.bloom);
      this.layers.glass.appendChild(slot.glass);
    });
  }

  private close(d: Painted): void { for (const b of [d.win, d.bloom, d.ring, d.head]) b?.close(); }

  /** Arrête les fondus d'une fenêtre montée (un élément détaché ne rend aucune animation). */
  private stopFades(s: Slot): void { for (const el of [s.bloom, s.glass]) for (const a of el.getAnimations()) a.cancel(); }

  /** Démonte une fenêtre sans fondu resté accroché (il la rendrait invisible si on la remontait). */
  private unmount(s: Slot): void { this.stopFades(s); s.exit = null; s.bloom.remove(); s.glass.remove(); }

  private build(d: Painted): Slot {
    const known = this.built.get(d.key);
    if (known) return known;
    this.ready.delete(d.key);
    const cv = (bm: ImageBitmap, cls: string): HTMLCanvasElement => {
      const c = document.createElement('canvas');
      c.className = cls; c.width = bm.width; c.height = bm.height;
      const r = c.getContext('bitmaprenderer');
      if (r) r.transferFromImageBitmap(bm); else { c.getContext('2d')?.drawImage(bm, 0, 0); bm.close(); }
      return c;
    };
    const bloom = document.createElement('div');
    bloom.className = 'slot'; bloom.appendChild(cv(d.bloom, 'bloom'));
    const glass = document.createElement('div');
    glass.className = 'slot'; glass.dataset.kind = isMoonKey(d.key) ? 'moon' : 'song';
    glass.appendChild(cv(d.win, 'win'));
    if (d.ring && d.head) glass.append(cv(d.ring, 'ring'), cv(d.head, 'head'));
    const slot: Slot = { key: d.key, lum: d.pal.lum, bloom, glass, exit: null };
    this.built.set(d.key, slot);
    // on garde : la lune, l'affichée, la nouvelle, la préparée (montée invisible), celles qui s'effacent encore,
    // et les deux plus récentes (retour arrière, annulation)
    const keep = [this.cur?.key, d.key, this.pre?.key];
    for (const s of this.built.values()) if (s.exit) keep.push(s.key);
    for (const k of evictable([...this.built.keys()], keep)) {
      const s = this.built.get(k);
      if (s) this.unmount(s);
      this.built.delete(k);
    }
    return slot;
  }

  private swap(slot: Slot, fade: number): void {
    const old = this.cur;
    this.cur = slot;
    if (this.pre === slot) this.pre = null;
    if (!slot.glass.isConnected) { this.layers.bloom.appendChild(slot.bloom); this.layers.glass.appendChild(slot.glass); }
    // Une fenêtre remontrée (la lune au deuxième soir, un titre rejoué, un retour arrière) garde son fondu de
    // sortie (fill 'forwards', opacité 0), qui l'emporterait de nouveau à la fin du fondu d'entrée : on l'annule,
    // APRÈS le rattachement (détaché, un élément ne rend aucune animation).
    this.stopFades(slot);
    slot.exit = null;
    for (const el of [slot.bloom, slot.glass]) { el.style.opacity = ''; el.style.zIndex = '2'; }
    if (old) for (const el of [old.bloom, old.glass]) el.style.zIndex = '1';
    setLumiere(slot.lum);   // instantané : caché dans le fondu de la rosace (DESIGN §5, écart 4)
    if (fade && old) {
      this.busyUntil = performance.now() + fade + 60;
      // Jour ↔ nuit : la lune (rose entière) et un titre (rose coupée au linteau) ne se recouvrent pas,
      // l'ancienne s'efface donc aussi ; entre deux titres, elle reste opaque dessous (pas de creux de lumière).
      const out = old.glass.dataset.kind !== slot.glass.dataset.kind ? 0 : 1;
      for (const el of [slot.bloom, slot.glass]) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: fade, easing: 'ease', fill: 'backwards' });
      old.bloom.animate([{ opacity: 1 }, { opacity: 0 }], { duration: fade, easing: 'ease', fill: 'forwards' });
      const exit = old.glass.animate([{ opacity: 1 }, { opacity: out }], { duration: fade, easing: 'ease', fill: 'forwards' });
      old.exit = exit;
      // ce fondu-là seulement : remontrée entre-temps (fondu annulé) ou repartie dans un autre fondu, elle reste
      const done = (): void => { if (old.exit === exit && old !== this.cur) this.unmount(old); };
      exit.finished.then(done, done);
    } else if (!old) {
      for (const el of [slot.bloom, slot.glass]) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FIRST_FADE_MS, easing: 'ease', fill: 'backwards' });
    } else this.unmount(old);
  }
}
