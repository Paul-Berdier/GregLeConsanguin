'use client';

import { useCallback, useEffect, useState } from 'react';
import { OFFSET_KEY, parseOffset } from '@/lib/stage/cover';

/** Décalage vidéo ↔ son du Roi, gardé dans localStorage, par appareil (tech.md §5.4). 0 par défaut. */
export function useVideoOffset(): [number, (v: number) => void] {
  const [offset, setOffsetState] = useState(0);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(OFFSET_KEY);
      const x = parseOffset(raw);
      setOffsetState(x);
      // ancien réglage (±10 s, pas de 0,5 s) : réécrit borné et arrondi
      if (raw != null && String(x) !== raw) { if (x) localStorage.setItem(OFFSET_KEY, String(x)); else localStorage.removeItem(OFFSET_KEY); }
    } catch {}
  }, []);

  const setOffset = useCallback((v: number) => {
    const x = parseOffset(v);
    setOffsetState(x);
    try { if (x) localStorage.setItem(OFFSET_KEY, String(x)); else localStorage.removeItem(OFFSET_KEY); } catch {}
  }, []);

  return [offset, setOffset];
}
