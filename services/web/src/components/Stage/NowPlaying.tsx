'use client';

import { useEffect, useRef } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { kingName } from '@/components/Header/KingAvatar';
import { parseTitle } from '@/lib/titles';
import { kickerKey, kingSealSrc, requesterKeys, requesterOf, seedOf } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';
import { useCeremony } from './coronation';
import { runGlint } from './glint';
import Swap from './Swap';

/** Id du titre du morceau : il nomme l'horloge (role=progressbar, aria-labelledby). */
export const NOW_TITLE_ID = 'now-title';

/**
 * Ce qui joue, sous le portail : surtitre (état + réplique de Greg), titre en Grenze, artiste et demandeur.
 * Le Roi, c'est l'utilisateur : son propre titre porte son sceau et « Demandé par vous ».
 * Les emplacements sont toujours rendus et gardent leur hauteur sans titre (la mise en page de la scène n'en dépend pas).
 * Au Couronnement (coronation.ts), titre et demandeur se croisent (Swap) selon le plan de la cérémonie, puis le reflet
 * d'or passe sur le titre (glint.ts) ; en vol, à l'atterrissage. Styles : now.css.
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

  const req = current ? requesterOf(current.addedBy, me?.id) : null;
  const keys = req ? requesterKeys(req) : null;
  const vars = req?.kind === 'other' ? { name: req.name } : undefined;
  const q = current && keys?.quips ? quip(keys.quips, seedOf(current.url || current.title), vars) : null;
  const cer = useCeremony();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const key = current?.key || '';
  const plan = cer && cer.key === key ? cer.plan : null;

  // reflet d'or, une fois par cérémonie ; en vol, à l'atterrissage (landed relance l'effet)
  useEffect(() => {
    if (!cer || cer.key !== key || cer.plan.glintAt == null || (cer.mode === 'flight' && !cer.landed)) return;
    const tm = setTimeout(() => { if (titleRef.current) runGlint(titleRef.current); }, cer.mode === 'flight' ? 0 : cer.plan.glintAt);
    return () => clearTimeout(tm);
  }, [cer, key]);

  return (
    <div className="now-text" aria-hidden={current ? undefined : true}>
      <div className="kicker">{current && <>
        <span className="eq" aria-hidden="true"><i/><i/><i/></span>
        <span className="kk">{t(kickerKey({ paused, repeat }))}</span>
        {q && <span className="kq quip" aria-hidden="true">— {q}</span>}
      </>}</div>
      <h2 className="title-slot" id={NOW_TITLE_ID} title={current?.title} ref={titleRef}>
        <Swap k={key} plan={plan} delay={plan?.titleDelay ?? 0}>{song}</Swap>
      </h2>
      <p className="meta-slot">
        <Swap k={key} plan={plan} delay={plan?.metaDelay ?? 0}>
          {parsed?.artist && <><span className="artist">{parsed.artist}</span><span className="dot-sep" aria-hidden="true"/></>}
          {req && keys && <span className="by">
            {req.kind === 'mine' && <img className="seal" src={kingSealSrc(kingName(me))} alt="" width={20} height={20} decoding="async"/>}
            {t(keys.plain, vars)}
          </span>}
        </Swap>
      </p>
    </div>
  );
}
