/**
 * Régulateur de la vidéo muette (spec synchro son/vidéo §6.1, §6.2). Écart = position vidéo − cible (s) : en avance,
 * la vidéo ralentit ; en retard, elle accélère. YouTube applique 0,90 / 0,95 / 1,05 / 1,10 sans voile ni mise en
 * tampon (sondé) ; au-delà de SEEK_S, saut sous le poster, sans surcompensation fixe. Pur, sans import runtime
 * (tests/controller.test.mjs).
 */

export const CTL_TICK_MS = 250;            // boucle à 4 Hz
export const DEAD_S = 0.04;                // zone morte : vitesse ×1
export const HYST_S = 0.015;               // un recalage en cours finit sous 15 ms
export const NUDGE_MAX_S = 0.3;            // jusqu'ici ×0,95 / ×1,05, puis ×0,90 / ×1,10
export const SEEK_S = 2;                   // au-delà : saut
export const SEEK_SETTLE_MS = 1000;        // un saut à la fois : le temps que YouTube reparte
export const HOLD_MS = 3000;               // après une reprise, un blocage, un nouveau play_id : le client Discord se recale
export const NORATE_SEEK_S = 0.25, NORATE_GAP_MS = 10_000;   // vitesse non confirmée par YouTube : sauts seuls
export const COMPAT_SEEK_S = 1.2, COMPAT_GAP_MS = 15_000;    // ancien bot (positions à la seconde) : l'ancien régime
export const RATE_CONFIRM_MS = 600;        // délai avant de lire getPlaybackRate()
const SLOW = 0.95, SLOWER = 0.9, FAST = 1.05, FASTER = 1.1;

export type CtlState = { rate: number; lastSeekAt: number };
export const CTL_INIT: CtlState = { rate: 1, lastSeekAt: -Infinity };
export type Decision = { rate: number } | { seek: number };
/**
 * target, current : secondes (cible = son + réglage ; current = getCurrentTime()) ; now, holdUntil : performance.now().
 * rateOk : YouTube a confirmé les vitesses ; compat : pas de bloc clock (ancien bot).
 */
export type DecideInput = {
  target: number; current: number; state: CtlState; rateOk: boolean; holdUntil: number; now: number; compat?: boolean;
};

/** Décision du régulateur : { rate }, { seek } ou null (rien à faire). */
export function decide(i: DecideInput): Decision | null {
  const { target, current, state, now } = i;
  if (!Number.isFinite(target) || !Number.isFinite(current)) return null;
  if (now < i.holdUntil) return state.rate !== 1 ? { rate: 1 } : null;
  const err = current - target;
  const a = Math.abs(err);
  if (i.compat || !i.rateOk) {
    if (state.rate !== 1) return { rate: 1 };
    const thr = i.compat ? COMPAT_SEEK_S : NORATE_SEEK_S;
    const gap = i.compat ? COMPAT_GAP_MS : NORATE_GAP_MS;
    return a > thr && now - state.lastSeekAt >= gap ? { seek: Math.max(0, target) } : null;
  }
  if (a > SEEK_S) return now - state.lastSeekAt >= SEEK_SETTLE_MS ? { seek: Math.max(0, target) } : null;
  let want = 1;
  if (a > NUDGE_MAX_S) want = err > 0 ? SLOWER : FASTER;
  else if (a >= DEAD_S || (state.rate !== 1 && a >= HYST_S)) want = err > 0 ? SLOW : FAST;
  return want === state.rate ? null : { rate: want };
}

/** État du régulateur après une décision appliquée. */
export function afterDecision(s: CtlState, d: Decision | null, now: number): CtlState {
  if (!d) return s;
  return 'seek' in d ? { ...s, lastSeekAt: now } : { ...s, rate: d.rate };
}

type HoldKey = { playId: string | null; status: string | null };
/** Fin de l'attente : HOLD_MS à chaque entrée en lecture (reprise, fin de blocage, départ) ou nouveau play_id. */
export function nextHold(prev: HoldKey | null, next: HoldKey, now: number, hold: number): number {
  if (next.status !== 'playing') return hold;
  if (prev && prev.status === 'playing' && prev.playId === next.playId) return hold;
  return now + HOLD_MS;
}

/** Vitesse demandée confirmée par getPlaybackRate() ? 'wait' avant RATE_CONFIRM_MS ; 'ok' sans demande en cours. */
export function rateCheck(asked: { rate: number; at: number } | null, reported: number | undefined, now: number): 'wait' | 'ok' | 'failed' {
  if (!asked) return 'ok';
  if (now - asked.at < RATE_CONFIRM_MS) return 'wait';
  return typeof reported === 'number' && Math.abs(reported - asked.rate) < 0.001 ? 'ok' : 'failed';
}

type GateClock = { playId: string | null; status: string | null; compat: boolean };
/**
 * Démarrage gardé : charger `videoId` maintenant ? Avec bloc clock, seulement quand le bot joue vraiment ce titre
 * (statut playing, `clockVideo` = vidéo du lien de ce play_id) sous un play_id pas encore chargé. Sans bloc clock
 * (ancien bot, ou aucun état reçu), dès que le titre change, comme avant.
 */
export function gateLoad(c: GateClock, clockVideo: string | null, videoId: string | null,
  loaded: { id: string | null; playId: string | null }): boolean {
  if (!videoId) return false;
  if (c.compat || c.status === null) return loaded.id !== videoId;
  return c.status === 'playing' && clockVideo === videoId && (loaded.id !== videoId || loaded.playId !== c.playId);
}
