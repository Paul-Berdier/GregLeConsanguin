'use client';

import { memo } from 'react';
import type { Track } from '@/lib/types';
import { parseTitle } from '@/lib/titles';
import { extractVideoId, fmt } from '@/lib/format';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import Shield from './Shield';

// Icônes du prototype (app.js, lignes 168–177 : ICON.play, next, del, grip).
const GRIP = <svg viewBox="0 0 8 14" fill="currentColor" aria-hidden="true"><circle cx="2" cy="2" r="1.3"/><circle cx="6" cy="2" r="1.3"/><circle cx="2" cy="7" r="1.3"/><circle cx="6" cy="7" r="1.3"/><circle cx="2" cy="12" r="1.3"/><circle cx="6" cy="12" r="1.3"/></svg>;
const PLAY = <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13L18.5 12z"/></svg>;
const NEXT = <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.5h14"/><path d="M12 20V9.5"/><path d="M7.5 14L12 9.5l4.5 4.5"/></svg>;
const DEL = <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>;

/** Miniature « pochette » : celle du bot, sinon celle de la vidéo YouTube. */
export function thumbOf(x: { thumb?: string | null; thumbnail?: string | null; url?: string }): string | null {
  const id = extractVideoId(x.url);
  return x.thumb || x.thumbnail || (id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : null);
}

export type QueueRowProps = {
  item: Track;
  /** « À suivre », « dans 4 min », ou vide (durée inconnue avant). */
  eta: string;
  next: boolean;
  /** Titre du Roi : son sceau à son initiale sur la pochette, « vous » comme demandeur. */
  sealSrc: string | null;
  picked: boolean;
  leaving: boolean;
  /** Tabindex itinérant (QueuePanel, useRoving) : 0 pour la ligne active de la liste, -1 pour les autres. */
  tabIndex: 0 | -1;
};

/**
 * Une ligne de la file (DESIGN §12.5) : poignée 6 points, pochette (poignée elle aussi), titre nettoyé (le brut en
 * info-bulle), artiste, blason et demandeur, durée et heure estimée ; actions rapides sur une puce opaque.
 * Les clics sont délégués à la liste (QueuePanel : data-act). Styles : queue.css.
 * Clavier : la ligne est l'arrêt de Tab ; ses boutons restent hors de la tabulation (Entrée, Suppr et Alt+Début les
 * remplacent, DESIGN §12.7). Le sceau du Roi se charge en différé (QueuePanel le décode au premier temps mort).
 */
function QueueRow({ item, eta, next, sealSrc, picked, leaving, tabIndex }: QueueRowProps) {
  const p = parseTitle(item.title, item.artist);
  const song = p.song || item.title || '—';
  const mine = !!sealSrc;
  const who = mine ? t('queue.mine.label') : item.addedBy?.name || '';
  // Sans artiste, tx laisse « {artist} » en place et on retire ce segment : sinon on lirait « Titre, , votre titre ».
  const art: Record<string, string> = p.artist ? { artist: p.artist } : {};
  const raw = mine ? tx('queue.rowAriaMine', { title: song, ...art })
    : who ? tx('queue.rowAria', { title: song, ...art, name: who }) : tx('queue.rowAriaUnknown', { title: song, ...art });
  const label = p.artist ? raw : raw.replace(', {artist}', '');
  const thumb = thumbOf(item);
  return (
    <li className={`row${next ? ' next' : ''}`} data-key={item.key} data-leaving={leaving || undefined}
      data-picked={picked || undefined} aria-label={label} tabIndex={tabIndex}>
      <div className="card">
        <span className="grip" aria-hidden="true">{GRIP}</span>
        <div className="thumb">
          <div className="im">{thumb && <img src={thumb} alt="" loading="lazy" decoding="async" width={72} height={41} draggable={false}/>}</div>
          {sealSrc && <span className="seal" title={t('queue.mine.tip')}><img src={sealSrc} alt="" width={23} height={23} loading="lazy" decoding="async" draggable={false}/></span>}
        </div>
        <div className="meta">
          <div className="t" title={item.title}>{song}</div>
          <div className="a">
            {p.artist && <><span className="nm">{p.artist}</span><span className="dot-sep" aria-hidden="true"/></>}
            <Shield id={item.addedBy?.id}/>
            <span className="by">{who}</span>
          </div>
        </div>
        <div className="side tnum" aria-hidden="true"><span className="dur">{fmt(item.duration)}</span><span className="eta">{eta}</span></div>
        <div className="acts">
          <button type="button" tabIndex={-1} className="act" data-act="play" aria-label={t('queue.actions.playNowAria', { title: song })} title={t('queue.actions.playNow')}>{PLAY}</button>
          <button type="button" tabIndex={-1} className="act" data-act="next" aria-label={t('queue.actions.playNextAria', { title: song })} title={t('queue.actions.playNext')}>{NEXT}</button>
          <button type="button" tabIndex={-1} className="act del" data-act="del" aria-label={t('queue.actions.removeAria', { title: song })} title={t('queue.actions.remove')}>{DEL}</button>
        </div>
        <span className="flash" aria-hidden="true"/>
      </div>
    </li>
  );
}

export default memo(QueueRow);
