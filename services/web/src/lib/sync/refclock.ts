/**
 * Horloge de référence du son (spec synchro son/vidéo §3, §6.1). Une ancre {play_id, status, position_ms, at} :
 * `at` est l'heure de l'API (ms epoch) de l'échantillon, relay_at_ms. Elle n'est recalée que sur un changement de
 * play_id ou de statut, ou quand un échantillon s'écarte de plus de REANCHOR_MS de la prédiction : les ticks et les
 * relectures REST ne la font plus sauter. Un échantillon plus ancien que l'ancre est ignoré.
 * Sans bloc `clock` (ancien bot), ou sans relay_at_ms (ancienne API pendant un déploiement : ses ticks arrivent sans
 * `clock`, et sampled_at_ms est l'horloge du bot, pas la sienne) : mode compatibilité, ancre à la réception (`at` =
 * heure de l'API à la réception), recalée à chaque état, comme avant. Pur, sans import runtime (tests/refclock.test.mjs).
 */

export type ClockStatus = 'idle' | 'loading' | 'playing' | 'paused' | 'stalled';
/** Un échantillon, et l'ancre qu'il devient. position_ms null : aucun son encore (idle, loading). */
export type ClockSample = { play_id: string | null; status: ClockStatus; position_ms: number | null; at: number; compat: boolean };
export type Anchor = ClockSample;
/** stale : plus ancien que l'ancre, ignoré ; kept : conforme à la prédiction ; anchored : nouvelle ancre. */
export type Ingest = 'stale' | 'kept' | 'anchored';

export const REANCHOR_MS = 40;
const STATUSES: readonly string[] = ['idle', 'loading', 'playing', 'paused', 'stalled'];

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const truthy = (v: unknown): boolean => v === true || v === 1 || v === '1' || v === 'true';

/**
 * Échantillon d'un état reçu (REST /playlist, socket playlist_update, tick `only_elapsed`). `recvNow` : heure de l'API
 * à la réception (mode compatibilité). null : état périmé (contrat C3) ou rien de lisible.
 */
export function clockSampleOf(payload: any, recvNow: number): ClockSample | null {
  const root = payload && typeof payload === 'object' ? payload : null;
  if (!root || root.ok === false || root.stale === true) return null;
  const p = root.state || root.pm || root.data || root;
  if (!p || typeof p !== 'object') return null;
  const c = p.clock;
  if (c && typeof c === 'object' && STATUSES.includes(c.status)) {
    // sans relay_at_ms : ancienne API, états datés et ticks sans clock alterneraient (vue et régulateur relancés)
    const at = num(p.relay_at_ms);
    if (at != null) {
      return {
        play_id: typeof c.play_id === 'string' ? c.play_id : null,
        status: c.status as ClockStatus,
        position_ms: num(c.position_ms),
        at,
        compat: false,
      };
    }
  }
  // compatibilité : secondes entières, ancrées à la réception
  const sec = num(Number(p.progress?.elapsed ?? p.position ?? p.elapsed ?? 0));
  if (sec == null) return null;
  const idle = !p.only_elapsed && !(p.current || p.now_playing);
  const paused = truthy(p.is_paused ?? p.paused);
  return { play_id: null, status: idle ? 'idle' : paused ? 'paused' : 'playing', position_ms: Math.max(0, sec) * 1000, at: recvNow, compat: true };
}

/** Position (ms) prédite par l'ancre à l'heure `t` de l'API : avance en lecture, figée sinon ; null sans son. */
export function predict(a: Anchor, t: number): number | null {
  if (a.position_ms == null) return null;
  return a.status === 'playing' ? Math.max(0, a.position_ms + (t - a.at)) : a.position_ms;
}

export interface RefClock {
  ingest(s: ClockSample): Ingest;
  /** Position du son (ms) à l'heure `serverNow` de l'API ; null sans ancre ou sans son. */
  positionAt(serverNow: number): number | null;
  anchor(): Anchor | null;
  reset(): void;
}

export function createRefClock(): RefClock {
  let a: Anchor | null = null;
  return {
    ingest(s) {
      const both = a !== null && !a.compat && !s.compat;
      if (both && s.at < (a as Anchor).at) return 'stale';
      if (both && s.play_id === (a as Anchor).play_id && s.status === (a as Anchor).status) {
        const p = predict(a as Anchor, s.at);
        if (s.position_ms == null ? p == null : p != null && Math.abs(s.position_ms - p) <= REANCHOR_MS) return 'kept';
      }
      a = { ...s };
      return 'anchored';
    },
    positionAt: (t) => (a ? predict(a, t) : null),
    anchor: () => a,
    reset() { a = null; },
  };
}

/** Ce que la page suit de l'horloge (store) : play_id, statut, mode, et le lien du titre joué sous ce play_id. */
export type ClockView = { playId: string | null; status: ClockStatus | null; compat: boolean; url: string | null };
export const NO_CLOCK: ClockView = { playId: null, status: null, compat: false, url: null };

/**
 * Vue après un échantillon accepté. `url` : lien du titre d'un état complet (null : aucun titre) ; undefined pour un
 * tick (sans titre) : le lien reste celui du même play_id, inconnu pour un autre. Même objet si rien ne change.
 */
export function clockViewOf(prev: ClockView, a: Anchor | null, url?: string | null): ClockView {
  if (!a) return NO_CLOCK;
  const u = url !== undefined ? url : a.play_id === prev.playId ? prev.url : null;
  if (prev.playId === a.play_id && prev.status === a.status && prev.compat === a.compat && prev.url === u) return prev;
  return { playId: a.play_id, status: a.status, compat: a.compat, url: u };
}
