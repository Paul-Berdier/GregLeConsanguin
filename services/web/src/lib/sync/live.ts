/**
 * Les instances de la synchro son/vidéo pour la page : mesure de l'horloge de l'API (socket time_sync, lib/socket.ts)
 * et horloge de référence du son, nourrie par chaque état reçu (hooks/usePlayer.ts) et lue par le régulateur
 * (components/Stage/Portal.tsx).
 */
import { createRefClock } from './refclock';
import { createTimeSync } from './timesync';

export const timeSync = createTimeSync();
export const refClock = createRefClock();

/** Heure de l'API vue d'ici (ms epoch) ; avant la première mesure, l'horloge murale du navigateur. */
export const serverNow = (perfNow: number): number => timeSync.serverNow(perfNow) ?? performance.timeOrigin + perfNow;
