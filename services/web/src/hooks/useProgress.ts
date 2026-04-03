'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useStore } from './usePlayer';

/**
 * Hook de progression fluide — met à jour le DOM directement via refs
 * au lieu de passer par le store zustand (évite 60 re-renders/s).
 *
 * Usage:
 *   const { progressRef, currentRef, totalRef } = useProgress();
 *   <div ref={progressRef} className="progress-fill" />
 *   <span ref={currentRef} />
 *   <span ref={totalRef} />
 */
export function useProgress() {
  const progressRef = useRef<HTMLDivElement>(null);
  const currentRef = useRef<HTMLSpanElement>(null);
  const totalRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let rafId: number;

    function formatTime(sec: number): string {
      if (!isFinite(sec) || sec < 0) return '--:--';
      const s = Math.max(0, Math.floor(sec));
      const m = Math.floor(s / 60);
      const r = s % 60;
      return `${m}:${String(r).padStart(2, '0')}`;
    }

    function tick() {
      const s = useStore.getState();
      const cur = s.player.current;

      if (cur && progressRef.current) {
        const dur = s.tickBase.dur || s.player.duration || cur.duration || 0;
        const basePos = s.tickBase.pos || 0;
        const paused = s.player.paused;
        const now = performance.now();
        const elapsed = paused ? 0 : (now - s.tickBase.at) / 1000;
        const pos = basePos + elapsed;
        const clamped = dur > 0 ? Math.min(Math.max(pos, 0), dur) : Math.max(0, pos);
        const pct = dur > 0 ? (clamped / dur) * 100 : 0;

        progressRef.current.style.width = `${Math.min(100, pct)}%`;

        if (currentRef.current) {
          currentRef.current.textContent = formatTime(clamped);
        }
        if (totalRef.current) {
          totalRef.current.textContent = dur > 0 ? formatTime(dur) : '--:--';
        }
      } else {
        if (progressRef.current) progressRef.current.style.width = '0%';
        if (currentRef.current) currentRef.current.textContent = '0:00';
        if (totalRef.current) totalRef.current.textContent = '--:--';
      }

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  return { progressRef, currentRef, totalRef };
}

/**
 * Hook qui retourne la position live à un rythme réduit (4fps)
 * pour les composants qui ont besoin de la valeur en React state.
 */
export function useLivePosition(): number {
  const posRef = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const s = useStore.getState();
      const cur = s.player.current;
      if (!cur) { posRef.current = 0; return; }

      const dur = s.tickBase.dur || s.player.duration || cur.duration || 0;
      const basePos = s.tickBase.pos || 0;
      const paused = s.player.paused;
      const now = performance.now();
      const elapsed = paused ? 0 : (now - s.tickBase.at) / 1000;
      const pos = basePos + elapsed;
      posRef.current = dur > 0 ? Math.min(Math.max(pos, 0), dur) : Math.max(0, pos);
    }, 250);

    return () => clearInterval(interval);
  }, []);

  return posRef.current;
}
