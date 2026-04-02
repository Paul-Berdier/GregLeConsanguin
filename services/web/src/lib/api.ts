/**
 * Greg API client — routes matching backend (player.js compatible)
 *
 * Backend routes:
 *   GET  /users/me, /auth/login, /auth/logout (POST), /guilds
 *   GET  /playlist?guild_id=..., /search/autocomplete?q=...&limit=8
 *   POST /queue/add, /queue/remove, /queue/skip, /queue/stop
 *   POST /playlist/play_at, /playlist/toggle_pause, /playlist/repeat, /playlist/restart
 *   POST /voice/join
 *   GET  /spotify/login, /spotify/status, /spotify/me, /spotify/playlists
 *   GET  /spotify/playlist_tracks?playlist_id=...
 *   POST /spotify/playlist_create, /spotify/playlist_remove_tracks
 *   POST /spotify/playlist_delete, /spotify/quickplay, /spotify/logout
 *   POST /spotify/add_current_to_playlist, /spotify/add_queue_to_playlist
 */

const DEFAULT_RAILWAY = 'https://gregleconsanguin.up.railway.app/api/v1';

function getApiBase(): string {
  if (typeof window === 'undefined') return '/api/v1';

  const raw = (window as any).GREG_API_BASE || '/api/v1';
  const b = String(raw).trim();
  if (!b) return DEFAULT_RAILWAY;

  if (/^https?:\/\//i.test(b)) return b.replace(/\/+$/, '');
  if (location.hostname.includes('railway.app')) return b.replace(/\/+$/, '');
  if (b === '/api/v1') return DEFAULT_RAILWAY;

  return b.replace(/\/+$/, '');
}

let API_BASE = '/api/v1';
if (typeof window !== 'undefined') {
  API_BASE = getApiBase();
}

export function getApiOrigin(): string {
  try {
    if (/^https?:\/\//i.test(API_BASE)) return new URL(API_BASE).origin;
    return '';
  } catch {
    return '';
  }
}

async function request(method: string, path: string, opts?: {
  query?: Record<string, string>;
  json?: any;
}): Promise<any> {
  const url = new URL(`${API_BASE}${path}`, typeof window !== 'undefined' ? location.href : 'http://localhost');

  if (opts?.query) {
    for (const [k, v] of Object.entries(opts.query)) {
      if (v === undefined || v === null || v === '') continue;
      url.searchParams.set(k, String(v));
    }
  }

  const fetchOpts: RequestInit = {
    method,
    credentials: 'include',
    headers: {} as Record<string, string>,
  };

  if (opts?.json !== undefined) {
    (fetchOpts.headers as Record<string, string>)['Content-Type'] = 'application/json';
    fetchOpts.body = JSON.stringify(opts.json);
  }

  const res = await fetch(url.toString(), fetchOpts);
  const ct = (res.headers.get('content-type') || '').toLowerCase();
  let payload: any = null;

  if (ct.includes('application/json')) {
    payload = await res.json().catch(() => null);
  } else {
    payload = await res.text().catch(() => null);
  }

  if (!res.ok) {
    const msg = payload?.error || payload?.message || `HTTP ${res.status}`;
    throw Object.assign(new Error(msg), { status: res.status, payload });
  }

  if (payload && typeof payload === 'object' && payload.ok === false) {
    throw Object.assign(new Error(payload.error || payload.message || 'Request failed'), {
      status: res.status,
      payload,
    });
  }

  return payload;
}

function get(path: string, query?: Record<string, string>) {
  return request('GET', path, { query });
}

function post(path: string, json?: any, query?: Record<string, string>) {
  return request('POST', path, { json, query });
}

// ── Helpers ──
function basePayload(guildId: string, userId: string, extra: Record<string, any> = {}) {
  const out: Record<string, any> = { ...extra };
  if (guildId) out.guild_id = String(guildId);
  if (userId) out.user_id = String(userId);
  return out;
}

export const api = {
  API_BASE,

  // Auth
  getMe: () => get('/users/me'),
  getLoginUrl: () => `${API_BASE}/auth/login`,
  logout: () => post('/auth/logout', {}),
  getGuilds: () => get('/guilds'),

  // Playlist state
  getPlaylistState: (guildId: string) =>
    get('/playlist', guildId ? { guild_id: guildId } : undefined),

  // Queue
  queueAdd: (guildId: string, userId: string, payload: Record<string, any>) => {
    const body = basePayload(guildId, userId, payload);
    return post('/queue/add', body);
  },

  queueRemove: (guildId: string, userId: string, index: number) =>
    post('/queue/remove', basePayload(guildId, userId, { index })),

  queueSkip: (guildId: string, userId: string) =>
    post('/queue/skip', basePayload(guildId, userId)),

  queueStop: (guildId: string, userId: string) =>
    post('/queue/stop', basePayload(guildId, userId)),

  // Playlist controls
  playAt: (guildId: string, userId: string, index: number) =>
    post('/playlist/play_at', basePayload(guildId, userId, { index })),

  togglePause: (guildId: string, userId: string) =>
    post('/playlist/toggle_pause', basePayload(guildId, userId)),

  repeat: (guildId: string, userId: string) =>
    post('/playlist/repeat', basePayload(guildId, userId)),

  restart: (guildId: string, userId: string) =>
    post('/playlist/restart', basePayload(guildId, userId)),

  // Voice
  voiceJoin: (guildId: string, userId: string, reason?: string) =>
    post('/voice/join', basePayload(guildId, userId, { reason: reason || '' })),

  // Search
  autocomplete: async (q: string, limit = 8): Promise<SearchResult[]> => {
    const endpoints = ['/search/autocomplete', '/autocomplete'];
    for (const path of endpoints) {
      try {
        const data = await get(path, { q, limit: String(limit) });
        const rows = Array.isArray(data?.results) ? data.results
          : Array.isArray(data) ? data
          : [];
        return rows;
      } catch (e: any) {
        if (e?.status === 404) continue;
        return [];
      }
    }
    return [];
  },

  // Spotify
  getSpotifyLoginUrl: (sid: string) =>
    `${API_BASE}/spotify/login?sid=${encodeURIComponent(sid)}`,

  spotifyStatus: () => get('/spotify/status'),
  spotifyMe: () => get('/spotify/me'),
  spotifyLogout: () => post('/spotify/logout', {}),
  spotifyPlaylists: () => get('/spotify/playlists'),
  spotifyPlaylistTracks: (playlistId: string) =>
    get('/spotify/playlist_tracks', { playlist_id: playlistId }),

  spotifyCreatePlaylist: (name: string, isPublic: boolean) =>
    post('/spotify/playlist_create', { name, public: isPublic }),

  spotifyDeletePlaylist: (playlistId: string) =>
    post('/spotify/playlist_delete', { playlist_id: playlistId }),

  spotifyRemoveTracks: (playlistId: string, trackUris: string[]) =>
    post('/spotify/playlist_remove_tracks', { playlist_id: playlistId, track_uris: trackUris }),

  spotifyQuickplay: (guildId: string, userId: string, track: any) =>
    post('/spotify/quickplay', basePayload(guildId, userId, { track })),

  spotifyAddCurrentToPlaylist: (playlistId: string, guildId: string) =>
    post('/spotify/add_current_to_playlist', { playlist_id: playlistId, guild_id: guildId }),

  spotifyAddQueueToPlaylist: (playlistId: string, guildId: string, maxItems = 20) =>
    post('/spotify/add_queue_to_playlist', { playlist_id: playlistId, guild_id: guildId, max_items: maxItems }),
};

type SearchResult = import('./types').SearchResult;
