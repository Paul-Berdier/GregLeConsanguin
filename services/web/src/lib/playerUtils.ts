/**
 * Helpers purs du web player (aucun import runtime, testables avec node:test).
 * Voir tests/playerUtils.test.mjs.
 */
import type { Track, GuildInfo } from './types';

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

  return { title: String(title || ''), url: String(url || ''), artist: String(artist || ''), duration, thumb, provider, addedBy, raw: it };
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
