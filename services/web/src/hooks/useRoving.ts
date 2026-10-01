'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FocusEvent, KeyboardEvent, RefObject } from 'react';
import { translateYOf } from '@/lib/flip';
import { focusOutWatcher, keyboardFocus, rescueKey, revealDelta } from '@/lib/focus';
import { listKey } from '@/lib/keys';
import type { ListAct } from '@/lib/keys';
import { reducedMotion } from '@/lib/motion';

/** Sur une ligne, ces touches restent à la liste même sans effet (première ligne, dernière, touche maintenue) :
 * Alt+Début ouvre la page d'accueil de Chrome (Windows, Linux) et ferait quitter l'app. */
const ALT_KEYS = new Set(['Home', 'ArrowUp', 'ArrowDown']);

/** Ligne refocalisée au clavier : ramenée dans la vue de son défilement, à sa place d'arrivée (sans la translation FLIP en
 * cours). Celle qui garde le focus en montant (Alt+Début, Alt+↑ en haut) n'est sinon jamais défilée. */
function reveal(el: HTMLElement): void {
  const sc = el.closest<HTMLElement>('.scroller');
  if (!sc) return;
  const r = el.getBoundingClientRect(), v = sc.getBoundingClientRect(), cs = getComputedStyle(sc);
  const dy = translateYOf(getComputedStyle(el).transform);
  // marges du défilement comprises : la place gardée sous la file pour la pile du Héraut (--herald-h)
  const top = revealDelta(r.top - dy, r.bottom - dy, v.top + parseFloat(cs.paddingTop || '0'), v.bottom - parseFloat(cs.paddingBottom || '0'));
  if (top) sc.scrollBy({ top, behavior: reducedMotion() ? 'auto' : 'smooth' });
}

/**
 * Tabindex itinérant (DESIGN §12.7) : un arrêt de Tab par liste ; ↑ ↓ Début Fin sans animation ; le reste va à `onAct`, qui rend
 * la ligne à focaliser (null : aucune ; undefined : la même), refocalisée après le rendu qui l'a déplacée. attr : data-key ou data-url.
 * Un refocus en attente ne vole jamais le focus : il est abandonné si sa ligne a quitté la liste, si le focus est parti hors de la
 * liste (ailleurs que sur <body>), si le Roi parcourt la liste aux flèches ou y focalise une autre ligne.
 * Focus perdu hors d'un geste clavier (titre joué ou retiré ailleurs, ligne remontée, dernière ligne partie) : rendu à la même
 * ligne, sinon à celle qui a pris sa place, sinon à l'onglet du volet ; sans défilement. Seulement s'il venait du clavier
 * (:focus-visible) : au pointeur, il tombe. Oublié dès que le focus quitte la liste.
 */
export function useRoving(listRef: RefObject<HTMLElement>, keys: readonly string[], attr: 'key' | 'url',
  onAct: (act: Exclude<ListAct, { kind: 'focus' }>, key: string, index: number) => string | null | undefined) {
  const [active, setActive] = useState<string | null>(null);
  const refocus = useRef<string | null>(null);
  /** Ligne qui a le focus (son rang, suivi tant qu'elle est là ; kb : venu du clavier) ; null : le focus n'est pas dans la liste. */
  const last = useRef<{ key: string; index: number; kb: boolean } | null>(null);
  /** id de l'onglet du volet de la liste : où va le focus quand elle se vide. */
  const home = useRef<string | null>(null);
  const current = active != null && keys.includes(active) ? active : keys[0] ?? null;
  const rowOf = useCallback((k: string) =>
    listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-${attr}="${CSS.escape(k)}"]`) ?? null, [listRef, attr]);

  useLayoutEffect(() => {
    const k = refocus.current, list = listRef.current;
    const at = document.activeElement;
    if (k) {
      if (!list || !keys.includes(k) || (at && at !== document.body && !list.contains(at))) refocus.current = null;
      else {
        const el = rowOf(k);
        if (!el || el.dataset.leaving != null) return;   // pas encore là : au prochain rendu
        refocus.current = null;
        if (at !== el) el.focus();
        reveal(el);
        return;
      }
    }
    const l = last.current;
    if (!l) return;
    const i = keys.indexOf(l.key);
    if (i >= 0) l.index = i;
    // perdu : sur <body> (ligne démontée), ou sur une ligne qui sort (tabindex -1, plus de touches) ; sinon rien à faire
    const lost = !at || at === document.body || !!(list?.contains(at) && at.closest('[data-leaving]'));
    if (!lost) return;
    if (!l.kb) { last.current = null; return; }   // au pointeur : il tombe, comme avant (boutons et raccourcis libres)
    const to = rescueKey(keys, l.key, l.index), el = to ? rowOf(to) : null;
    if (to && (!el || el.dataset.leaving != null)) return;   // pas encore là : au prochain rendu
    last.current = null;   // onFocus le reprend sur la ligne rendue
    (el ?? (home.current ? document.getElementById(home.current) : null))?.focus({ preventScroll: true });
  });

  // Focus sorti de la liste (ailleurs, ou sur <body> d'un clic) : plus rien à rendre. Fenêtre quittée : il y reste
  // (activeElement inchangé), gardé. Décidé après coup (lib/focus.ts) : Chrome lance focusout quand React retire ou
  // déplace la ligne focalisée, avant que l'effet de rendu ne rende le focus.
  useEffect(() => {
    const out = focusOutWatcher({
      list: () => listRef.current, active: () => document.activeElement,
      defer: (fn) => queueMicrotask(fn), forget: () => { last.current = null; },
    });
    document.addEventListener('focusout', out);
    return () => document.removeEventListener('focusout', out);
  }, [listRef]);

  const onKeyDown = (e: KeyboardEvent<HTMLElement>): void => {
    const row = e.target as HTMLElement;
    if (!row.classList.contains('row') || row.parentElement !== listRef.current) return;   // pas depuis un bouton
    if (e.altKey && !e.ctrlKey && !e.metaKey && ALT_KEYS.has(e.key)) e.preventDefault();
    const k = row.dataset[attr] || '', i = keys.indexOf(k);
    const act = i < 0 ? null : listKey(e, i, keys.length);
    if (!act) return;
    e.preventDefault();
    if (act.kind === 'focus') { refocus.current = null; const to = keys[act.index]; setActive(to); rowOf(to)?.focus(); return; }
    const next = onAct(act, k, i), target = next === undefined ? k : next;
    refocus.current = target;
    if (target) setActive(target);
  };
  const onFocus = (e: FocusEvent<HTMLElement>): void => {
    const row = (e.target as HTMLElement).closest<HTMLElement>('.row');
    const k = row && row.parentElement === listRef.current ? row.dataset[attr] : undefined;
    if (!k) return;
    if (refocus.current !== k) refocus.current = null;
    last.current = { key: k, index: keys.indexOf(k), kb: keyboardFocus(e.target as HTMLElement) };
    home.current = listRef.current?.closest('[role="tabpanel"]')?.getAttribute('aria-labelledby') ?? null;
    setActive(k);
  };
  return { tabIndexOf: (k: string): 0 | -1 => (k === current ? 0 : -1), onKeyDown, onFocus };
}
