'use client';

import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { livePosition } from '@/lib/playerUtils';
import { fmt } from '@/lib/format';
import { clockPane, fmtSpoken } from '@/lib/stage/dial';
import { t } from '@/theme/copy';

const TICK_MS = 250;

/**
 * Le temps de la scène, sans boucle par image (motion.md P4) : toutes les 250 ms, écrit les libellés
 * `[data-clock=cur]` / `[data-clock=tot]` et l'aria de `[data-clock=aria]` sous `rootRef` (seulement
 * ce qui change ; React ne leur donne jamais de texte), et renvoie le panneau courant de l'horloge :
 * un rendu React par panneau, pas plus.
 */
export function useStageClock(rootRef: RefObject<HTMLElement>, n: number): number {
  const [pane, setPane] = useState(-1);
  const nRef = useRef(n);
  nRef.current = n;

  useEffect(() => {
    let lastPane = -2;
    // écrit seulement ce qui diffère : un libellé monté plus tard (TimesRow) est rempli au tick suivant
    const put = (root: HTMLElement, sel: string, text: string) =>
      root.querySelectorAll(sel).forEach((el) => { if (el.textContent !== text) el.textContent = text; });
    const tick = () => {
      const root = rootRef.current;
      if (!root) return;
      const s = useStore.getState();
      const track = s.player.current;
      const dur = track ? s.tickBase.dur || s.player.duration || track.duration || 0 : 0;
      const pos = track ? livePosition(s.tickBase, s.player.paused, performance.now()) : 0;
      put(root, '[data-clock=cur]', track ? fmt(pos) : '0:00');
      put(root, '[data-clock=tot]', dur > 0 ? fmt(dur) : '--:--');
      const el = root.querySelector('[data-clock=aria]');
      const text = track && dur > 0 ? t('now.progressAria', { cur: fmtSpoken(pos), length: fmtSpoken(dur) }) : '';
      if (el && el.getAttribute('aria-valuetext') !== text) {
        el.setAttribute('aria-valuemax', String(Math.round(dur)));
        el.setAttribute('aria-valuenow', String(Math.round(Math.min(pos, dur))));
        el.setAttribute('aria-valuetext', text);
      }
      const i = track ? clockPane(pos, dur, nRef.current) : -1;
      if (i !== lastPane) { lastPane = i; setPane(i); }
    };
    tick();
    const id = setInterval(tick, TICK_MS);
    return () => clearInterval(id);
  }, [rootRef]);

  return pane;
}
