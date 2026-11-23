'use client';

import { memo } from 'react';
import type { HistoryItem } from '@/lib/queue/view';
import { parseTitle } from '@/lib/titles';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import Shield from '@/components/Queue/Shield';
import { thumbOf } from '@/components/Queue/QueueRow';
import { HEART } from '@/components/Library/glyphs';

const PLUS = <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>;

export type HistoryRowProps = {
  item: HistoryItem;
  /** Rang dans « Plus joués » (1 à 3 : doré) ; 0 : pas de rang (Récents, Souvent demandés). */
  rank: number;
  /** « 14 écoutes », « il y a 3 h ». */
  meta: string;
  /** Demandeur connu (« vous », un courtisan de la file) ; vide : ni blason ni nom. */
  byName: string;
  variant: 'hrow' | 'srow';
  picked: boolean;
  /** Parmi les coups de cœur du Roi (chansonnier, useLibrary) : son cœur est pressé et reste visible. */
  liked: boolean;
  /** Tabindex itinérant (useRequeueList, useRoving) : 0 pour la ligne active de la liste, -1 pour les autres. */
  tabIndex: 0 | -1;
};

/**
 * Une ligne de l'historique ou de « Souvent demandés ici » (app.js, lignes 1209–1219 : histRow) : rang
 * (les trois premiers dorés), pochette, titre nettoyé, méta, « + » pour remettre dans la file.
 * Clic : sélection ; double-clic, « + » : remettre ; le cœur : les coups de cœur du Roi (délégués à la liste,
 * useRequeue). Styles : history.css.
 * Clavier : la ligne est l'arrêt de Tab, Entrée la remet dans la file, J bascule son cœur ; « + » et le cœur restent hors
 * de la tabulation. Le cœur pressé se dit dans le nom de la ligne.
 */
function HistoryRow({ item, rank, meta, byName, variant, picked, liked, tabIndex }: HistoryRowProps) {
  const p = parseTitle(item.title, item.artist);
  const song = p.song || item.title || '—';
  const thumb = thumbOf({ thumb: item.thumb, url: item.url });
  return (
    <li className={`row ${variant}`} data-url={item.url} data-picked={picked || undefined}
      aria-label={[song, p.artist, meta, liked && tx('library.like.state')].filter(Boolean).join(', ')} tabIndex={tabIndex}>
      <div className="card">
        <span className={`rank tnum${rank && rank <= 3 ? ' top' : ''}`} aria-hidden="true">{rank || ''}</span>
        <div className="thumb"><div className="im">{thumb && <img src={thumb} alt="" loading="lazy" decoding="async" draggable={false}/>}</div></div>
        <div className="meta">
          <div className="t" title={item.title}>{song}</div>
          <div className="a">
            <span className="nm">{[p.artist, meta].filter(Boolean).join(' · ')}</span>
            {byName && <><span className="dot-sep" aria-hidden="true"/><Shield id={item.last_played_by}/><span className="by">{byName}</span></>}
          </div>
        </div>
        <button type="button" tabIndex={-1} className="like" data-act="like" aria-pressed={liked} aria-label={tx('library.like.aria', { title: song })}
          title={tx(liked ? 'library.like.remove' : 'library.like.add')}>{HEART}</button>
        <button type="button" tabIndex={-1} className="add" data-act="add" aria-label={t('history.requeue.ariaTitle', { title: song })} title={t('history.requeue.aria')}>{PLUS}</button>
      </div>
    </li>
  );
}

export default memo(HistoryRow);
