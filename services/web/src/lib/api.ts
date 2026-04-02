import type { ApiResponse, SearchResult } from './types';

const API_BASE = '/api/v1';

async function request<T = any>(
  path: string,
  opts: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...opts.headers,
      },
      ...opts,
    });

    return await res.json();
  } catch (e) {
    return {
      ok: false,
      error: String(e),
    };
  }
}

export const api = {
  // Player
  getState: (guildId: string) =>
    request(`/player/state?guild_id=${encodeURIComponent(guildId)}`),

  enqueue: (
    guildId: string,
    userId: string,
    query: string,
    meta?: Record<string, any>
  ) =>
    request('/player/enqueue', {
      method: 'POST',
      body: JSON.stringify({
        guild_id: guildId,
        user_id: userId,
        query,
        url: query,
        ...meta,
      }),
    }),

  skip: (guildId: string, userId: string) =>
    request('/player/skip', {
      method: 'POST',
      body: JSON.stringify({ guild_id: guildId, user_id: userId }),
    }),

  stop: (guildId: string, userId: string) =>
    request('/player/stop', {
      method: 'POST',
      body: JSON.stringify({ guild_id: guildId, user_id: userId }),
    }),

  togglePause: (guildId: string, userId: string) =>
    request('/player/pause', {
      method: 'POST',
      body: JSON.stringify({ guild_id: guildId, user_id: userId }),
    }),

  repeat: (guildId: string, mode = 'toggle') =>
    request('/player/repeat', {
      method: 'POST',
      body: JSON.stringify({ guild_id: guildId, mode }),
    }),

  remove: (guildId: string, userId: string, index: number) =>
    request(`/player/queue/${index}`, {
      method: 'DELETE',
      body: JSON.stringify({ guild_id: guildId, user_id: userId }),
    }),

  move: (guildId: string, userId: string, src: number, dst: number) =>
    request('/player/move', {
      method: 'POST',
      body: JSON.stringify({ guild_id: guildId, user_id: userId, src, dst }),
    }),

  joinVoice: (guildId: string, userId: string) =>
    request('/voice/join', {
      method: 'POST',
      body: JSON.stringify({ guild_id: guildId, user_id: userId }),
    }),

  // Search
  autocomplete: (q: string, limit = 8): Promise<ApiResponse<SearchResult>> =>
    request(`/search/autocomplete?q=${encodeURIComponent(q)}&limit=${limit}`),

  // Auth
  getMe: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  getGuilds: () => request('/guilds'),
};