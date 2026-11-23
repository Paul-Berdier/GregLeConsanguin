'use client';

import { libraryActions, useLibrary } from '@/hooks/useLibrary';
import { trackKey } from '@/lib/library';
import type { TrackLike } from '@/lib/library';
import { parseTitle } from '@/lib/titles';
import { tx } from '@/theme/copy.extra';
import { HEART } from './glyphs';

/**
 * Le cœur du Roi (bouton à bascule, aria-pressed) pour un titre hors d'une liste : celui en lecture (NowPlaying), et
 * la surcouche plein écran à l'intégration. Les lignes de la file et de l'historique ont le leur, délégué à leur liste
 * (data-act="like", hors de la tabulation). Libellé constant, l'état dit par aria-pressed ; l'info-bulle dit le geste.
 * Pressé : rempli de la lumière du morceau (styles du `className`, now.css pour .nbtn).
 */
export default function LikeButton({ track, className = 'nbtn' }: { track: TrackLike | null; className?: string }) {
  const k = track?.url ? trackKey(track.url) : '';
  const liked = useLibrary((s) => !!k && s.liked.has(k));
  const song = track ? parseTitle(track.title, track.artist).song || track.title || '' : '';
  return (
    <button type="button" className={className} disabled={!k} aria-pressed={liked}
      aria-label={tx('library.like.aria', { title: song })} title={tx(liked ? 'library.like.remove' : 'library.like.add')}
      onClick={() => { if (track) libraryActions.toggleLike(track); }}>
      {HEART}
    </button>
  );
}
