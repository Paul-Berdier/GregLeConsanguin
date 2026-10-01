'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { NightKind } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';

/** « Ajouter un titre » : donne le focus à la recherche de l'en-tête. */
function focusSearch(): void {
  document.querySelector<HTMLInputElement>('.top .field input')?.focus();
}

/**
 * La nuit (spec §4) : rien en lecture, chargement ou déconnecté. La rosace entière est au clair de lune ;
 * son oculus porte la couronne qui attend le Roi (rien en lecture), la couronne qui tourne (chargement) ou
 * le portrait de Greg en bonnet de valet (déconnecté). Greg ne porte jamais la couronne. Styles : night.css.
 */
export default function NightState({ kind, afterDay = false }: { kind: NightKind; afterDay?: boolean }) {
  const after = afterDay ? 'day' : undefined;   // après le jour, le texte attend la rose (night.css)
  // Réplique tirée au montage côté client seulement (pas d'écart d'hydratation).
  const [seed, setSeed] = useState(0);
  useEffect(() => { setSeed(Math.floor(Math.random() * 1e6)); }, [kind]);

  if (kind === 'loading') {
    return (
      <div className="night" data-kind="loading" role="status" data-after={after}>
        <div className="vl-inner">
          <div className="heart">
            <picture className="loader">
              <source srcSet="/gothique/crown-still-128.avif" media="(prefers-reduced-motion: reduce)"/>
              <img src="/gothique/crown-turn-128.avif" alt="" width={96} height={96} decoding="async"/>
            </picture>
          </div>
          <p className="vl-body">{t('loading.boot.text')}</p>
          <p className="quip" aria-hidden="true">{quip('loading.boot', seed)}</p>
        </div>
      </div>
    );
  }

  if (kind === 'out') {
    return (
      <div className="night" data-kind="out" data-after={after}>
        <div className="vl-inner">
          <div className="heart valet">
            <span className="portrait"><img src="/gothique/greg-face-192.webp" alt={t('brand.portraitAlt')} width={150} height={150} decoding="async"/></span>
            <img className="cap" src="/gothique/jester-cap-256.webp" srcSet="/gothique/jester-cap-256.webp 1x, /gothique/jester-cap-512.webp 2x"
              alt="" width={128} height={128} decoding="async"/>
          </div>
          <p className="vl-kicker">{t('auth.kicker')}</p>
          <h2 className="vl-title">{t('auth.title')}</h2>
          <p className="vl-body">{t('auth.body')}</p>
          <a className="btn-solid" href={api.getLoginUrl()}>{t('auth.cta')}</a>
          <p className="vl-small">{t('auth.privacy')}</p>
          <p className="quip" aria-hidden="true">{quip('auth', seed)}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="night" data-kind="empty" data-after={after}>
      <div className="vl-inner">
        <div className="heart"><img className="throne" src="/gothique/crown-320.webp" alt="" width={150} height={150} decoding="async"/></div>
        <h2 className="vl-title">{t('now.idle.title')}</h2>
        <p className="vl-body">{t('now.idle.body')}</p>
        <p className="quip" aria-hidden="true">{quip('now.idle', seed)}</p>
        <button type="button" className="btn-ghost" onClick={focusSearch}>{t('now.idle.cta')}</button>
      </div>
    </div>
  );
}
