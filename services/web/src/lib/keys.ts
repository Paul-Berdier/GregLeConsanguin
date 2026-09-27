/**
 * Clavier (spec §5, DESIGN §7 et §12.7), pur (tests/keys.test.mjs). L'interrupteur « Raccourcis clavier »
 * (WCAG 2.1.4) coupe tout ce qui tient en une touche, saisie directe comprise.
 */
export type KeyEv = { key: string; code?: string; shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; repeat?: boolean };
/** onRow : ligne d'une liste (ses touches sont à elle) ; onControl : bouton, lien, onglet (Espace l'active). */
export type KeyCtx = { enabled: boolean; loggedIn: boolean; inField: boolean; inPopover: boolean; onRow: boolean; onControl: boolean; dragging: boolean };
export type Shortcut = 'togglePause' | 'skip' | 'restart' | 'search' | 'help' | 'type';
export type ListAct = { kind: 'focus'; index: number } | { kind: 'activate' } | { kind: 'remove' } | { kind: 'move'; dir: -1 | 1 } | { kind: 'next' };
export const SHORTCUTS_STORAGE_KEY = 'greg.webplayer.keys';
export const HELP_EVENT = 'greg:help';
export const shortcutsOn = (stored: string | null | undefined): boolean => stored !== 'off';

export function shortcutFor(ev: KeyEv, c: KeyCtx): Shortcut | null {
  if (!c.enabled || !c.loggedIn || c.inField || c.inPopover || c.dragging) return null;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return null;
  if (ev.key === '/') return 'search';
  if (ev.key === '?') return 'help';
  if (c.onRow) return null;
  if (ev.code === 'Space' || ev.key === ' ') return c.onControl || ev.repeat ? null : 'togglePause';
  if (ev.shiftKey && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) return ev.repeat ? null : ev.key === 'ArrowRight' ? 'skip' : 'restart';
  return ev.key.length === 1 && /\S/.test(ev.key) ? 'type' : null;
}

/** Touche maintenue : on parcourt et on déplace encore, mais Entrée, Suppr et Alt+Début n'agissent qu'une fois
 * (sinon, la ligne suivante prenant le focus, elles joueraient ou retireraient la file en chaîne). */
export function listKey(ev: KeyEv, index: number, count: number): ListAct | null {
  if (ev.ctrlKey || ev.metaKey || count <= 0) return null;
  if (ev.repeat && (ev.key === 'Enter' || ev.key === 'Delete' || (ev.altKey && ev.key === 'Home'))) return null;
  const last = count - 1;
  if (ev.altKey) {
    if (ev.key === 'ArrowUp') return index > 0 ? { kind: 'move', dir: -1 } : null;
    if (ev.key === 'ArrowDown') return index < last ? { kind: 'move', dir: 1 } : null;
    return ev.key === 'Home' && index > 0 ? { kind: 'next' } : null;
  }
  switch (ev.key) {
    case 'ArrowDown': return { kind: 'focus', index: Math.min(last, index + 1) };
    case 'ArrowUp': return { kind: 'focus', index: Math.max(0, index - 1) };
    case 'Home': return { kind: 'focus', index: 0 };
    case 'End': return { kind: 'focus', index: last };
    case 'Enter': return { kind: 'activate' };
    case 'Delete': return { kind: 'remove' };
    default: return null;
  }
}

/** Clé devant laquelle déposer `key` décalé d'un rang (moveTrack) ; null : fin de file ; undefined : impossible. */
export function moveBefore(keys: readonly string[], key: string, dir: -1 | 1): string | null | undefined {
  const i = keys.indexOf(key), j = i + dir;
  if (i < 0 || j < 0 || j >= keys.length) return undefined;
  return dir < 0 ? keys[j] : keys[i + 2] ?? null;
}
