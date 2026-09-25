'use client';

import { useEffect, useCallback } from 'react';
import { create } from 'zustand';
import { getSocket, overlayRegister, subscribeGuild, unsubscribeGuild, startPing, getSocketId } from '@/lib/socket';
import { api } from '@/lib/api';
import {
  toSeconds, normalizeItem, buildUsersMap, isStalePayload,
  looksLikeUrl, describeError, errorCode, enqueueSuccessText, pickDefaultGuild,
  createSeqGate, staleStateText, livePosition, recoveredStatusText,
} from '@/lib/playerUtils';
import type {
  PlayerState, Track, UserInfo, GuildInfo,
  SpotifyProfile, SpotifyPlaylist, SpotifyTrack,
  StatusKind, SearchResult,
} from '@/lib/types';

// ── Helpers ──
function clamp(n: number, a: number, b: number): number {
  if (!isFinite(n)) return a;
  return Math.min(Math.max(n, a), b);
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

  // History
  historyItems: any[];

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
  setHistoryItems: (items: any[]) => void;
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

  historyItems: [],

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
  setHistoryItems: (historyItems) => set({ historyItems }),

  applyPlaylistPayload: (payload: any) => {
    const root = payload && typeof payload === 'object' ? payload : {};
    // État périmé / en échec (bot occupé, TIMEOUT…) : on garde l'état précédent
    if (isStalePayload(root)) return;
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
    // added_by est un id : les infos user arrivent à part (queue_users / requested_by_user)
    const users = buildUsersMap(p);
    const normQ = (it: any) => normalizeItem(it, users);
    const norm = (it: any) => { const n = normalizeItem(it, users); return n && (n.title || n.url) ? n : null; };

    let current = state.player.current;
    if (!isTick) current = norm(p.current || p.now_playing || p.playing || null);
    else { const maybe = norm(p.current || p.now_playing || p.playing); if (maybe) current = maybe; }

    let queue = state.player.queue;
    if (!isTick) {
      const qRaw = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : Array.isArray(p.list) ? p.list : [];
      queue = qRaw.map(normQ).filter(Boolean) as Track[];
    } else {
      const qM = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : null;
      if (qM) queue = qM.map(normQ).filter(Boolean) as Track[];
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
const RESYNC_IDLE_MS = 15000;
const POLL_FALLBACK_MS = 3000;
const VOICE_JOIN_COOLDOWN_MS = 8000;

let _voiceJoinLastAt = 0;
// /users/me : seule une réponse définitive (succès ou 401) plus récente que la dernière appliquée compte
const _meGate = createSeqGate();

/**
 * usePlayerInit — MUST be called exactly ONCE in the root component.
 * Sets up socket listeners, intervals, guild subscription.
 */
export function usePlayerInit() {
  const guildId = useStore((s) => s.guildId);

  // Socket setup (once)
  useEffect(() => {
    const socket = getSocket();

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
    if (!guildId) return;
    subscribeGuild(guildId);
    return () => { unsubscribeGuild(guildId); };
  }, [guildId]);

  // Server resync — pas conditionné à `current` : rapide en lecture ou si le dernier
  // état était périmé, plus espacé sinon (rattrape un ajout fini après un TIMEOUT).
  useEffect(() => {
    let lastAt = 0;
    const interval = setInterval(async () => {
      const s = useStore.getState();
      if (!s.me || !s.guildId) return;
      if (!s.socketReady) return; // socket coupé : le polling de secours s'en charge déjà
      const playing = !!s.player.current && !s.player.paused;
      const now = Date.now();
      if (!playing && !_stateStale && now - lastAt < RESYNC_IDLE_MS) return;
      lastAt = now;
      await backgroundRefresh();
    }, RESYNC_MS);
    return () => clearInterval(interval);
  }, []);

  // Polling fallback
  useEffect(() => {
    const interval = setInterval(async () => {
      const s = useStore.getState();
      if (s.socketReady) return;
      if (!s.me || !s.guildId) return;
      await backgroundRefresh();
    }, POLL_FALLBACK_MS);
    return () => clearInterval(interval);
  }, []);
}

/**
 * usePlayer — returns store state + action callbacks.
 * Can be called from ANY component, NO side effects.
 */
export function usePlayer() {
  const store = useStore();

  // ── Refresh functions ──
  const refreshMe = useCallback(async () => {
    const seq = _meGate.next();
    try {
      const raw = await api.getMe();
      const me = normalizeMePayload(raw);
      // Une réponse plus récente a déjà tranché : on ne l'écrase pas
      if (_meGate.tryApply(seq)) useStore.getState().setMe(me);
      return useStore.getState().me;
    } catch (e: any) {
      // Seul un 401 signifie « déconnecté » ; réseau / 5xx / proxy = erreur transitoire,
      // qui n'invalide pas une réponse plus ancienne encore en vol (ex. /users/me du boot)
      if (e?.status === 401) {
        if (_meGate.tryApply(seq)) useStore.getState().setMe(null);
        return useStore.getState().me;
      }
      const prev = useStore.getState().me;
      if (prev) useStore.getState().setStatus('Serveur injoignable — session conservée, nouvelle tentative plus tard…', 'warn');
      return prev;
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
  const refreshHistory = useCallback(async () => {
    const s = useStore.getState();
    if (!s.guildId) { useStore.getState().setHistoryItems([]); return; }
    try {
      const data = await api.getHistory(s.guildId, 'top', 30);
      useStore.getState().setHistoryItems(data?.items || []);
    } catch {
      useStore.getState().setHistoryItems([]);
    }
  }, []);

  const setGuild = useCallback(async (id: string) => {
    const oldGid = useStore.getState().guildId;
    if (oldGid) unsubscribeGuild(oldGid);
    useStore.getState().setGuildId(id);
    // L'état affiché appartient à l'ancien serveur : on le vide (un état périmé du nouveau ne l'écrasera pas)
    if (id !== oldGid) {
      useStore.getState().applyPlaylistPayload({ current: null, queue: [], paused: true, repeat: false, position: 0, duration: 0 });
    }
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
    if (now - _voiceJoinLastAt < VOICE_JOIN_COOLDOWN_MS) return;
    _voiceJoinLastAt = now;
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
      if (doRefresh) await refreshPlaylist({ quiet: true }).catch(() => {});
      return res;
    } catch (e: any) {
      useStore.getState().setStatus(describeError(e), 'err');
      throw e;
    }
  }, []);

  /**
   * Ajoute un titre / un lien / une playlist. Renvoie true si l'ajout a réussi,
   * false s'il n'a pas été envoyé ; lève l'erreur API sinon (statut déjà affiché).
   */
  const enqueue = useCallback(async (payload: Record<string, any>): Promise<boolean> => {
    const s = useStore.getState();
    if (!s.me || !s.guildId) {
      useStore.getState().setStatus('Connecte-toi et choisis un serveur.', 'warn');
      return false;
    }
    // Lien collé (pas une suggestion avec titre) : peut être une playlist, plus long à charger
    const pastedLink = !payload?.title && looksLikeUrl(String(payload?.query || payload?.url || ''));
    useStore.getState().setStatus(
      pastedLink ? 'Chargement du lien… (une playlist peut prendre quelques secondes)' : 'Ajout en cours…',
      'info',
    );
    try {
      const res = await api.queueAdd(s.guildId, s.me!.id, payload);
      useStore.getState().setStatus(enqueueSuccessText(res), 'ok');
    } catch (e: any) {
      // TIMEOUT : le bot peut encore finir l'ajout → avertissement plutôt qu'erreur
      useStore.getState().setStatus(describeError(e), errorCode(e) === 'TIMEOUT' ? 'warn' : 'err');
      throw e;
    } finally {
      // Toujours resynchroniser (même en échec : le bot a pu ajouter une partie des titres)
      await refreshPlaylist({ quiet: true }).catch(() => {});
    }
    await bestEffortVoiceJoin('add');
    return true;
  }, [bestEffortVoiceJoin]);

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

    // Serveur sauvegardé absent de la liste → écarté ; auto-sélection : premier serveur où Greg est présent
    const s = useStore.getState();
    const chosen = pickDefaultGuild(s.guilds, s.guildId);
    if (chosen.discarded && typeof window !== 'undefined') localStorage.removeItem('greg.webplayer.guild_id');
    if (chosen.guildId !== s.guildId) useStore.getState().setGuildId(chosen.guildId);

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
    await refreshHistory().catch(() => {});
    useStore.getState().setStatus('Prêt ✅', 'ok');
  }, [refreshMe, refreshGuilds, refreshSpotify, refreshSpotifyPlaylists, refreshHistory]);

  return {
    ...store,
    boot,
    setGuild,
    refreshMe,
    refreshGuilds,
    refreshSpotify,
    refreshSpotifyPlaylists,
    refreshHistory,
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
let _stateSeq = 0;          // numéro de la dernière requête lancée
let _stateAppliedSeq = 0;   // numéro de la dernière réponse appliquée
let _stateInFlight = 0;
let _stateStale = false;    // dernier état non rafraîchi (bot occupé / API en échec)
let _staleNotice = '';      // code du dernier état périmé déjà signalé (un message par cause)
let _staleText = '';        // texte de l'avertissement affiché pour cette cause (effacé au retour)

/**
 * Rafraîchit l'état du lecteur. En cas d'échec ou d'état périmé (stale), on GARDE
 * l'état précédent (jamais de faux « Rien en lecture »). `quiet` : pas de message de statut.
 */
async function refreshPlaylist(opts?: { quiet?: boolean }) {
  const s = useStore.getState();
  if (!s.me || !s.guildId) {
    s.applyPlaylistPayload({ current: null, queue: [], paused: true, repeat: false, position: 0, duration: 0 });
    return;
  }
  const gid = s.guildId;
  const seq = ++_stateSeq;
  _stateInFlight++;
  try {
    const data = await api.getPlaylistState(gid);
    // Réponse d'un autre serveur ou plus ancienne qu'une réponse déjà appliquée : ignorée
    if (useStore.getState().guildId !== gid || seq < _stateAppliedSeq) return;
    if (isStalePayload(data)) throw Object.assign(new Error('stale'), { payload: data });
    _stateAppliedSeq = seq;
    _stateStale = false;
    _staleNotice = '';
    // L'avertissement « hors ligne / occupé » encore affiché est remplacé (sinon il reste à vie)
    const recovered = recoveredStatusText(useStore.getState().status.text, _staleText);
    _staleText = '';
    if (recovered) useStore.getState().setStatus(recovered, 'ok');
    useStore.getState().applyPlaylistPayload(data);
  } catch (e: any) {
    if (useStore.getState().guildId !== gid || seq < _stateAppliedSeq) return;
    _stateStale = true;
    const code = errorCode(e) || (isStalePayload(e?.payload) ? 'STALE' : 'ERROR');
    // Bot hors ligne : plus rien ne joue côté Discord → on fige la progression (pas de piste fantôme)
    if (code === 'BOT_OFFLINE') {
      const st = useStore.getState();
      if (st.player.current && !st.player.paused) {
        const now = performance.now();
        const pos = livePosition(st.tickBase, false, now);
        st.setPlayer({ paused: true, position: pos });
        st.setTickBase({ pos, at: now, dur: st.tickBase.dur });
      }
    }
    // Un message par cause (évite de spammer toutes les 5 s) ; `quiet` marque la cause comme vue
    if (code !== _staleNotice) {
      _staleNotice = code;
      if (!opts?.quiet) {
        _staleText = staleStateText(e);
        useStore.getState().setStatus(_staleText, 'warn');
      }
    }
  } finally {
    _stateInFlight--;
  }
}

/** Rafraîchissement périodique : jamais deux requêtes d'état en parallèle. */
async function backgroundRefresh() {
  if (_stateInFlight > 0) return;
  await refreshPlaylist().catch(() => {});
}

export { refreshPlaylist };
