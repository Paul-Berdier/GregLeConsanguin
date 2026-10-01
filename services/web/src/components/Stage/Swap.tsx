'use client';

import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { dropLeft, mergePresence } from '@/lib/flip';
import type { Presence } from '@/lib/flip';
import { EASE } from '@/lib/motion';
import type { CrownPlan } from '@/lib/stage/coronation';

type Line = { k: string; node: ReactNode };
const keyOf = (l: Line): string => l.k;

/**
 * Légendes croisées (DESIGN §5, .line de now.css, superposées sur une même case de grille) : l'ancienne sort vers le
 * haut (aria-hidden), la nouvelle entre après `delay`, d'après le plan de la cérémonie (translation `shift`, 0 : fondu) ;
 * sans plan, elle paraît sans mouvement. Aucun flou (écart 1). `k` : la clé du titre ; '' : rien.
 */
export default function Swap({ k, plan, delay, children }: { k: string; plan: CrownPlan | null; delay: number; children: ReactNode }) {
  const [shownK, setShownK] = useState(k);
  const [lines, setLines] = useState<Presence<Line>[]>(() => (k ? [{ key: k, item: { k, node: children }, leaving: false }] : []));
  // contenu du dernier rendu validé : la ligne qui part montre ce qu'elle affichait (« Demandé par vous » venu
  // après son entrée, un titre complété), pas ce qu'elle avait en entrant
  const rendered = useRef<ReactNode>(children);
  useLayoutEffect(() => { rendered.current = children; });
  if (shownK !== k) {
    setShownK(k);
    const last = lines.map((l) => (l.key === shownK && !l.leaving ? { ...l, item: { k: l.key, node: rendered.current } } : l));
    setLines(mergePresence(last, k ? [{ k, node: children }] : [], keyOf));
  }
  const els = useRef(new Map<string, HTMLSpanElement>());
  const first = useRef(true), planRef = useRef(plan), delayRef = useRef(delay);
  planRef.current = plan; delayRef.current = delay;

  useLayoutEffect(() => {
    const p = planRef.current;
    for (const l of lines) {
      const el = els.current.get(l.key);
      if (!el) continue;
      if (l.leaving) {
        if (el.dataset.exiting) continue;
        el.dataset.exiting = '1';
        // une entrée pas finie (titres en rafale) : la sortie part de l'opacité rendue, sans éclair
        const running = el.getAnimations();
        const from = running.length ? Number(getComputedStyle(el).opacity) : 1;
        for (const a of running) a.cancel();
        const drop = (): void => setLines((ls) => dropLeft(ls, l.key));
        el.animate([{ opacity: from, transform: 'none' }, { opacity: 0, transform: `translateY(${-(p?.shift ?? 0)}px)` }],
          { duration: p?.exitMs ?? 180, easing: EASE.out, fill: 'forwards' }).finished.then(drop, drop);
      } else if (el.dataset.exiting) {   // revenue pendant sa sortie
        delete el.dataset.exiting;
        for (const a of el.getAnimations()) a.cancel();
      } else if (!el.dataset.entered) {
        el.dataset.entered = '1';
        if (first.current || !p) continue;
        el.animate([{ opacity: 0, transform: `translateY(${p.shift}px)` }, { opacity: 1, transform: 'none' }],
          { duration: p.enterMs, delay: delayRef.current, easing: EASE.out, fill: 'backwards' });
      }
    }
    first.current = false;
  }, [lines]);

  return <>{lines.map((l) => (
    <span key={l.key} className="line" aria-hidden={l.leaving || undefined}
      ref={(el) => { if (el) els.current.set(l.key, el); else els.current.delete(l.key); }}>
      {l.leaving ? l.item.node : children}
    </span>
  ))}</>;
}
