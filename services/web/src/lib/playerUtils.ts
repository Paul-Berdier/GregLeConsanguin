/**
 * Helpers purs du web player (aucun import runtime, testables avec node:test).
 * Voir tests/playerUtils.test.mjs.
 */
import type { Track, GuildInfo, PlayerState, Snapshot } from './types';

// ── Durées ──
// Le bot envoie TOUJOURS des secondes : seules les valeurs explicitement en ms
// (duration_ms / length_ms) sont converties. Plus d'heuristique « > 10000 = ms ».
export function toSeconds(v: any, unit: 's' | 'ms' = 's'): number | null {
  if (v == null) return null;
  const div = unit === 'ms' ? 1000 : 1;
  if (typeof v === 'number') {
    if (!isFinite(v)) return null;
    return Math.floor(v / div);
  }
  const s = String(v).trim();
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    if (!isFinite(n)) return null;
    return Math.floor(n / div);
  }
  const parts = s.split(':').map(Number);
  if (parts.some((x) => !isFinite(x))) return null;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}

// ── Items ──
// `users` : table id → infos user (queue_users / requested_by_user du get_state).
// Le bot stocke added_by / requested_by comme un simple id (string).
export function normalizeItem(it: any, users?: Record<string, any> | null): Track | null {
  if (!it || typeof it !== 'object') return null;

  const title = it.title || it.name || it.track_title || it.track || '';
  const url = it.url || it.webpage_url || it.href || it.link || '';
  const artist = it.artist || it.uploader || it.author || it.channel || it.by || '';
  const duration = toSeconds(it.duration ?? it.duration_s ?? it.duration_sec ?? it.length ?? it.length_s)
    ?? toSeconds(it.duration_ms ?? it.length_ms, 'ms')
    ?? null;
  const thumb = it.thumb || it.thumbnail || it.image || it.artwork || it.cover || null;
  const provider = it.provider || it.source || it.platform || null;

  let rb = it.requested_by || it.added_by || it.requester || it.user || null;
  if (rb != null && typeof rb !== 'object') {
    const id = String(rb);
    rb = (users && users[id]) || { id };
  }
  const addedById = (rb && (rb.id || rb.user_id)) || it.requested_by_id || it.added_by_id || it.user_id || null;
  const addedByName = (rb && (rb.display_name || rb.global_name || rb.username || rb.name)) || it.requested_by_name || it.added_by_name || it.user_name || it.username || '';
  const addedBy = (addedById || addedByName) ? { id: addedById ? String(addedById) : '', name: String(addedByName || '').trim() } : null;

  return { key: '', title: String(title || ''), url: String(url || ''), artist: String(artist || ''), duration, thumb, provider, addedBy, raw: it };
}

/** Table id → user à partir de queue_users + requested_by_user (payload get_state). */
export function buildUsersMap(p: any): Record<string, any> {
  const out: Record<string, any> = {};
  if (!p || typeof p !== 'object') return out;
  const qu = p.queue_users;
  if (qu && typeof qu === 'object' && !Array.isArray(qu)) {
    for (const [k, v] of Object.entries(qu)) if (v && typeof v === 'object') out[String(k)] = v;
  }
  const rbu = p.requested_by_user;
  if (rbu && typeof rbu === 'object' && rbu.id != null) out[String(rbu.id)] = rbu;
  return out;
}

/**
 * État « périmé » : l'API n'a pas pu joindre le bot (TIMEOUT, Redis…).
 * On ne doit JAMAIS l'appliquer (sinon on efface current/queue à tort).
 */
export function isStalePayload(p: any): boolean {
  if (!p || typeof p !== 'object') return false;
  return p.stale === true || p.ok === false || (p.backend_error != null && p.backend_error !== '');
}

// ── Clés stables et état reçu (tech.md §3.2 ; motion.md P8, P9) ──

// Empreinte d'un titre : `q:<qid>` si le bot en donne un, sinon url | added_by | ts | repeat_tag.
// Le bot n'a pas d'identifiant par titre ; `ts` est posé à l'ajout (_coerce_item) et suit le titre.
function fingerprint(t: Track): string {
  const r = t.raw && typeof t.raw === 'object' ? t.raw : {};
  if (r.qid) return `q:${r.qid}`;
  return `f:${[t.url || r.url || '', r.added_by ?? r.requested_by ?? '', r.ts ?? '', r.repeat_tag ?? ''].join('|')}`;
}

/**
 * Clés stables : l'empreinte suivie du rang de l'occurrence (`#0`, `#1` pour de vrais doublons).
 * Un titre garde sa clé quand d'autres s'insèrent avant lui : les lignes ne sont jamais remontées.
 */
export function assignKeys(items: Track[]): Track[] {
  const seen = new Map<string, number>();
  return items.map((t) => {
    const fp = fingerprint(t);
    const n = seen.get(fp) ?? 0;
    seen.set(fp, n + 1);
    const key = `${fp}#${n}`;
    return t.key === key ? t : { ...t, key };
  });
}

/** Même titre, mêmes champs affichés (raw ignoré). */
export function sameTrack(a: Track | null, b: Track | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.key === b.key && a.url === b.url && a.title === b.title && a.artist === b.artist
    && a.duration === b.duration && a.thumb === b.thumb && a.provider === b.provider
    && (a.addedBy?.id ?? '') === (b.addedBy?.id ?? '') && (a.addedBy?.name ?? '') === (b.addedBy?.name ?? '');
}

/** Partage structurel : un titre inchangé garde son objet, une file inchangée garde son tableau (lignes mémoïsées). */
export function shareTracks(prev: Track[], next: Track[]): Track[] {
  const byKey = new Map(prev.map((t) => [t.key, t]));
  let same = prev.length === next.length;
  const out = next.map((t, i) => {
    const old = byKey.get(t.key);
    const keep = old && sameTrack(old, t) ? old : t;
    if (keep !== prev[i]) same = false;
    return keep;
  });
  return same ? prev : out;
}

const pick = (...vals: any[]) => vals.find((v) => v !== undefined && v !== null);
function toBool(v: any): boolean {
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0;
  if (typeof v === 'string') return ['1', 'true', 'yes', 'on'].includes(v.trim().toLowerCase());
  return !!v;
}

/**
 * État reçu (REST /playlist, socket playlist_update) → instantané, fusionné avec le précédent :
 * - null pour un état périmé (contrat C3 : on garde l'état précédent) ;
 * - un tick (`only_elapsed`) ne touche qu'au temps et à la pause : titre, file et boucle restent ;
 * - clés stables et partage structurel (une file inchangée garde son tableau).
 * `now` : performance.now() à la réception, ancre de l'horloge.
 */
export function snapshotFromPayload(payload: any, prev: Snapshot, now: number): Snapshot | null {
  const root = payload && typeof payload === 'object' ? payload : {};
  if (isStalePayload(root)) return null;
  const p = root.state || root.pm || root.data || root;
  const isTick = !!p.only_elapsed;
  // added_by est un id : les infos user arrivent à part (queue_users / requested_by_user)
  const users = buildUsersMap(p);

  let current = prev.player.current;
  const rawCur = normalizeItem(p.current || p.now_playing || p.playing || null, users);
  const cur = rawCur && (rawCur.title || rawCur.url) ? assignKeys([rawCur])[0] : null;
  if (!isTick || cur) current = cur && sameTrack(prev.player.current, cur) ? prev.player.current : cur;

  let queue = prev.player.queue;
  const qRaw = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : Array.isArray(p.list) ? p.list : null;
  if (qRaw || !isTick) {
    const items = (qRaw || []).map((it: any) => normalizeItem(it, users)).filter(Boolean) as Track[];
    queue = shareTracks(prev.player.queue, assignKeys(items));
  }

  const paused = toBool(pick(p.is_paused, p.paused, p.isPaused, p.pause, false));
  // Un tick ne porte pas la boucle : elle garde sa valeur (sinon elle s'éteint à chaque seconde)
  const repeat = isTick ? prev.player.repeat : toBool(pick(p.repeat_all, p.repeat, p.repeat_mode, p.loop, false));
  const elapsed = toSeconds(pick(p.progress?.elapsed, p.progress?.position, p.elapsed, p.position, p.pos, p.current_time, 0)) ?? 0;
  const duration = toSeconds(pick(p.progress?.duration, p.duration, p.total, p.length, current?.duration, 0)) ?? 0;

  const player: PlayerState = {
    current, queue, paused: paused || !current, repeat,
    position: Math.max(0, elapsed), duration: Math.max(0, duration),
  };
  return { player, tickBase: { pos: player.position, at: now, dur: player.duration } };
}

/** État vide (déconnecté, changement de serveur). */
export function emptySnapshot(now = 0): Snapshot {
  return {
    player: { current: null, queue: [], paused: true, repeat: false, position: 0, duration: 0 },
    tickBase: { pos: 0, at: now, dur: 0 },
  };
}

// ── Liens ──
const KNOWN_HOSTS = /^(?:(?:www\.|m\.|music\.)?youtube\.com|youtu\.be|(?:on\.|m\.)?soundcloud\.com|open\.spotify\.com|spotify\.link)(?:[/?#:]|$)/i;

/** Vrai si le texte est un lien (avec ou sans schéma) : jamais d'autocomplétion dessus. */
export function looksLikeUrl(s: string): boolean {
  let v = String(s || '').trim();
  if (v.startsWith('<') && v.endsWith('>')) v = v.slice(1, -1).trim();
  if (!v || /\s/.test(v)) return false;
  if (/^https?:\/\//i.test(v)) return true;
  if (/^spotify:/i.test(v)) return true;
  return KNOWN_HOSTS.test(v);
}

/** Entrée : on ne prend une suggestion que si elle a été choisie AU CLAVIER dans une liste ouverte. */
export function enterPicksSuggestion(open: boolean, idx: number, count: number, query: string): boolean {
  return !!open && idx >= 0 && idx < count && !looksLikeUrl(query);
}

// ── Erreurs / toasts (contrat C4) ──
const ERROR_MESSAGES: Record<string, string> = {
  TIMEOUT: "Greg met trop de temps à répondre… (l'ajout continue peut-être en arrière-plan)",
  BOT_OFFLINE: 'Greg est hors ligne pour le moment.',
  REDIS_UNAVAILABLE: 'Greg est injoignable pour le moment.',
  QUOTA_EXCEEDED: 'Quota atteint : tu as déjà assez de titres dans la file.',
  PLAYLIST_UNAVAILABLE: 'Playlist inaccessible (privée, supprimée ou bloquée).',
  PLAYLIST_EMPTY: 'Playlist vide (ou aucun titre disponible).',
  SPOTIFY_UNSUPPORTED: 'Les liens Spotify ne sont pas pris en charge : colle un lien YouTube ou le titre du morceau.',
  UNSUPPORTED_SOURCE: 'Source non prise en charge : colle un lien YouTube ou SoundCloud.',
  NO_RESULTS: 'Aucun résultat trouvé.',
  EXPAND_TIMEOUT: 'La playlist met trop de temps à charger, réessaie plus tard.',
  USER_NOT_IN_VOICE: "Rejoins d'abord un salon vocal.",
  BOT_IN_OTHER_CHANNEL: 'Greg joue déjà dans un autre salon vocal.',
  GUILD_NOT_FOUND: "Greg n'est pas sur ce serveur : choisis-en un autre.",
  VOICE_CONNECT_FAILED: 'Impossible de rejoindre le salon vocal.',
  PRIORITY_FORBIDDEN: 'Action refusée : priorité insuffisante.',
  // Contrats SEC-C1/C2 : identité par la session, appartenance vérifiée par le bot
  NOT_AUTHENTICATED: 'Connecte-toi avec Discord pour contrôler Greg.',
  NOT_GUILD_MEMBER: "Tu n'es pas membre de ce serveur.",
  MEMBER_CHECK_FAILED: 'Vérification impossible, réessaie dans un instant.',
};

/** Code d'erreur applicatif (payload.error, ou backend_error d'un état périmé C3) ou ''. */
export function errorCode(e: any): string {
  const p = e?.payload;
  if (!p || typeof p !== 'object') return '';
  if (typeof p.error === 'string' && p.error.trim()) return p.error.trim();
  return typeof p.backend_error === 'string' ? p.backend_error.trim() : '';
}

/** Message utilisateur en français : payload.message, puis code traduit, puis repli HTTP/réseau. */
export function describeError(e: any): string {
  const p = e?.payload && typeof e.payload === 'object' ? e.payload : null;
  const msg = p && typeof p.message === 'string' ? p.message.trim() : '';
  if (msg) return msg;
  const code = errorCode(e);
  // /users/me et /guilds répondent « not_authenticated » en minuscules
  const known = code && (ERROR_MESSAGES[code] || ERROR_MESSAGES[code.toUpperCase()]);
  if (known) return known;
  if (code) return code;
  const status = Number(e?.status) || 0;
  if (status >= 500) return `Serveur injoignable (HTTP ${status}), réessaie dans un instant.`;
  if (status === 401) return 'Session expirée : reconnecte-toi.';
  if (e?.name === 'TypeError') return 'Connexion au serveur impossible.';
  return String(e?.message || e || 'Erreur inconnue');
}

// Codes d'erreur qui ont leur texte dans le deck (copy.v2.json, section `error`).
const DECK_ERRORS = new Set([
  'QUOTA_EXCEEDED', 'PLAYLIST_UNAVAILABLE', 'PLAYLIST_EMPTY', 'SPOTIFY_UNSUPPORTED', 'UNSUPPORTED_SOURCE',
  'CHANNEL_LINK', 'NO_RESULTS', 'EXPAND_TIMEOUT', 'TIMEOUT', 'BOT_OFFLINE', 'REDIS_UNAVAILABLE',
  'USER_NOT_IN_VOICE', 'BOT_IN_OTHER_CHANNEL', 'GUILD_NOT_FOUND', 'VOICE_CONNECT_FAILED', 'PRIORITY_FORBIDDEN',
  'NOT_AUTHENTICATED', 'NOT_GUILD_MEMBER', 'MEMBER_CHECK_FAILED', 'MOVE_FAILED', 'MOVE_PROMOTE_PRIORITY',
  'MOVE_DEMOTE_PRIORITY', 'MOVE_CONFLICT', 'NOT_PLAYING', 'EXPIRED', 'GUILDS_FAILED',
]);

/** Texte d'une erreur pour le Héraut : `key` = entrée du deck (kind, quips), `path` = texte à rendre avec `vars`. */
export type ErrorCopy = { key: string; path: string; vars?: Record<string, string> } | { key: string; text: string };

/**
 * Erreur d'API → texte du deck (vouvoiement du Roi), avec son contexte :
 * - `name` : qui a ajouté le titre visé (PRIORITY_FORBIDDEN nomme le prioritaire) ;
 * - `q` : texte cherché (NO_RESULTS) ;
 * - `action` : 'move' fait d'un refus sans code (409, file changée côté bot) un MOVE_CONFLICT ;
 *   'state' fait d'un état périmé (TIMEOUT ou cause inconnue) le « Greg est occupé » de toast.stale.
 * Code inconnu : le message français de l'API s'il y en a un, sinon HTTP_5XX, HTTP_401, NETWORK ou UNKNOWN.
 */
export function errorCopy(e: any, ctx: { name?: string; q?: string; action?: string } = {}): ErrorCopy {
  const code = errorCode(e).toUpperCase();
  const status = Number(e?.status) || 0;
  if (code === 'PRIORITY_FORBIDDEN') {
    return ctx.name ? { key: 'error.PRIORITY_FORBIDDEN', path: 'error.PRIORITY_FORBIDDEN.text', vars: { name: ctx.name } }
      : { key: 'error.PRIORITY_FORBIDDEN', path: 'error.PRIORITY_FORBIDDEN.textGeneric' };
  }
  if (code === 'NO_RESULTS') {
    return ctx.q ? { key: 'error.NO_RESULTS', path: 'error.NO_RESULTS.text', vars: { q: ctx.q } }
      : { key: 'error.NO_RESULTS', path: 'error.NO_RESULTS.textGeneric' };
  }
  // Le quota exact (k, cap) n'est pas dans la réponse de l'API
  if (code === 'QUOTA_EXCEEDED') return { key: 'error.QUOTA_EXCEEDED', path: 'error.QUOTA_EXCEEDED.textGeneric' };
  // État du lecteur périmé (contrat C3) : « occupé » pour un TIMEOUT ou une cause inconnue
  if (ctx.action === 'state' && isStalePayload(e?.payload) && (code === 'TIMEOUT' || !DECK_ERRORS.has(code))) {
    return { key: 'toast.stale', path: 'toast.stale.text' };
  }
  if (DECK_ERRORS.has(code)) return { key: `error.${code}`, path: `error.${code}.text` };
  if (code.startsWith('UNKNOWN_ACTION')) return { key: 'error.UNKNOWN_ACTION', path: 'error.UNKNOWN_ACTION.text' };
  if (!code && ctx.action === 'move' && status === 409) return { key: 'error.MOVE_CONFLICT', path: 'error.MOVE_CONFLICT.text' };
  const p = e?.payload && typeof e.payload === 'object' ? e.payload : null;
  const msg = p && typeof p.message === 'string' ? p.message.trim() : '';
  if (msg) return { key: 'error.UNKNOWN', text: msg };
  if (status >= 500) return { key: 'error.HTTP_5XX', path: 'error.HTTP_5XX.text' };
  if (status === 401) return { key: 'error.HTTP_401', path: 'error.HTTP_401.text' };
  if (e?.name === 'TypeError') return { key: 'error.NETWORK', path: 'error.NETWORK.text' };
  return { key: 'error.UNKNOWN', path: 'error.UNKNOWN.text' };
}

const BUSY_TEXT = 'Greg est occupé — état du lecteur non rafraîchi…';

/**
 * Message d'un état du lecteur non rafraîchi (contrat C3). « Occupé » seulement pour un
 * TIMEOUT (ou un code inconnu) : BOT_OFFLINE / REDIS_UNAVAILABLE… affichent le message
 * de l'API ou le code traduit ; un échec HTTP / réseau passe par describeError.
 */
export function staleStateText(e: any): string {
  const p = e?.payload && typeof e.payload === 'object' ? e.payload : null;
  const code = errorCode(e);
  if (code === 'TIMEOUT') return BUSY_TEXT;
  const hasMsg = !!(p && typeof p.message === 'string' && p.message.trim());
  if (hasMsg || (code && ERROR_MESSAGES[code]) || !isStalePayload(p)) return describeError(e);
  return BUSY_TEXT;
}

// ── Abonnement Socket.IO à un serveur (contrat SEC-C4/C7) ──
// Mêmes codes que le `retry` calculé par l'API (utilisés seulement si le booléen manque).
const JOIN_RETRY_CODES = ['TIMEOUT', 'BOT_OFFLINE', 'REDIS_UNAVAILABLE', 'MEMBER_CHECK_FAILED'];

/**
 * Réaction à un `guild_join_error` {guild_id, error, message, retry} :
 * - 'ignore' : erreur d'un autre serveur que celui affiché (ou aucun serveur affiché) ;
 * - 'retry'  : échec transitoire → se réabonner un peu plus tard ;
 * - 'show'   : refus définitif (NOT_GUILD_MEMBER, NOT_AUTHENTICATED…) → afficher `text`.
 */
export function guildJoinErrorAction(p: any, currentGuildId: string): {
  action: 'ignore' | 'retry' | 'show'; code: string; text: string;
} {
  const cur = String(currentGuildId || '');
  if (!p || typeof p !== 'object' || !cur) return { action: 'ignore', code: '', text: '' };
  if (p.guild_id != null && String(p.guild_id) !== cur) return { action: 'ignore', code: '', text: '' };
  const code = typeof p.error === 'string' ? p.error.trim() : '';
  const hasMsg = typeof p.message === 'string' && !!p.message.trim();
  const text = code || hasMsg ? describeError({ payload: p }) : "Impossible de suivre ce serveur pour l'instant.";
  const retry = typeof p.retry === 'boolean' ? p.retry : JOIN_RETRY_CODES.includes(code);
  return { action: retry ? 'retry' : 'show', code, text };
}

/**
 * État du lecteur revenu : texte qui remplace l'avertissement « périmé » encore affiché
 * (null si un autre message l'a déjà remplacé, ou si aucun avertissement n'était affiché).
 */
export function recoveredStatusText(currentText: string, staleText: string): string | null {
  if (!staleText || currentText !== staleText) return null;
  return 'Greg est de nouveau disponible ✅';
}

/** Toast de succès d'un ajout (contrat C2/C4 : added / requested / truncated / playlist / title). */
export function enqueueSuccessText(res: any): string {
  const r = res && typeof res === 'object' ? res : {};
  const num = (v: any) => (v != null && v !== '' && isFinite(Number(v)) ? Number(v) : null);
  const added = num(r.added);
  const requested = num(r.requested);
  const title = typeof r.title === 'string' ? r.title.trim() : '';

  if (r.playlist) {
    const n = added ?? 0;
    let txt = `Playlist ajoutée : ${n} titre${n > 1 ? 's' : ''}`;
    if (r.truncated === 'quota') txt += ' (limité par ton quota)';
    else if (r.truncated === 'limit') txt += ` (limité aux ${n} premiers)`;
    else if (requested != null && requested > n) txt += ` sur ${requested}`;
    return `${txt} ✅`;
  }
  // Playlist illisible (privée, trop lente) : seule la vidéo du lien a été ajoutée.
  const message = typeof r.message === 'string' ? r.message.trim() : '';
  if (r.playlist_error && message) return `⚠️ ${message}`;
  if (title) return `Ajouté : ${title} ✅`;
  return 'Ajouté à la file ✅';
}

// ── Lecture ──
/** Position courante (s) déduite de tickBase, bornée à la durée (horloge de la scène, useStageClock, et synchro vidéo). */
export function livePosition(tb: { pos: number; at: number; dur: number }, paused: boolean, now: number): number {
  const pos = (tb.pos || 0) + (paused ? 0 : (now - tb.at) / 1000);
  return tb.dur > 0 ? Math.min(Math.max(pos, 0), tb.dur) : Math.max(0, pos);
}

// ── Requêtes concurrentes ──
/**
 * Numérotation de requêtes concurrentes (ex. /users/me au boot + au focus) : une réponse
 * n'est appliquée que si elle est plus récente que la dernière APPLIQUÉE. Une requête plus
 * récente en échec transitoire (5xx, réseau) n'appelle pas tryApply → elle n'annule pas
 * une réponse plus ancienne valide.
 */
export function createSeqGate() {
  let last = 0;
  let applied = 0;
  return {
    next: (): number => ++last,
    tryApply(seq: number): boolean {
      if (seq <= applied) return false;
      applied = seq;
      return true;
    },
  };
}

// ── Serveurs (contrat C5) ──
/**
 * Choix du serveur au boot. Un serveur sauvegardé présent dans la liste est gardé ;
 * sinon (aucun, ou absent de la liste → écarté) on prend le premier où Greg est présent.
 * Liste vide (échec /guilds) : on ne valide rien.
 */
export function pickDefaultGuild(guilds: GuildInfo[], current: string): { guildId: string; discarded: boolean } {
  const list = Array.isArray(guilds) ? guilds : [];
  const cur = String(current || '');
  if (!list.length) return { guildId: cur, discarded: false };
  if (cur && list.some((g) => String(g.id) === cur)) return { guildId: cur, discarded: false };

  const withBot = list.find((g) => g.bot_present === true);
  const known = list.some((g) => typeof g.bot_present === 'boolean');
  const pick = withBot || (known ? null : list[0]);
  return { guildId: pick ? String(pick.id) : '', discarded: !!cur };
}

// ── Raccourcis clavier ──
/** Vrai si le keydown ne doit PAS déclencher de raccourci (Ctrl+R, Cmd+P, champ de saisie…). */
export function isShortcutIgnored(ev: {
  ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; repeat?: boolean;
  code?: string; key?: string; target?: any;
}): boolean {
  if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat) return true;
  const t = ev.target;
  const tag = String(t?.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || t?.isContentEditable) return true;
  if (ev.code === 'Space' || ev.key === ' ') {
    // Espace sur un bouton/lien focalisé : laisser le navigateur l'activer
    if (tag === 'button' || tag === 'a') return true;
    if (typeof t?.closest === 'function' && t.closest('button,a,select,[role=button]')) return true;
  }
  return false;
}

/**
 * Toast du Héraut après un ajout réussi (contrat C2/C4 : added / requested / truncated / playlist / title),
 * en clés du deck : `path` (texte), `suffix` (complément de playlist), `vars`, `action` (libellé d'annulation).
 */
export function addedCopy(res: any, fallbackTitle: string): {
  key: string; path: string; suffix: string | null; vars: Record<string, string | number>; action: string;
} {
  const r = res && typeof res === 'object' ? res : {};
  const num = (v: any) => (v != null && v !== '' && isFinite(Number(v)) ? Number(v) : null);
  const message = typeof r.message === 'string' ? r.message.trim() : '';
  if (r.playlist_error && message) {
    return { key: 'toast.playlistPartial', path: 'toast.playlistPartial.text', suffix: null, vars: {}, action: 'toast.added.action' };
  }
  if (r.playlist) {
    const n = num(r.added) ?? 0;
    const m = num(r.requested);
    const suffix = r.truncated === 'quota' ? 'toast.playlistAdded.suffixQuota'
      : r.truncated === 'limit' ? 'toast.playlistAdded.suffixLimit'
        : m != null && m > n ? 'toast.playlistAdded.suffixOf' : null;
    return { key: 'toast.playlistAdded', path: 'toast.playlistAdded.text', suffix, vars: { n, m: m ?? n }, action: 'toast.playlistAdded.action' };
  }
  const title = (typeof r.title === 'string' && r.title.trim()) || fallbackTitle;
  return { key: 'toast.added', path: 'toast.added.text', suffix: null, vars: { title }, action: 'toast.added.action' };
}
