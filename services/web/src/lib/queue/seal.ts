/** Le Sceau (DESIGN §5, motion.md §6.5) : l'ajout du Roi attendu, reconnu à l'entrée de sa ligne. Pur (tests/seal.test.mjs). */
import type { Box } from '../stage/coronation';

export type SealExpect = { url: string | null; from: Box | null; thumb: string | null; at: number };
export const SEAL_TTL_MS = 10_000, SEAL_STAMP_DELAY_MS = 380, SEAL_FLIGHT_MS = 460;
// Mêmes formes que VIDEO_ID (links.ts, qui décide qu'un lien collé est une vidéo) : ?v=, /shorts/, /live/, /embed/, youtu.be/, /v/ /e/ /watch/
const YT_ID = /(?:[?&]v=|\/shorts\/|\/live\/|\/embed\/(?!videoseries)|youtu\.be\/|\.com\/(?:v|e|watch)\/)([A-Za-z0-9_-]{11})/;

export function sameTrack(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const ia = YT_ID.exec(a)?.[1], ib = YT_ID.exec(b)?.[1];
  return ia || ib ? ia === ib : a === b;
}

/** Un ajout attendu à la fois (le dernier l'emporte) ; url null (recherche tapée) : la prochaine ligne du Roi. */
export function createSealBook(ttl = SEAL_TTL_MS) {
  let wait: SealExpect | null = null;
  return {
    expect(e: SealExpect): void { wait = e; },
    take(row: { url?: string | null; mine: boolean }, now: number): SealExpect | null {
      const w = wait;
      if (!w || now - w.at > ttl) { wait = null; return null; }
      if (!row.mine || (w.url && !sameTrack(w.url, row.url))) return null;
      wait = null;
      return w;
    },
    clear(): void { wait = null; },
  };
}
export const sealBook = createSealBook();
