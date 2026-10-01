'use client';

import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent, RefObject } from 'react';
import {
  DRAG_THRESHOLD, autoScrollSpeed, clampOffset, dropAnchor, dropDuration, shiftFor, targetIndex,
} from '@/lib/queue/drag';
import { DUR, EASE, FLASH_MS, SHAKE_MS, SHAKE_X, SPRING, reducedMotion } from '@/lib/motion';

type Drag = {
  li: HTMLElement; pid: number; y0: number; started: boolean;
  rows: HTMLElement[]; from: number; to: number; tops: number[]; step: number; grab: number;
  y: number; py: number | null; raf: number;
};

export type QueueDragOptions = {
  listRef: RefObject<HTMLElement>;
  scrollRef: RefObject<HTMLElement>;
  /** Signature de l'ordre affiché : au rendu du nouvel ordre, les décalages du glisser s'effacent. */
  order: string;
  /** Saisie : les états reçus attendent le dépôt (usePlayer.setDragging(true)). */
  onLift: () => void;
  /** Fin du glisser, déposé ou non (setDragging(false)). */
  onEnd: () => void;
  /** Dépôt de `key` devant `beforeKey` (null : en fin de file) ; false = refusé (retour en arrière déjà fait). */
  onDrop: (key: string, beforeKey: string | null) => Promise<boolean>;
  /** useFlip : le prochain rendu remesure sans animer (la ligne est déjà dessinée à sa place). */
  freeze: () => void;
  /** Accalmie de la liste (clics ignorés 400 ms ou jusqu'à 3 px de mouvement). */
  settle: () => void;
};

const rowsOf = (list: HTMLElement): HTMLElement[] => Array.from(list.children)
  .filter((el): el is HTMLElement => el instanceof HTMLElement && !!el.dataset.key && el.dataset.leaving == null);

/** Éclair après le dépôt (Atlassian) : la ligne est à sa place. */
export function flashRow(li: HTMLElement | null | undefined): void {
  li?.querySelector('.flash')?.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FLASH_MS, easing: EASE.flash });
}

/** Refus du serveur : la ligne est déjà revenue (FLIP) ; secousse à 40 % du ressort, ou anneau rouge en mouvement réduit. */
export function refuseRow(li: HTMLElement | null | undefined): void {
  if (!li) return;
  if (reducedMotion()) { li.classList.add('refused'); setTimeout(() => li.classList.remove('refused'), 600); return; }
  setTimeout(() => {
    li.querySelector('.card')?.animate(SHAKE_X.map((x, i) => ({ transform: `translateX(${x}px)`, offset: i / (SHAKE_X.length - 1) })),
      { duration: SHAKE_MS, easing: 'ease-out' });
  }, SPRING.move.dur * 0.4);
}

/**
 * Glisser pour réordonner (DESIGN §5, §12.5 ; motion.md §6.8 ; portage de app.js, lignes 881–957) :
 * - depuis la poignée ou la pochette, après 4 px ; le corps de la ligne ne glisse jamais ;
 * - la ligne suit le pointeur 1:1 (élastique aux bords), les autres s'écartent (--dur-shift), défilement
 *   automatique près des bords ; Échap ou pointercancel : retour à sa place (×0,6) ;
 * - dépôt : la ligne rejoint sa place (330 → 550 ms, --ease-drop), l'ordre optimiste est rendu et les
 *   décalages s'effacent dans le même rendu, puis l'éclair ; un refus revient en arrière et secoue la ligne.
 * Mouvement réduit : la ligne suit toujours le pointeur ; le reste est instantané.
 */
export function useQueueDrag(o: QueueDragOptions): {
  onPointerDown: (e: ReactPointerEvent) => void;
  /** Vrai une fois juste après un glisser : le clic qui le termine n'est pas une sélection. */
  swallowClick: () => boolean;
} {
  const opts = useRef(o);
  opts.current = o;
  const drag = useRef<Drag | null>(null);
  const pendingClear = useRef<(() => void) | null>(null);
  const swallow = useRef(false);

  useLayoutEffect(() => {
    pendingClear.current?.();
    pendingClear.current = null;
  }, [o.order]);

  const follow = useCallback((d: Drag) => {
    const list = opts.current.listRef.current;
    if (!list || d.py == null) return;
    const y = clampOffset(d.py - d.grab - list.getBoundingClientRect().top - d.tops[d.from], d.tops, d.from);
    d.y = y;
    d.li.style.transform = `translateY(${y}px)`;
    const to = targetIndex(d.tops, d.from, y, d.step);
    if (to === d.to) return;
    d.to = to;
    d.rows.forEach((r, i) => {
      if (r === d.li) return;
      const s = shiftFor(i, d.from, to, d.step);
      r.style.transform = s ? `translateY(${s}px)` : '';
    });
  }, []);

  const begin = useCallback((d: Drag, e: PointerEvent): boolean => {
    const list = opts.current.listRef.current, sc = opts.current.scrollRef.current;
    if (!list || !sc) return false;
    const rows = rowsOf(list);
    const from = rows.indexOf(d.li);
    if (from < 0) return false;
    for (const r of rows) for (const a of r.getAnimations()) if (a.id === 'flip') a.finish();
    const tops = rows.map((r) => r.offsetTop);
    Object.assign(d, {
      started: true, rows, from, to: from, tops, y: 0,
      step: rows.length > 1 ? tops[1] - tops[0] : d.li.offsetHeight + 2,
      grab: e.clientY - d.li.getBoundingClientRect().top,
    });
    d.li.setPointerCapture?.(d.pid);
    d.li.classList.add('dragging');
    document.body.classList.add('is-dragging');
    const reduce = reducedMotion();
    for (const r of rows) if (r !== d.li) r.style.transition = reduce ? 'none' : `transform ${DUR.shift}ms ${EASE.shift}`;
    opts.current.onLift();
    const tick = () => {
      const dd = drag.current;
      if (!dd?.started) return;
      if (dd.py != null) {
        const b = sc.getBoundingClientRect();
        const v = autoScrollSpeed(dd.py, b.top, b.bottom);
        if (v) { sc.scrollTop += v; follow(dd); }
      }
      dd.raf = requestAnimationFrame(tick);
    };
    d.raf = requestAnimationFrame(tick);
    return true;
  }, [follow]);

  const end = useCallback((cancel: boolean) => {
    const d = drag.current;
    drag.current = null;
    if (!d?.started) return;
    cancelAnimationFrame(d.raf);
    swallow.current = true;
    setTimeout(() => { swallow.current = false; }, 0);
    document.body.classList.remove('is-dragging');
    d.li.classList.remove('dragging');
    const to = cancel ? d.from : d.to;
    const targetY = d.tops[to] - d.tops[d.from];
    if (cancel) for (const r of d.rows) if (r !== d.li) r.style.transform = '';
    const dur = reducedMotion() ? 0 : dropDuration(targetY - d.y, cancel);
    const a = d.li.animate([{ transform: `translateY(${d.y}px)` }, { transform: `translateY(${targetY}px)` }],
      { duration: dur, easing: EASE.drop, fill: 'forwards' });
    d.li.style.transform = '';
    const clear = () => {
      a.cancel();
      for (const r of d.rows) { r.style.transition = 'none'; r.style.transform = ''; }
      void d.li.offsetHeight;
      for (const r of d.rows) r.style.transition = '';
    };
    const finish = () => {
      const o2 = opts.current;
      if (cancel || to === d.from) { clear(); o2.onEnd(); return; }
      const keys = d.rows.map((r) => r.dataset.key || '');
      const key = d.li.dataset.key || '';
      pendingClear.current = clear;
      o2.freeze();
      o2.settle();
      o2.onDrop(key, dropAnchor(keys, key, to)).then((ok) => { if (!ok) refuseRow(d.li); });
      o2.onEnd();
      // filet : si l'ordre ne change pas dans ce rendu, les décalages s'effacent à l'image suivante
      requestAnimationFrame(() => { pendingClear.current?.(); pendingClear.current = null; });
      flashRow(d.li);
    };
    a.finished.then(finish, finish);
  }, []);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = drag.current;
      if (!d || e.pointerId !== d.pid) return;
      if (!d.started) {
        if (Math.abs(e.clientY - d.y0) < DRAG_THRESHOLD) return;
        if (!begin(d, e)) { drag.current = null; return; }
      }
      d.py = e.clientY;
      follow(d);
    };
    const onUp = (e: PointerEvent) => {
      const d = drag.current;
      if (!d || e.pointerId !== d.pid) return;
      if (!d.started) { drag.current = null; return; }
      end(false);
    };
    const onCancel = (e: PointerEvent) => { if (drag.current?.pid === e.pointerId) end(true); };
    const onKey = (e: KeyboardEvent) => { if (drag.current?.started && e.key === 'Escape') { e.preventDefault(); end(true); } };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
      window.removeEventListener('keydown', onKey);
      if (drag.current?.started) end(true);
    };
  }, [begin, follow, end]);

  const onPointerDown = useCallback((e: ReactPointerEvent) => {
    if (e.button !== 0 || drag.current) return;
    const target = e.target as HTMLElement;
    if (target.closest('.act') || !target.closest('.grip, .thumb')) return;
    const li = target.closest<HTMLElement>('.row');
    if (!li || li.dataset.leaving != null) return;
    drag.current = { li, pid: e.pointerId, y0: e.clientY, started: false, rows: [], from: 0, to: 0, tops: [], step: 0, grab: 0, y: 0, py: null, raf: 0 };
    e.preventDefault();
  }, []);

  const swallowClick = useCallback(() => swallow.current, []);
  return { onPointerDown, swallowClick };
}
