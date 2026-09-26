import { io, Socket } from 'socket.io-client';
import { getApiOrigin, isBrowserReachable } from './api';

// Socket connects to the API service, not the Next.js frontend.
// On Railway, they're separate services so we need the API origin.
function getWsUrl(): string {
  const env = (typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_WS_URL || '').trim()
    : '');
  // Même garde que la base REST (api.ts) : une URL injoignable depuis ce navigateur
  // (http://api:3000, localhost figé au build…) → origine de l'API / même origine.
  if (env && isBrowserReachable(env, location.hostname)) return env;

  // Fallback: connect to API origin (same as API base) — '' = même origine (rewrite /socket.io)
  if (typeof window !== 'undefined') {
    return getApiOrigin() || '';
  }
  return '';
}

let socket: Socket | null = null;
let pingInterval: ReturnType<typeof setInterval> | null = null;

export function getSocket(): Socket {
  if (!socket) {
    const url = getWsUrl();
    socket = io(url || undefined, {
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

/**
 * Déconnexion Discord (contrat SEC-C7) : la session du socket est figée à la poignée de
 * main, l'ancienne connexion resterait dans les rooms guild:<id>. On coupe puis on rouvre
 * (nouvelle poignée de main, cookie à jour → socket anonyme, sans aucune room de serveur).
 */
export function resetSocket() {
  if (!socket) return;
  try {
    socket.disconnect();
    socket.connect();
  } catch {}
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