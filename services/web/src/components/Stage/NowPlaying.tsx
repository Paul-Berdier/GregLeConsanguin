'use client';

import { useEffect } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { kingName } from '@/components/Header/KingAvatar';
import { parseTitle } from '@/lib/titles';
import { kickerKey, kingSealSrc, requesterKeys, requesterOf, seedOf } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';

/** Id du titre du morceau : il nomme l'horloge (role=progressbar, aria-labelledby). */
export const NOW_TITLE_ID = 'now-title';

/**
 * Ce qui joue, sous le portail : surtitre (état + réplique de Greg), titre en Grenze, artiste et demandeur.
 * Le Roi, c'est l'utilisateur : son propre titre porte son sceau et « Demandé par vous ».
 * Les emplacements gardent leur hauteur sans titre (la mise en page de la scène n'en dépend pas).
 * Styles : now.css.
 */
export default function NowPlaying() {
  const current = useStore((s) => s.player.current);
  const paused = useStore((s) => s.player.paused);
  const repeat = useStore((s) => s.player.repeat);
  const me = useStore((s) => s.me);
  const parsed = current ? parseTitle(current.title, current.artist) : null;
  const song = parsed?.song || current?.title || '';

  useEffect(() => {
    document.title = current
      ? t(paused ? 'brand.docTitle.paused' : 'brand.docTitle.playing', { title: song })
      : t('brand.docTitle.idle');
  }, [current, paused, song]);

  if (!current || !parsed) {
    return (
      <div className="now-text" aria-hidden="true">
        <div className="kicker"/><div className="title-slot"/><div className="meta-slot"/>
      </div>
    );
  }

  const req = requesterOf(current.addedBy, me?.id);
  const keys = requesterKeys(req);
  const vars = req.kind === 'other' ? { name: req.name } : undefined;
  const q = keys.quips ? quip(keys.quips, seedOf(current.url || current.title), vars) : null;

  return (
    <div className="now-text">
      <div className="kicker">
        <span className="eq" aria-hidden="true"><i/><i/><i/></span>
        <span className="kk">{t(kickerKey({ paused, repeat }))}</span>
        {q && <span className="kq quip" aria-hidden="true">— {q}</span>}
      </div>
      <h2 className="title-slot" id={NOW_TITLE_ID} title={current.title}>{song}</h2>
      <p className="meta-slot">
        {parsed.artist && <><span className="artist">{parsed.artist}</span><span className="dot-sep" aria-hidden="true"/></>}
        <span className="by">
          {req.kind === 'mine' && <img className="seal" src={kingSealSrc(kingName(me))} alt="" width={20} height={20} decoding="async"/>}
          {t(keys.plain, vars)}
        </span>
      </p>
    </div>
  );
}
