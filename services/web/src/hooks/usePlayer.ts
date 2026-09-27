'use client';

import { useEffect } from 'react';
import { create } from 'zustand';
import { getSocket, overlayRegister, subscribeGuild, unsubscribeGuild, startPing, resetSocket } from '@/lib/socket';
import { api, onAuthLost } from '@/lib/api';
import {
  looksLikeUrl, errorCode, pickDefaultGuild, createSeqGate, livePosition, guildJoinErrorAction,
  snapshotFromPayload, emptySnapshot, addedCopy,
} from '@/lib/playerUtils';
import { createQueueEngine, moveIndices, viewOf } from '@/lib/queue/optimistic';
import type { Mutation } from '@/lib/queue/optimistic';
import { addedKeys, restorePlan } from '@/lib/queue/undo';
import { requesterOf } from '@/lib/stage/scene';
import { parseTitle } from '@/lib/titles';
import { herald, say, sayError } from '@/components/Herald/store';
import { t } from '@/theme/copy';
import type { PlayerState, Snapshot, TickBase, Track, UserInfo, GuildInfo } from '@/lib/types';

// ── Helpers ──
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

/** Titre nettoyé pour le Héraut (le titre brut reste dans la file). */
const songOf = (t0: Track): string => parseTitle(t0.title, t0.artist).song || t0.title;

// ── Store ──
interface GregStore {
  me: UserInfo | null;
  guilds: GuildInfo[];
  guildId: string;
  socketReady: boolean;
  /** Vue affichée : dernier état reçu + ordres du Roi pas encore confirmés (lib/queue/optimistic.ts). */
  player: PlayerState;
  tickBase: TickBase;
  historyItems: any[];

  setMe: (me: UserInfo | null) => void;
  setGuilds: (g: GuildInfo[]) => void;
  setGuildId: (id: string) => void;
  setSocketReady: (v: boolean) => void;
  setHistoryItems: (items: any[]) => void;
}

const EMPTY = emptySnapshot();

export const useStore = create<GregStore>((set) => ({
  me: null,
  guilds: [],
  guildId: '',
  socketReady: false,
  player: EMPTY.player,
  tickBase: EMPTY.tickBase,
  historyItems: [],

  setMe: (me) => set({ me }),
  setGuilds: (guilds) => set({ guilds }),
  setGuildId: (guildId) => set({ guildId }),
  setSocketReady: (socketReady) => set({ socketReady }),
  setHistoryItems: (historyItems) => set({ historyItems }),
}));

// ── Actions optimistes (spec §5) ──
// Indices calculés sur `before`, l'état que le bot verra (une requête à la fois) ; null : devenu sans effet.
function sendMutation(m: Mutation, before: Snapshot): Promise<unknown> | null {
  const s = useStore.getState();
  if (!s.me || !s.guildId) return null;
  const gid = s.guildId, uid = s.me.id;
  const q = before.player.queue;
  const at = (key: string) => q.findIndex((x) => x.key === key);
  switch (m.kind) {
    case 'remove': { const i = at(m.key); return i < 0 ? null : api.queueRemove(gid, uid, i); }
    case 'move': { const mv = moveIndices(q, m.key, m.beforeKey); return mv ? api.move(gid, uid, mv.src, mv.dst) : null; }
    case 'playAt': {
      const i = at(m.key);
      return i < 0 || (before.player.current?.key ?? null) !== m.fromKey ? null : api.playAt(gid, uid, i);
    }
    case 'skip': return before.player.current && before.player.current.key === m.fromKey ? api.queueSkip(gid, uid) : null;
    case 'setPaused': return before.player.current && before.player.paused !== m.paused ? api.togglePause(gid, uid) : null;
  }
}

// Qui a demandé le titre visé (la scène pour sauter ou mettre en pause) : un refus PRIORITY_FORBIDDEN nomme le
// prioritaire. Jamais le Roi lui-même : sur ses propres titres, le bot refuse pour la zone prioritaire ou la scène
// d'un mieux placé, que la réponse ne dit pas ; le texte générique parle alors.
function requesterName(m: Mutation, before: Snapshot): string | undefined {
  const x = 'key' in m ? before.player.queue.find((q) => q.key === m.key) : before.player.current;
  const r = requesterOf(x?.addedBy, useStore.getState().me?.id);
  return r.kind === 'other' ? r.name : undefined;
}

const engine = createQueueEngine({
  initial: EMPTY,
  now: () => performance.now(),
  send: sendMutation,
  onView: (v) => useStore.setState({ player: v.player, tickBase: v.tickBase }),
  onRefused: (m, e, before) => { sayError(e, { name: requesterName(m, before), action: m.kind === 'move' ? 'move' : undefined }); },
});

/**
 * La vue telle qu'elle sera une fois l'état gardé en tampon appliqué. Une action en vol (Espace, N, un retrait)
 * retient jusqu'à HOLD_MAX_MS l'état relu après un ajout : « Annuler » le cherche ici, pas dans la vue affichée.
 */
const upcoming = (): Snapshot => viewOf(engine.latest(), engine.pending());

/** État reçu (REST ou socket) : clés, partage structurel, tampon pendant une action ou un glisser. */
function receive(payload: any): boolean {
  const snap = snapshotFromPayload(payload, engine.latest(), performance.now());   // l'état gardé compris : un tick ne l'efface pas
  if (!snap) return false;
  engine.receive(snap);
  return true;
}

/** Autre serveur, déconnexion : vue vide, ordres en attente oubliés. */
function resetPlayer() {
  engine.reset(emptySnapshot(performance.now()));
}

// ── Hooks ──

const RESYNC_MS = 5000;
const RESYNC_IDLE_MS = 15000;
const POLL_FALLBACK_MS = 3000;
const VOICE_JOIN_COOLDOWN_MS = 8000;
const GUILD_JOIN_RETRY_MS = 5000;

let _voiceJoinLastAt = 0;
let _socketDown = false;
const _meGate = createSeqGate();
let _joinRetry: ReturnType<typeof setTimeout> | null = null;

function clearJoinRetry() {
  if (!_joinRetry) return;
  clearTimeout(_joinRetry);
  _joinRetry = null;
}

/**
 * Session Discord terminée (bouton Déco, ou 401 NOT_AUTHENTICATED sur n'importe quel appel) : me = null,
 * état vidé, socket reconnecté pour quitter les rooms. `lost` : l'erreur 401 à annoncer.
 */
function handleLoggedOut(lost?: unknown) {
  const st = useStore.getState();
  const wasLoggedIn = !!st.me;
  _meGate.tryApply(_meGate.next());
  st.setMe(null);
  if (!wasLoggedIn) return;
  clearJoinRetry();
  st.setGuilds([]);
  resetPlayer();
  st.setHistoryItems([]);
  resetSocket();
  if (lost) sayError(lost);
  else say('toast.loggedOut');
}

/** usePlayerInit — à appeler UNE fois, dans le composant racine : socket, minuteurs, abonnement au serveur. */
export function usePlayerInit() {
  const guildId = useStore((s) => s.guildId);
  const meId = useStore((s) => s.me?.id || '');

  useEffect(() => onAuthLost((e) => handleLoggedOut(e)), []);

  useEffect(() => {
    const socket = getSocket();

    const onConnect = () => {
      useStore.getState().setSocketReady(true);
      if (_socketDown) { _socketDown = false; say('toast.socketUp'); }
      const s = useStore.getState();
      overlayRegister('', s.me?.id);
      if (s.me && s.guildId) subscribeGuild(s.guildId);
    };

    const onDisconnect = () => {
      useStore.getState().setSocketReady(false);
      if (!_socketDown && useStore.getState().me) { _socketDown = true; say('toast.socketDown'); }
    };

    const onGuildJoinError = (payload: any) => {
      const s = useStore.getState();
      const a = guildJoinErrorAction(payload, s.me ? s.guildId : '');
      if (a.action === 'ignore') return;
      if (a.action === 'show') { sayError({ payload }); return; }
      if (_joinRetry) return;
      const gid = s.guildId;
      _joinRetry = setTimeout(() => {
        _joinRetry = null;
        const st = useStore.getState();
        if (st.me && st.guildId === gid) subscribeGuild(gid);
      }, GUILD_JOIN_RETRY_MS);
    };

    const onPlaylistUpdate = (payload: any) => { receive(payload); };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('playlist_update', onPlaylistUpdate);
    socket.on('guild_join_error', onGuildJoinError);
    startPing();

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('playlist_update', onPlaylistUpdate);
      socket.off('guild_join_error', onGuildJoinError);
      clearJoinRetry();
    };
  }, []);

  useEffect(() => {
    if (!guildId || !meId) return;
    subscribeGuild(guildId);
    return () => { clearJoinRetry(); unsubscribeGuild(guildId); };
  }, [guildId, meId]);

  useEffect(() => {
    let lastAt = 0;
    const interval = setInterval(async () => {
      const s = useStore.getState();
      if (!s.me || !s.guildId || !s.socketReady) return;
      const playing = !!s.player.current && !s.player.paused;
      const now = Date.now();
      if (!playing && !_stateStale && now - lastAt < RESYNC_IDLE_MS) return;
      lastAt = now;
      await backgroundRefresh();
    }, RESYNC_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(async () => {
      const s = useStore.getState();
      if (s.socketReady || !s.me || !s.guildId) return;
      await backgroundRefresh();
    }, POLL_FALLBACK_MS);
    return () => clearInterval(interval);
  }, []);
}

// ── Actions (au niveau du module : le clavier de page.tsx les appelle hors de React) ──

async function refreshMe() {
  const seq = _meGate.next();
  try {
    const me = normalizeMePayload(await api.getMe());
    if (_meGate.tryApply(seq)) useStore.getState().setMe(me);
    return useStore.getState().me;
  } catch (e: any) {
    if (e?.status === 401) {
      if (_meGate.tryApply(seq)) useStore.getState().setMe(null);
      return useStore.getState().me;
    }
    const prev = useStore.getState().me;
    if (prev) sayError(e);
    return prev;
  }
}

async function refreshGuilds() {
  if (!useStore.getState().me) { useStore.getState().setGuilds([]); return []; }
  try {
    const guilds = normalizeGuildsPayload(await api.getGuilds());
    useStore.getState().setGuilds(guilds);
    return guilds;
  } catch {
    useStore.getState().setGuilds([]);
    say('guild.listFailed');
    return [];
  }
}

async function refreshHistory() {
  const s = useStore.getState();
  if (!s.guildId) { s.setHistoryItems([]); return; }
  try {
    const data = await api.getHistory(s.guildId, 'top', 30);
    useStore.getState().setHistoryItems(data?.items || []);
  } catch {
    useStore.getState().setHistoryItems([]);
  }
}

async function setGuild(id: string) {
  const oldGid = useStore.getState().guildId;
  useStore.getState().setGuildId(id);
  if (id !== oldGid) resetPlayer();
  if (id) localStorage.setItem('greg.webplayer.guild_id', id);
  else localStorage.removeItem('greg.webplayer.guild_id');
  await refreshPlaylist().catch(() => {});
  await refreshHistory().catch(() => {});
}

async function logout() {
  try { await api.logout(); } catch (e) { sayError(e); return; }
  handleLoggedOut();
}

async function bestEffortVoiceJoin(reason: string) {
  const now = Date.now();
  if (now - _voiceJoinLastAt < VOICE_JOIN_COOLDOWN_MS) return;
  _voiceJoinLastAt = now;
  const s = useStore.getState();
  if (!s.me || !s.guildId) return;
  try { await api.voiceJoin(s.guildId, s.me.id, reason); } catch {}
}

/** Commande non optimiste (arrêt, boucle, reprise au début) : pas de toast au succès, erreur au Héraut. */
async function command(fn: (gid: string, uid: string) => Promise<unknown>) {
  const s = useStore.getState();
  if (!s.me || !s.guildId) return;
  try { await fn(s.guildId, s.me.id); } catch (e) { sayError(e); return; }
  await refreshPlaylist({ quiet: true }).catch(() => {});
}

/**
 * Ajoute un titre / un lien / une playlist. true si l'ajout a réussi, false s'il n'a pas été envoyé ;
 * lève l'erreur API sinon (déjà annoncée par le Héraut). Le toast propose d'annuler l'ajout.
 */
async function enqueue(payload: Record<string, any>): Promise<boolean> {
  const s = useStore.getState();
  if (!s.me || !s.guildId) {
    say(s.me ? 'guild.pickFirst' : 'error.NOT_AUTHENTICATED', { text: s.me ? t('guild.pickFirst.body') : undefined, kind: 'warn' });
    return false;
  }
  const meId = s.me.id;
  const before = upcoming().player.queue.map((x) => x.key);
  const typed = String(payload?.title || payload?.query || '');
  let res: any;
  try {
    res = await api.queueAdd(s.guildId, meId, payload);
  } catch (e) {
    sayError(e, { q: looksLikeUrl(typed) ? undefined : typed });
    await refreshPlaylist({ quiet: true }).catch(() => {});   // le bot a pu ajouter une partie des titres
    throw e;
  }
  await refreshPlaylist({ quiet: true }).catch(() => {});
  const keys = addedKeys(before, upcoming().player.queue, meId);
  const c = addedCopy(res, parseTitle(typed, payload?.artist).song || typed);
  const text = t(c.path, c.vars) + (c.suffix ? t(c.suffix, c.vars) : '');
  say(c.key, {
    text, vars: c.vars,
    action: keys.length ? { label: t(c.action), run: () => { for (const k of keys) void removeTrack(k, { silent: true }); } } : null,
  });
  await bestEffortVoiceJoin('add');
  return true;
}

const trackPayload = (x: Track) => ({
  query: x.url || x.title, url: x.url, title: x.title, artist: x.artist, thumb: x.thumb, duration: x.duration,
  provider: x.provider || 'youtube',
});

/** « Annuler » d'un retrait : le titre est rajouté (le bot n'a pas de « remettre »), puis replacé. */
async function restoreTrack(x: Track, index: number) {
  const s = useStore.getState();
  if (!s.me || !s.guildId) return;
  const before = upcoming().player.queue.map((q) => q.key);
  try { await api.queueAdd(s.guildId, s.me.id, trackPayload(x)); } catch (e) { sayError(e); return; }
  await refreshPlaylist({ quiet: true }).catch(() => {});
  // Le déplacement part après l'action en vol, une fois le tampon appliqué : il voit alors le titre remis.
  const plan = restorePlan(before, upcoming().player.queue, x.url, index);
  if (plan) await engine.dispatch({ kind: 'move', key: plan.key, beforeKey: plan.beforeKey });
}

async function removeTrack(key: string, o: { silent?: boolean } = {}): Promise<boolean> {
  // Annuler un ajout : retrait par clé, même si la ligne attend encore dans l'état gardé en tampon.
  if (o.silent) return engine.dispatch({ kind: 'remove', key });
  const q = engine.view().player.queue;
  const i = q.findIndex((x) => x.key === key);
  if (i < 0) return false;
  const x = q[i];
  const id = say('toast.removed', {
    vars: { title: songOf(x) },
    action: { label: t('toast.removed.action'), run: () => { void restoreTrack(x, i); } },
  });
  const ok = await engine.dispatch({ kind: 'remove', key });
  if (!ok) herald.dismiss(id);
  return ok;
}

/** Déposer `key` devant `beforeKey` (null : en fin de file). Un refus revient en arrière (onRefused). */
function moveTrack(key: string, beforeKey: string | null): Promise<boolean> {
  return engine.dispatch({ kind: 'move', key, beforeKey });
}

async function playNext(key: string): Promise<boolean> {
  const q = engine.view().player.queue;
  const i = q.findIndex((x) => x.key === key);
  if (i < 0) return false;
  if (i === 0) { say('toast.alreadyNext'); return true; }
  const back = q[i + 1]?.key ?? null;
  const id = say('toast.playNext', {
    vars: { title: songOf(q[i]) },
    action: { label: t('toast.playNext.action'), run: () => { void moveTrack(key, back); } },
  });
  const ok = await moveTrack(key, q[0].key);
  if (!ok) herald.dismiss(id);
  return ok;
}

async function playNow(key: string): Promise<boolean> {
  const v = engine.view().player;
  const x = v.queue.find((q) => q.key === key);
  if (!x) return false;
  const ok = await engine.dispatch({ kind: 'playAt', key, fromKey: v.current?.key ?? null });
  if (ok) { say('toast.playNow', { vars: { title: songOf(x) } }); await bestEffortVoiceJoin('play_at'); }
  return ok;
}

function skip(): Promise<boolean> {
  const cur = engine.view().player.current;
  return cur ? engine.dispatch({ kind: 'skip', fromKey: cur.key }) : Promise.resolve(false);
}

function togglePause(): Promise<boolean> {
  const p = engine.view().player;
  return p.current ? engine.dispatch({ kind: 'setPaused', paused: !p.paused }) : Promise.resolve(false);
}

/** Glisser en cours : les états reçus attendent le dépôt. */
function setDragging(on: boolean) {
  if (on) engine.hold(); else engine.release();
}

async function boot() {
  const saved = typeof window !== 'undefined' ? localStorage.getItem('greg.webplayer.guild_id') || '' : '';
  if (saved) useStore.getState().setGuildId(saved);
  await refreshMe();
  await refreshGuilds();
  const s = useStore.getState();
  const chosen = pickDefaultGuild(s.guilds, s.guildId);
  if (chosen.discarded && typeof window !== 'undefined') localStorage.removeItem('greg.webplayer.guild_id');
  if (chosen.guildId !== s.guildId) useStore.getState().setGuildId(chosen.guildId);
  await refreshPlaylist().catch(() => {});
  await refreshHistory().catch(() => {});
}

export const playerActions = {
  boot, setGuild, logout, refreshMe, refreshGuilds, refreshHistory, enqueue,
  skip, togglePause, setDragging, removeTrack, moveTrack, playNext, playNow, bestEffortVoiceJoin,
  stop: () => command((g, u) => api.queueStop(g, u)),
  toggleRepeat: () => command((g, u) => api.repeat(g, u)),
  restartTrack: () => command((g, u) => api.restart(g, u)),
  // Compat de l'ancien panneau (index de la file affichée) : retirée à la tâche 6.
  removeFromQueue: (i: number) => removeTrack(engine.view().player.queue[i]?.key ?? ''),
  playAt: (i: number) => playNow(engine.view().player.queue[i]?.key ?? ''),
};
export type PlayerActions = typeof playerActions;

/** usePlayer — état du store et actions, depuis n'importe quel composant, sans effet de bord. */
export function usePlayer(): GregStore & PlayerActions {
  return { ...useStore(), ...playerActions };
}

// ── Rafraîchissement ──
let _stateSeq = 0;
let _stateAppliedSeq = 0;
let _stateInFlight = 0;
let _stateStale = false;
let _staleNotice = '';
let _staleShown = false;

/**
 * Rafraîchit l'état du lecteur. Échec ou état périmé : on GARDE l'état précédent (jamais de faux
 * « Rien en lecture »). `quiet` : la cause est notée sans toast.
 */
async function refreshPlaylist(opts?: { quiet?: boolean }) {
  const s = useStore.getState();
  if (!s.me || !s.guildId) { resetPlayer(); return; }
  const gid = s.guildId;
  const seq = ++_stateSeq;
  _stateInFlight++;
  try {
    const data = await api.getPlaylistState(gid);
    if (!useStore.getState().me || useStore.getState().guildId !== gid || seq < _stateAppliedSeq) return;
    if (!receive(data)) throw Object.assign(new Error('stale'), { payload: data });
    _stateAppliedSeq = seq;
    _stateStale = false;
    _staleNotice = '';
    if (_staleShown) { _staleShown = false; say('toast.recovered'); }
  } catch (e: any) {
    if (!useStore.getState().me || useStore.getState().guildId !== gid || seq < _stateAppliedSeq) return;
    _stateStale = true;
    const code = errorCode(e) || 'ERROR';
    // Bot hors ligne : la progression se fige (pas de piste fantôme)
    if (code === 'BOT_OFFLINE') {
      const srv = engine.latest();
      if (srv.player.current && !srv.player.paused) {
        const now = performance.now();
        const pos = livePosition(srv.tickBase, false, now);
        engine.receive({ player: { ...srv.player, paused: true, position: pos }, tickBase: { pos, at: now, dur: srv.tickBase.dur } });
      }
    }
    if (code !== _staleNotice) {
      _staleNotice = code;
      if (!opts?.quiet) { _staleShown = true; sayError(e, { action: 'state' }); }
    }
  } finally {
    _stateInFlight--;
  }
}

async function backgroundRefresh() {
  if (_stateInFlight > 0) return;
  await refreshPlaylist().catch(() => {});
}

export { refreshPlaylist };
