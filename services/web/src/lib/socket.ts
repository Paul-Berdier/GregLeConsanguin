import { io, Socket } from 'socket.io-client';

const WS_URL =
  (process.env.NEXT_PUBLIC_WS_URL || '').trim()

let socket: Socket | null = null;
let pingInterval: ReturnType<typeof setInterval> | null = null;

export function getSocket(): Socket {
  if (!socket) {
    socket = io(WS_URL, {
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

export function startPing() {
  if (pingInterval) return;

  pingInterval = setInterval(() => {
    const s = getSocket();
    if (!s.connected) return;

    try {
      s.emit('overlay_ping', {
        t: Date.now(),
        sid: s.id || undefined,
      });
    } catch {}
  }, 25000);
}

export function stopPing() {
  if (!pingInterval) return;
  clearInterval(pingInterval);
  pingInterval = null;
}