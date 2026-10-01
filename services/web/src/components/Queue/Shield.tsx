'use client';

import { useId } from 'react';
import { armsOf, SHIELD_PATH } from '@/lib/queue/arms';
import type { Division } from '@/lib/queue/arms';

// Pièces des partitions (proto-gothique/work/refine/src/app.js, lignes 155–166 : shieldSvg).
const CHARGE: Record<Division, (b: string) => JSX.Element> = {
  pale: (b) => <rect x="6.5" y="0" width="7" height="16" fill={b}/>,
  chevron: (b) => <path d="M0 12.5L6.5 5l6.5 7.5V9L6.5 1.5 0 9z" fill={b}/>,
  bend: (b) => <path d="M-1 3L3 -1l14 14-4 4z" fill={b}/>,
  fess: (b) => <rect x="0" y="5.2" width="14" height="4" fill={b}/>,
  quarterly: (b) => <><rect x="6.5" y="0" width="7" height="7" fill={b}/><rect x="0" y="7" width="6.5" height="9" fill={b}/></>,
  bordure: (b) => <path d="M3 3h7v4c0 2-1.6 3.4-3.5 4.3C4.6 10.4 3 9 3 7z" fill={b}/>,
};

/** Blason d'un demandeur (13 × 15 px, décoratif) : tiré de son id Discord, jamais de rouge (lib/queue/arms.ts). */
export default function Shield({ id }: { id: string | null | undefined }) {
  const clip = `shield-${useId().replace(/:/g, '')}`;
  const { d, a, b } = armsOf(id);
  return (
    <svg className="shield" viewBox="0 0 13 15" aria-hidden="true" focusable="false">
      <clipPath id={clip}><path d={SHIELD_PATH}/></clipPath>
      <g clipPath={`url(#${clip})`}><rect width="14" height="16" fill={a}/>{CHARGE[d](b)}</g>
      <path d={SHIELD_PATH} fill="none" stroke="#060403" strokeWidth="1.1"/>
      <path d="M1.9 1.9h9.2" stroke="rgb(255 255 255 / .35)" strokeWidth=".6"/>
    </svg>
  );
}
