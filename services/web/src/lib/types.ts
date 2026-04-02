export interface Track {
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

export interface GuildInfo {
  id: string;
  name: string;
  icon?: string;
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

export interface SpotifyProfile {
  id: string;
  display_name?: string;
  email?: string;
  images?: { url: string }[];
}

export interface SpotifyPlaylist {
  id: string;
  name: string;
  owner?: { display_name?: string; id?: string } | string;
  tracks?: { total?: number };
  tracks_total?: number;
  tracksCount?: number;
  images?: { url: string }[];
  image?: string;
  cover?: string;
}

export interface SpotifyTrack {
  id: string;
  name?: string;
  title?: string;
  uri?: string;
  artists?: { name: string }[] | string;
  artist?: string;
  duration_ms?: number;
  album?: { images?: { url: string }[] };
  image?: string;
}

export type StatusKind = 'info' | 'ok' | 'err' | 'warn';
