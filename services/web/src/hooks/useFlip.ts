'use client';

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { dropLeft, mergePresence, reverseStagger, staggerDelay, translateYOf } from '@/lib/flip';
import type { Presence } from '@/lib/flip';
import { DUR, EASE, SPRING, STAGGER_CAP, reducedMotion } from '@/lib/motion';

const EXIT_STYLE = ['position', 'top', 'left', 'right', 'margin', 'pointerEvents'] as const;

/**
 * FLIP d'une liste avec l'API Web Animations (spec §3, motion.md §6.6–6.7), sans bibliothèque.
 * - `rendered` : les éléments de `items`, plus ceux qui sortent (lib/flip.ts, mergePresence) ;
 * - après chaque rendu, chaque ligne `[data-key]` enfant directe de `listRef` part de son ancienne place
 *   (translateY) vers la nouvelle, avec --spring-move ; une animation en cours repart de là où elle en est ;
 * - une ligne nouvelle entre (fondu, 8 px, cascade de 30 ms plafonnée à 8) ; pas au premier rendu ;
 * - une ligne partie (`data-leaving`) sort hors du flux, vers la droite ou vers la scène (`exitDir`), puis
 *   quitte la liste ;
 * - `exitStagger` : les lignes qui sortent ensemble partent de la dernière à la première (reverseStagger, 20 ms,
 *   plafond 8 : l'arrêt, DESIGN §5) ; sinon toutes à la fois ;
 * - `onEnter(key, el)` : appelé pour chaque ligne nouvelle avant l'entrée par défaut ; `true` : elle a sa propre
 *   entrée (Le Sceau, Queue/seal.ts) et l'entrée par défaut n'est pas jouée ;
 * - `freeze()` : le prochain rendu remesure sans animer (dépôt d'un glisser, déjà dessiné à sa place).
 * Mouvement réduit : fondus seuls. Onglet caché : rien n'est animé (motion.md P11).
 * La liste doit être `position: relative` (les lignes qui sortent s'y placent en absolu).
 */
export function useFlip<T>(
  listRef: RefObject<HTMLElement>,
  items: readonly T[],
  keyOf: (t: T) => string,
  opts: { exitDir?: (key: string) => 1 | -1; exitStagger?: boolean; onEnter?: (key: string, el: HTMLElement) => boolean } = {},
): { rendered: Presence<T>[]; freeze: () => void } {
  const [state, setState] = useState(() => ({ items, rendered: mergePresence<T>([], items, keyOf) }));
  let rendered = state.rendered;
  if (state.items !== items) {
    rendered = mergePresence(state.rendered, items, keyOf);
    setState({ items, rendered });
  }

  const tops = useRef(new Map<string, number>());
  const first = useRef(true);
  const frozen = useRef(false);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const onExited = useCallback((key: string) => {
    setState((s) => {
      const next = dropLeft(s.rendered, key);
      return next === s.rendered ? s : { ...s, rendered: next };
    });
  }, []);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const hidden = document.hidden;
    const reduce = reducedMotion();
    const next = new Map<string, number>();
    let entering = 0;
    const exits: { el: HTMLElement; key: string }[] = [];   // animées après la boucle : leur rang compte (exitStagger)
    for (const el of Array.from(list.children) as HTMLElement[]) {
      const key = el.dataset.key;
      if (!key) continue;
      if (el.dataset.leaving != null) {
        if (el.dataset.exiting) continue;
        el.dataset.exiting = '1';
        if (hidden) { onExited(key); continue; }
        const top = tops.current.get(key) ?? el.offsetTop;
        for (const a of el.getAnimations()) a.cancel();
        Object.assign(el.style, { position: 'absolute', top: `${top}px`, left: '0', right: '0', margin: '0', pointerEvents: 'none' });
        exits.push({ el, key });
        continue;
      }
      if (el.dataset.exiting) {   // revenu pendant sa sortie
        delete el.dataset.exiting;
        for (const a of el.getAnimations()) a.cancel();
        for (const p of EXIT_STYLE) el.style[p] = '';
      }
      const top = el.offsetTop;
      next.set(key, top);
      if (first.current || frozen.current || hidden) continue;
      const old = tops.current.get(key);
      if (old == null) {
        if (optsRef.current.onEnter?.(key, el)) { entering++; continue; }
        const kf = reduce ? [{ opacity: 0 }, { opacity: 1 }]
          : [{ opacity: 0, transform: 'translateY(8px) scale(.98)' }, { opacity: 1, transform: 'none' }];
        el.animate(kf, { duration: reduce ? 150 : DUR.enter, delay: reduce ? 0 : staggerDelay(entering++, DUR.stagger, STAGGER_CAP), easing: EASE.out, fill: 'backwards' });
        continue;
      }
      const running = el.getAnimations().find((a) => a.id === 'flip');
      const shown = old + (running ? translateYOf(getComputedStyle(el).transform) : 0);
      running?.cancel();
      const dy = shown - top;
      if (reduce || Math.abs(dy) < 0.5) continue;
      const a = el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: SPRING.move.dur, easing: SPRING.move.easing });
      a.id = 'flip';
    }
    const stagger = !!optsRef.current.exitStagger && !reduce && exits.length > 1;
    exits.forEach(({ el, key }, i) => {
      const dir = optsRef.current.exitDir?.(key) ?? 1;
      const kf = reduce ? [{ opacity: 1 }, { opacity: 0 }] : [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: `translateX(${12 * dir}px) scale(.98)` }];
      el.animate(kf, { duration: reduce ? 120 : DUR.exit, delay: stagger ? reverseStagger(i, exits.length) : 0, easing: EASE.out, fill: 'forwards' })
        .finished.then(() => onExited(key), () => onExited(key));
    });
    tops.current = next;
    first.current = false;
    frozen.current = false;
  }, [rendered, listRef, onExited]);

  const freeze = useCallback(() => { frozen.current = true; }, []);
  return { rendered, freeze };
}
