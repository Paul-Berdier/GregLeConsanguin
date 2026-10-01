'use client';

import { useSyncExternalStore } from 'react';
import { createHerald, deckToast, errorToast, withExtras } from '@/lib/herald';
import type { DeckReader, SayOptions, Toast } from '@/lib/herald';
import { errorCopy } from '@/lib/playerUtils';
import { seedOf } from '@/lib/stage/scene';
import { has, quip, t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';

let announcer: ((t: Toast) => void) | null = null;

/** Le Héraut de la page (un seul) : usePlayer y annonce, <Herald/> l'affiche et le lit aux lecteurs d'écran. */
export const herald = createHerald({
  now: () => Date.now(),
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
  announce: (toast) => announcer?.(toast),
});

/** <Herald/> branche ici ses régions aria-live persistantes. */
export function setAnnouncer(fn: ((t: Toast) => void) | null): void {
  announcer = fn;
}

let speaker: ((text: string, assertive: boolean) => void) | null = null;
export function setSpeaker(fn: ((text: string, assertive: boolean) => void) | null): void { speaker = fn; }
/** Annonce sans notification visible (clavier, changement de titre), dans les régions persistantes (DESIGN §7). */
export function speak(text: string, o: { assertive?: boolean } = {}): void { if (text) speaker?.(text, !!o.assertive); }

const EMPTY: readonly Toast[] = [];
export function useToasts(): readonly Toast[] {
  return useSyncExternalStore(herald.subscribe, herald.getSnapshot, () => EMPTY);
}

// Le deck, puis ses compléments (copy.extra.ts : error.SEARCH_FAILED, error.BUSY…).
const DECK: DeckReader = withExtras({ t, has, quip, seedOf }, tx);

/**
 * Message du deck : `key` est une entrée `{ text, kind?, quips? }` (ex. 'toast.removed').
 * `text` remplace le texte de l'entrée (texte déjà rendu) ; la réplique vient des `quips` de l'entrée (deckToast).
 */
export function say(key: string, o: SayOptions = {}): number {
  return herald.notify(deckToast(key, o, DECK));
}

/**
 * Erreur d'API → texte du deck (errorCopy) et sa sorte ; `ctx.name` nomme le demandeur d'un titre prioritaire,
 * `ctx.link` la nature du texte envoyé (un EXPAND_TIMEOUT de recherche ou de vidéo seule : Greg occupé).
 */
export function sayError(e: unknown, ctx?: Parameters<typeof errorCopy>[1]): number {
  return herald.notify(errorToast(errorCopy(e, ctx), DECK));
}
