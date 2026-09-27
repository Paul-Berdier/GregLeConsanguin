'use client';

import { useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { playerActions } from '@/hooks/usePlayer';
import { createDedupe } from '@/lib/queue/drag';
import type { HistoryItem } from '@/lib/queue/view';

/** Remettre un titre de l'historique dans la file (un ajout du Roi : toast « Ajouté », annulable). */
export function requeue(item: HistoryItem): void {
  if (!item.url && !item.title) return;
  playerActions.enqueue({
    query: item.url || item.title, url: item.url, title: item.title, artist: item.artist,
    thumb: item.thumb, duration: item.duration, provider: item.provider || 'youtube',
  }).catch(() => {});   // l'erreur est déjà annoncée par le Héraut
}

/**
 * Clics d'une liste d'historique (délégués) : un clic sélectionne, un double-clic ou « + » remet dans la file.
 * Un seul ajout par 500 ms : « + » cliqué deux fois, ou la ligne de « Souvent demandés ici » qui remonte sous le
 * pointeur quand la précédente entre dans la file, ne remettent pas un second titre.
 */
export function useRequeueList(items: readonly HistoryItem[]) {
  const [picked, setPicked] = useState<string | null>(null);
  const once = useRef(createDedupe());
  const add = (item: HistoryItem) => { if (!once.current('add', performance.now())) requeue(item); };
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
  return { picked, onClick, onDoubleClick };
}
