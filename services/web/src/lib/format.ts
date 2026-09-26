// Helpers de formatage purs (sans import runtime : testés via tests/_loadTs.mjs).

export function fmt(sec?: number | null): string {
  if (sec == null || !isFinite(sec) || sec < 0) return '--:--';
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function extractVideoId(url?: string | null): string | null {
  if (!url) return null;
  const m = url.match(/(?:v=|\/shorts\/|youtu\.be\/)([A-Za-z0-9_\-]{11})/);
  return m ? m[1] : null;
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
