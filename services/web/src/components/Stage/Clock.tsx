'use client';

import { useRef } from 'react';
import type { PointerEvent } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { fmt } from '@/lib/format';
import { hitArcPath, paneAtPoint, paneTime } from '@/lib/stage/dial';
import type { DialGeometry } from '@/lib/stage/dial';

/**
 * L'horloge en lecture seule : l'anneau du vitrail (allumé par la rosace) porte une zone de survol qui
 * montre le temps sous le pointeur ; ni clic ni touches (le bot n'a pas de seek, spec §2). Les temps sont
 * posés aux naissances de l'arc, comme les chiffres d'un cadran. Textes écrits par useStageClock
 * (`data-clock`). `labelledBy` : id du titre du morceau. Styles : clock.css.
 */
export default function Clock({ dial, active, labelledBy }: { dial: DialGeometry; active: boolean; labelledBy: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  const onMove = (e: PointerEvent<SVGPathElement>) => {
    const svg = svgRef.current, tip = tipRef.current;
    const stage = svg?.closest('.stage');
    const s = useStore.getState();
    // même durée que useStageClock (le total affiché aux naissances de l'arc)
    const dur = s.tickBase.dur || s.player.duration || s.player.current?.duration || 0;
    if (!active || !svg || !tip || !stage || !(dur > 0)) return;
    const r = svg.getBoundingClientRect();
    const i = paneAtPoint(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2), dial);
    tip.textContent = fmt(paneTime(i, dial.n, dur));
    const sr = stage.getBoundingClientRect();
    tip.style.left = `${e.clientX - sr.left}px`;
    tip.style.top = `${e.clientY - sr.top}px`;
    tip.dataset.on = 'true';
  };
  const onLeave = () => { if (tipRef.current) tipRef.current.dataset.on = 'false'; };

  return (
    <>
      <svg ref={svgRef} className="dial" viewBox="-1.06 -1.06 2.12 2.12" data-clock="aria"
        role="progressbar" aria-labelledby={labelledBy} aria-valuemin={0} aria-hidden={active ? undefined : true}>
        <path className="dial-hit" d={hitArcPath(dial)} strokeWidth={0.1} onPointerMove={onMove} onPointerLeave={onLeave}/>
      </svg>
      <span className="spring l tnum" data-clock="cur" aria-hidden="true"/>
      <span className="spring r tnum" data-clock="tot" aria-hidden="true"/>
      <div className="dial-tip plaque tnum" ref={tipRef} aria-hidden="true"/>
    </>
  );
}

/** Les mêmes temps, en ligne sous le portail quand les naissances de l'arc manquent de place. */
export function TimesRow() {
  return (
    <div className="times-row tnum" aria-hidden="true">
      <span data-clock="cur"/>
      <span data-clock="tot"/>
    </div>
  );
}
