/**
 * Nature d'un lien collé dans la recherche (pastille et libellé du bouton « Ajouter »).
 * Fonctions pures, sans import runtime : testées via tests/_loadTs.mjs (tests/links.test.mjs).
 *
 * Seul YouTube est pris en charge : Spotify a sa propre pastille (message dédié côté bot),
 * SoundCloud et tout autre site sont « non pris en charge ».
 *
 * Pour YouTube, mêmes règles que le bot (packages/shared/greg_shared/extractors/youtube.py :
 * `_is_youtube_host`, `_YTID_RE`, `is_playlist_or_mix_url`, `expand_bundle`), pour que la pastille
 * décrive ce que l'ajout fera vraiment.
 */

export type LinkKind = 'none' | 'video' | 'playlist' | 'mix' | 'channel' | 'spotify' | 'unsupported';

// Sans schéma, seuls ces hôtes font un lien : mêmes règles que looksLikeUrl (playerUtils),
// pour que la pastille décrive exactement ce que l'envoi fera (« Mr.Brightside » reste un titre).
const SCHEMELESS_LINK = /^(?:(?:www\.|m\.|music\.)?youtube\.com|youtu\.be|(?:on\.|m\.)?soundcloud\.com|open\.spotify\.com|spotify\.link)(?:[/?#:]|$)/i;
// Le domaine ou l'un de ses sous-domaines (www., m., music.…), comme _is_youtube_host.
const YOUTUBE_HOST = /(?:^|\.)(?:youtube\.com|youtu\.be|youtube-nocookie\.com)$/;
const SPOTIFY_HOST = /^(?:open\.spotify\.com|spotify\.link)$/;
// Identifiant de vidéo (_YTID_RE) : ?v=, /shorts/, /live/, /embed/, youtu.be/, anciennes formes /v/ /e/ /watch/
const VIDEO_ID = /(?:[?&]v=|\/shorts\/|\/live\/|\/embed\/(?!videoseries)|youtu\.be\/|\.com\/(?:v|e|watch)\/)[A-Za-z0-9_-]{11}/;
// Listes lues comme un mix (_MIX_PREFIXES)
const MIX_PREFIX = /^(?:RD|UL|PU)/;
// YouTube Music : playlist /browse/VL<id> (_bundle_list_id) et album /browse/MPREb_… (_YT_MUSIC_ALBUM_RE)
const MUSIC_LIST_PATH = /^\/browse\/VL([\w-]+)/;
const MUSIC_ALBUM_PATH = /^\/browse\/MPREb_[\w-]+\/?$/;
// Chaîne ou onglet que le bot déplie à plat (_YT_TAB_PATH_RE) ; les autres onglets ne donnent rien.
const CHANNEL_TAB_PATH = /^\/(?:@[^/]+|channel\/[^/]+|c\/[^/]+|user\/[^/]+)(?:\/(?:videos|shorts|streams))?\/?$/i;

export function classifyLink(input: string): LinkKind {
  let v = String(input || '').trim();
  if (v.startsWith('<') && v.endsWith('>')) v = v.slice(1, -1).trim(); // lien <…> copié depuis Discord
  if (!v || /\s/.test(v)) return 'none';
  if (/^spotify:/i.test(v)) return 'spotify';
  if (!/^https?:\/\//i.test(v)) {
    if (!SCHEMELESS_LINK.test(v)) return 'none';
    v = `https://${v}`;
  }

  let u: URL;
  try { u = new URL(v); } catch { return 'unsupported'; }
  const host = u.hostname.toLowerCase();
  if (SPOTIFY_HOST.test(host)) return 'spotify';
  if (!YOUTUBE_HOST.test(host)) return 'unsupported';

  const q = u.searchParams;
  const path = u.pathname;
  const music = host === 'music.youtube.com';
  const list = q.get('list') || (music && MUSIC_LIST_PATH.exec(path)?.[1]) || '';
  const video = VIDEO_ID.test(u.href);
  const radio = q.get('start_radio') === '1' || q.get('start_radio') === 'true';
  if (MIX_PREFIX.test(list) || (!list && radio && video)) return 'mix';
  if (list || /^\/playlist\/?$/i.test(path) || (music && MUSIC_ALBUM_PATH.test(path))) return 'playlist';
  if (video) return 'video';
  if (host !== 'youtu.be' && CHANNEL_TAB_PATH.test(path)) return 'channel';
  return 'unsupported';
}

/**
 * Clé du deck pour le bouton d'envoi : une playlist ou un mix se disent, le reste « Ajouter ».
 * Une chaîne est ajoutée comme une playlist (ses derniers titres, expand_bundle côté bot).
 */
export function submitLabelKey(kind: LinkKind): 'search.submit.default' | 'search.submit.playlist' | 'search.submit.mix' {
  if (kind === 'playlist' || kind === 'channel') return 'search.submit.playlist';
  if (kind === 'mix') return 'search.submit.mix';
  return 'search.submit.default';
}

/** Pastille rouge : le lien ne donnera rien ici (Spotify, autre site, page YouTube que le bot ne lit pas). */
export function isBadLink(kind: LinkKind): boolean {
  return kind === 'spotify' || kind === 'unsupported';
}
