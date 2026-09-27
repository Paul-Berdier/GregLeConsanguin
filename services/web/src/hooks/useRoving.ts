'use client';

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import type { FocusEvent, KeyboardEvent, RefObject } from 'react';
import { listKey } from '@/lib/keys';
import type { ListAct } from '@/lib/keys';

/** Sur une ligne, ces touches restent à la liste même sans effet (première ligne, dernière, touche maintenue) :
 * Alt+Début ouvre la page d'accueil de Chrome (Windows, Linux) et ferait quitter l'app. */
const ALT_KEYS = new Set(['Home', 'ArrowUp', 'ArrowDown']);

/**
 * Tabindex itinérant (DESIGN §12.7) : un arrêt de Tab par liste ; ↑ ↓ Début Fin sans animation ; le reste va à `onAct`, qui rend
 * la ligne à focaliser (null : aucune ; undefined : la même), refocalisée après le rendu qui l'a déplacée. attr : data-key ou data-url.
 * Un refocus en attente ne vole jamais le focus : il est abandonné si sa ligne a quitté la liste, si le focus est parti hors de la
 * liste (ailleurs que sur <body>), si le Roi parcourt la liste aux flèches ou y focalise une autre ligne.
 */
export function useRoving(listRef: RefObject<HTMLElement>, keys: readonly string[], attr: 'key' | 'url',
  onAct: (act: Exclude<ListAct, { kind: 'focus' }>, key: string, index: number) => string | null | undefined) {
  const [active, setActive] = useState<string | null>(null);
  const refocus = useRef<string | null>(null);
  const current = active != null && keys.includes(active) ? active : keys[0] ?? null;
  const rowOf = useCallback((k: string) =>
    listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-${attr}="${CSS.escape(k)}"]`) ?? null, [listRef, attr]);

  useLayoutEffect(() => {
    const k = refocus.current, list = listRef.current;
    if (!k) return;
    const at = document.activeElement;
    if (!list || !keys.includes(k) || (at && at !== document.body && !list.contains(at))) { refocus.current = null; return; }
    const el = rowOf(k);
    if (!el || el.dataset.leaving != null) return;   // pas encore là : au prochain rendu
    refocus.current = null;
    if (at !== el) el.focus();
  });

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
    setActive(k);
  };
  return { tabIndexOf: (k: string): 0 | -1 => (k === current ? 0 : -1), onKeyDown, onFocus };
}
