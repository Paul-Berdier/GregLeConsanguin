import { totalSeconds } from '@/lib/library';
import type { Library, LibraryTrack } from '@/lib/types';
import { fmtLong } from '@/lib/queue/view';
import { tx } from '@/theme/copy.extra';

const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** « 12 titres · 47 min », « 1 titre · 3 min », « 2 titres » (durées inconnues : pas de « 0 min »), « Aucun titre ». */
export function tracksMeta(tracks: readonly LibraryTrack[]): string {
  const n = tracks.length, s = totalSeconds(tracks);
  if (!n) return cap(tx('library.count.tracksNone'));
  return s >= 30 ? `${tx('library.count.tracks', { n })} · ${fmtLong(s)}` : tx('library.count.tracks', { n });
}

/** Sous-titre de l'onglet : « 12 coups de cœur · 3 playlists », « Aucun coup de cœur · 1 playlist ». */
export function librarySummary(lib: Library): string {
  const likes = lib.likes.length, lists = lib.playlists.length;
  const a = likes ? tx('library.count.likes', { n: likes }) : tx('library.count.likesNone');
  const b = lists ? tx('library.count.playlists', { n: lists }) : tx('library.count.playlistsNone');
  return cap(`${a} · ${b}`);
}
