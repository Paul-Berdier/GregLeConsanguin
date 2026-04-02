import { io, Socket } from 'socket.io-client';
import { getApiOrigin } from './api';

let socket: Socket | null = null;

export function getSocket(): Socket {
  if (!socket) {
    const origin = getApiOrigin() || undefined;

    socket = io(origin, {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      withCredentials: true,
      reconnection: true,
      reconnectionAttempts: 999,
      reconnectionDelay: 400,
      reconnectionDelayMax: 2500,
      timeout: 8000,
      autoConnect: true,
    });
  }
  return socket;
}

export function getSocketId(): string {
  return socket?.id || '';
}

export function overlayRegister(guildId?: string, userId?: string) {
  const s = getSocket();
  if (!s.connected) return;
  try {
    s.emit('overlay_register', {
      kind: 'web_player',
      page: 'player',
      guild_id: guildId || undefined,
      user_id: userId || undefined,
      t: Date.now(),
    });
  } catch {}
}

export function subscribeGuild(guildId: string) {
  const s = getSocket();
  if (!s.connected) return;
  try {
    s.emit('overlay_subscribe_guild', { guild_id: guildId });
  } catch {}
}

export function unsubscribeGuild(guildId: string) {
  const s = getSocket();
  if (!s.connected) return;
  try {
    s.emit('overlay_unsubscribe_guild', { guild_id: guildId });
  } catch {}
}

// Keep-alive ping
let pingInterval: ReturnType<typeof setInterval> | null = null;

export function startPing() {
  if (pingInterval) return;
  pingInterval = setInterval(() => {
    const s = getSocket();
    if (!s.connected) return;
    try {
      s.emit('overlay_ping', { t: Date.now(), sid: s.id || undefined });
    } catch {}
  }, 25000);
}
