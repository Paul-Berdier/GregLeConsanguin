// Helpers de formatage purs (sans import runtime : testés via tests/_loadTs.mjs).

export function fmt(sec?: number | null): string {
  if (sec == null || !isFinite(sec) || sec < 0) return '--:--';
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// Mêmes formes que VIDEO_ID (links.ts, la pastille) et _YTID_RE (le bot) : ?v=, /shorts/, /live/, /embed/, youtu.be/,
// anciennes formes /v/ /e/ /watch/. Copie et non import : ce module est chargé sans import runtime (tests/_loadTs.mjs).
const VIDEO_ID = /(?:[?&]v=|\/shorts\/|\/live\/|\/embed\/(?!videoseries)|youtu\.be\/|\.com\/(?:v|e|watch)\/)([A-Za-z0-9_-]{11})/;
// Hôtes YouTube (YOUTUBE_HOST de links.ts, _is_youtube_host du bot) : ailleurs (soundcloud.com/watch/…), pas de vidéo.
const YOUTUBE_HOST = /(?:^|\.)(?:youtube\.com|youtu\.be|youtube-nocookie\.com)$/;

function onYouTube(url: string): boolean {
  let v = url.trim();
  if (v.startsWith('<') && v.endsWith('>')) v = v.slice(1, -1).trim();   // lien <…> copié depuis Discord
  try { return YOUTUBE_HOST.test(new URL(/^https?:\/\//i.test(v) ? v : `https://${v}`).hostname.toLowerCase()); } catch { return false; }
}

export function extractVideoId(url?: string | null): string | null {
  if (!url) return null;
  const m = url.match(VIDEO_ID);
  return m && onYouTube(url) ? m[1] : null;
}

export function discordAvatar(me: any, size = 96): string | null {
  if (!me?.id) return null;
  if (me.avatar_url?.startsWith('http')) return me.avatar_url;
  if (me.avatar) return `https://cdn.discordapp.com/avatars/${me.id}/${me.avatar}.png?size=${size}`;
  // Default avatar index: (user_id >> 22) % 6
  let idx = 0;
  try { idx = Number((BigInt(me.id) >> 22n) % 6n); } catch { idx = parseInt(String(me.id).slice(-2), 10) % 6 || 0; }
  return `https://cdn.discordapp.com/embed/avatars/${idx}.png`;
}
