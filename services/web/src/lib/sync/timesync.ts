/**
 * Mesure de l'horloge de l'API (spec synchro son/vidéo §3, §6.1) : socket time_sync {t0} → {t0, ts}.
 * t0 et t1 : horloge du client (performance.now(), ms) ; ts : horloge murale de l'API (ms epoch).
 * Un échantillon donne offset = ts − (t0 + t1) / 2 et rtt = t1 − t0 ; on garde les TS_KEEP derniers et on retient
 * celui dont l'aller-retour est le plus court (le moins bruité). Pur, sans import runtime (tests/timesync.test.mjs).
 */

export type SyncSample = { offset: number; rtt: number };

export const TS_KEEP = 8;
export const TS_MAX_RTT_MS = 2000;   // au-delà : rejeté (aberrant)

/** Échantillon (t0, ts, t1), ou null s'il est illisible ou aberrant (aller-retour négatif ou > TS_MAX_RTT_MS). */
export function sampleOf(t0: number, ts: number, t1: number): SyncSample | null {
  if (![t0, ts, t1].every((v) => typeof v === 'number' && Number.isFinite(v))) return null;
  const rtt = t1 - t0;
  if (rtt < 0 || rtt > TS_MAX_RTT_MS) return null;
  return { offset: ts - (t0 + t1) / 2, rtt };
}

export interface TimeSync {
  /** Ajoute une mesure ; false si elle est rejetée. */
  add(t0: number, ts: number, t1: number): boolean;
  /** Échantillon retenu (aller-retour le plus court des TS_KEEP derniers), null sans mesure. */
  best(): SyncSample | null;
  /** Heure de l'API vue d'ici (ms epoch) pour un performance.now() donné ; null sans mesure. */
  serverNow(perfNow: number): number | null;
  reset(): void;
}

export function createTimeSync(): TimeSync {
  let samples: SyncSample[] = [];
  const best = (): SyncSample | null => samples.reduce<SyncSample | null>((b, s) => (!b || s.rtt < b.rtt ? s : b), null);
  return {
    add(t0, ts, t1) {
      const s = sampleOf(t0, ts, t1);
      if (!s) return false;
      samples = [...samples, s].slice(-TS_KEEP);
      return true;
    },
    best,
    serverNow(perfNow) {
      const b = best();
      return b ? perfNow + b.offset : null;
    },
    reset() { samples = []; },
  };
}
