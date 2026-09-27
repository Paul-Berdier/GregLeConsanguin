'use client';

import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

/**
 * Un seul lecteur YouTube pour toute la session (tech.md §5.2) : créé une fois, les titres passent par
 * loadVideoById dans la même iframe (≈ 400 ms au lieu de ≈ 690 ms, sans iframe recréée).
 * React ne possède que l'enveloppe vide : l'iframe remplace un enfant créé ici, jamais un nœud React.
 */

export type YTPlayer = {
  loadVideoById(o: { videoId: string; startSeconds?: number }): void;
  playVideo(): void;
  pauseVideo(): void;
  stopVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  mute(): void;
  getIframe(): HTMLIFrameElement;
  destroy(): void;
};
type YTNamespace = { Player: new (el: HTMLElement, opts: Record<string, unknown>) => YTPlayer };
type YTWindow = Window & { YT?: YTNamespace; onYouTubeIframeAPIReady?: () => void };
export type YTHandlers = { onState: (state: number) => void; onError: (code: number) => void };

const API_SRC = 'https://www.youtube.com/iframe_api';
let apiPromise: Promise<YTNamespace> | null = null;

/** Charge l'API une seule fois ; enchaîne un onYouTubeIframeAPIReady déjà posé. */
export function loadYouTubeApi(): Promise<YTNamespace> {
  const w = window as YTWindow;
  if (w.YT?.Player) return Promise.resolve(w.YT);
  apiPromise ??= new Promise<YTNamespace>((resolve) => {
    const prev = w.onYouTubeIframeAPIReady;
    w.onYouTubeIframeAPIReady = () => { prev?.(); if (w.YT) resolve(w.YT); };
    if (!document.querySelector(`script[src="${API_SRC}"]`)) {
      const tag = document.createElement('script');
      tag.src = API_SRC;
      tag.async = true;
      document.head.appendChild(tag);
    }
  });
  return apiPromise;
}

/** Crée le lecteur dans `wrapRef` au montage, le détruit au démontage. Renvoie null tant qu'il n'est pas prêt. */
export function useYouTubePlayer(wrapRef: RefObject<HTMLDivElement>, handlers: YTHandlers): YTPlayer | null {
  const [player, setPlayer] = useState<YTPlayer | null>(null);
  const h = useRef(handlers);
  h.current = handlers;

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    let alive = true;
    let created: YTPlayer | null = null;
    const host = document.createElement('div');
    wrap.appendChild(host);
    loadYouTubeApi().then((YT) => {
      if (!alive) return;
      created = new YT.Player(host, {
        width: '100%', height: '100%',
        playerVars: {
          autoplay: 1, mute: 1, controls: 0, rel: 0, iv_load_policy: 3, disablekb: 1,
          playsinline: 1, fs: 0, cc_load_policy: 0, enablejsapi: 1, origin: location.origin,
        },
        events: {
          onReady: () => {
            if (!alive || !created) return;
            created.mute();
            try { created.getIframe().tabIndex = -1; } catch {}   // image seule : jamais dans l'ordre de tabulation
            setPlayer(created);
          },
          onStateChange: (e: { data: number }) => { if (alive) h.current.onState(e.data); },
          onError: (e: { data: number }) => { if (alive) h.current.onError(e.data); },
        },
      });
    }).catch(() => {});
    return () => {
      alive = false;
      try { created?.destroy(); } catch {}
      wrap.replaceChildren();
      setPlayer(null);
    };
  }, [wrapRef]);

  return player;
}
