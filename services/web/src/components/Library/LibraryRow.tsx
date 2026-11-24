'use client';

import { memo } from 'react';
import { fmt } from '@/lib/format';
import { trackKey } from '@/lib/library';
import type { LibraryTrack } from '@/lib/types';
import { parseTitle } from '@/lib/titles';
import { thumbOf } from '@/components/Queue/QueueRow';
import { tx } from '@/theme/copy.extra';
import { DEL, PLUS } from './glyphs';

export type LibraryRowProps = {
  track: LibraryTrack;
  /** Rang dans la playlist (0 : le premier), affiché à partir de 1. */
  index: number;
  /** Ligne des coups de cœur : « Retirer » les retire des coups de cœur. */
  likes: boolean;
  picked: boolean;
  /** Tabindex itinérant (PlaylistView, useRoving) : 0 pour la ligne active de la liste, -1 pour les autres. */
  tabIndex: 0 | -1;
};

/**
 * Un titre d'une playlist ou des coups de cœur, au style de l'historique : rang, pochette, titre nettoyé (le brut en
 * info-bulle), artiste, durée ; au survol ou au focus, la puce d'actions de la file (queue.css) : « + » (dans la file,
 * avec Le Sceau) et « Retirer ». Clics délégués à la liste (data-act) ; ses boutons restent hors de la tabulation
 * (Entrée, Suppr les remplacent). `data-key` : l'identité du titre (trackKey), unique dans une playlist.
 */
function LibraryRow({ track, index, likes, picked, tabIndex }: LibraryRowProps) {
  const p = parseTitle(track.title, track.artist);
  const song = p.song || track.title || '—';
  const thumb = thumbOf({ thumb: track.thumb, url: track.url });
  return (
    <li className="row trow" data-key={trackKey(track.url)} data-picked={picked || undefined}
      aria-label={[song, p.artist].filter(Boolean).join(', ')} tabIndex={tabIndex}>
      <div className="card">
        <span className="rank tnum" aria-hidden="true">{index + 1}</span>
        <div className="thumb"><div className="im">{thumb && <img src={thumb} alt="" loading="lazy" decoding="async" width={72} height={41} draggable={false}/>}</div></div>
        <div className="meta">
          <div className="t" title={track.title}>{song}</div>
          <div className="a">{p.artist && <span className="nm">{p.artist}</span>}</div>
        </div>
        <div className="side tnum" aria-hidden="true"><span className="dur">{track.duration != null ? fmt(track.duration) : ''}</span></div>
        <div className="acts">
          <button type="button" tabIndex={-1} className="act" data-act="add" aria-label={tx('library.requeueAria', { title: song })} title={tx('library.requeue')}>{PLUS}</button>
          <button type="button" tabIndex={-1} className="act del" data-act="del" title={tx('library.remove')}
            aria-label={tx(likes ? 'library.unlikeAria' : 'library.removeAria', { title: song })}>{DEL}</button>
        </div>
      </div>
    </li>
  );
}

export default memo(LibraryRow);
