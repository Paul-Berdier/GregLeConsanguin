export interface Track {
  /** Clé stable d'un titre d'un état à l'autre (assignKeys, playerUtils.ts) ; '' avant assignKeys. */
  key: string;
  url: string;
  title: string;
  artist?: string;
  duration?: number | null;
  thumb?: string | null;
  thumbnail?: string | null;
  provider?: string | null;
  addedBy?: { id: string; name: string } | null;
  raw?: any;
}

export interface UserInfo {
  id: string;
  username: string;
  display_name?: string;
  global_name?: string;
  avatar?: string;
  avatar_url?: string;
  weight?: number;
  is_admin?: boolean;
  is_owner?: boolean;
}

export interface PlayerState {
  current: Track | null;
  queue: Track[];
  paused: boolean;
  repeat: boolean;
  position: number;
  duration: number;
}

/**
 * Ancre de l'horloge : position `pos` (s) à l'instant `at` (performance.now(), ms), durée `dur` (s).
 * `frozen` : le son n'avance pas même hors pause (titre en chargement, flux du bot bloqué : synchro son/vidéo).
 */
export interface TickBase {
  pos: number;
  at: number;
  dur: number;
  frozen?: boolean;
}

/** Un état complet du lecteur : ce que l'API ou le socket envoient, ou ce que la page affiche. */
export interface Snapshot {
  player: PlayerState;
  tickBase: TickBase;
}

export interface GuildInfo {
  id: string;
  name: string;
  icon?: string;
  owner?: boolean;
  // Absent si l'API ne connaît pas la présence du bot (clé Redis greg:bot:guilds manquante)
  bot_present?: boolean;
}

export interface SearchResult {
  title: string;
  url: string;
  webpage_url?: string;
  artist?: string;
  uploader?: string;
  channel?: string;
  duration?: number | null;
  thumb?: string | null;
  thumbnail?: string | null;
  source?: string;
  provider?: string;
}

export type StatusKind = 'info' | 'ok' | 'err' | 'warn';

/**
 * Un titre du chansonnier du Roi (API /library, spec 2026-11-23 §3) : lien http(s), titre brut (nettoyé à l'affichage),
 * durée en secondes, ajouté à `added_at` (secondes epoch).
 */
export interface LibraryTrack {
  url: string;
  title: string;
  artist: string | null;
  duration: number | null;
  thumb: string | null;
  provider: 'youtube' | 'soundcloud' | null;
  added_at: number;
}

/** Une playlist du Roi : `id` donné par l'API (ou provisoire, « tmp:… », tant qu'elle n'a pas répondu). */
export interface LibraryPlaylist {
  id: string;
  name: string;
  tracks: LibraryTrack[];
  created_at: number;
  updated_at: number;
}

/** Plafonds de l'API : coups de cœur, playlists, titres par playlist, caractères d'un nom. */
export interface LibraryLimits {
  likes: number;
  playlists: number;
  tracks: number;
  name: number;
}

/** Le chansonnier d'un Roi : coups de cœur (le plus récent en tête) et playlists. */
export interface Library {
  likes: LibraryTrack[];
  playlists: LibraryPlaylist[];
  limits: LibraryLimits;
}
