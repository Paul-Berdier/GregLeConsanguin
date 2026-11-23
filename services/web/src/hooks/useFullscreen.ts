'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { create } from 'zustand';
import type { RefObject } from 'react';
import { FS_ASK_MS, canNativeFs, exitFs, fsElement, fsModeAfterChange, requestFs } from '@/lib/stage/fullscreen';
import type { FsDoc, FsEl, FsMode } from '@/lib/stage/fullscreen';

export type Fullscreen = { mode: FsMode | null; enter: () => void; exit: () => void; toggle: () => void };

/**
 * L'élément en plein écran (API ou repli), null sinon. Hors de lui, rien n'est visible en plein écran : page.tsx y monte
 * le Héraut (createPortal) pour que les confirmations et « Annuler » restent à l'écran.
 */
export const useFsHost = create<{ host: HTMLElement | null }>(() => ({ host: null }));

const CHANGE = ['fullscreenchange', 'webkitfullscreenchange'] as const;
const ERROR = ['fullscreenerror', 'webkitfullscreenerror'] as const;

/**
 * Plein écran d'un élément (`.video`, Portal.tsx ; conception du 2026-11-23, §2). L'API d'abord : `enter` et `toggle`
 * s'appellent dans le gestionnaire du clic ou du double-clic (l'activation de l'utilisateur ne vaut qu'un temps) ; l'état
 * suit `fullscreenchange` (Échap, sortie imposée par le navigateur, élément retiré). Sans API pour un élément (iPhone),
 * si le navigateur refuse ou ne répond pas : le repli « pseudo », en CSS (theater.css), qu'Échap et le bouton quittent.
 * `onExit` : après chaque sortie, quelle qu'en soit la cause (le focus revient au bouton d'entrée, Stage.tsx).
 */
export function useFullscreen(elRef: RefObject<HTMLElement>, onExit: () => void): Fullscreen {
  const [mode, setMode] = useState<FsMode | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const onExitRef = useRef(onExit);
  onExitRef.current = onExit;
  // demande partie, réponse du navigateur pas encore reçue : la minuterie du repli (FS_ASK_MS)
  const asking = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Fin d'une demande. `fallback` : refusée ou restée sans réponse, le repli prend le relais (sauf plein écran obtenu). */
  const settle = useCallback((fallback: boolean) => {
    if (asking.current == null) return;
    clearTimeout(asking.current);
    asking.current = null;
    if (fallback && !fsElement(document as Document & FsDoc)) setMode('pseudo');
  }, []);

  useEffect(() => {
    const doc = document as Document & FsDoc;
    const sync = (): void => {
      settle(false);
      const el = elRef.current;
      setMode((m) => fsModeAfterChange(m, !!el && fsElement(doc) === el));
    };
    // refus (iframe sans allow="fullscreen", préfixe webkit sans promesse)
    const refused = (): void => settle(true);
    for (const ev of CHANGE) doc.addEventListener(ev, sync);
    for (const ev of ERROR) doc.addEventListener(ev, refused);
    return () => {
      for (const ev of CHANGE) doc.removeEventListener(ev, sync);
      for (const ev of ERROR) doc.removeEventListener(ev, refused);
      if (asking.current != null) { clearTimeout(asking.current); asking.current = null; }
    };
  }, [elRef, settle]);

  const enter = useCallback(() => {
    const el = elRef.current as (HTMLElement & FsEl) | null;
    if (!el || modeRef.current || asking.current != null) return;
    if (!canNativeFs(document as Document & FsDoc, el)) { setMode('pseudo'); return; }
    // vue web qui ne répond jamais (ni accord ni refus) : le repli au bout d'une seconde, le bouton ne reste pas muet
    asking.current = setTimeout(() => settle(true), FS_ASK_MS);
    requestFs(el).catch(() => settle(true));
  }, [elRef, settle]);

  const exit = useCallback(() => {
    const doc = document as Document & FsDoc;
    if (modeRef.current === 'pseudo') { setMode(null); return; }
    // l'API : `fullscreenchange` remettra l'état à null
    if (fsElement(doc)) exitFs(doc).catch(() => {});
  }, []);

  const toggle = useCallback(() => { if (modeRef.current) exit(); else enter(); }, [enter, exit]);

  // Repli : Échap le quitte (avec l'API, Échap appartient au navigateur). Un popover ouvert (confirmation d'arrêt) garde
  // son Échap : usePopover l'arrête et l'annule avant nous.
  useEffect(() => {
    if (mode !== 'pseudo') return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      e.preventDefault();
      setMode(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mode]);

  // Toute sortie, quelle qu'en soit la cause : onExit, une fois. (Élément retiré du document : le navigateur sort seul.)
  const was = useRef(mode);
  useEffect(() => {
    if (was.current && !mode) onExitRef.current();
    was.current = mode;
    useFsHost.setState({ host: mode ? elRef.current : null });
  }, [mode, elRef]);
  // démonté en plein écran (élément retiré : le navigateur sort seul) : le Héraut revient à la page
  useEffect(() => () => { if (useFsHost.getState().host === elRef.current) useFsHost.setState({ host: null }); }, [elRef]);

  return { mode, enter, exit, toggle };
}
