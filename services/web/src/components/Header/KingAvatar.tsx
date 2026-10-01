'use client';

import { useEffect, useState } from 'react';
import { discordAvatar } from '@/lib/format';
import { t } from '@/theme/copy';
import type { UserInfo } from '@/lib/types';

export function kingName(me: UserInfo | null): string {
  return me?.global_name || me?.display_name || me?.username || '';
}

/**
 * Avatar Discord du Roi (l'utilisateur connecté), coiffé de la couronne (rendu Blender) en haut à droite.
 * Le Roi, c'est lui : la couronne ne va jamais sur Greg. Surtitre « Sa Majesté » et pseudo à côté
 * quand la place le permet (header.css).
 */
export default function KingAvatar({ me }: { me: UserInfo }) {
  const src = discordAvatar(me, 96);
  const name = kingName(me);
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [src]);

  return (
    <>
      <span className="king" title={t('header.account.crownTip', { theKing: 'Votre Majesté' })}>
        <span className="avatar" aria-hidden="true">
          {src && !broken
            ? <img src={src} alt="" width={34} height={34} decoding="async" onError={() => setBroken(true)}/>
            : (name.trim()[0] || '?').toUpperCase()}
        </span>
        <img className="crown" src="/gothique/crown-badge-64.webp"
          srcSet="/gothique/crown-badge-64.webp 1x, /gothique/crown-badge-128.webp 2x"
          alt="" width={24} height={24} decoding="async" aria-hidden="true"/>
      </span>
      <span className="king-id" aria-hidden="true">
        <small>{t('header.account.kicker')}</small>
        <b>{name}</b>
      </span>
    </>
  );
}
