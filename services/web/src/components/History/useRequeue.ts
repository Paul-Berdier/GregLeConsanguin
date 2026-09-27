'use client';

import { useMemo, useRef, useState } from 'react';
import type { MouseEvent, RefObject } from 'react';
import { playerActions } from '@/hooks/usePlayer';
import { useRoving } from '@/hooks/useRoving';
import { reducedMotion } from '@/lib/motion';
import { createDedupe } from '@/lib/queue/drag';
import { sealBook } from '@/lib/queue/seal';
import type { HistoryItem } from '@/lib/queue/view';
import { boxOf } from '@/lib/stage/coronation';

/**
 * Remettre un titre de l'historique dans la file (un ajout du Roi : toast « Ajouté », annulable). Son sceau est
 * attendu (sealBook) : sa ligne entrera avec Le Sceau, la pochette `from` volant jusqu'à elle (Queue/seal.ts).
 */
export function requeue(item: HistoryItem, from?: HTMLElement | null): void {
  if (!item.url && !item.title) return;
  sealBook.expect({ url: item.url || null, from: from && !reducedMotion() ? boxOf(from) : null,
    thumb: from?.querySelector('img')?.currentSrc || item.thumb || null, at: performance.now() });
  playerActions.enqueue({ query: item.url || item.title, url: item.url, title: item.title, artist: item.artist,
    thumb: item.thumb, duration: item.duration, provider: item.provider || 'youtube' })
    .then((ok) => { if (!ok) sealBook.clear(); }, () => { sealBook.clear(); });   // erreur déjà annoncée par le Héraut
}

/**
 * Clics d'une liste d'historique (délégués) : un clic sélectionne, un double-clic ou « + » remet dans la file.
 * Un seul ajout par 500 ms : « + » cliqué deux fois, ou la ligne de « Souvent demandés ici » qui remonte sous le
 * pointeur quand la précédente entre dans la file, ne remettent pas un second titre.
 * Clavier (useRoving) : un arrêt de Tab, ↑ ↓ Début Fin, Entrée remet le titre dans la file (depuis sa pochette).
 * `leaves` : la ligne remise quitte la liste (« Souvent demandés ici » écarte ce qui est dans la file) ; Entrée passe alors
 * le focus à sa voisine, au lieu de le laisser tomber sur <body>. Les autres touches n'ont rien à refocaliser.
 */
export function useRequeueList(items: readonly HistoryItem[], listRef: RefObject<HTMLOListElement>, leaves = false) {
  const [picked, setPicked] = useState<string | null>(null);
  const once = useRef(createDedupe());
  const sourceOf = (url?: string): HTMLElement | null =>
    (url ? listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-url="${CSS.escape(url)}"] .thumb`) ?? null : null);
  /** false : un ajout vient d'être fait (moins de 500 ms), celui-ci n'est pas envoyé. */
  const add = (item: HistoryItem): boolean => {
    if (once.current('add', performance.now())) return false;
    requeue(item, sourceOf(item.url));
    return true;
  };
  const itemOf = (e: MouseEvent) => {
    const url = (e.target as HTMLElement).closest<HTMLElement>('.row')?.dataset.url;
    return url ? items.find((x) => x.url === url) ?? null : null;
  };
  const onClick = (e: MouseEvent) => {
    const it = itemOf(e);
    if (!it) return;
    if ((e.target as HTMLElement).closest('[data-act=add]')) add(it);
    else setPicked(it.url || null);
  };
  const onDoubleClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest('[data-act=add]')) return;
    const it = itemOf(e);
    if (it) add(it);
  };
  const keys = useMemo(() => items.map((x) => x.url || ''), [items]);
  const roving = useRoving(listRef, keys, 'url', (act, url, i) => {   // Entrée : remettre dans la file, depuis sa pochette
    const hit = act.kind === 'activate' ? items.find((x) => x.url === url) : undefined;
    if (!hit || !add(hit)) return null;
    return leaves ? keys[i + 1] ?? keys[i - 1] ?? null : null;
  });
  return { picked, onClick, onDoubleClick, onKeyDown: roving.onKeyDown, onFocus: roving.onFocus, tabIndexOf: roving.tabIndexOf };
}
