'use client';

import { useSyncExternalStore } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { extractVideoId } from '@/lib/format';
import { reducedMotion, watchReducedMotion } from '@/lib/motion';
import { FLIGHT_MS, NEXT, boxOf, crownMode, crownPlan, flightFrames, kingOrders, visibleIn } from '@/lib/stage/coronation';
import type { Box, CrownMode, CrownPlan } from '@/lib/stage/coronation';
import { parseTitle } from '@/lib/titles';
import { speak } from '@/components/Herald/store';
import { tx } from '@/theme/copy.extra';
import { decodedPosters } from './Portal';

/**
 * Le chef de cérémonie (DESIGN §5, §8, §12.6), hors de React : au changement de titre du store, il reprend l'ordre du Roi,
 * choisit le mode et mesure la source AVANT le rendu (la ligne est encore à sa place), publie la cérémonie (useCeremony),
 * puis fait voler la pochette à l'image suivante. NowPlaying, Portal et Rose suivent son plan (lib/stage/coronation.ts).
 * Le fantôme porte l'image du titre, jamais rien du Roi ni de Greg. tests/choreo-stage.test.mjs.
 */
export type Ceremony = { seq: number; key: string; mode: CrownMode; plan: CrownPlan; at: number; landed: boolean };
type Source = { im: HTMLElement; img: HTMLImageElement; from: Box; to: Box };

let current: Ceremony | null = null, seq = 0, lastAt = -Infinity;
let ghost: HTMLDivElement | null = null, flight: Animation | null = null, hiddenIm: HTMLElement | null = null;
const listeners = new Set<() => void>();
const set = (c: Ceremony | null): void => { current = c; for (const l of listeners) l(); };

function ghostEl(): HTMLDivElement {
  if (ghost?.isConnected) return ghost;
  ghost = document.createElement('div');
  ghost.className = 'ghost';
  ghost.setAttribute('aria-hidden', 'true');
  document.body.appendChild(ghost);
  return ghost;
}

/** Vol fini ou interrompu : le fantôme s'efface, la pochette cachée revient (un refus peut ramener la ligne). */
function ground(): void {
  flight?.cancel(); flight = null;
  if (ghost) ghost.style.opacity = '0';
  hiddenIm?.style.removeProperty('visibility'); hiddenIm = null;
}

/** Vol coupé avant l'atterrissage (mouvement réduit demandé en direct, débranchement) : la cérémonie se pose, le poster retenu paraît. */
function abort(): void {
  ground();
  if (current && !current.landed) set({ ...current, landed: true });
}

/** Pochette de la ligne `key`, visible à moitié dans la file et dans la fenêtre, la scène visible aussi (une colonne). */
function source(key: string): Source | null {
  const pane = document.getElementById('pane-queue');
  if (!pane || pane.getAttribute('aria-hidden') === 'true' || document.hidden) return null;
  const im = pane.querySelector<HTMLElement>(`.qcontent > .qlist > .row[data-key="${CSS.escape(key)}"] .thumb > .im`);
  const img = im?.querySelector('img'), scroller = pane.querySelector<HTMLElement>('.scroller');
  const video = document.querySelector<HTMLElement>('.stage .video');
  if (!im || !img || !scroller || !video) return null;
  const from = boxOf(im), to = boxOf(video), vp = { left: 0, top: 0, width: innerWidth, height: innerHeight };
  return visibleIn(from, boxOf(scroller)) && visibleIn(from, vp) && visibleIn(to, vp) ? { im, img, from, to } : null;
}

function land(c: Ceremony): void {
  if (current?.seq !== c.seq) return;
  set({ ...c, landed: true });
  // le fantôme se lève quand le vrai poster est décodé dessous (600 ms au plus)
  const poster = document.querySelector<HTMLImageElement>('.stage .video .poster:not([data-leaving])');
  const lift = (): void => { requestAnimationFrame(() => { if (current?.seq === c.seq) ground(); }); };
  Promise.race([poster?.decode?.() ?? Promise.resolve(), new Promise((r) => setTimeout(r, 600))]).then(lift, lift);
}

/** poster : déjà décodé (le prochain titre, Portal.tsx) : net à l'arrivée, sans mise au point (DESIGN §12.6). */
function fly(c: Ceremony, src: Source, poster: string | null): void {
  const g = ghostEl();
  g.style.backgroundImage = `url("${poster || src.img.currentSrc || src.img.src}")`;
  g.style.width = `${src.to.width}px`;
  g.style.height = `${src.to.height}px`;
  src.im.style.visibility = 'hidden';
  hiddenIm = src.im;
  requestAnimationFrame(() => {
    if (current?.seq !== c.seq) return;
    g.style.opacity = '1';
    flight = g.animate(flightFrames(src.from, src.to), { duration: FLIGHT_MS, easing: 'linear', fill: 'forwards' });
    flight.finished.then(() => land(c), () => {});
  });
}

/**
 * quiet : le premier état reçu au chargement (la page montre le titre, ce n'est pas un changement). Sinon, annoncé
 * sauf un ordre nommé : « jouer maintenant » a son toast après l'atterrissage, un retour après refus (noté par
 * usePlayer.ts) suit l'erreur que le Héraut vient de dire.
 */
function begin(key: string, prevNext: string | null, fromNight: boolean, title: string, id: string | null, quiet: boolean): void {
  ground();
  const now = performance.now(), order = kingOrders.take(key, prevNext, now), reduced = reducedMotion();
  const src = !reduced && !fromNight && order?.via === 'pointer' ? source(key) : null;
  const mode = crownMode({ via: order?.via ?? null, sinceLast: now - lastAt, reduced, canFly: !!src, fromNight });
  lastAt = now;
  const c: Ceremony = { seq: ++seq, key, mode, plan: crownPlan(mode), at: now, landed: mode !== 'flight' };
  set(c);
  if (mode === 'flight' && src) fly(c, src, id ? decodedPosters.get(id) ?? null : null);
  if (!quiet && (!order || order.target === NEXT)) speak(tx('a11y.nowPlaying', { title }));
}

/** Branché une fois (Stage.tsx) ; rend de quoi se débrancher. */
export function startCoronation(): () => void {
  // la vue d'avant le premier état reçu (store vide) : en sortir n'est pas un changement de titre
  let unloaded: unknown = useStore.getState().player;
  const unsub = useStore.subscribe((s, prev) => {
    const boot = prev.player === unloaded;
    if (s.player !== prev.player) unloaded = null;
    const t = s.player.current, k = t?.key || null, pk = prev.player.current?.key || null;
    if (k === pk) return;
    if (!t || !k) { ground(); set(null); return; }
    begin(k, prev.player.queue[0]?.key ?? null, !pk, parseTitle(t.title, t.artist).song || t.title, extractVideoId(t.url), boot);
  });
  const unwatch = watchReducedMotion((r) => { if (r) abort(); });
  // premier vol aussi fluide que le dixième : le fantôme est créé et composé pendant un temps mort
  const warm = (): void => { ghostEl().animate([{ transform: 'translate(-200vw, 0) scale(.2)' }, { transform: 'translate(-200vw, 0) scale(.3)' }], { duration: 32 }); };
  const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void };
  const idle = w.requestIdleCallback ? w.requestIdleCallback(warm, { timeout: 2000 }) : window.setTimeout(warm, 500);
  return () => {
    if (w.cancelIdleCallback) w.cancelIdleCallback(idle); else clearTimeout(idle);
    // débranché en plein vol : la cérémonie se pose, le poster retenu paraît
    unsub(); unwatch(); abort();
  };
}

const subscribe = (fn: () => void): (() => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
/** La cérémonie en cours (null : la nuit). */
export function useCeremony(): Ceremony | null { return useSyncExternalStore(subscribe, () => current, () => null); }
