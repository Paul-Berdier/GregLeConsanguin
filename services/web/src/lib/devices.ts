/**
 * Appareils liés (spec 2026-11-25 §5) : le code que l'appli Greg affiche, le code gardé le temps de se connecter
 * avec Discord, le serveur par défaut proposé et les erreurs de la page /lier (app/lier/page.tsx).
 * Pur, sans import runtime (tests/devices.test.mjs).
 */

/** Lettres du `user_code` (consonnes seulement : ni voyelle ni chiffre), comme l'API (services/overlay_tokens.py). */
export const USER_CODE_ALPHABET = 'BCDFGHJKLMNPQRSTVWXZ';
/** Clé du code en attente dans sessionStorage, et sa durée : celle du code côté API (10 min). */
export const PENDING_KEY = 'greg.lier.pending';
export const PENDING_TTL_MS = 600_000;

const USER_CODE_LEN = 8;
const USER_CODE_RE = new RegExp(`^[${USER_CODE_ALPHABET}]{${USER_CODE_LEN}}$`);

/** Ce que le code lit d'un stockage (sessionStorage, ou un double dans les tests). */
export type KV = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void };

/** Un serveur de GET /overlay/guilds : commun à Greg et au Roi ; ids en chaînes (au-delà de 2^53). */
export type DeviceGuild = {
  id: string;
  name: string;
  icon_url: string | null;
  greg_voice: { id: string; name: string } | null;
  user_voice: { id: string; name: string } | null;
  playing: boolean;
};

/** Un jeton de GET /overlay/tokens (sans empreinte) ; horodatages en secondes epoch. */
export type DeviceToken = { id: string; label: string; created_at: number; last_used_at: number; expires_at: number; current: boolean };

/** Saisie du Roi (« bcdf-ghjk », « BCDF GHJK »…) → « BCDFGHJK », ou null si ce n'est pas un code : même règle que l'API. */
export function normalizeUserCode(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const code = raw.replace(/[^\p{L}\p{N}]/gu, '').toUpperCase();
  return USER_CODE_RE.test(code) ? code : null;
}

/** « BCDFGHJK » → « BCDF-GHJK », comme l'appli l'affiche. */
export function formatUserCode(code: string): string {
  const half = USER_CODE_LEN / 2;
  return `${code.slice(0, half)}-${code.slice(half)}`;
}

/** sessionStorage du navigateur, ou null : absent (rendu serveur) ou bloqué (y accéder peut lever SecurityError). */
export function browserSession(): KV | null {
  try {
    return (globalThis as { sessionStorage?: KV }).sessionStorage ?? null;
  } catch {
    return null;
  }
}

function forget(kv: KV): void {
  try { kv.removeItem(PENDING_KEY); } catch {}
}

/** Garde le code le temps de la connexion Discord ; un code invalide n'est pas gardé, un stockage qui lève est ignoré. */
export function savePendingCode(kv: KV | null, raw: string, now: number): void {
  const code = normalizeUserCode(raw);
  if (!kv || !code) return;
  try { kv.setItem(PENDING_KEY, JSON.stringify({ code, at: now })); } catch {}
}

/** Le code en attente, sans le retirer ; illisible ou vieux de 10 min ou plus : retiré, null. */
export function peekPendingCode(kv: KV | null, now: number): string | null {
  if (!kv) return null;
  let raw: string | null;
  try { raw = kv.getItem(PENDING_KEY); } catch { return null; }
  if (raw === null) return null;
  let saved: { code?: unknown; at?: unknown } | null = null;
  try { saved = JSON.parse(raw); } catch {}
  const code = normalizeUserCode(saved?.code);
  const at = saved?.at;
  if (code && typeof at === 'number' && Number.isFinite(at) && now - at < PENDING_TTL_MS) return code;
  forget(kv);
  return null;
}

/** Le code en attente, retiré aussitôt : « / » ne renvoie vers /lier qu'une fois, même si le Roi n'y décide rien. */
export function takePendingCode(kv: KV | null, now: number): string | null {
  const code = peekPendingCode(kv, now);
  if (kv) forget(kv);
  return code;
}

/** Serveur proposé : celui déjà choisi s'il est listé, sinon celui où le Roi est en vocal, puis où Greg joue, puis le premier. */
export function pickDeviceGuild(guilds: readonly DeviceGuild[], saved: string | null): string | null {
  if (saved !== null && guilds.some((g) => g.id === saved)) return saved;
  const g = guilds.find((x) => x.user_voice) ?? guilds.find((x) => x.playing) ?? guilds[0];
  return g ? g.id : null;
}

/** Âge d'une demande en minutes entières (≥ 0) : `createdAtS` en secondes epoch, `nowMs` en millisecondes. */
export function ageMinutes(createdAtS: number, nowMs: number): number {
  const m = Math.floor((nowMs - createdAtS * 1000) / 60_000);
  return Number.isFinite(m) ? Math.max(0, m) : 0;
}

const DEVICE_ERRORS: readonly string[] = ['CODE_EXPIRED', 'ALREADY_USED', 'RATE_LIMITED', 'NOT_GUILD_MEMBER'];

/** Clé du texte (EXTRA.devices.error) d'un refus de l'API ; un INVALID_REQUEST est un code mal saisi. */
export function deviceErrorKey(e: unknown): string {
  const code = (e as { payload?: { error?: unknown } } | null | undefined)?.payload?.error;
  if (typeof code === 'string' && DEVICE_ERRORS.includes(code)) return `devices.error.${code}`;
  if (code === 'INVALID_REQUEST') return 'devices.error.INVALID_CODE';
  return 'devices.error.generic';
}
