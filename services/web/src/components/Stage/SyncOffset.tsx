'use client';

import { useId } from 'react';
import { usePopover } from '@/components/Header/GuildPicker';
import { OFFSET_MAX, OFFSET_MIN, OFFSET_STEP, fmtOffset } from '@/lib/stage/cover';
import { t } from '@/theme/copy';

/**
 * Réglage « Synchro vidéo » : décale l'image par rapport au son de Discord (−10 à +10 s, pas de 0,5 s).
 * Popover plaque hors de la vidéo (tech.md §5.4 : jamais de flou d'arrière-plan sur l'iframe).
 */
export default function SyncOffset({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const { open, setOpen, btnRef, wrapProps } = usePopover();
  const popId = useId();
  const helpId = useId();
  const rangeId = useId();
  const shown = fmtOffset(value);

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
          <input id={rangeId} type="range" min={OFFSET_MIN} max={OFFSET_MAX} step={OFFSET_STEP} value={value}
            aria-valuetext={shown} aria-describedby={helpId} onChange={(e) => onChange(Number(e.target.value))}/>
        </div>
        <p className="sync-help" id={helpId}>{t('now.sync.help')}</p>
        <button type="button" className="sync-reset" disabled={value === 0} onClick={() => onChange(0)}>{t('now.sync.reset')}</button>
      </div>
    </div>
  );
}
