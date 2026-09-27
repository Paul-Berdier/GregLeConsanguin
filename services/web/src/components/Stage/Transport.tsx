'use client';

import { useEffect, useId, useRef } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { usePopover } from '@/components/Header/GuildPicker';
import { seedOf } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';

const I = {
  stop: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="6.5" width="11" height="11"/></svg>,
  restart: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5.5v13"/><path d="M18.5 6.5v11L9.5 12z"/></svg>,
  skip: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5.5v13"/><path d="M5.5 6.5v11l9-5.5z"/></svg>,
  repeat: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M16.5 3.5l3 3-3 3"/><path d="M4.5 12V10a3.5 3.5 0 0 1 3.5-3.5h11"/><path d="M7.5 20.5l-3-3 3-3"/><path d="M19.5 12v2a3.5 3.5 0 0 1-3.5 3.5H5"/></svg>,
};

/**
 * Transport : tout arrêter (confirmé si la file a des titres), reprendre au début, lecture/pause
 * (une rondelle du verre du morceau, en --lumiere), suivant, boucle. Libellés : deck `controls.*`.
 * Les actions passent par usePlayer (les mises à jour optimistes arrivent à l'étape 3). Styles : now.css.
 */
export default function Transport() {
  const { player, togglePause, skip, stop, toggleRepeat, restartTrack } = usePlayer();
  const on = !!player.current;
  const queued = player.queue.length;
  const confirm = usePopover();
  const noRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Le dialogue d'arrêt met le focus sur le choix sûr (DESIGN §7).
  useEffect(() => { if (confirm.open) noRef.current?.focus(); }, [confirm.open]);
  // La file s'est vidée pendant la question (arrêt ou saut venu d'ailleurs, fin de file) : il n'y a plus
  // rien à confirmer, le dialogue se ferme et rend le focus au bouton (s'il est encore actif).
  const { open: confirmOpen, close: closeConfirm } = confirm;
  useEffect(() => { if (confirmOpen && !queued) closeConfirm(true); }, [confirmOpen, queued, closeConfirm]);

  const onStop = () => {
    if (!on && !queued) return;
    if (queued) confirm.setOpen((o) => !o);
    else stop().catch(() => {});
  };
  const confirmStop = () => { confirm.close(true); stop().catch(() => {}); };

  return (
    <div className="transport" role="group" aria-label={t('controls.group')}>
      <div className="stop-wrap" {...confirm.wrapProps}>
        <button ref={confirm.btnRef} type="button" className="tbtn" disabled={!on && !queued} onClick={onStop}
          aria-label={t('controls.stop.aria')} aria-haspopup={queued ? 'dialog' : undefined} aria-expanded={queued ? confirm.open : undefined}>
          {I.stop}<span className="tip plaque" aria-hidden="true">{t('controls.stop.tip')}</span>
        </button>
        <div className="pop plaque confirm" role="dialog" aria-labelledby={titleId} data-open={confirm.open}>
          <h3 id={titleId}>{t('confirm.stop.title')}</h3>
          <p>{t('confirm.stop.body', { n: queued })}</p>
          <p className="quip" aria-hidden="true">{quip('confirm.stop', seedOf(String(queued)))}</p>
          <div className="row-btns">
            <button ref={noRef} type="button" className="btn-ghost" onClick={() => confirm.close(true)}>{t('confirm.stop.cancel')}</button>
            <button type="button" className="btn-danger" onClick={confirmStop}>{t('confirm.stop.confirm')}</button>
          </div>
        </div>
      </div>
      <button type="button" className="tbtn" disabled={!on} onClick={() => restartTrack().catch(() => {})} aria-label={t('controls.restart.aria')}>
        {I.restart}<span className="tip plaque" aria-hidden="true">{t('controls.restart.tip')}</span>
      </button>
      <button type="button" className="tbtn main" disabled={!on} onClick={() => togglePause().catch(() => {})} aria-label={t(player.paused ? 'controls.play.aria' : 'controls.pause.aria')}>
        <svg className="ic-pause" data-shown={on && !player.paused} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6.5" y="4.8" width="4.2" height="14.4"/><rect x="13.3" y="4.8" width="4.2" height="14.4"/></svg>
        <svg className="ic-play" data-shown={!on || player.paused} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8.3 4.8v14.4L19.6 12z"/></svg>
        <span className="tip plaque" aria-hidden="true">{t(player.paused ? 'controls.play.tip' : 'controls.pause.tip')}</span>
      </button>
      <button type="button" className="tbtn" disabled={!on} onClick={() => skip().catch(() => {})} aria-label={t('controls.skip.aria')}>
        {I.skip}<span className="tip plaque" aria-hidden="true">{t('controls.skip.tip')}</span>
      </button>
      <button type="button" className="tbtn" disabled={!on} aria-pressed={player.repeat} onClick={() => toggleRepeat().catch(() => {})} aria-label={t('controls.repeat.aria')}>
        {I.repeat}<span className="tip plaque" aria-hidden="true">{t('controls.repeat.tip')}</span>
      </button>
    </div>
  );
}
