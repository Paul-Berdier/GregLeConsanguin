/**
 * La vidéo en plein écran, « La Grand-Salle » (conception du 2026-11-23, §2), pur (tests/fullscreen.test.mjs).
 * L'élément mis en plein écran est `.video` (Portal.tsx) : l'iframe YouTube n'y bouge jamais (la déplacer la recharge).
 * Ici : détection de l'API (préfixes webkit), état après `fullscreenchange`, délais, file mémorisée, raccourcis de la
 * page ignorés, ordre du focus piégé, minuterie de repos des commandes. Le DOM et React restent dans
 * hooks/useFullscreen.ts et components/Stage/Theater.tsx.
 */
import type { Shortcut } from '@/lib/keys';

/** native : l'API plein écran (couche du dessus) ; pseudo : le repli CSS (fixe, tout l'écran), là où l'API manque (iPhone). */
export type FsMode = 'native' | 'pseudo';

/** Commandes de la surcouche effacées après 3 s sans souris, sans touche, sans focus qui change. */
export const FS_IDLE_MS = 3000;
/** Plus de titre en cours pendant 1,5 s (fin de file, arrêt) : on sort du plein écran. Un creux entre deux titres passe. */
export const FS_EXIT_MS = 1500;
/**
 * Demande sans réponse au bout d'une seconde (ni `fullscreenchange` ni erreur : vue web embarquée qui ne l'accorde
 * jamais) : le repli prend le relais. Un accord tardif l'emporte encore (fsModeAfterChange).
 */
export const FS_ASK_MS = 1000;
/** File « À suivre » montrée ou masquée, mémorisée ; absente ou illisible : montrée. */
export const FS_QUEUE_KEY = 'greg.webplayer.fsQueue';
/** Lignes de la file dans la surcouche (au-delà : « …et N autres titres ») : chaque ligne a deux arrêts de Tab. */
export const FS_MAX_ROWS = 30;
/** Raccourcis de la page sans objet en plein écran : la recherche et l'aide sont hors de l'écran (Espace, Maj+→/← restent). */
export const FS_SKIPPED: readonly Shortcut[] = ['type', 'search', 'help'];

/** La vidéo en plein écran, API ou repli (Portal.tsx pose data-fs) : ce que lit le clavier de la page (page.tsx). */
export const FS_ACTIVE = '.video[data-fs]';
/** Double-clic sur la vidéo : plein écran, entrée comme sortie ; pas sur une commande, un popover ou la file de la surcouche. */
export const FS_NO_DBLCLICK = 'button, a[href], input, .pop, .th-queue';

export const fsSkips = (act: Shortcut): boolean => FS_SKIPPED.includes(act);
export const fsQueueOn = (stored: string | null | undefined): boolean => stored !== 'off';

type StorageLike = { getItem(k: string): string | null; setItem(k: string, v: string): void };

/** Lit le réglage ; `storage` est une fonction : localStorage lui-même peut lever (stockage bloqué, SecurityError). */
export function loadFsQueue(storage: () => StorageLike): boolean {
  try { return fsQueueOn(storage().getItem(FS_QUEUE_KEY)); } catch { return true; }
}
/** Écrit le réglage ; un stockage bloqué le garde pour la session seulement. */
export function saveFsQueue(storage: () => StorageLike, on: boolean): void {
  try { storage().setItem(FS_QUEUE_KEY, on ? 'on' : 'off'); } catch {}
}

/** Ce que le document expose de l'API, préfixes webkit compris (Safari d'iPad, anciens moteurs). */
export type FsDoc = {
  fullscreenEnabled?: boolean; webkitFullscreenEnabled?: boolean;
  fullscreenElement?: unknown; webkitFullscreenElement?: unknown;
  exitFullscreen?: () => Promise<void> | void; webkitExitFullscreen?: () => void;
};
/** Ce que l'élément expose : `requestFullscreen` rend une promesse, `webkitRequestFullscreen` rien (échec par événement). */
export type FsEl = { requestFullscreen?: (o?: { navigationUI?: 'auto' | 'hide' | 'show' }) => Promise<void> | void; webkitRequestFullscreen?: () => void };

/** L'élément en plein écran (API), ou null. */
export function fsElement(doc: FsDoc): unknown {
  return doc.fullscreenElement ?? doc.webkitFullscreenElement ?? null;
}

/** L'API plein écran sert pour cet élément : autorisée par le document (permissions, iframe) et présente sur l'élément. */
export function canNativeFs(doc: FsDoc, el: FsEl): boolean {
  const enabled = doc.fullscreenEnabled ?? doc.webkitFullscreenEnabled ?? false;
  return enabled && typeof (el.requestFullscreen ?? el.webkitRequestFullscreen) === 'function';
}

/** Demande le plein écran. À appeler dans le gestionnaire du clic : l'activation de l'utilisateur n'y vaut qu'un temps. */
export function requestFs(el: FsEl): Promise<void> {
  try {
    if (el.requestFullscreen) return Promise.resolve(el.requestFullscreen({ navigationUI: 'hide' }));
    el.webkitRequestFullscreen?.();
    return Promise.resolve();
  } catch (e) {
    return Promise.reject(e);
  }
}

export function exitFs(doc: FsDoc): Promise<void> {
  try {
    if (doc.exitFullscreen) return Promise.resolve(doc.exitFullscreen());
    doc.webkitExitFullscreen?.();
    return Promise.resolve();
  } catch (e) {
    return Promise.reject(e);
  }
}

/**
 * État après un `fullscreenchange` : `nativeOn` vrai si l'élément de la vidéo est l'élément en plein écran.
 * Sortie par le navigateur (Échap, autre onglet en plein écran) : null ; le repli, lui, ne dépend pas de l'API.
 */
export function fsModeAfterChange(prev: FsMode | null, nativeOn: boolean): FsMode | null {
  if (nativeOn) return 'native';
  return prev === 'native' ? null : prev;
}

/** Délai avant de quitter le plein écran faute de titre (null : rien à faire). */
export function fsExitDelay(active: boolean, playing: boolean): number | null {
  return active && !playing ? FS_EXIT_MS : null;
}

/**
 * Tab piégé dans la surcouche : rang du prochain arrêt parmi `count` (ordre du document), en boucle.
 * `index` hors des arrêts (-1 : le focus est sur la surcouche elle-même) : le premier, ou le dernier avec Maj.
 * -1 : aucun arrêt, le focus reste sur la surcouche.
 */
export function trapIndex(count: number, index: number, back: boolean): number {
  if (count <= 0) return -1;
  if (index < 0 || index >= count) return back ? count - 1 : 0;
  return (index + (back ? count - 1 : 1)) % count;
}

/** Ligne qui prend le focus quand `key` quitte la liste (jouée ou retirée) : la suivante, sinon la précédente. */
export function neighbourKey(keys: readonly string[], key: string): string | null {
  const i = keys.indexOf(key);
  if (i < 0) return null;
  return keys[i + 1] ?? keys[i - 1] ?? null;
}

/** Part écoulée du titre, de 0 à 1 (durée inconnue : 0). */
export function progressOf(pos: number, dur: number): number {
  if (!(dur > 0) || !(pos > 0)) return 0;
  return Math.min(1, pos / dur);
}

export type IdleTimers = { set: (fn: () => void, ms: number) => unknown; clear: (handle: unknown) => void };
export type Idle = { wake(): void; stop(): void; readonly idle: boolean };

/**
 * Repos des commandes : onIdle(true) après `ms` sans activité, onIdle(false) à la première activité (wake).
 * `hold()` vrai à l'échéance (dialogue ouvert, pointeur posé sur une commande) : elles restent, on attend encore `ms`.
 * Minuterie injectée : setTimeout dans la page, une horloge factice dans les tests.
 */
export function createIdle(ms: number, onIdle: (idle: boolean) => void, hold: () => boolean, timers: IdleTimers): Idle {
  let handle: unknown = null, idle = false, stopped = false;
  const fire = (): void => {
    handle = null;
    if (stopped) return;
    if (hold()) { handle = timers.set(fire, ms); return; }
    idle = true;
    onIdle(true);
  };
  return {
    wake(): void {
      if (stopped) return;
      if (handle != null) timers.clear(handle);
      if (idle) { idle = false; onIdle(false); }
      handle = timers.set(fire, ms);
    },
    stop(): void {
      stopped = true;
      if (handle != null) timers.clear(handle);
      handle = null;
    },
    get idle(): boolean { return idle; },
  };
}
