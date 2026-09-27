/**
 * Actions optimistes de la file et du transport (spec §5 ; tech.md §3.2 à §3.4).
 * Pur, sans import runtime (tests/optimistic.test.mjs).
 *
 * La page affiche `view = pending.reduce(applyMutation, server)` :
 * - `server` : le dernier état complet reçu (REST /playlist, socket playlist_update) ;
 * - `pending` : les ordres du Roi pas encore confirmés, par CLÉ de titre (jamais par index), donc
 *   rejouables sur un état plus récent. Chacun est idempotent ou conditionnel : le rejouer sur un état
 *   qui le contient déjà ne fait rien (pas de double saut, pas de clignotement).
 * Une seule requête en vol (le bot exécute les commandes d'un serveur une par une, dans l'ordre).
 * Les états reçus pendant ce temps, ou pendant un glisser, sont gardés en tampon (le dernier seulement)
 * et appliqués d'un coup quand l'action se termine : rien ne bouge sous la main du Roi.
 * Refus de l'API : la mutation est retirée, la vue revient à `server` (retour en arrière).
 */
import type { Snapshot, Track } from '../types';

export type MutationBody =
  | { kind: 'remove'; key: string }
  | { kind: 'move'; key: string; beforeKey: string | null }
  | { kind: 'playAt'; key: string; fromKey: string | null }
  | { kind: 'skip'; fromKey: string | null }
  | { kind: 'setPaused'; paused: boolean };

export type Mutation = MutationBody & { id: number; at: number; status: 'queued' | 'sent' | 'acked'; ackedAt?: number };

/** Un ordre accusé mais pas encore visible dans un état reçu est gardé au plus ce temps. */
export const ACK_GRACE_MS = 4000;
/** Un état reçu pendant une requête en vol attend au plus ce temps (un bot lent ne fige pas la page). */
export const HOLD_MAX_MS = 2500;

const idx = (q: Track[], key: string | null) => (key == null ? -1 : q.findIndex((t) => t.key === key));

// Position vivante de l'horloge (même calcul que livePosition, playerUtils.ts).
function live(s: Snapshot, now: number): number {
  const { pos, at, dur } = s.tickBase;
  const p = pos + (s.player.paused ? 0 : (now - at) / 1000);
  return dur > 0 ? Math.min(Math.max(p, 0), dur) : Math.max(0, p);
}

/** Indices de POST /player/move {src, dst} : le bot fait queue.insert(dst, queue.pop(src)). null : rien à faire. */
export function moveIndices(q: Track[], key: string, beforeKey: string | null): { src: number; dst: number } | null {
  const src = idx(q, key);
  if (src < 0) return null;
  const rest = q.filter((t) => t.key !== key);
  const b = beforeKey == null ? rest.length : idx(rest, beforeKey);   // null : fin de file
  if (b < 0) return null;   // ancre disparue : rien à envoyer, le titre garde sa place (comme applyMutation)
  return b === src ? null : { src, dst: b };
}

// Le titre `next` prend la scène : horloge à zéro, lecture.
function crown(s: Snapshot, next: Track | null, queue: Track[], at: number): Snapshot {
  const dur = next?.duration || 0;
  return {
    player: { ...s.player, current: next, queue, paused: !next, position: 0, duration: dur },
    tickBase: { pos: 0, at, dur },
  };
}

export function applyMutation(s: Snapshot, m: Mutation): Snapshot {
  const q = s.player.queue;
  switch (m.kind) {
    case 'remove':
      return idx(q, m.key) < 0 ? s : { ...s, player: { ...s.player, queue: q.filter((t) => t.key !== m.key) } };
    case 'move': {
      const i = idx(q, m.key);
      if (i < 0) return s;                       // joué ou retiré entre-temps
      const rest = q.filter((_, k) => k !== i);
      const b = m.beforeKey == null ? rest.length : idx(rest, m.beforeKey);
      const to = b < 0 ? Math.min(i, rest.length) : b;   // ancre disparue : le titre garde sa place
      if (to === i) return s;
      rest.splice(to, 0, q[i]);
      return { ...s, player: { ...s.player, queue: rest } };
    }
    case 'playAt': {
      // conditionnel : seulement si la scène est encore celle du clic
      if ((s.player.current?.key ?? null) !== m.fromKey) return s;
      const i = idx(q, m.key);
      return i < 0 ? s : crown(s, q[i], q.filter((_, k) => k !== i), m.at);
    }
    case 'skip':
      // déjà passé côté bot : jamais de double saut
      if (!s.player.current || s.player.current.key !== m.fromKey) return s;
      return crown(s, q[0] ?? null, q.slice(1), m.at);
    case 'setPaused': {
      if (s.player.paused === m.paused || !s.player.current) return s;
      const pos = live(s, m.at);   // l'horloge s'arrête (ou repart) à l'instant du clic
      return { player: { ...s.player, paused: m.paused, position: pos }, tickBase: { ...s.tickBase, pos, at: m.at } };
    }
  }
}

export const viewOf = (server: Snapshot, pending: readonly Mutation[]): Snapshot => pending.reduce(applyMutation, server);

/** Vrai quand l'état reçu montre déjà l'effet de la mutation. */
export function isSatisfied(m: Mutation, s: Snapshot): boolean {
  const q = s.player.queue;
  switch (m.kind) {
    case 'remove': return idx(q, m.key) < 0;
    case 'move': {
      const i = idx(q, m.key);
      if (i < 0) return true;
      if (m.beforeKey == null) return i === q.length - 1;
      const b = idx(q, m.beforeKey);
      return b < 0 || b === i + 1;
    }
    case 'playAt':
    case 'skip': return (s.player.current?.key ?? null) !== m.fromKey;
    case 'setPaused': return s.player.paused === m.paused || !s.player.current;
  }
}

/** Le second ordre fixe seul l'effet du premier : deux déplacements du même titre, ou deux pauses. */
const sameTarget = (a: Mutation, b: Mutation) =>
  (a.kind === 'move' && b.kind === 'move' && a.key === b.key) || (a.kind === 'setPaused' && b.kind === 'setPaused');

/**
 * À chaque état reçu : les mutations non accusées restent (rejouées dessus) ; une mutation accusée part dès
 * que l'état la montre, ou après ACK_GRACE_MS (on croit alors le serveur).
 * Une mutation accusée part aussi quand une plus récente de même cible est accusée : gardée, elle serait rejouée
 * par-dessus (« Annuler » de « Jouer ensuite », ou une reprise, sans effet jusqu'au prochain état reçu).
 */
export function reconcile(pending: readonly Mutation[], server: Snapshot, now: number): Mutation[] {
  return pending.filter((m, i) => {
    if (m.status !== 'acked') return true;
    if (pending.some((p, j) => j > i && p.status === 'acked' && sameTarget(m, p))) return false;
    if (isSatisfied(m, server)) return false;
    return now - (m.ackedAt ?? now) < ACK_GRACE_MS;
  });
}

/** Avant l'envoi : un déplacement du même titre, ou une pause, pas encore envoyés, sont remplacés par le nouveau. */
export function enqueueMutation(pending: readonly Mutation[], m: Mutation): Mutation[] {
  return [...pending.filter((p) => !(p.status === 'queued' && sameTarget(p, m))), m];
}

export interface QueueEngineOptions {
  initial: Snapshot;
  now: () => number;
  /** Requête d'une mutation, calculée sur `before` (l'état que le bot verra) ; null si elle est devenue sans effet. */
  send: (m: Mutation, before: Snapshot) => Promise<unknown> | null;
  /** Appelé à chaque nouvelle vue (référence différente de la précédente). */
  onView: (view: Snapshot) => void;
  /** Refus de l'API ; la mutation est déjà retirée (la vue revient en arrière juste après). */
  onRefused?: (m: Mutation, error: unknown, before: Snapshot) => void;
  holdMaxMs?: number;
}

export interface QueueEngine {
  view(): Snapshot;
  server(): Snapshot;
  pending(): readonly Mutation[];
  /** Dernier état reçu, celui gardé en tampon compris : un tick (snapshotFromPayload) se calcule dessus, sinon il l'écraserait. */
  latest(): Snapshot;
  /** État complet reçu (REST, socket) : appliqué, ou gardé en tampon pendant une action en vol ou un glisser. */
  receive(next: Snapshot): void;
  /** Ordre du Roi : vue changée tout de suite ; résolue à true à l'accusé (ou si devenu sans effet), false au refus. */
  dispatch(body: MutationBody): Promise<boolean>;
  /** Glisser en cours : les états reçus attendent release(). */
  hold(): void;
  release(): void;
  /** Autre serveur, déconnexion : plus rien en attente, réponses en retard ignorées. */
  reset(next: Snapshot): void;
}

export function createQueueEngine(o: QueueEngineOptions): QueueEngine {
  const holdMax = o.holdMaxMs ?? HOLD_MAX_MS;
  let server = o.initial;
  let view = server;
  let pending: Mutation[] = [];
  let seq = 0;
  let epoch = 0;
  let sending: { id: number; since: number } | null = null;
  let held: Snapshot | null = null;
  let drags = 0;
  const waiters = new Map<number, (ok: boolean) => void>();

  const refresh = () => {
    const next = viewOf(server, pending);
    if (next !== view) { view = next; o.onView(view); }
  };
  const resolve = (id: number, ok: boolean) => {
    const w = waiters.get(id);
    if (w) { waiters.delete(id); w(ok); }
  };
  const holding = () => drags > 0 || (sending !== null && o.now() - sending.since < holdMax);
  const apply = (next: Snapshot) => {
    server = next;
    pending = reconcile(pending, server, o.now());
    refresh();
  };
  const flush = () => {
    if (!held || holding()) return;
    const h = held;
    held = null;
    apply(h);
  };

  function pump(): void {
    if (sending) return;
    const i = pending.findIndex((m) => m.status === 'queued');
    if (i < 0) return;
    const m = pending[i];
    const before = viewOf(server, pending.slice(0, i));
    let call: Promise<unknown> | null;
    try { call = o.send(m, before); } catch (e) { call = Promise.reject(e); }
    if (!call) {   // devenue sans effet (titre parti, déjà à sa place) : rien à envoyer
      pending = pending.filter((p) => p.id !== m.id);
      refresh();
      resolve(m.id, true);
      pump();
      return;
    }
    const ep = epoch;
    sending = { id: m.id, since: o.now() };
    pending = pending.map((p) => (p.id === m.id ? { ...p, status: 'sent' } : p));
    const done = (ok: boolean) => {
      sending = null;
      flush();
      refresh();
      resolve(m.id, ok);
      pump();
    };
    call.then(() => {
      if (ep !== epoch) return;
      const now = o.now();
      pending = reconcile(pending.map((p) => (p.id === m.id ? { ...p, status: 'acked', ackedAt: now } : p)), server, now);
      done(true);
    }, (e: unknown) => {
      if (ep !== epoch) return;
      pending = pending.filter((p) => p.id !== m.id);
      o.onRefused?.(m, e, before);
      done(false);
    });
  }

  return {
    view: () => view,
    server: () => server,
    pending: () => pending,
    latest: () => held ?? server,
    receive(next) {
      if (holding()) { held = next; return; }
      held = null;
      apply(next);
    },
    dispatch(body) {
      const m = { ...body, id: ++seq, at: o.now(), status: 'queued' } as Mutation;
      const prev = pending;
      pending = enqueueMutation(pending, m);
      for (const p of prev) if (!pending.includes(p)) resolve(p.id, true);   // remplacée par la nouvelle
      const result = new Promise<boolean>((r) => waiters.set(m.id, r));
      refresh();
      pump();
      return result;
    },
    hold() { drags++; },
    release() {
      drags = Math.max(0, drags - 1);
      flush();
    },
    reset(next) {
      epoch++;
      sending = null;
      held = null;
      drags = 0;
      pending = [];
      for (const id of [...waiters.keys()]) resolve(id, false);
      server = next;
      refresh();
    },
  };
}
