'use client';

import { useEffect, useCallback, useRef } from 'react';
import { create } from 'zustand';
import { getSocket, overlayRegister, subscribeGuild, unsubscribeGuild, startPing, getSocketId } from '@/lib/socket';
import { api } from '@/lib/api';
import type {
  PlayerState, Track, UserInfo, GuildInfo,
  SpotifyProfile, SpotifyPlaylist, SpotifyTrack,
  StatusKind, SearchResult,
} from '@/lib/types';

// ── Helpers ──
function toSeconds(v: any): number | null {
  if (v == null) return null;
  if (typeof v === 'number' && isFinite(v)) {
    if (v > 10000) return Math.floor(v / 1000);
    return Math.floor(v);
  }
  const s = String(v).trim();
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    if (!isFinite(n)) return null;
    if (n > 10000) return Math.floor(n / 1000);
    return Math.floor(n);
  }
  const parts = s.split(':').map(Number);
  if (parts.some((x) => !isFinite(x))) return null;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}

function clamp(n: number, a: number, b: number): number {
  if (!isFinite(n)) return a;
  return Math.min(Math.max(n, a), b);
}

function normalizeItem(it: any): Track | null {
  if (!it || typeof it !== 'object') return null;

  const title = it.title || it.name || it.track_title || it.track || '';
  const url = it.url || it.webpage_url || it.href || it.link || '';
  const artist = it.artist || it.uploader || it.author || it.channel || it.by || '';
  const duration = toSeconds(it.duration ?? it.duration_s ?? it.duration_sec ?? it.duration_ms ?? it.length ?? it.length_s ?? it.length_ms) ?? null;
  const thumb = it.thumb || it.thumbnail || it.image || it.artwork || it.cover || null;
  const provider = it.provider || it.source || it.platform || null;

  const rb = it.requested_by || it.added_by || it.requester || it.user || null;
  const addedById = (rb && (rb.id || rb.user_id)) || it.requested_by_id || it.added_by_id || it.user_id || null;
  const addedByName = (rb && (rb.display_name || rb.global_name || rb.username || rb.name)) || it.requested_by_name || it.added_by_name || it.user_name || it.username || '';
  const addedBy = (addedById || addedByName) ? { id: addedById ? String(addedById) : '', name: String(addedByName || '').trim() } : null;

  return { title: String(title || ''), url: String(url || ''), artist: String(artist || ''), duration, thumb, provider, addedBy, raw: it };
}

function normalizeMePayload(payload: any): UserInfo | null {
  if (!payload) return null;
  if (payload.ok === true && payload.user?.id) return payload.user;
  if (payload.id) return payload;
  if (payload.user?.id) return payload.user;
  return null;
}

function normalizeGuildsPayload(payload: any): GuildInfo[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload;
  if (payload.guilds && Array.isArray(payload.guilds)) return payload.guilds;
  if (payload.data?.guilds && Array.isArray(payload.data.guilds)) return payload.data.guilds;
  return [];
}

// ── Store ──
interface GregStore {
  // Auth
  me: UserInfo | null;
  guilds: GuildInfo[];
  guildId: string;
  socketReady: boolean;

  // Player
  player: PlayerState;
  tickBase: { pos: number; at: number; dur: number };

  // Spotify
  spotifyLinked: boolean;
  spotifyProfile: SpotifyProfile | null;
  spotifyPlaylists: SpotifyPlaylist[];
  spotifyTracks: SpotifyTrack[];
  spotifyCurrentPlaylistId: string;

  // Status
  status: { text: string; kind: StatusKind };

  // Actions
  setMe: (me: UserInfo | null) => void;
  setGuilds: (g: GuildInfo[]) => void;
  setGuildId: (id: string) => void;
  setSocketReady: (v: boolean) => void;
  setPlayer: (p: Partial<PlayerState>) => void;
  setTickBase: (tb: { pos: number; at: number; dur: number }) => void;
  applyPlaylistPayload: (payload: any) => void;
  setStatus: (text: string, kind?: StatusKind) => void;

  setSpotifyLinked: (v: boolean) => void;
  setSpotifyProfile: (p: SpotifyProfile | null) => void;
  setSpotifyPlaylists: (p: SpotifyPlaylist[]) => void;
  setSpotifyTracks: (t: SpotifyTrack[]) => void;
  setSpotifyCurrentPlaylistId: (id: string) => void;
}

export const useStore = create<GregStore>((set, get) => ({
  me: null,
  guilds: [],
  guildId: '',
  socketReady: false,

  player: {
    current: null,
    queue: [],
    paused: true,
    repeat: false,
    position: 0,
    duration: 0,
  },
  tickBase: { pos: 0, at: 0, dur: 0 },

  spotifyLinked: false,
  spotifyProfile: null,
  spotifyPlaylists: [],
  spotifyTracks: [],
  spotifyCurrentPlaylistId: '',

  status: { text: 'Initialisation…', kind: 'info' },

  setMe: (me) => set({ me }),
  setGuilds: (guilds) => set({ guilds }),
  setGuildId: (guildId) => set({ guildId }),
  setSocketReady: (socketReady) => set({ socketReady }),
  setPlayer: (partial) => set((s) => ({ player: { ...s.player, ...partial } })),
  setTickBase: (tickBase) => set({ tickBase }),
  setStatus: (text, kind = 'info') => set({ status: { text, kind } }),

  setSpotifyLinked: (spotifyLinked) => set({ spotifyLinked }),
  setSpotifyProfile: (spotifyProfile) => set({ spotifyProfile }),
  setSpotifyPlaylists: (spotifyPlaylists) => set({ spotifyPlaylists }),
  setSpotifyTracks: (spotifyTracks) => set({ spotifyTracks }),
  setSpotifyCurrentPlaylistId: (spotifyCurrentPlaylistId) => set({ spotifyCurrentPlaylistId }),

  applyPlaylistPayload: (payload: any) => {
    const root = payload && typeof payload === 'object' ? payload : {};
    const p = root.state || root.pm || root.data || root;
    const isTick = !!p.only_elapsed;
    const state = get();

    const pick = (...vals: any[]) => vals.find((v) => v !== undefined && v !== null);
    const toBool = (v: any) => {
      if (typeof v === 'boolean') return v;
      if (typeof v === 'number') return v !== 0;
      if (typeof v === 'string') return ['1', 'true', 'yes', 'on'].includes(v.trim().toLowerCase());
      return !!v;
    };
    const norm = (it: any) => { const n = normalizeItem(it); return n && (n.title || n.url) ? n : null; };

    let current = state.player.current;
    if (!isTick) current = norm(p.current || p.now_playing || p.playing || null);
    else { const maybe = norm(p.current || p.now_playing || p.playing); if (maybe) current = maybe; }

    let queue = state.player.queue;
    if (!isTick) {
      const qRaw = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : Array.isArray(p.list) ? p.list : [];
      queue = qRaw.map(normalizeItem).filter(Boolean) as Track[];
    } else {
      const qM = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : null;
      if (qM) queue = qM.map(normalizeItem).filter(Boolean) as Track[];
    }

    const paused = toBool(pick(p.is_paused, p.paused, p.isPaused, p.pause, false));
    const repeat = toBool(pick(p.repeat_all, p.repeat, p.repeat_mode, p.loop, false));
    const elapsed = toSeconds(pick(p.progress?.elapsed, p.progress?.position, p.elapsed, p.position, p.pos, p.current_time, 0)) ?? 0;
    const duration = toSeconds(pick(p.progress?.duration, p.duration, p.total, p.length, current?.duration, 0)) ?? 0;

    const newPlayer: PlayerState = {
      current,
      queue,
      paused: paused || !current,
      repeat,
      position: Math.max(0, elapsed),
      duration: Math.max(0, duration),
    };

    set({
      player: newPlayer,
      tickBase: {
        pos: newPlayer.position,
        at: performance.now(),
        dur: newPlayer.duration,
      },
    });
  },
}));

// ── Hooks ──

const RESYNC_MS = 5000;
const POLL_FALLBACK_MS = 3000;
const VOICE_JOIN_COOLDOWN_MS = 8000;

export function usePlayer() {
  const store = useStore();
  const voiceJoinLastAt = useRef(0);
  const resyncLastAt = useRef(0);

  // Socket setup
  useEffect(() => {
    const socket = getSocket();
    const { setSocketReady, applyPlaylistPayload, setStatus, setSpotifyLinked, setSpotifyProfile } = useStore.getState();

    const onConnect = () => {
      useStore.getState().setSocketReady(true);
      useStore.getState().setStatus('Socket connecté ✅', 'ok');
      const s = useStore.getState();
      overlayRegister(s.guildId, s.me?.id);
      if (s.guildId) subscribeGuild(s.guildId);
    };

    const onDisconnect = () => {
      useStore.getState().setSocketReady(false);
      useStore.getState().setStatus('Socket déconnecté — polling actif', 'warn');
    };

    const onPlaylistUpdate = (payload: any) => {
      useStore.getState().applyPlaylistPayload(payload);
    };

    const onSpotifyLinked = (payload: any) => {
      useStore.getState().setSpotifyLinked(true);
      useStore.getState().setSpotifyProfile(payload?.profile || payload?.data?.profile || null);
      useStore.getState().setStatus('Spotify lié ✅', 'ok');
    };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('playlist_update', onPlaylistUpdate);
    socket.on('spotify:linked', onSpotifyLinked);

    startPing();

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('playlist_update', onPlaylistUpdate);
      socket.off('spotify:linked', onSpotifyLinked);
    };
  }, []);

  // Guild subscription
  useEffect(() => {
    const gid = store.guildId;
    if (!gid) return;
    subscribeGuild(gid);
    return () => { unsubscribeGuild(gid); };
  }, [store.guildId]);

  // Progress ticker (RAF)
  useEffect(() => {
    let rafId: number;

    const tick = () => {
      const s = useStore.getState();
      if (s.player.current && !s.player.paused) {
        const now = performance.now();
        const elapsed = (now - s.tickBase.at) / 1000;
        const pos = s.tickBase.pos + elapsed;
        const dur = s.tickBase.dur || s.player.duration || s.player.current.duration || 0;
        const clamped = dur > 0 ? clamp(pos, 0, dur) : Math.max(0, pos);

        // Only update the player position, not the full state, to avoid re-renders
        useStore.setState((prev) => ({
          player: { ...prev.player, position: clamped },
        }));

        // Resync from server periodically
        if (s.me && s.guildId && Date.now() - resyncLastAt.current > RESYNC_MS) {
          resyncLastAt.current = Date.now();
          refreshPlaylist().catch(() => {});
        }
      }
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  // Polling fallback when socket disconnected
  useEffect(() => {
    const interval = setInterval(async () => {
      const s = useStore.getState();
      if (s.socketReady) return;
      if (!s.me || !s.guildId) return;
      await refreshPlaylist().catch(() => {});
    }, POLL_FALLBACK_MS);

    return () => clearInterval(interval);
  }, []);

  // ── Refresh functions ──
  const refreshMe = useCallback(async () => {
    try {
      const raw = await api.getMe();
      const me = normalizeMePayload(raw);
      useStore.getState().setMe(me);
      return me;
    } catch {
      useStore.getState().setMe(null);
      return null;
    }
  }, []);

  const refreshGuilds = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me) { useStore.getState().setGuilds([]); return []; }
    try {
      const data = await api.getGuilds();
      const guilds = normalizeGuildsPayload(data);
      useStore.getState().setGuilds(guilds);
      return guilds;
    } catch {
      useStore.getState().setGuilds([]);
      return [];
    }
  }, []);

  const refreshSpotify = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me) {
      useStore.getState().setSpotifyLinked(false);
      useStore.getState().setSpotifyProfile(null);
      return;
    }
    try {
      const st = await api.spotifyStatus();
      const linked = 'linked' in st ? !!st.linked : !!st?.ok;
      useStore.getState().setSpotifyLinked(linked);
      useStore.getState().setSpotifyProfile(st?.profile || st?.me || st?.data?.profile || null);

      if (linked && !useStore.getState().spotifyProfile) {
        try {
          const me = await api.spotifyMe();
          useStore.getState().setSpotifyProfile(me?.profile || me?.me || me?.data?.profile || me || null);
        } catch {}
      }
    } catch {
      useStore.getState().setSpotifyLinked(false);
      useStore.getState().setSpotifyProfile(null);
    }
  }, []);

  const refreshSpotifyPlaylists = useCallback(async () => {
    const s = useStore.getState();
    if (!s.spotifyLinked) {
      useStore.getState().setSpotifyPlaylists([]);
      useStore.getState().setSpotifyTracks([]);
      return;
    }
    try {
      const data = await api.spotifyPlaylists();
      const items = data?.items || data?.playlists || data?.data?.items || data?.data?.playlists || (Array.isArray(data) ? data : []);
      useStore.getState().setSpotifyPlaylists(items);

      let currentPl = useStore.getState().spotifyCurrentPlaylistId;
      if (!currentPl) {
        const saved = typeof window !== 'undefined' ? localStorage.getItem('greg.spotify.last_playlist_id') || '' : '';
        currentPl = saved;
      }
      if (!currentPl && items.length) currentPl = items[0]?.id || '';
      useStore.getState().setSpotifyCurrentPlaylistId(currentPl);

      if (currentPl) {
        await loadSpotifyTracks(currentPl);
      }
    } catch {
      useStore.getState().setSpotifyPlaylists([]);
    }
  }, []);

  const loadSpotifyTracks = useCallback(async (playlistId: string) => {
    try {
      const data = await api.spotifyPlaylistTracks(playlistId);
      const items = data?.tracks || data?.items || data?.tracks?.items || data?.data?.items || (Array.isArray(data) ? data : []);
      const tracks = items.map((x: any) => x?.track || x).filter(Boolean);
      useStore.getState().setSpotifyTracks(tracks);
    } catch {
      useStore.getState().setSpotifyTracks([]);
    }
  }, []);

  // ── Actions ──
  const setGuild = useCallback(async (id: string) => {
    const oldGid = useStore.getState().guildId;
    if (oldGid) unsubscribeGuild(oldGid);
    useStore.getState().setGuildId(id);
    if (id) {
      localStorage.setItem('greg.webplayer.guild_id', id);
      subscribeGuild(id);
    } else {
      localStorage.removeItem('greg.webplayer.guild_id');
    }
    await refreshPlaylist().catch(() => {});
  }, []);

  const bestEffortVoiceJoin = useCallback(async (reason: string) => {
    const now = Date.now();
    if (now - voiceJoinLastAt.current < VOICE_JOIN_COOLDOWN_MS) return;
    voiceJoinLastAt.current = now;
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    try {
      await api.voiceJoin(s.guildId, s.me.id, reason);
    } catch {}
  }, []);

  const safeAction = useCallback(async (fn: () => Promise<any>, okText: string, doRefresh = false) => {
    useStore.getState().setStatus('Action en cours…', 'info');
    try {
      const res = await fn();
      useStore.getState().setStatus(okText, 'ok');
      if (doRefresh) await refreshPlaylist().catch(() => {});
      return res;
    } catch (e: any) {
      const msg = e?.payload?.error || e?.payload?.message || e?.message || String(e);
      useStore.getState().setStatus(msg, 'err');
      throw e;
    }
  }, []);

  const enqueue = useCallback(async (payload: Record<string, any>) => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) {
      useStore.getState().setStatus('Connecte-toi et choisis un serveur.', 'warn');
      return;
    }
    await safeAction(
      () => api.queueAdd(s.guildId, s.me!.id, payload),
      'Ajouté à la file ✅',
      true,
    );
    await bestEffortVoiceJoin('add');
  }, [safeAction, bestEffortVoiceJoin]);

  const skip = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.queueSkip(s.guildId, s.me!.id), 'Skip ✅', true);
  }, [safeAction]);

  const stop = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.queueStop(s.guildId, s.me!.id), 'Stop ✅', true);
  }, [safeAction]);

  const togglePause = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.togglePause(s.guildId, s.me!.id), 'Lecture/Pause ✅', true);
  }, [safeAction]);

  const toggleRepeat = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.repeat(s.guildId, s.me!.id), 'Repeat togglé ✅', true);
  }, [safeAction]);

  const restartTrack = useCallback(async () => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.restart(s.guildId, s.me!.id), 'Restart ✅', true);
  }, [safeAction]);

  const removeFromQueue = useCallback(async (index: number) => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.queueRemove(s.guildId, s.me!.id, index), 'Retiré ✅', true);
  }, [safeAction]);

  const playAt = useCallback(async (index: number) => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) return;
    await safeAction(() => api.playAt(s.guildId, s.me!.id, index), `Lecture: #${index + 1}`, true);
    await bestEffortVoiceJoin('play_at');
  }, [safeAction, bestEffortVoiceJoin]);

  // Spotify actions
  const spotifyLogin = useCallback(() => {
    const s = useStore.getState();
    if (!s.me) {
      useStore.getState().setStatus('Connecte-toi à Discord avant Spotify.', 'warn');
      return;
    }
    const sid = getSocketId();
    const url = api.getSpotifyLoginUrl(sid);
    const w = 520, h = 720;
    const y = Math.round(window.outerHeight / 2 + window.screenY - h / 2);
    const x = Math.round(window.outerWidth / 2 + window.screenX - w / 2);
    const popup = window.open(url, 'spotify_link', `toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=${w},height=${h},top=${y},left=${x}`);
    if (!popup) {
      useStore.getState().setStatus('Popup bloquée — autorise les popups.', 'warn');
      return;
    }
    useStore.getState().setStatus('Ouverture Spotify…', 'info');

    // Poll for link status
    (async () => {
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        await refreshSpotify();
        if (useStore.getState().spotifyLinked) {
          useStore.getState().setStatus('Spotify connecté ✅', 'ok');
          await refreshSpotifyPlaylists().catch(() => {});
          break;
        }
      }
    })().catch(() => {});
  }, [refreshSpotify, refreshSpotifyPlaylists]);

  const spotifyLogout = useCallback(async () => {
    await safeAction(() => api.spotifyLogout(), 'Spotify délié ✅', false);
    const st = useStore.getState();
    st.setSpotifyLinked(false);
    st.setSpotifyProfile(null);
    st.setSpotifyPlaylists([]);
    st.setSpotifyTracks([]);
    st.setSpotifyCurrentPlaylistId('');
    localStorage.removeItem('greg.spotify.last_playlist_id');
  }, [safeAction]);

  const selectSpotifyPlaylist = useCallback(async (playlistId: string) => {
    useStore.getState().setSpotifyCurrentPlaylistId(playlistId);
    localStorage.setItem('greg.spotify.last_playlist_id', playlistId);
    await loadSpotifyTracks(playlistId);
  }, [loadSpotifyTracks]);

  const spotifyQuickplay = useCallback(async (track: any) => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) {
      useStore.getState().setStatus('Choisis un serveur Discord.', 'warn');
      return;
    }
    await safeAction(() => api.spotifyQuickplay(s.guildId, s.me!.id, track), 'Lecture Spotify ✅', true);
    await bestEffortVoiceJoin('spotify_quickplay');
  }, [safeAction, bestEffortVoiceJoin]);

  const spotifyDeletePlaylist = useCallback(async (playlistId: string) => {
    await safeAction(() => api.spotifyDeletePlaylist(playlistId), 'Playlist supprimée ✅', false);
    if (useStore.getState().spotifyCurrentPlaylistId === playlistId) {
      useStore.getState().setSpotifyCurrentPlaylistId('');
      useStore.getState().setSpotifyTracks([]);
      localStorage.removeItem('greg.spotify.last_playlist_id');
    }
    await refreshSpotifyPlaylists().catch(() => {});
  }, [safeAction, refreshSpotifyPlaylists]);

  const spotifyRemoveTrack = useCallback(async (playlistId: string, uri: string) => {
    await safeAction(() => api.spotifyRemoveTracks(playlistId, [uri]), 'Titre retiré ✅', false);
    await loadSpotifyTracks(playlistId).catch(() => {});
  }, [safeAction, loadSpotifyTracks]);

  const spotifyCreatePlaylist = useCallback(async (name: string, isPublic: boolean) => {
    const data = await safeAction(
      () => api.spotifyCreatePlaylist(name, isPublic),
      'Playlist créée ✅',
      false,
    );
    await refreshSpotifyPlaylists().catch(() => {});
    const id = data?.id || data?.playlist_id || data?.playlist?.id || '';
    if (id) {
      useStore.getState().setSpotifyCurrentPlaylistId(id);
      localStorage.setItem('greg.spotify.last_playlist_id', id);
      await loadSpotifyTracks(id).catch(() => {});
    }
  }, [safeAction, refreshSpotifyPlaylists, loadSpotifyTracks]);

  const spotifyAddCurrent = useCallback(async (playlistId: string) => {
    const s = useStore.getState();
    if (!s.guildId) { useStore.getState().setStatus('Choisis un serveur.', 'warn'); return; }
    await safeAction(() => api.spotifyAddCurrentToPlaylist(playlistId, s.guildId), 'Titre ajouté à la playlist ✅', false);
    await loadSpotifyTracks(playlistId).catch(() => {});
  }, [safeAction, loadSpotifyTracks]);

  const spotifyAddQueue = useCallback(async (playlistId: string) => {
    const s = useStore.getState();
    if (!s.guildId) { useStore.getState().setStatus('Choisis un serveur.', 'warn'); return; }
    await safeAction(() => api.spotifyAddQueueToPlaylist(playlistId, s.guildId, 20), 'File ajoutée ✅', false);
    await loadSpotifyTracks(playlistId).catch(() => {});
  }, [safeAction, loadSpotifyTracks]);

  // ── Boot ──
  const boot = useCallback(async () => {
    const saved = typeof window !== 'undefined' ? localStorage.getItem('greg.webplayer.guild_id') || '' : '';
    if (saved) useStore.getState().setGuildId(saved);

    await refreshMe();
    await refreshGuilds();

    const s = useStore.getState();
    if (!s.guildId && s.guilds.length) {
      useStore.getState().setGuildId(s.guilds[0].id);
    }

    try {
      await refreshSpotify();
      if (useStore.getState().spotifyLinked) {
        await refreshSpotifyPlaylists().catch(() => {});
      }
    } catch {
      useStore.getState().setSpotifyLinked(false);
      useStore.getState().setSpotifyProfile(null);
      useStore.getState().setSpotifyPlaylists([]);
      useStore.getState().setSpotifyTracks([]);
    }

    await refreshPlaylist().catch(() => {});
    useStore.getState().setStatus('Prêt ✅', 'ok');
  }, [refreshMe, refreshGuilds, refreshSpotify, refreshSpotifyPlaylists]);

  return {
    ...store,
    boot,
    setGuild,
    refreshMe,
    refreshGuilds,
    refreshSpotify,
    refreshSpotifyPlaylists,
    loadSpotifyTracks,
    enqueue,
    skip,
    stop,
    togglePause,
    toggleRepeat,
    restartTrack,
    removeFromQueue,
    playAt,
    bestEffortVoiceJoin,
    spotifyLogin,
    spotifyLogout,
    selectSpotifyPlaylist,
    spotifyQuickplay,
    spotifyDeletePlaylist,
    spotifyRemoveTrack,
    spotifyCreatePlaylist,
    spotifyAddCurrent,
    spotifyAddQueue,
  };
}

// Standalone refresh
async function refreshPlaylist() {
  const s = useStore.getState();
  if (!s.me || !s.guildId) {
    s.applyPlaylistPayload({ current: null, queue: [], paused: true, repeat: false, position: 0, duration: 0 });
    return;
  }
  try {
    const data = await api.getPlaylistState(s.guildId);
    s.applyPlaylistPayload(data);
  } catch (e: any) {
    s.setStatus(String(e?.message || e), 'err');
  }
}

export { refreshPlaylist };
