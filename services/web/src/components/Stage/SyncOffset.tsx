'use client';

import { useId, useRef } from 'react';
import { usePopover } from '@/components/Header/GuildPicker';
import { OFFSET_MAX, OFFSET_MIN, OFFSET_STEP, fmtOffset } from '@/lib/stage/cover';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';

/**
 * Réglage « Synchro vidéo » : le retard propre à Discord sur cet appareil (−3 à +3 s, pas de 50 ms). La vidéo y va
 * par le régulateur (vitesse, pas de saut brut). Popover plaque hors de la vidéo (tech.md §5.4 : jamais de flou
 * d'arrière-plan sur l'iframe).
 */
export default function SyncOffset({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const { open, setOpen, btnRef, wrapProps } = usePopover();
  const popId = useId();
  const helpId = useId();
  const rangeId = useId();
  const rangeRef = useRef<HTMLInputElement>(null);
  const shown = fmtOffset(value);
  // « Remettre à zéro » se désactive une fois cliqué : le focus passe au curseur avant, sinon il tomberait sur <body>
  // et Échap ne fermerait plus le popover
  const reset = () => { onChange(0); rangeRef.current?.focus(); };

  return (
    <div className="sync" {...wrapProps}>
      <button ref={btnRef} type="button" className="sync-btn" aria-haspopup="dialog" aria-expanded={open}
        aria-controls={popId} onClick={() => setOpen((o) => !o)}>
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><path d="M14 4.5v5M6 14.5v5"/></svg>
        {t('now.sync.button')}
        {value !== 0 && <span className="tnum">{shown}</span>}
      </button>
      <div id={popId} className="pop plaque sync-pop" role="dialog" aria-label={t('now.sync.label')} data-open={open}>
        {/* label lié par for/id : enveloppant, il nommerait l'<output> (premier élément « labelable »), pas le curseur */}
        <div className="sync-row">
          <label htmlFor={rangeId}>{t('now.sync.label')}</label>
          <output className="tnum" htmlFor={rangeId} aria-live="off">{t('now.sync.value', { value: shown })}</output>
          <input ref={rangeRef} id={rangeId} type="range" min={OFFSET_MIN} max={OFFSET_MAX} step={OFFSET_STEP} value={value}
            aria-valuetext={shown} aria-describedby={helpId} onChange={(e) => onChange(Number(e.target.value))}/>
        </div>
        <p className="sync-help" id={helpId}>{tx('sync.help')}</p>
        <button type="button" className="sync-reset" disabled={value === 0} onClick={reset}>{t('now.sync.reset')}</button>
      </div>
    </div>
  );
}
