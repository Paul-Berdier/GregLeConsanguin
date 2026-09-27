/**
 * Le Héraut : les notifications (DESIGN §5 et §12.6, motion.md §6.16), à la façon de Sonner.
 * - pile de 3 au plus, la plus récente devant ; les suivantes dépassent de 14 px, 5 % plus petites,
 *   à la hauteur de celle de devant ; les autres attendent, invisibles et inactives ;
 * - survol ou focus : les minuteurs s'arrêtent ; à la sortie, chacune repart pour 2,4 s ;
 * - onglet caché : les minuteurs s'arrêtent et reprennent où ils en étaient (toute sa durée pour
 *   une notification arrivée entre-temps) ;
 * - un même fait sans action, encore affiché, devient « ×2 », « ×3 » ;
 * - une action d'annulation (« Annuler ») se rejoue aussi par Ctrl+Z pendant 15 s ;
 * - au plus une réplique de Greg toutes les 30 s (le reste : le fait seul).
 * Pur, sans import runtime (tests/herald.test.mjs) : horloge, minuteurs et deck injectés.
 */
import type { CopyVars } from '../theme/copy';
import type { ErrorCopy } from './playerUtils';

export type ToastKind = 'ok' | 'info' | 'warn' | 'err';
export type ToastAction = { label: string; run: () => void };
export type ToastInput = {
  kind?: ToastKind;
  fact: string;
  /** Réplique de Greg : quand elle est gardée, son portrait (en valet) remplace l'icône. */
  quip?: string | null;
  action?: ToastAction | null;
  ms?: number;
};
export type Toast = {
  id: number;
  kind: ToastKind;
  fact: string;
  quip: string | null;
  action: ToastAction | null;
  n: number;
  leaving: boolean;
};

export const LIFE: Record<ToastKind, number> = { ok: 3500, info: 4000, warn: 6000, err: 8000 };
export const ACTION_LIFE = 6500;
export const RELEASE_MS = 2400;
export const LEAVE_MS = 260;
export const UNDO_MS = 15000;
export const QUIP_EVERY_MS = 30000;
export const VISIBLE = 3;
export const STEP_Y = 14;
export const STEP_SCALE = 0.05;
export const GAP = 8;

export type StackSlot = {
  /** décalage vers le haut (px) */
  y: number;
  /** échelle */
  s: number;
  /** opacité */
  o: number;
  /** plan (z-index) */
  z: number;
  /** pile repliée : hauteur imposée (celle de la plaque de devant), son contenu s'efface ; null : hauteur réelle */
  fold: number | null;
  /** au-delà des 3 visibles : ni pointeur ni focus */
  hidden: boolean;
};

/** Place de chaque notification (0 = la plus récente, en bas), d'après les hauteurs réelles des plaques. */
export function stackLayout(heights: readonly number[], expanded: boolean): StackSlot[] {
  let acc = 0;
  return heights.map((h, i) => {
    const y = expanded ? acc : i * STEP_Y;
    acc += h + GAP;
    return {
      y,
      s: expanded ? 1 : Math.max(0, 1 - i * STEP_SCALE),
      o: i < VISIBLE ? 1 : 0,
      z: 100 - i,
      fold: !expanded && i > 0 ? heights[0] : null,
      hidden: i >= VISIBLE,
    };
  });
}

/** Hauteur occupée par la pile repliée (la file garde cette place pour ses dernières lignes). */
export function stackHeight(heights: readonly number[]): number {
  if (!heights.length) return 0;
  return heights[0] + Math.min(heights.length - 1, VISIBLE - 1) * STEP_Y;
}

/**
 * Texte lu par les lecteurs d'écran : le fait, « ×N », puis l'annulation proposée (`undoHint(label)`).
 * Un point sépare le fait de l'annulation quand il ne finit pas déjà une phrase (« Retiré : X », « Ajouté : X »).
 */
export function spokenText(t: Toast, undoHint: (label: string) => string): string {
  const said = `${t.fact}${t.n > 1 ? ` ×${t.n}` : ''}`;
  if (!t.action) return said;
  const sep = /[.!?…]\s*[»”’"]?\s*$/.test(said) ? ' ' : '. ';
  return `${said}${sep}${undoHint(t.action.label)}`;
}

/** Lecture du deck (`t`, `has`, `quip` de theme/copy.ts ; `seedOf` de lib/stage/scene.ts), injectée. */
export type DeckReader = {
  t: (path: string, vars?: CopyVars) => string;
  has: (path: string) => boolean;
  quip: (path: string, seed: number, vars?: CopyVars) => string | null;
  seedOf: (s: string) => number;
};
export type SayOptions = { vars?: CopyVars; text?: string; action?: ToastAction | null; kind?: ToastKind };

const KINDS: readonly ToastKind[] = ['ok', 'info', 'warn', 'err'];

/**
 * Notification d'une entrée du deck `{ text, kind?, quips? }` (ex. 'toast.removed') :
 * - le fait : `o.text` (texte déjà rendu), sinon `${key}.text` ;
 * - la sorte : `o.kind`, sinon `${key}.kind` s'il en nomme une, sinon « info » ;
 * - la réplique : dans les `quips` de l'entrée, la graine étant le fait.
 */
export function deckToast(key: string, o: SayOptions, d: DeckReader): ToastInput {
  const fact = o.text ?? d.t(`${key}.text`, o.vars);
  const deckKind = d.has(`${key}.kind`) ? d.t(`${key}.kind`) : '';
  const kind = o.kind ?? (KINDS.includes(deckKind as ToastKind) ? (deckKind as ToastKind) : 'info');
  return { kind, fact, quip: d.quip(key, d.seedOf(fact), o.vars), action: o.action ?? null };
}

/** Erreur traduite (`errorCopy`) : son texte (du deck ou de l'API), sa sorte, ou « err » quand l'entrée n'en dit pas. */
export function errorToast(c: ErrorCopy, d: DeckReader): ToastInput {
  const text = 'path' in c ? d.t(c.path, c.vars) : c.text;
  return deckToast(c.key, { text, kind: d.has(`${c.key}.kind`) ? undefined : 'err' }, d);
}

/** Ce qui arrête les minuteurs : le survol ou le focus de la pile, ou l'onglet caché. */
export type HoldReason = 'hover' | 'tab';

export interface Herald {
  subscribe(fn: () => void): () => void;
  getSnapshot(): readonly Toast[];
  notify(input: ToastInput): number;
  dismiss(id: number): void;
  /** Bouton d'action de la notification : l'action, puis la notification s'en va. */
  act(id: number): void;
  /** Ctrl+Z : la dernière annulation proposée, si elle a moins de UNDO_MS. */
  undo(): boolean;
  /** Arrête les minuteurs. Survol (par défaut) : un compte ; onglet : un état (le signaler deux fois ne compte qu'une). */
  hold(reason?: HoldReason): void;
  /** Fin du survol : chacune repart pour 2,4 s ; fin de l'onglet caché : chacune reprend son temps restant. */
  release(reason?: HoldReason): void;
}

export type HeraldOptions = {
  now: () => number;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  /** Annonce aux lecteurs d'écran (nouvelle notification, ou un « ×N » de plus). */
  announce?: (t: Toast) => void;
};

export function createHerald(o: HeraldOptions): Herald {
  let list: Toast[] = [];
  let seq = 0;
  let hovers = 0;
  let hidden = false;
  let lastQuipAt = -Infinity;
  let lastUndo: { id: number; run: () => void; until: number } | null = null;
  const timers = new Map<number, { h: unknown; at: number }>();
  /** durée de vie complète de chaque notification */
  const lives = new Map<number, number>();
  /** temps restant de chaque notification, à jour quand son minuteur est arrêté */
  const left = new Map<number, number>();
  const subs = new Set<() => void>();

  const paused = () => hovers > 0 || hidden;
  const emit = () => { for (const fn of subs) fn(); };
  const stop = (id: number) => {
    const tm = timers.get(id);
    if (!tm) return;
    o.clearTimer(tm.h);
    timers.delete(id);
    left.set(id, Math.max(0, tm.at - o.now()));
  };
  const arm = (id: number, ms: number) => {
    stop(id);
    left.set(id, ms);
    if (paused()) return;
    timers.set(id, { h: o.setTimer(() => { timers.delete(id); dismiss(id); }, ms), at: o.now() + ms });
  };
  const resume = () => {
    if (paused()) return;
    for (const t of list) if (!t.leaving && !timers.has(t.id)) arm(t.id, left.get(t.id) ?? lives.get(t.id) ?? RELEASE_MS);
  };
  const update = (id: number, patch: Partial<Toast>) => {
    list = list.map((t) => (t.id === id ? { ...t, ...patch } : t));
  };

  function dismiss(id: number): void {
    const t = list.find((x) => x.id === id);
    if (!t || t.leaving) return;
    stop(id);
    lives.delete(id);
    left.delete(id);
    update(id, { leaving: true });
    emit();
    o.setTimer(() => { list = list.filter((x) => x.id !== id); emit(); }, LEAVE_MS);
  }

  return {
    subscribe(fn) { subs.add(fn); return () => { subs.delete(fn); }; },
    getSnapshot: () => list,
    notify(input) {
      const kind = input.kind ?? 'ok';
      const action = input.action ?? null;
      const life = input.ms ?? (action ? ACTION_LIFE : LIFE[kind]);
      const same = !action && list.find((t) => !t.leaving && !t.action && t.kind === kind && t.fact === input.fact);
      if (same) {
        update(same.id, { n: same.n + 1 });
        lives.set(same.id, life);
        arm(same.id, life);
        emit();
        o.announce?.(list.find((t) => t.id === same.id)!);
        return same.id;
      }
      const now = o.now();
      let quip = input.quip || null;
      if (quip && now - lastQuipAt < QUIP_EVERY_MS) quip = null;
      if (quip) lastQuipAt = now;
      const t: Toast = { id: ++seq, kind, fact: input.fact, quip, action, n: 1, leaving: false };
      list = [t, ...list];
      lives.set(t.id, life);
      if (action) lastUndo = { id: t.id, run: action.run, until: now + UNDO_MS };
      arm(t.id, life);
      emit();
      o.announce?.(t);
      return t.id;
    },
    dismiss,
    act(id) {
      const t = list.find((x) => x.id === id);
      if (!t || t.leaving || !t.action) return;
      if (lastUndo?.id === id) lastUndo = null;
      t.action.run();
      dismiss(id);
    },
    undo() {
      const u = lastUndo;
      if (!u || o.now() > u.until) return false;
      lastUndo = null;
      u.run();
      dismiss(u.id);
      return true;
    },
    hold(reason = 'hover') {
      if (reason === 'tab') {
        if (hidden) return;
        hidden = true;
      } else {
        hovers++;
      }
      for (const id of [...timers.keys()]) stop(id);
    },
    release(reason = 'hover') {
      if (reason === 'tab') {
        if (!hidden) return;
        hidden = false;
      } else {
        if (hovers === 0) return;
        hovers--;
        if (hovers > 0) return;
        for (const t of list) if (!t.leaving) left.set(t.id, Math.min(RELEASE_MS, lives.get(t.id) ?? RELEASE_MS));
      }
      resume();
    },
  };
}
