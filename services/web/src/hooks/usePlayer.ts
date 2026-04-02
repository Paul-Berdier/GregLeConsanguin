'use client';

import { useEffect, useCallback } from 'react';
import { create } from 'zustand';
import { getSocket } from '@/lib/socket';
import { api } from '@/lib/api';
import type { PlayerState, Track } from '@/lib/types';

interface PlayerStore {
  guildId: string;
  userId: string;
  state: PlayerState;
  connected: boolean;
  setGuild: (id: string) => void;
  setUser: (id: string) => void;
  updateState: (partial: Partial<PlayerState>) => void;
  setConnected: (v: boolean) => void;
}

export const usePlayerStore = create<PlayerStore>((set) => ({
  guildId: '',
  userId: '',
  state: {
    queue: [],
    paused: false,
    position: 0,
    repeat_all: false,
  },
  connected: false,
  setGuild: (id) => set({ guildId: id }),
  setUser: (id) => set({ userId: id }),
  updateState: (partial) =>
    set((s) => ({ state: { ...s.state, ...partial } })),
  setConnected: (v) => set({ connected: v }),
}));


export function usePlayer() {
  const { guildId, userId, state, connected, setGuild, setUser, updateState, setConnected } =
    usePlayerStore();

  // Socket.IO connection
  useEffect(() => {
    const socket = getSocket();

    socket.on('connect', () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));

    socket.on('playlist_update', (data: Partial<PlayerState>) => {
      if (data.only_elapsed) {
        // Progress tick only
        updateState({
          position: data.position ?? state.position,
          duration: data.duration ?? state.duration,
          paused: data.paused ?? state.paused,
        });
      } else {
        updateState(data);
      }
    });

    return () => {
      socket.off('connect');
      socket.off('disconnect');
      socket.off('playlist_update');
    };
  }, []);

  // Join guild room when guildId changes
  useEffect(() => {
    if (!guildId) return;
    const socket = getSocket();
    socket.emit('join_guild', { guild_id: guildId });
    socket.emit('request_state', { guild_id: guildId });

    return () => {
      socket.emit('leave_guild', { guild_id: guildId });
    };
  }, [guildId]);

  // Actions
  const enqueue = useCallback(
    async (query: string, meta?: Record<string, any>) => {
      if (!guildId || !userId) return;
      return api.enqueue(guildId, userId, query, meta);
    },
    [guildId, userId]
  );

  const skip = useCallback(async () => {
    if (!guildId || !userId) return;
    return api.skip(guildId, userId);
  }, [guildId, userId]);

  const stop = useCallback(async () => {
    if (!guildId || !userId) return;
    return api.stop(guildId, userId);
  }, [guildId, userId]);

  const togglePause = useCallback(async () => {
    if (!guildId || !userId) return;
    return api.togglePause(guildId, userId);
  }, [guildId, userId]);

  const repeat = useCallback(async () => {
    if (!guildId) return;
    return api.repeat(guildId);
  }, [guildId]);

  const remove = useCallback(
    async (index: number) => {
      if (!guildId || !userId) return;
      return api.remove(guildId, userId, index);
    },
    [guildId, userId]
  );

  return {
    state,
    guildId,
    userId,
    connected,
    setGuild,
    setUser,
    enqueue,
    skip,
    stop,
    togglePause,
    repeat,
    remove,
  };
}
