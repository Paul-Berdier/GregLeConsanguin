'use client';

import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import { sameLayout, solveStageLayout } from '@/lib/stage/layout';
import type { StageLayout } from '@/lib/stage/layout';

/** Écart de hauteur du bloc sous le portail en deçà duquel on ne recalcule pas (évite un aller-retour). */
const BELOW_EPS = 2;

/**
 * Mise en page de la scène (DESIGN §12.4) : observe la colonne de scène et le bloc sous le portail,
 * recalcule R au plus une fois par image, et ne rend que si la mise en page change.
 * null tant que rien n'a été mesuré (rendu serveur, premier rendu) : la CSS garde ses valeurs par défaut.
 */
export function useStageLayout(colRef: RefObject<HTMLElement>, belowRef: RefObject<HTMLElement>): StageLayout | null {
  const [layout, setLayout] = useState<StageLayout | null>(null);

  useEffect(() => {
    const col = colRef.current;
    if (!col) return;
    let raf = 0, lastBelow = -1;
    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const belowH = belowRef.current?.offsetHeight ?? 0;
        lastBelow = belowH;
        const next = solveStageLayout({ colW: col.clientWidth, colH: col.clientHeight, belowH, viewportW: window.innerWidth });
        setLayout((prev) => (sameLayout(prev, next) ? prev : next));
      });
    };
    const ro = new ResizeObserver((entries) => {
      // le bloc du dessous ne compte que s'il a vraiment changé (police chargée, une ligne de plus)
      const onlyBelow = entries.every((e) => e.target !== col);
      if (onlyBelow && Math.abs((belowRef.current?.offsetHeight ?? 0) - lastBelow) < BELOW_EPS) return;
      measure();
    });
    ro.observe(col);
    if (belowRef.current) ro.observe(belowRef.current);
    window.addEventListener('resize', measure);
    document.fonts?.ready.then(measure).catch(() => {});
    measure();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener('resize', measure); };
  }, [colRef, belowRef]);

  return layout;
}
