'use client';

import { useEffect } from 'react';
import { create } from 'zustand';
import { api } from '@/lib/api';
import {
  DEFAULT_LIMITS, LIKES, TMP, addPlan, checkOp, cleanName, createLibraryEngine, findPlaylist, libraryCode, likedKeys,
  moveIndices, nameOk, noticeOf, parseLibrary, toLibraryTrack, trackKey, wireTrack,
} from '@/lib/library';
import type { LibraryOp, TrackLike } from '@/lib/library';
import type { Library, LibraryTrack } from '@/lib/types';
import { parseTitle } from '@/lib/titles';
import { playerActions, useStore } from '@/hooks/usePlayer';
import { herald, say, sayError, speak } from '@/components/Herald/store';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';

export type LibraryStatus = 'off' | 'loading' | 'ready' | 'error';

interface LibraryStore {
  /** off : aucun Roi connecté ; loading : première lecture ; ready : chargé ; error : illisible (Redis indisponible…). */
  status: LibraryStatus;
  /** Vue du chansonnier : l'état confirmé par l'API, plus les modifications pas encore accusées (lib/library.ts). */
  lib: Library | null;
  /** Clés (trackKey) des coups de cœur : le cœur d'une ligne se dit pressé sans parcourir la liste. */
  liked: ReadonlySet<string>;
  /** Vue ouverte dans l'onglet Chansonnier : LIKES, l'id d'une playlist, ou null (vue d'ensemble). */
  open: string | null;
}

const NONE: ReadonlySet<string> = new Set();

/** Le chansonnier du Roi connecté (spec 2026-11-23 §3) : un seul, quel que soit le serveur. */
export const useLibrary = create<LibraryStore>(() => ({ status: 'off', lib: null, liked: NONE, open: null }));

// Les cœurs ne changent pas : le même ensemble (les lignes de la file, mémoïsées, ne se redessinent pas)
let _likesOf: readonly LibraryTrack[] | null = null;
function show(lib: Library | null): void {
  const liked = !lib ? NONE : lib.likes === _likesOf ? useLibrary.getState().liked : likedKeys(lib.likes);
  _likesOf = lib?.likes ?? null;
  useLibrary.setState({ lib, liked });
}

/** Une modification vers l'API ; un déplacement se compte sur le chansonnier confirmé, celui que l'API modifie. */
function send(op: LibraryOp, base: Library): Promise<unknown> {
  switch (op.kind) {
    case 'like': return api.libraryLike(wireTrack(op.track));
    case 'unlike': return api.libraryUnlike(op.url);
    case 'create': return api.playlistCreate(op.name, op.tracks.map(wireTrack));
    case 'rename': return api.playlistRename(op.id, op.name);
    case 'delete': return api.playlistDelete(op.id);
    case 'add': return api.playlistAdd(op.id, op.tracks.map(wireTrack));
    case 'remove': return api.playlistRemove(op.id, op.url);
    case 'move': {
      const mv = moveIndices(findPlaylist(base, op.id)?.tracks ?? [], op.url, op.to);
      return mv ? api.playlistMove(op.id, mv.src, mv.dst) : Promise.resolve(null);
    }
  }
}

/**
 * Échecs après lesquels le chansonnier confirmé est relu : playlist disparue (supprimée dans un autre onglet) ; issue
 * inconnue, l'écriture peut avoir eu lieu (503 STORAGE_UNAVAILABLE : « le site relit », dit l'API ; réseau, réponse
 * illisible : sans code) ; requête invalide, souvent comptée sur une copie dépassée (rangs d'un déplacement).
 */
const REREAD = new Set(['PLAYLIST_NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INVALID_REQUEST', '']);

/**
 * Refus de l'API, la vue déjà revenue en arrière : le Héraut dit pourquoi. Session perdue (401) : la perte de session
 * le dit déjà (usePlayer, onAuthLost) et vide le chansonnier. Copie peut-être dépassée (REREAD) : relue.
 */
function failed(op: LibraryOp, e: unknown): void {
  const code = libraryCode(e);
  if (code === 'NOT_AUTHENTICATED') return;
  const n = noticeOf(code, op, engine.view());
  if (n) say(n.key, { vars: n.vars, kind: n.kind });
  else sayError(e);
  if (REREAD.has(code)) void load();
}

const engine = createLibraryEngine({
  send,
  now: () => Date.now(),
  onView: show,
  onFail: failed,
  // la vue ouverte sur une playlist tout juste créée suit son id définitif
  onAlias: (tmp, id) => { if (useLibrary.getState().open === tmp) useLibrary.setState({ open: id }); },
});

let _loadSeq = 0;

/**
 * Lit le chansonnier du Roi connecté ; une lecture dépassée (déconnexion, autre Roi, relecture, modification accusée
 * entre-temps) ne s'écrit pas.
 */
async function load(): Promise<void> {
  const meId = useStore.getState().me?.id;
  if (!meId) return;
  const seq = ++_loadSeq;
  const live = () => seq === _loadSeq && useStore.getState().me?.id === meId;
  const acks = engine.acks();
  if (!engine.view()) useLibrary.setState({ status: 'loading' });
  try {
    const lib = parseLibrary(await api.getLibrary());
    if (!live()) return;
    if (!lib) throw new Error('library');
    // une modification accusée pendant la lecture a rendu le chansonnier entier, peut-être plus récent que lui : gardé
    if (engine.acks() === acks || !engine.view()) engine.load(lib);
    useLibrary.setState({ status: 'ready' });
  } catch {
    // déjà chargé (relecture ratée) : la vue reste ; sinon l'onglet dit l'indisponibilité et propose de réessayer
    if (live()) useLibrary.setState({ status: engine.view() ? 'ready' : 'error' });
  }
}

/** Déconnexion ou autre Roi : rien ne reste du chansonnier précédent, ses réponses en vol sont ignorées. */
function clear(): void {
  _loadSeq++;
  engine.reset();
  useLibrary.setState({ status: 'off', open: null });
}

/** Le chansonnier chargé ; sinon null, et le Héraut dit pourquoi (une lecture ratée est relancée). */
function ready(): Library | null {
  const s = useLibrary.getState();
  if (s.lib) return s.lib;
  if (!useStore.getState().me) say('error.NOT_AUTHENTICATED', { kind: 'warn' });
  else if (s.status === 'error') { say('library.error.STORAGE_UNAVAILABLE', { kind: 'err' }); void load(); }
  else say('library.error.notReady', { kind: 'info' });
  return null;
}

/** true : refusée d'avance (plafond, nom, playlist disparue), dite par le Héraut ; « déjà fait » refusé en silence. */
function refused(lib: Library, op: LibraryOp): boolean {
  const r = checkOp(lib, op);
  if (!r) return false;
  const n = noticeOf(r.code, op, lib);
  if (n) say(n.key, { vars: n.vars, kind: n.kind });
  return true;
}

/**
 * Modification vérifiée d'avance, puis optimiste. false : refusée (d'avance, ou par l'API : vue revenue en arrière).
 * L'id provisoire d'une playlist créée depuis (une annulation préparée avant sa réponse) devient le vrai avant la
 * vérification : la vue ne connaît plus que lui (sinon « Cette playlist n'existe plus », le titre perdu).
 */
function run(op: LibraryOp): Promise<boolean> {
  const lib = ready();
  const real = engine.resolve(op);
  if (!lib || refused(lib, real)) return Promise.resolve(false);
  return engine.dispatch(real);
}

const songOf = (x: { title: string; artist: string | null }): string => parseTitle(x.title, x.artist ?? undefined).song || x.title;
const trackOf = (x: TrackLike): LibraryTrack | null => toLibraryTrack(x, Date.now());
const playlistOf = (id: string) => findPlaylist(useLibrary.getState().lib, engine.idOf(id));

/**
 * Cœur d'un titre de la file, de l'historique ou en lecture : pressé, il le garde ; relâché, il le retire.
 * `spoken` : basculé au clavier (J sur une ligne) ; le cœur de la ligne n'a pas le focus, son état n'est pas lu :
 * l'accusé est dit aux lecteurs d'écran, sans notification visible (comme un déplacement Alt+↑ ↓).
 */
function toggleLike(item: TrackLike, o: { spoken?: boolean } = {}): Promise<boolean> {
  if (!ready()) return Promise.resolve(false);
  const tr = trackOf(item);
  if (!tr) { say('library.error.INVALID_TRACK', { kind: 'warn' }); return Promise.resolve(false); }
  const on = !useLibrary.getState().liked.has(trackKey(tr.url));
  const done = run(on ? { kind: 'like', track: tr } : { kind: 'unlike', url: tr.url });
  if (o.spoken) void done.then((ok) => { if (ok) speak(tx(on ? 'library.toast.liked.text' : 'library.toast.unliked.text', { title: songOf(tr) })); });
  return done;
}

/** Retirer un coup de cœur depuis sa liste : annonce annulable (le titre revient en tête). */
function unlike(track: LibraryTrack): Promise<boolean> {
  const done = run({ kind: 'unlike', url: track.url });
  const id = say('library.toast.unliked', {
    vars: { title: songOf(track) }, kind: 'info',
    action: { label: t('toast.undo'), run: () => { void run({ kind: 'like', track }); } },
  });
  void done.then((ok) => { if (!ok) herald.retract(id); });
  return done;
}

let _tmp = 0;

/**
 * Nouvelle playlist (nom nettoyé comme l'API, titres dédoublonnés et plafonnés) : visible tout de suite sous un id
 * provisoire (TMP), qui suit l'id de l'API à sa réponse (engine.idOf). null : refusée d'avance.
 */
function createPlaylist(rawName: string, items: readonly TrackLike[] = []): { id: string; done: Promise<boolean> } | null {
  const lib = ready();
  if (!lib) return null;
  // ce que l'API garderait (doublons écartés, 200 au plus) : une longue file (plus de 500 titres) serait sinon
  // refusée en entier (INVALID_REQUEST), et la requête resterait petite
  const tracks = addPlan([], items.map(trackOf).filter((x): x is LibraryTrack => !!x), lib.limits.tracks).added;
  const op: LibraryOp = { kind: 'create', id: `${TMP}${++_tmp}`, name: cleanName(rawName), tracks };
  if (refused(lib, op)) return null;
  return { id: op.id, done: engine.dispatch(op) };
}

/** « Nouvelle playlist… » du menu du titre en lecture : créée avec lui, annoncée à la réponse. */
function createPlaylistWith(rawName: string, item: TrackLike): { id: string; done: Promise<boolean> } | null {
  const made = createPlaylist(rawName, [item]);
  const tr = trackOf(item);
  if (made && tr) {
    void made.done.then((ok) => {
      const pl = ok ? playlistOf(made.id) : null;
      if (pl) say('library.toast.createdWith', { vars: { name: pl.name, title: songOf(tr) }, kind: 'ok' });
    });
  }
  return made;
}

/** Nom acceptable (nettoyé comme l'API) ; sinon le Héraut dit la règle et le champ reste ouvert. */
function nameValid(rawName: string): boolean {
  const max = useLibrary.getState().lib?.limits.name ?? DEFAULT_LIMITS.name;
  if (nameOk(cleanName(rawName), max)) return true;
  say('library.error.INVALID_NAME', { vars: { n: max }, kind: 'warn' });
  return false;
}

/** « Enregistrer la file » : le titre en cours puis la file, dans une nouvelle playlist (200 titres au plus). */
function saveQueue(rawName: string): { id: string; done: Promise<boolean> } | null {
  const p = useStore.getState().player;
  const items = [p.current, ...p.queue].filter((x): x is NonNullable<typeof x> => !!x);
  if (!items.length) { say('library.toast.nothingToSave', { kind: 'info' }); return null; }
  const made = createPlaylist(rawName, items);
  if (made) {
    void made.done.then((ok) => {
      const pl = ok ? playlistOf(made.id) : null;
      if (pl) say('library.toast.saved', { vars: { n: pl.tracks.length, name: pl.name }, kind: 'ok' });
    });
  }
  return made;
}

function renamePlaylist(id: string, rawName: string): Promise<boolean> {
  return run({ kind: 'rename', id: engine.idOf(id), name: cleanName(rawName) });
}

/** Supprimer une playlist (confirmé par la vue) : annonce annulable, qui la recrée avec ses titres. */
function deletePlaylist(id: string): Promise<boolean> {
  const pl = playlistOf(id);
  if (!pl) return run({ kind: 'delete', id: engine.idOf(id) });   // disparue : le refus le dit
  const done = run({ kind: 'delete', id: pl.id });
  const toast = say('library.toast.deleted', {
    vars: { name: pl.name }, kind: 'info',
    action: { label: t('toast.undo'), run: () => { createPlaylist(pl.name, pl.tracks); } },
  });
  void done.then((ok) => { if (!ok) herald.retract(toast); });
  return done;
}

/** Ajouter des titres à une playlist (à la fin, doublons écartés) ; un seul titre est annoncé, ou dit déjà dedans. */
function addToPlaylist(id: string, items: readonly TrackLike[]): Promise<boolean> {
  const lib = ready();
  const pl = playlistOf(id);
  if (!lib || !pl) return lib ? run({ kind: 'add', id: engine.idOf(id), tracks: [] }) : Promise.resolve(false);
  const tracks = items.map(trackOf).filter((x): x is LibraryTrack => !!x);
  const one = tracks.length === 1 ? songOf(tracks[0]) : '';
  if (tracks.length && !addPlan(pl.tracks, tracks, Infinity).added.length) {
    say('library.toast.already', { vars: { name: pl.name, title: one }, kind: 'info' });
    return Promise.resolve(false);
  }
  const op: LibraryOp = { kind: 'add', id: pl.id, tracks };
  if (refused(lib, op)) return Promise.resolve(false);
  const done = engine.dispatch(op);
  if (one) {
    const toast = say('library.toast.addedTo', { vars: { name: pl.name, title: one }, kind: 'ok' });
    void done.then((ok) => { if (!ok) herald.retract(toast); });
  }
  return done;
}

/** Ajouter à une vue du chansonnier : les coups de cœur (LIKES) ou une playlist ; annoncé comme l'ajout à une playlist. */
function addTo(id: string, item: TrackLike): Promise<boolean> {
  if (id !== LIKES) return addToPlaylist(id, [item]);
  const lib = ready(), tr = lib && trackOf(item);
  if (!lib || !tr) return Promise.resolve(false);
  const op: LibraryOp = { kind: 'like', track: tr };
  if (refused(lib, op)) return Promise.resolve(false);   // refus dit d'avance : pas d'annonce d'ajout
  const done = engine.dispatch(op);
  const toast = say('library.toast.liked', { vars: { title: songOf(tr) }, kind: 'ok' });
  void done.then((ok) => { if (!ok) herald.retract(toast); });
  return done;
}

/** Retirer un titre d'une playlist : annonce annulable (le titre revient à sa place). */
function removeFromPlaylist(id: string, track: LibraryTrack): Promise<boolean> {
  const pl = playlistOf(id);
  if (!pl) return run({ kind: 'remove', id: engine.idOf(id), url: track.url });
  const k = trackKey(track.url);
  const at = pl.tracks.findIndex((x) => trackKey(x.url) === k);
  const done = run({ kind: 'remove', id: pl.id, url: track.url });
  const toast = say('library.toast.removed', {
    vars: { name: pl.name, title: songOf(track) }, kind: 'info',
    // rajouté (à la fin), puis ramené à son rang : les deux partent l'un après l'autre (lib/library.ts)
    action: { label: t('toast.undo'), run: () => { void run({ kind: 'add', id: pl.id, tracks: [track] }); void run({ kind: 'move', id: pl.id, url: track.url, to: at }); } },
  });
  void done.then((ok) => { if (!ok) herald.retract(toast); });
  return done;
}

/** Alt+↑ / Alt+↓ : le titre `track` amené au rang `to`. */
function moveInPlaylist(id: string, track: LibraryTrack, to: number): Promise<boolean> {
  return run({ kind: 'move', id: engine.idOf(id), url: track.url, to });
}

/** « Tout jouer » : la playlist entière dans la file, d'un geste (playerActions.enqueueMany, toast annulable). */
function playAll(tracks: readonly LibraryTrack[], label: string): Promise<boolean> {
  if (!tracks.length) return Promise.resolve(false);
  return playerActions.enqueueMany(tracks.map(wireTrack), label).catch(() => false);   // erreur déjà annoncée
}

function setOpen(open: string | null): void {
  useLibrary.setState({ open });
}

export const libraryActions = {
  load, toggleLike, unlike, createPlaylist, createPlaylistWith, saveQueue, nameValid, renamePlaylist, deletePlaylist,
  addToPlaylist, addTo, removeFromPlaylist, moveInPlaylist, playAll, setOpen, idOf: engine.idOf, originOf: engine.originOf,
};

/**
 * Le chansonnier suit le Roi connecté : lu quand `me` arrive (ou change), vidé à la déconnexion, y compris quand un 401
 * fait perdre la session (handleLoggedOut). Abonnement au store : la déconnexion vide avant toute réponse en vol.
 * À appeler une fois (Sidebar, toujours monté).
 */
export function useLibraryInit(): void {
  useEffect(() => {
    let meId = '';
    const sync = (id: string) => {
      if (id === meId) return;
      meId = id;
      clear();
      if (id) void load();
    };
    sync(useStore.getState().me?.id ?? '');
    return useStore.subscribe((s) => sync(s.me?.id ?? ''));
  }, []);
}
