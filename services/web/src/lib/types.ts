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

/** Ancre de l'horloge : position `pos` (s) à l'instant `at` (performance.now(), ms), durée `dur` (s). */
export interface TickBase {
  pos: number;
  at: number;
  dur: number;
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
