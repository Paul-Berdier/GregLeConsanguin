/**
 * Le poster au-dessus du lecteur YouTube persistant (tech.md §5.3) et la synchro de la vidéo (§5.4).
 * Le poster couvre l'iframe jusqu'à PLAYING + REVEAL_AFTER_PLAYING_MS (si YouTube joue encore), et pendant la pause :
 * YouTube montre son habillage (titre, chaîne, icône, « Plus de vidéos ») à chaque départ, à chaque pause et à chaque saut.
 * Un saut de correction (seekTo) réarme donc le poster (mesuré : l'habillage revient ~4 s).
 * Pur, sans import runtime (tests/cover.test.mjs).
 */

export type CoverPhase = 'covered' | 'armed' | 'revealed';
/**
 * armedAt : instant (performance.now) de l'armement ; bySeek : armé par notre propre saut (pas de nouvel alignement) ;
 * playing : YouTube joue (dernier état PLAYING, pas BUFFERING), suivi armé comme révélé. Révélé seulement s'il joue
 * encore quand la minuterie tombe (tech.md §5.3) : un calage pendant l'armement garderait sinon la roue de chargement
 * ou l'image noire. Toujours false quand le poster couvre.
 */
export type Cover = { phase: CoverPhase; armedAt: number; bySeek: boolean; playing: boolean };
export type CoverEvent =
  | { type: 'track' } | { type: 'stop' } | { type: 'error' } | { type: 'pause' }
  | { type: 'yt'; state: number; now: number }   // YT.PlayerState reçu par onStateChange
  | { type: 'seek'; now: number }                // saut de correction automatique
  | { type: 'reveal'; now: number };             // minuterie de révélation écoulée

export const COVERED: Cover = { phase: 'covered', armedAt: 0, bySeek: false, playing: false };
export const YT_STATE = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 } as const;
// habillage YouTube replié vers 3924 (départ), 3929 (saut), 3916 (reprise) ms, 3937 au titre suivant (loadVideoById) ;
// sonde du 27/09/2026 (yt_probe.py, Chrome fr-FR) : vu au plus tard à 3,94 s selon les passes ; captures serrées :
// disparu partout avant 4,02 s. Sous-titres de la même sonde : voir muteCaptions.
// Aucun paramètre documenté ne le masque : on décale le lever du poster, la marque reste.
export const REVEAL_AFTER_PLAYING_MS = 4250;
// La dérive est corrigée par le régulateur (lib/sync/controller.ts) : vitesse, ou saut sans surcompensation.
export const LOAD_COMP_S = 0.4;                // loadVideoById met ~404 ms à jouer
const TIMER_SLACK_MS = 50;

/** L'échéance de révélation est passée (à la minuterie près). */
const revealDue = (c: Cover, now: number): boolean => now - c.armedAt >= REVEAL_AFTER_PLAYING_MS - TIMER_SLACK_MS;

export function coverNext(c: Cover, ev: CoverEvent): Cover {
  switch (ev.type) {
    case 'track': case 'stop': case 'error':
      return c.phase === 'covered' && !c.bySeek ? c : COVERED;
    case 'pause':
      return c.phase === 'covered' ? c : { ...c, phase: 'covered', playing: false };
    case 'seek':   // l'état de lecture suit : YouTube ne renvoie pas toujours BUFFERING → PLAYING après un saut
      return c.phase === 'covered' ? c : { phase: 'armed', armedAt: ev.now, bySeek: true, playing: c.playing };
    case 'reveal':
      return c.phase === 'armed' && c.playing && revealDue(c, ev.now) ? { ...c, phase: 'revealed' } : c;
    case 'yt':
      if (ev.state === YT_STATE.PLAYING) {
        if (c.phase === 'covered') return { phase: 'armed', armedAt: ev.now, bySeek: false, playing: true };
        if (c.playing) return c;
        if (c.phase === 'revealed') return { ...c, playing: true };
        // armé, la lecture reprend après un calage : révélé tout de suite si l'échéance est passée
        return { ...c, phase: revealDue(c, ev.now) ? 'revealed' : 'armed', playing: true };
      }
      if (ev.state === YT_STATE.BUFFERING) {
        // armé : la révélation attend la reprise ; révélé : un BUFFERING tardif ne remet pas le poster, mais il est
        // noté, pour qu'un saut pendant le calage réarme sans révéler avant la reprise
        return c.phase !== 'covered' && c.playing ? { ...c, playing: false } : c;
      }
      return c.phase === 'covered' ? c : { ...c, phase: 'covered', playing: false };   // ENDED, PAUSED, UNSTARTED, CUED
  }
}

/** Le poster est visible tant que la vidéo n'est pas révélée, et toujours pendant la pause. */
export const coverVisible = (c: Cover, paused: boolean): boolean => c.phase !== 'revealed' || paused;
/** Délai avant la révélation d'un poster armé. */
export const revealIn = (c: Cover, now: number): number => Math.max(0, c.armedAt + REVEAL_AFTER_PLAYING_MS - now);

/** Position de départ d'un loadVideoById, compensée du temps de chargement. */
export const loadStart = (clockPos: number, offset: number): number => Math.max(0, clockPos + offset + LOAD_COMP_S);

/** Recul du son (s) au-delà duquel la même vidéo est rechargée : les ticks du bot, arrondis à la seconde, n'y arrivent jamais. */
export const REWIND_S = 3;

/**
 * Le son est reparti en arrière sur la même vidéo (« Reprendre au début », boucle, même titre deux fois
 * de suite) : la nouvelle position est à plus de REWIND_S sous celle qu'on attendait. tech.md §5.4 :
 * nouvel alignement quand l'horloge saute. Sans ça, une vidéo finie (ENDED) resterait sous son poster.
 */
export function rewound(prev: { pos: number; at: number }, prevPaused: boolean, next: { pos: number; at: number }): boolean {
  const expected = prev.pos + (prevPaused ? 0 : Math.max(0, next.at - prev.at) / 1000);
  return Number.isFinite(next.pos) && next.pos < expected - REWIND_S;
}

// ── Décalage de la vidéo (réglage du Roi, gardé dans localStorage, par appareil) ──
// Synchro son/vidéo : le bot publie la position réellement lue ; reste le retard propre à Discord (serveur vocal,
// tampon du client, casque : 80 à 250 ms filaire, jusqu'à 500 ms en Bluetooth). Pas de 50 ms, ±3 s.
export const OFFSET_KEY = 'greg.webplayer.video_offset';
export const OFFSET_MIN = -3, OFFSET_MAX = 3, OFFSET_STEP = 0.05;
const PER_S = 20;   // 1 / OFFSET_STEP, entier : arrondi sans reste flottant (1,15 et non 1,1500000000000001)

/** Réglage lu (localStorage, curseur) : borné, arrondi au pas de 50 ms (demi-pas loin de 0), 0 si illisible. */
export function parseOffset(raw: string | number | null | undefined): number {
  const v = typeof raw === 'number' ? raw : raw == null || String(raw).trim() === '' ? NaN : Number(raw);
  if (!Number.isFinite(v)) return 0;
  const c = Math.min(OFFSET_MAX, Math.max(OFFSET_MIN, v));
  const stepped = (Math.sign(c) * Math.round(Math.abs(c) * PER_S)) / PER_S;   // demi-pas loin de 0, des deux côtés
  return stepped + 0;   // pas de −0
}

/** « 0 s », « +0,15 s », « −2 s » : virgule décimale, signe moins U+2212, espace insécable avant l'unité. */
export function fmtOffset(v: number): string {
  const x = parseOffset(v);
  const n = Math.abs(x).toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
  return `${x > 0 ? '+' : x < 0 ? '−' : ''}${n}\u00a0s`;
}

// ── Sous-titres ──
/**
 * Iframe muette : YouTube y montre une piste automatique malgré cc_load_policy: 0 (écart 5 de l'étape 2).
 * setOption('captions', 'track', {}) vide la piste ; unloadModule (non documenté) retire le module s'il existe.
 * Sonde du 27/09/2026 (Chrome fr-FR ; en-US à l'étape 2) : sans elle, piste allemande automatique, hl et
 * cc_lang_pref: 'fr' sans effet ; avec elle, aucun sous-titre au départ, au saut, à la reprise ni après
 * loadVideoById. getOption('captions', 'track') reste de-DE au premier titre (piste masquée), {} ensuite.
 */
export type CaptionsApi = { setOption?(module: string, option: string, value: unknown): void; unloadModule?(module: string): void };
export function muteCaptions(p: CaptionsApi): void {
  for (const m of ['captions', 'cc']) {
    try { p.setOption?.(m, 'track', {}); } catch {}
    try { p.unloadModule?.(m); } catch {}
  }
}

// ── Posters ──
export const posterUrl = (id: string, size: 'maxres' | 'hq' = 'maxres'): string =>
  `https://i.ytimg.com/vi/${id}/${size === 'maxres' ? 'maxresdefault' : 'hqdefault'}.jpg`;
/** maxresdefault absent : YouTube renvoie une vignette grise de 120 × 90 (ou un 404). */
export const isPlaceholderThumb = (naturalWidth: number): boolean => naturalWidth > 0 && naturalWidth <= 120;
