export interface Track {
  url: string;
  title: string;
  artist?: string;
  duration?: number;
  thumb?: string;
  thumbnail?: string;
  provider?: string;
  added_by?: string;
  priority?: number;
  requested_by?: string;
}

export interface UserInfo {
  id: string;
  username: string;
  display_name: string;
  global_name?: string;
  avatar?: string;
  avatar_url?: string;
  weight?: number;
  weight_key?: string;
  is_admin?: boolean;
  is_owner?: boolean;
}

export interface Progress {
  elapsed: number;
  duration?: number;
}

export interface PlayerState {
  guild_id?: number;
  current?: Track | null;
  queue: Track[];
  paused: boolean;
  is_paused?: boolean;
  position: number;
  duration?: number;
  progress?: Progress;
  thumbnail?: string;
  repeat_all: boolean;
  requested_by_user?: UserInfo | null;
  queue_users?: Record<string, UserInfo>;
  only_elapsed?: boolean;
}

export interface GuildInfo {
  id: string;
  name: string;
  icon?: string;
}

export interface SearchResult {
  title: string;
  url: string;
  artist: string;
  duration?: number;
  thumb: string;
  thumbnail: string;
  source: string;
}

export interface ApiResponse<T = any> {
  ok: boolean;
  error?: string;
  // Generic fields returned by various endpoints
  data?: T;
  state?: PlayerState;
  results?: T[];
  // Auth
  user?: UserInfo & Record<string, any>;
  // Guilds
  guilds?: GuildInfo[];
  // Player
  result?: any;
  repeat_all?: boolean;
  action?: string;
  [key: string]: any;  // Allow extra fields
}
