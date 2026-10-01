/**
 * Ce que montre la file (DESIGN §12.5) : heure estimée de chaque titre, fin de la file, « Souvent demandés ici »,
 * moment relatif de l'historique. Pur, sans import runtime (tests/queue-view.test.mjs).
 */
import type { Track } from '../types';

export type Eta = { key: string; next: boolean; mins: number | null };

/** Minutes avant chaque titre : le reste du titre en cours, puis les durées cumulées. null après un titre sans durée. */
export function queueEtas(queue: readonly Pick<Track, 'key' | 'duration'>[], remaining: number): Eta[] {
  let acc: number | null = Math.max(0, remaining || 0);
  return queue.map((t, i) => {
    const out = { key: t.key, next: i === 0, mins: acc == null ? null : Math.max(1, Math.round(acc / 60)) };
    acc = acc == null || t.duration == null || !Number.isFinite(t.duration) ? null : acc + Math.max(0, t.duration);
    return out;
  });
}

/** Durée connue de la file (s). */
export const queueSeconds = (queue: readonly Pick<Track, 'duration'>[]): number =>
  queue.reduce((s, t) => s + (t.duration != null && Number.isFinite(t.duration) ? Math.max(0, t.duration) : 0), 0);

const NBSP = ' ';

/** Durée longue du deck (`_meta.tokens.dur`) : « 47 min », « 1 h 05 ». */
export function fmtLong(sec: number): string {
  const m = Math.max(0, Math.round((sec || 0) / 60));
  return m < 60 ? `${m}${NBSP}min` : `${Math.floor(m / 60)}${NBSP}h${NBSP}${String(m % 60).padStart(2, '0')}`;
}

/** Heure d'horloge à la française : « 22 h 47 ». */
export function clockText(d: Date): string {
  return `${d.getHours()}${NBSP}h${NBSP}${String(d.getMinutes()).padStart(2, '0')}`;
}

/** Fin de la file : maintenant + reste du titre en cours + durées de la file. */
export const endsAt = (nowMs: number, remaining: number, queue: readonly Pick<Track, 'duration'>[]): Date =>
  new Date(nowMs + (Math.max(0, remaining || 0) + queueSeconds(queue)) * 1000);

export type HistoryItem = {
  url?: string; title?: string; artist?: string; thumb?: string | null; duration?: number | null; provider?: string;
  play_count?: number; last_played?: number; last_played_by?: string;
};

// Même vidéo YouTube sous deux formes d'url (youtu.be, watch?v=, &list=…) : même titre.
function sameAs(url: string | undefined): string {
  const u = url || '';
  const m = u.match(/(?:v=|\/shorts\/|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return m ? `yt:${m[1]}` : u;
}

/** « Souvent demandés ici » : les plus joués qui ne sont ni en lecture ni dans la file (3 au plus). */
export function oftenAsked(top: readonly HistoryItem[], queue: readonly Pick<Track, 'url'>[], currentUrl: string | null | undefined, n = 3): HistoryItem[] {
  const taken = new Set([currentUrl, ...queue.map((t) => t.url)].filter(Boolean).map((u) => sameAs(u as string)));
  const out: HistoryItem[] = [];
  for (const it of top) {
    const k = sameAs(it.url);
    if (!it.url || taken.has(k)) continue;
    taken.add(k);
    out.push(it);
    if (out.length === n) break;
  }
  return out;
}

export type Ago = { unit: 'now' | 'min' | 'h' | 'yesterday' | 'd'; n: number };

/** Moment relatif d'une écoute (`last_played`, secondes epoch) : clé de `history.ago.*` (theme/copy.extra.ts). */
export function agoOf(lastPlayedSec: number | undefined, nowMs: number): Ago | null {
  if (!lastPlayedSec || !Number.isFinite(lastPlayedSec)) return null;
  const s = Math.max(0, nowMs / 1000 - lastPlayedSec);
  if (s < 60) return { unit: 'now', n: 0 };
  if (s < 3600) return { unit: 'min', n: Math.floor(s / 60) };
  if (s < 86400) return { unit: 'h', n: Math.floor(s / 3600) };
  if (s < 2 * 86400) return { unit: 'yesterday', n: 1 };
  return { unit: 'd', n: Math.floor(s / 86400) };
}

/** Méta du deck dont le demandeur est inconnu (« 14 écoutes · ») : sans le point final. */
export const dropEmptyTail = (s: string): string => s.replace(/\s*·\s*$/, '');
