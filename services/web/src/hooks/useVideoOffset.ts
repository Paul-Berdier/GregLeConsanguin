'use client';

import { useCallback, useEffect, useState } from 'react';
import { OFFSET_KEY, parseOffset } from '@/lib/stage/cover';

/** Décalage vidéo ↔ son du Roi, gardé dans localStorage (tech.md §5.4). 0 par défaut. */
export function useVideoOffset(): [number, (v: number) => void] {
  const [offset, setOffsetState] = useState(0);

  useEffect(() => {
    try { setOffsetState(parseOffset(localStorage.getItem(OFFSET_KEY))); } catch {}
  }, []);

  const setOffset = useCallback((v: number) => {
    const x = parseOffset(v);
    setOffsetState(x);
    try { if (x) localStorage.setItem(OFFSET_KEY, String(x)); else localStorage.removeItem(OFFSET_KEY); } catch {}
  }, []);

  return [offset, setOffset];
}
