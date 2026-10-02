import { io, Socket } from 'socket.io-client';
import { getApiOrigin, isBrowserReachable } from './api';
import { timeSync } from './sync/live';
import { sampleOf } from './sync/timesync';

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

// ── Synchro d'horloge (spec synchro son/vidéo §3, §6.2) ──
const TIME_SYNC_BURST = 5, TIME_SYNC_GAP_MS = 1000, TIME_SYNC_EVERY_MS = 30_000, TIME_SYNC_TIMEOUT_MS = 2000;
let timeSyncInterval: ReturnType<typeof setInterval> | null = null;
let timeSyncBurst: ReturnType<typeof setTimeout>[] = [];
let timeSyncStale = false;   // nouvelle connexion : les mesures d'avant servent jusqu'à la première nouvelle

/** Une mesure : {t0} → accusé {t0, ts} (ts : horloge de l'API, ms) ; sans réponse sous 2 s, ignorée. */
function measureClock(s: Socket) {
  if (!s.connected) return;
  const t0 = performance.now();
  try {
    s.timeout(TIME_SYNC_TIMEOUT_MS).emit('time_sync', { t0 }, (err: unknown, res: any) => {
      if (err || !res || res.t0 !== t0) return;
      const ts = Number(res.ts), t1 = performance.now();
      if (timeSyncStale && sampleOf(t0, ts, t1)) { timeSyncStale = false; timeSync.reset(); }
      timeSync.add(t0, ts, t1);
    });
  } catch {}
}

/**
 * 5 mesures à chaque connexion (1 s d'écart), puis une toutes les 30 s. Nouvelle connexion (peut-être une autre instance
 * de l'API) : les anciennes mesures sont remplacées par la première nouvelle, jamais vidées avant (sinon l'horloge du
 * navigateur servirait le temps d'un aller-retour, et la vidéo sauterait de son écart).
 */
export function startTimeSync() {
  if (timeSyncInterval) return;
  const s = getSocket();
  const burst = () => {
    timeSyncBurst.forEach(clearTimeout);
    timeSyncStale = true;
    timeSyncBurst = Array.from({ length: TIME_SYNC_BURST }, (_, i) => setTimeout(() => measureClock(s), i * TIME_SYNC_GAP_MS));
  };
  s.on('connect', burst);
  if (s.connected) burst();
  timeSyncInterval = setInterval(() => measureClock(s), TIME_SYNC_EVERY_MS);
}

export function stopPing() {
  if (!pingInterval) return;
  clearInterval(pingInterval);
  pingInterval = null;
}