/**
 * Le chansonnier du Roi (spec 2026-11-23 §3) : ses coups de cœur et ses playlists, gardés par l'API (Redis) pour chaque Roi.
 * Pur, sans import runtime (tests/library.test.mjs) :
 * - identité d'un titre (trackKey) : la même clé que l'API, qui écarte les doublons avec elle ;
 * - titre du chansonnier tiré d'un titre de la file, de l'historique ou d'une recherche (toLibraryTrack), nettoyé comme l'API ;
 * - durées, recherche d'une playlist, plan d'un ajout (doublons écartés, plafond de 200 titres) ;
 * - application optimiste des modifications (applyOp) et refus prévus d'avance (checkOp), message du Héraut (noticeOf) ;
 * - annulations à l'ancien rang (undoOf), appel de l'API de chaque modification (sendOp) ;
 * - moteur qui envoie les modifications une à une et revient en arrière quand l'API refuse (createLibraryEngine).
 */
import type { Library, LibraryLimits, LibraryPlaylist, LibraryTrack } from './types';

/** Plafonds de l'API (spec §3), quand sa réponse ne les donne pas. */
export const DEFAULT_LIMITS: LibraryLimits = { likes: 500, playlists: 50, tracks: 200, name: 60 };
/** POST /queue/add_many : 1 à 100 titres par appel. */
export const ADD_MANY_MAX = 100;
/** Vue des coups de cœur dans le chansonnier : jamais l'id d'une playlist (token_urlsafe(8) : 11 caractères). */
export const LIKES = 'likes';
/** Préfixe d'un id provisoire : la playlist créée attend le sien de l'API. */
export const TMP = 'tmp:';

const URL_MAX = 500, TITLE_MAX = 200, ARTIST_MAX = 120, DURATION_MAX = 86400;

// Les formes de l'API (library_store._YT_ID_RE, _YT_HOST_RE), qui sont celles de VIDEO_ID / YOUTUBE_HOST de
// lib/format.ts et du bot : ?v=, /shorts/, /live/, /embed/ (sauf « videoseries », une playlist), youtu.be/, anciennes
// formes /v/ /e/ /watch/ ; hôtes youtube.com (www., m., music.…), youtu.be, youtube-nocookie.com. Une forme de moins
// ici, et un titre que l'API dit aimé paraîtrait libre (cœur relâché, doublon accepté puis écarté). Copie et non
// import (lib/format.ts) : module pur.
const YT_ID = /(?:[?&]v=|\/shorts\/|\/live\/|\/embed\/(?!videoseries)|youtu\.be\/|\.com\/(?:v|e|watch)\/)([A-Za-z0-9_-]{11})/;
const YT_HOST = /(?:^|\.)(?:youtube\.com|youtu\.be|youtube-nocookie\.com)$/;
const SC_HOST = /(?:^|\.)soundcloud\.com$/;

function hostOf(url: string): string {
  try { return new URL(/^[a-z][\w+.-]*:\/\//i.test(url) ? url : `https://${url}`).hostname.toLowerCase(); } catch { return ''; }
}

/** Id de la vidéo YouTube d'un lien (formes de la spec), sinon null. */
export function youtubeId(url: string | null | undefined): string | null {
  const u = String(url ?? '').trim();
  const m = u.match(YT_ID);
  return m && YT_HOST.test(hostOf(u)) ? m[1] : null;
}

/**
 * Identité d'un titre, calculée comme l'API (library_store.track_key) : `yt:<id>` pour une vidéo YouTube, sinon
 * `url:<lien>` sans aucun blanc ni « / » final. '' : pas de lien.
 */
export function trackKey(url: string | null | undefined): string {
  const u = String(url ?? '').trim();
  if (!u) return '';
  const id = youtubeId(u);
  return id ? `yt:${id}` : `url:${u.replace(/\s+/g, '').replace(/\/+$/, '')}`;
}

/** Source déduite de l'hôte, comme l'API quand le titre ne la dit pas. */
export function providerOf(url: string): LibraryTrack['provider'] {
  const h = hostOf(url.trim());
  return YT_HOST.test(h) ? 'youtube' : SC_HOST.test(h) ? 'soundcloud' : null;
}

/** Ce qu'on sait d'un titre de la file (Track), de l'historique (HistoryItem) ou d'une recherche (SearchResult). */
export type TrackLike = {
  url?: string | null; webpage_url?: string | null; title?: string | null; artist?: string | null;
  duration?: number | null; thumb?: string | null; thumbnail?: string | null; provider?: string | null; added_at?: number | null;
};

const text = (v: unknown): string => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim() : '');
/** Lien http(s) que l'API garde (library_store._http_url) : sans blanc, caractère de contrôle ni « \ » (sinon toute la
 * liste envoyée serait refusée, INVALID_TRACK). */
const httpUrl = (v: unknown): string | null => {
  const s = typeof v === 'string' ? v.trim() : '';
  return s.length <= URL_MAX && /^https?:\/\/[^\s\\\u0000-\u001f\u007f-\u009f]+$/i.test(s) ? s : null;
};
/** Coupé à `n` caractères (points de code, comme len() de Python). */
const clip = (s: string, n: number): string => { const cps = [...s]; return cps.length > n ? cps.slice(0, n).join('') : s; };

/**
 * Titre du chansonnier, nettoyé comme l'API le stocke (spec §3) : lien http(s) d'au plus 500 caractères (sinon null),
 * titre (200, le lien à défaut), artiste (120) ou null, durée entière 0..86400 ou null, pochette http(s) ou null,
 * source youtube / soundcloud (déduite de l'hôte si absente), ajouté à `added_at` (secondes) ou maintenant.
 */
export function toLibraryTrack(x: TrackLike | null | undefined, nowMs: number): LibraryTrack | null {
  if (!x || typeof x !== 'object') return null;
  const url = httpUrl(x.url) ?? httpUrl(x.webpage_url);
  if (!url) return null;
  const d = typeof x.duration === 'number' ? x.duration : NaN;
  const at = typeof x.added_at === 'number' ? x.added_at : NaN;
  return {
    url,
    title: clip(text(x.title) || url, TITLE_MAX),
    artist: clip(text(x.artist), ARTIST_MAX) || null,
    duration: Number.isFinite(d) && d >= 0 && d <= DURATION_MAX ? Math.floor(d) : null,
    thumb: httpUrl(x.thumb) ?? httpUrl(x.thumbnail),
    provider: x.provider === 'youtube' || x.provider === 'soundcloud' ? x.provider : providerOf(url),
    added_at: Number.isFinite(at) && at > 0 ? Math.floor(at) : Math.floor(nowMs / 1000),
  };
}

/** Ce que l'API reçoit d'un titre (elle date l'ajout elle-même) ; aussi un élément de POST /queue/add_many. */
export function wireTrack(t: LibraryTrack): Omit<LibraryTrack, 'added_at'> {
  return { url: t.url, title: t.title, artist: t.artist, duration: t.duration, thumb: t.thumb, provider: t.provider };
}

/** Nom d'une playlist nettoyé comme l'API : espaces réduits, caractères de contrôle retirés. */
export function cleanName(s: unknown): string {
  return typeof s === 'string' ? s.replace(/\s+/g, ' ').replace(/[\u0000-\u001f\u007f-\u009f]/g, '').trim() : '';
}

/** Nom valide (déjà nettoyé) : 1 à `max` caractères. */
export const nameOk = (name: string, max: number = DEFAULT_LIMITS.name): boolean => {
  const n = [...name].length;
  return n >= 1 && n <= max;
};

/** Durée totale (secondes) ; une durée inconnue compte pour rien. */
export const totalSeconds = (tracks: readonly Pick<LibraryTrack, 'duration'>[]): number =>
  tracks.reduce((s, t) => s + (t.duration && t.duration > 0 ? t.duration : 0), 0);

export function findPlaylist(lib: Library | null | undefined, id: string | null | undefined): LibraryPlaylist | null {
  return (id && lib?.playlists.find((p) => p.id === id)) || null;
}

/** Titres d'une vue du chansonnier : les coups de cœur (LIKES) ou une playlist ; null : elle n'existe pas (ou plus). */
export function tracksOf(lib: Library | null | undefined, id: string | null | undefined): LibraryTrack[] | null {
  if (!lib || !id) return null;
  return id === LIKES ? lib.likes : findPlaylist(lib, id)?.tracks ?? null;
}

/** Clés (trackKey) des coups de cœur : un cœur se dit « pressé » en O(1) sur chaque ligne de la file. */
export const likedKeys = (likes: readonly LibraryTrack[]): Set<string> => new Set(likes.map((t) => trackKey(t.url)));

/** Ajout à une playlist (ou à sa création) : titres nouveaux, sans doublon entre eux ni avec `existing`, dans la place restante. */
export function addPlan(existing: readonly LibraryTrack[], tracks: readonly LibraryTrack[], max: number): { added: LibraryTrack[]; skipped: number } {
  const seen = new Set(existing.map((t) => trackKey(t.url)));
  const room = Math.max(0, max - existing.length);
  const added: LibraryTrack[] = [];
  for (const t of tracks) {
    const k = trackKey(t.url);
    if (!k || seen.has(k) || added.length >= room) continue;
    seen.add(k);
    added.push(t);
  }
  return { added, skipped: tracks.length - added.length };
}

/**
 * POST /library/playlists/move {src, dst} : l'API fait tracks.insert(dst, tracks.pop(src)), le titre `url` arrive au
 * rang `to` (borné à la playlist). null : rien à faire.
 */
export function moveIndices(tracks: readonly LibraryTrack[], url: string, to: number): { src: number; dst: number } | null {
  if (!Number.isFinite(to) || !tracks.length) return null;
  const k = trackKey(url);
  const src = tracks.findIndex((t) => trackKey(t.url) === k);
  if (src < 0) return null;
  const dst = Math.max(0, Math.min(tracks.length - 1, Math.trunc(to)));
  return dst === src ? null : { src, dst };
}

/** Rang d'insertion borné à [0, n] (NaN : 0, Infinity : n). */
const clampAt = (i: number, n: number): number => Math.max(0, Math.min(n, Math.trunc(i) || 0));

/**
 * Une modification du chansonnier, par identité de titre (jamais par rang : rejouable sur un état plus récent). Seules
 * les annulations portent un rang (`at`, borné par l'API comme ici) : le coup de cœur retiré, la playlist supprimée
 * reviennent où ils étaient.
 */
export type LibraryOp =
  | { kind: 'like'; track: LibraryTrack; at?: number }
  | { kind: 'unlike'; url: string }
  | { kind: 'create'; id: string; name: string; tracks: LibraryTrack[] }
  | { kind: 'restore'; id: string; name: string; tracks: LibraryTrack[]; created_at: number; updated_at: number; at: number }
  | { kind: 'rename'; id: string; name: string }
  | { kind: 'delete'; id: string }
  | { kind: 'add'; id: string; tracks: LibraryTrack[] }
  | { kind: 'remove'; id: string; url: string }
  | { kind: 'move'; id: string; url: string; to: number };

function withPlaylist(lib: Library, id: string, fn: (p: LibraryPlaylist) => LibraryPlaylist): Library {
  const i = lib.playlists.findIndex((p) => p.id === id);
  if (i < 0) return lib;
  const next = fn(lib.playlists[i]);
  if (next === lib.playlists[i]) return lib;
  const playlists = lib.playlists.slice();
  playlists[i] = next;
  return { ...lib, playlists };
}

/**
 * Applique une modification comme l'API le fera (vue optimiste). Idempotente : la rejouer sur un état qui la contient
 * déjà ne change rien, et le même objet revient quand rien ne change (le reste du chansonnier garde ses références).
 * Cœur : en tête (ou au rang `at`), sans doublon, plafonné. Création : à la fin, titres dédoublonnés et plafonnés.
 * Restauration : au rang `at`, sous son id et ses dates, sauf si cet id est déjà là. Ajout : à la fin.
 */
export function applyOp(lib: Library, op: LibraryOp, nowMs: number): Library {
  const now = Math.floor(nowMs / 1000);
  switch (op.kind) {
    case 'like': {
      const k = trackKey(op.track.url);
      if (!k || lib.likes.length >= lib.limits.likes || lib.likes.some((t) => trackKey(t.url) === k)) return lib;
      const likes = lib.likes.slice();
      likes.splice(clampAt(op.at ?? 0, likes.length), 0, op.track);
      return { ...lib, likes };
    }
    case 'restore': {
      if (findPlaylist(lib, op.id) || lib.playlists.length >= lib.limits.playlists) return lib;
      const playlists = lib.playlists.slice();
      playlists.splice(clampAt(op.at, playlists.length), 0, {
        id: op.id, name: op.name, tracks: addPlan([], op.tracks, lib.limits.tracks).added, created_at: op.created_at, updated_at: op.updated_at,
      });
      return { ...lib, playlists };
    }
    case 'unlike': {
      const k = trackKey(op.url);
      const likes = lib.likes.filter((t) => trackKey(t.url) !== k);
      return likes.length === lib.likes.length ? lib : { ...lib, likes };
    }
    case 'create': {
      if (findPlaylist(lib, op.id) || lib.playlists.length >= lib.limits.playlists) return lib;
      const tracks = addPlan([], op.tracks, lib.limits.tracks).added;
      return { ...lib, playlists: [...lib.playlists, { id: op.id, name: op.name, tracks, created_at: now, updated_at: now }] };
    }
    case 'rename':
      return withPlaylist(lib, op.id, (p) => (p.name === op.name ? p : { ...p, name: op.name, updated_at: now }));
    case 'delete': {
      const playlists = lib.playlists.filter((p) => p.id !== op.id);
      return playlists.length === lib.playlists.length ? lib : { ...lib, playlists };
    }
    case 'add':
      return withPlaylist(lib, op.id, (p) => {
        const { added } = addPlan(p.tracks, op.tracks, lib.limits.tracks);
        return added.length ? { ...p, tracks: [...p.tracks, ...added], updated_at: now } : p;
      });
    case 'remove':
      return withPlaylist(lib, op.id, (p) => {
        const k = trackKey(op.url);
        const tracks = p.tracks.filter((t) => trackKey(t.url) !== k);
        return tracks.length === p.tracks.length ? p : { ...p, tracks, updated_at: now };
      });
    case 'move':
      return withPlaylist(lib, op.id, (p) => {
        const mv = moveIndices(p.tracks, op.url, op.to);
        if (!mv) return p;
        const tracks = p.tracks.slice();
        tracks.splice(mv.dst, 0, ...tracks.splice(mv.src, 1));
        return { ...p, tracks, updated_at: now };
      });
  }
}

/** Refus prévu sans appeler l'API ; NOOP : rien à faire (déjà fait) ; DUPLICATE : tous les titres y sont déjà. */
export type Refusal =
  | { code: 'LIMIT_REACHED'; limit: 'likes' | 'playlists' | 'tracks' }
  | { code: 'INVALID_NAME' | 'INVALID_TRACK' | 'PLAYLIST_NOT_FOUND' | 'DUPLICATE' | 'NOOP' };

/** Ce que l'API refuserait (ou ce qui ne ferait rien) : le Héraut le dit sans aller-retour, rien n'est envoyé. */
export function checkOp(lib: Library, op: LibraryOp): Refusal | null {
  const { limits } = lib;
  const has = (list: readonly LibraryTrack[], url: string) => { const k = trackKey(url); return list.some((t) => trackKey(t.url) === k); };
  switch (op.kind) {
    case 'like':
      if (!trackKey(op.track.url)) return { code: 'INVALID_TRACK' };
      if (has(lib.likes, op.track.url)) return { code: 'NOOP' };
      return lib.likes.length >= limits.likes ? { code: 'LIMIT_REACHED', limit: 'likes' } : null;
    case 'unlike':
      return has(lib.likes, op.url) ? null : { code: 'NOOP' };
    case 'create':
    case 'restore':
      // restaurée déjà là (par un autre onglet, relue depuis) : rien à faire ; sinon nom et plafond d'une création
      if (op.kind === 'restore' && findPlaylist(lib, op.id)) return { code: 'NOOP' };
      if (!nameOk(op.name, limits.name)) return { code: 'INVALID_NAME' };
      return lib.playlists.length >= limits.playlists ? { code: 'LIMIT_REACHED', limit: 'playlists' } : null;
    default: {
      const p = findPlaylist(lib, op.id);
      if (!p) return { code: 'PLAYLIST_NOT_FOUND' };
      if (op.kind === 'rename') return !nameOk(op.name, limits.name) ? { code: 'INVALID_NAME' } : op.name === p.name ? { code: 'NOOP' } : null;
      if (op.kind === 'delete') return null;
      if (op.kind === 'remove') return has(p.tracks, op.url) ? null : { code: 'NOOP' };
      if (op.kind === 'move') return moveIndices(p.tracks, op.url, op.to) ? null : { code: 'NOOP' };
      if (!op.tracks.some((t) => trackKey(t.url))) return { code: 'INVALID_TRACK' };
      if (addPlan(p.tracks, op.tracks, limits.tracks).added.length) return null;
      return addPlan(p.tracks, op.tracks, Infinity).added.length ? { code: 'LIMIT_REACHED', limit: 'tracks' } : { code: 'DUPLICATE' };
    }
  }
}

/** Code d'erreur de l'API (`error` de la réponse), en majuscules ; '' : aucun (réseau, réponse illisible). */
export function libraryCode(e: unknown): string {
  const p = (e as { payload?: unknown } | null)?.payload;
  const code = p && typeof p === 'object' ? (p as { error?: unknown }).error : null;
  return typeof code === 'string' ? code.trim().toUpperCase() : '';
}

/** Écart minimal entre deux relectures au retour sur la fenêtre (comme la session, app/page.tsx). */
export const REREAD_MIN_MS = 15_000;

/**
 * Retour sur la fenêtre : le chansonnier est relu (changé depuis un autre appareil ou onglet : un déplacement compté sur
 * l'ancien ordre viserait un autre titre). Seulement chargé, rien en attente (chaque accusé rend le chansonnier entier),
 * au plus une fois par REREAD_MIN_MS.
 */
export const rereadOnFocus = (o: { status: string; pending: number; now: number; last: number }): boolean =>
  o.status === 'ready' && o.pending === 0 && o.now - o.last >= REREAD_MIN_MS;

/** Message du Héraut (section `library.error` de copy.extra.ts) ; `vars` : plafond, nom de la playlist. */
export type Notice = { key: string; vars?: Record<string, string | number>; kind: 'info' | 'warn' | 'err' };

/**
 * Le refus `code` d'une modification `op`, dit par le Héraut. null : à l'appelant (NOT_AUTHENTICATED passe par la perte
 * de session, une erreur inconnue par le texte générique, NOOP et DUPLICATE par leur propre message ou rien).
 */
export function noticeOf(code: string, op: LibraryOp, lib: Library | null | undefined, limit?: unknown): Notice | null {
  const limits = lib?.limits ?? DEFAULT_LIMITS;
  const name = 'id' in op ? findPlaylist(lib, op.id)?.name ?? ('name' in op ? op.name : '') : '';
  switch (code) {
    case 'LIMIT_REACHED':
      // budget d'octets du chansonnier entier (API, MAX_LIBRARY_BYTES) : ni un plafond de titres, ni de playlists
      if (limit === 'size') return { key: 'library.error.limitSize', kind: 'warn' };
      if (op.kind === 'like') return { key: 'library.error.limitLikes', vars: { n: limits.likes }, kind: 'warn' };
      if (op.kind === 'create' || op.kind === 'restore') return { key: 'library.error.limitPlaylists', vars: { n: limits.playlists }, kind: 'warn' };
      return { key: 'library.error.limitTracks', vars: { n: limits.tracks, name }, kind: 'warn' };
    case 'INVALID_NAME': return { key: 'library.error.INVALID_NAME', vars: { n: limits.name }, kind: 'warn' };
    case 'INVALID_TRACK': return { key: 'library.error.INVALID_TRACK', kind: 'warn' };
    case 'PLAYLIST_NOT_FOUND': return { key: 'library.error.PLAYLIST_NOT_FOUND', kind: 'warn' };
    // déplacement compté sur une copie dépassée (réordonnée ailleurs) : l'API n'a rien bougé, le chansonnier est relu
    case 'STALE': return { key: 'library.error.STALE', kind: 'warn' };
    case 'STORAGE_UNAVAILABLE': return { key: 'library.error.STORAGE_UNAVAILABLE', kind: 'err' };
    default: return null;
  }
}

/** 404 sans code du chansonnier : la route manque (API plus ancienne que le site), pas une playlist disparue. */
export function routeMissing(e: unknown): boolean {
  return (e as { status?: unknown } | null)?.status === 404 && libraryCode(e) !== 'PLAYLIST_NOT_FOUND';
}

/**
 * L'annulation de `op`, préparée sur le chansonnier `lib` d'avant lui : le coup de cœur retiré revient à son rang, la
 * playlist supprimée revient à sa place, sous son id, avec ses titres et ses dates. null : rien à défaire (absent), ou
 * une modification sans annulation de ce genre.
 */
export function undoOf(lib: Library | null | undefined, op: LibraryOp): LibraryOp | null {
  if (!lib) return null;
  if (op.kind === 'unlike') {
    const k = trackKey(op.url);
    const at = lib.likes.findIndex((t) => trackKey(t.url) === k);
    return at < 0 ? null : { kind: 'like', track: lib.likes[at], at };
  }
  if (op.kind === 'delete') {
    const at = lib.playlists.findIndex((p) => p.id === op.id);
    const p = lib.playlists[at];
    return p ? { kind: 'restore', id: p.id, name: p.name, tracks: p.tracks, created_at: p.created_at, updated_at: p.updated_at, at } : null;
  }
  return null;
}

/** Les routes du chansonnier qu'une modification emprunte (lib/api.ts). */
export type LibraryApi = {
  libraryLike: (track: Record<string, unknown>, index?: number) => Promise<unknown>;
  libraryUnlike: (url: string) => Promise<unknown>;
  playlistCreate: (name: string, tracks: readonly Record<string, unknown>[]) => Promise<unknown>;
  playlistRestore: (playlist: Record<string, unknown>, index: number) => Promise<unknown>;
  playlistRename: (id: string, name: string) => Promise<unknown>;
  playlistDelete: (id: string) => Promise<unknown>;
  playlistAdd: (id: string, tracks: readonly Record<string, unknown>[]) => Promise<unknown>;
  playlistRemove: (id: string, url: string) => Promise<unknown>;
  playlistMove: (id: string, src: number, dst: number, url?: string) => Promise<unknown>;
};

/**
 * Une modification vers l'API (`send` du moteur). Un déplacement se compte sur `base`, le chansonnier confirmé, celui que
 * l'API modifie, et nomme son titre : copie dépassée, l'API répond STALE sans rien bouger. Une restauration garde l'id,
 * les dates et le rang ; une API d'avant sa route (404 sans code) recrée la playlist à la fin, sous un nouvel id que le
 * moteur suit comme celui d'une création.
 */
export function sendOp(api: LibraryApi, op: LibraryOp, base: Library): Promise<unknown> {
  switch (op.kind) {
    case 'like': return api.libraryLike(wireTrack(op.track), op.at);
    case 'unlike': return api.libraryUnlike(op.url);
    case 'create': return api.playlistCreate(op.name, op.tracks.map(wireTrack));
    case 'restore': {
      const playlist = { id: op.id, name: op.name, tracks: op.tracks.map((t) => ({ ...wireTrack(t), added_at: t.added_at })), created_at: op.created_at, updated_at: op.updated_at };
      return api.playlistRestore(playlist, op.at).catch((e: unknown) => {
        if (!routeMissing(e)) throw e;
        return api.playlistCreate(op.name, op.tracks.map(wireTrack));
      });
    }
    case 'rename': return api.playlistRename(op.id, op.name);
    case 'delete': return api.playlistDelete(op.id);
    case 'add': return api.playlistAdd(op.id, op.tracks.map(wireTrack));
    case 'remove': return api.playlistRemove(op.id, op.url);
    case 'move': {
      const mv = moveIndices(findPlaylist(base, op.id)?.tracks ?? [], op.url, op.to);
      return mv ? api.playlistMove(op.id, mv.src, mv.dst, op.url) : Promise.resolve(null);
    }
  }
}

const int = (v: unknown, dflt: number): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.floor(v) : dflt);

/**
 * Le chansonnier d'une réponse de l'API (`{ok, library}` ou le chansonnier seul), titres nettoyés ; null : illisible.
 * Les plafonds absents (réponse d'une modification) gardent ceux de `limits`.
 */
export function parseLibrary(payload: unknown, limits: LibraryLimits = DEFAULT_LIMITS): Library | null {
  const p = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : null;
  const raw = p && p.library && typeof p.library === 'object' ? (p.library as Record<string, unknown>)
    : p && (Array.isArray(p.likes) || Array.isArray(p.playlists)) ? p : null;
  if (!raw) return null;
  const tracks = (xs: unknown): LibraryTrack[] => (Array.isArray(xs)
    ? xs.map((x) => toLibraryTrack(x as TrackLike, 0)).filter((x): x is LibraryTrack => !!x) : []);
  const lim = raw.limits && typeof raw.limits === 'object' ? (raw.limits as Record<string, unknown>) : null;
  return {
    likes: tracks(raw.likes),
    playlists: (Array.isArray(raw.playlists) ? raw.playlists : [])
      .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object' && typeof (x as { id?: unknown }).id === 'string')
      .map((x) => ({
        id: x.id as string, name: typeof x.name === 'string' ? x.name : '', tracks: tracks(x.tracks),
        created_at: int(x.created_at, 0), updated_at: int(x.updated_at, 0),
      })),
    limits: lim ? { likes: int(lim.likes, limits.likes), playlists: int(lim.playlists, limits.playlists),
      tracks: int(lim.tracks, limits.tracks), name: int(lim.name, limits.name) } : limits,
  };
}

/**
 * Id de la playlist créée : `playlist_id` de la réponse, sinon (`guess`) celle qui n'était pas là avant. Une restauration
 * ne devine pas (une playlist créée entre-temps par un autre onglet passerait pour elle) : seule la création de repli
 * (sendOp) répond un `playlist_id`.
 */
function createdId(res: unknown, before: Library, after: Library, guess = true): string | null {
  const id = (res as { playlist_id?: unknown } | null)?.playlist_id;
  if (typeof id === 'string' && id) return id;
  if (!guess) return null;
  const known = new Set(before.playlists.map((p) => p.id));
  return after.playlists.find((p) => !known.has(p.id))?.id ?? null;
}

export type LibraryEngineOptions = {
  /** Envoie `op` à l'API et rend sa réponse ; `base` : le chansonnier confirmé, celui que l'API modifiera. */
  send: (op: LibraryOp, base: Library) => Promise<unknown>;
  now: () => number;
  /** La vue a changé : le chansonnier confirmé et les modifications pas encore accusées ; null : rien de chargé. */
  onView: (lib: Library | null) => void;
  /** Refus de l'API, la vue déjà revenue en arrière. */
  onFail?: (op: LibraryOp, e: unknown) => void;
  /** La playlist créée a reçu son id : le provisoire `tmp` en devient l'alias. */
  onAlias?: (tmp: string, id: string) => void;
};

type Pending = { op: LibraryOp; at: number; done: (ok: boolean) => void };

/**
 * Modifications optimistes du chansonnier : la vue est `pending.reduce(applyOp, server)`. Une requête à la fois, dans
 * l'ordre (chaque réponse rend le chansonnier entier, la suivante part de lui) ; refusée, la modification est retirée et
 * la vue revient en arrière. Une création porte un id provisoire (TMP) : ce qui l'attend reçoit le vrai à sa réponse, et
 * tombe avec elle si elle est refusée ; de même pour une restauration (son id, ou celui de la création de repli).
 * reset() (déconnexion) oublie tout ; une réponse arrivée après est ignorée.
 */
export function createLibraryEngine(o: LibraryEngineOptions) {
  let server: Library | null = null;
  let pending: Pending[] = [];
  let shown: Library | null = null;
  let busy = false;
  let epoch = 0;
  let acks = 0;
  const aliases = new Map<string, string>(), origins = new Map<string, string>();
  const idOf = (id: string): string => aliases.get(id) ?? id;
  const rename = (op: LibraryOp, from: string, to: string): LibraryOp => ('id' in op && op.id === from ? ({ ...op, id: to } as LibraryOp) : op);
  const resolve = (op: LibraryOp): LibraryOp => ('id' in op && aliases.has(op.id) ? rename(op, op.id, idOf(op.id)) : op);

  const emit = () => {
    shown = server && pending.reduce((lib, p) => applyOp(lib, p.op, p.at), server);
    o.onView(shown);
  };

  const pump = async (): Promise<void> => {
    if (busy || !server || !pending.length) return;
    busy = true;
    const e0 = epoch, head = pending[0], base = server;
    let res: unknown = null, err: unknown = null, ok = true;
    try { res = await o.send(head.op, base); } catch (e) { ok = false; err = e; }
    busy = false;
    if (e0 !== epoch) { void pump(); return; }   // oublié entre-temps (déconnexion) : ni accusé ni retour arrière
    pending.shift();
    if (ok) {
      acks++;
      // réponse sans chansonnier lisible : la modification telle qu'appliquée devient l'état confirmé
      server = parseLibrary(res, base.limits) ?? applyOp(base, head.op, head.at);
      if (head.op.kind === 'create' || head.op.kind === 'restore') {
        const tmp = head.op.id, id = createdId(res, base, server, head.op.kind === 'create');
        if (id && id !== tmp) {
          aliases.set(tmp, id);
          origins.set(id, tmp);
          pending = pending.map((p) => ({ ...p, op: rename(p.op, tmp, id) }));
          o.onAlias?.(tmp, id);
        }
      }
    } else if (head.op.kind === 'create' || head.op.kind === 'restore') {
      // la playlist n'existera pas (ni créée, ni revenue) : ce qui l'attendait tombe avec elle, sans autre annonce
      const tmp = head.op.id;
      const orphans = pending.filter((p) => 'id' in p.op && p.op.id === tmp);
      pending = pending.filter((p) => !orphans.includes(p));
      for (const p of orphans) p.done(false);
    }
    emit();
    head.done(ok);
    if (!ok) o.onFail?.(head.op, err);
    void pump();
  };

  return {
    view: (): Library | null => shown,
    /** Le chansonnier lu (GET /library) ; les modifications en attente se rejouent par-dessus. */
    load(lib: Library): void { server = lib; emit(); void pump(); },
    /** Déconnexion, autre Roi : tout est oublié ; les modifications en attente rendent false, sans annonce. */
    reset(): void {
      epoch++;
      const dropped = pending;
      pending = [];
      server = null;
      aliases.clear();
      origins.clear();
      emit();
      for (const p of dropped) p.done(false);
    },
    /** Modification du Roi : visible tout de suite, envoyée à son tour. false : refusée (vue revenue en arrière) ou oubliée. */
    dispatch(op: LibraryOp): Promise<boolean> {
      if (!server) return Promise.resolve(false);
      const real = resolve(op);
      return new Promise<boolean>((done) => { pending.push({ op: real, at: o.now(), done }); emit(); void pump(); });
    },
    /** Id d'une playlist, provisoire compris (« tmp:… » devenu celui de l'API). */
    idOf,
    /**
     * `op` visant l'id définitif de sa playlist : un geste préparé quand elle n'avait que son id provisoire (l'annulation
     * d'un retrait fait juste après sa création) se vérifie sur la vue, qui ne connaît plus que le vrai. Sinon `op` même.
     */
    resolve,
    /** Premier id d'une playlist (le provisoire qu'elle a porté, sinon le sien) : clé React stable, la ligne reste montée. */
    originOf: (id: string): string => origins.get(id) ?? id,
    /** Modifications pas encore accusées (en vol comprise). */
    pending: (): number => pending.length,
    /**
     * Réponses acceptées par l'API jusqu'ici (chacune rend le chansonnier entier, fait foi) : une relecture (GET) partie
     * avant l'une d'elles peut la précéder chez Redis ; comparé avant et après, il dit qu'elle ne doit pas l'écraser.
     */
    acks: (): number => acks,
  };
}

export type LibraryEngine = ReturnType<typeof createLibraryEngine>;
