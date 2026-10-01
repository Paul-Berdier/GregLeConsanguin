/**
 * Titres YouTube nettoyés pour l'affichage (DESIGN §6) : « Queen – Bohemian Rhapsody (Official Video
 * Remastered) » devient Bohemian Rhapsody / Queen. Le titre brut reste en info-bulle.
 * Repris de `cleanTitle` / `parse` (proto-gothique/work/refine/src/app.js, lignes 129–147), plus les
 * mentions françaises (« Clip officiel », « Vidéo officielle », « Paroles »).
 * Pur, sans import runtime (tests/titles.test.mjs).
 */

export type ParsedTitle = { song: string; artist: string };

const NOISE = /\s*[([][^)\]]*\b(official|officiel(?:le)?|video|vidéo|audio|remaster(?:ed)?|4k|hd|lyrics?|paroles|clip|upgrade|version|visualizer)\b[^)\]]*[)\]]/gi;

/**
 * Forme comparable : minuscules, sans accents, lettres et chiffres seulement, de toute écriture
 * (cyrillique, hangeul, kana… : réduits à rien, deux parties non latines passaient pour un doublon).
 */
export const normTitle = (x: string): string =>
  x.toLowerCase().normalize('NFD').replace(/[^\p{L}\p{N}]/gu, '');

export function cleanTitle(t: string): string {
  return t.normalize('NFC').replace(NOISE, '').replace(/\s+/g, ' ').trim();
}

export function cleanArtist(a: string): string {
  return a.replace(/VEVO$/i, '').replace(/\s*-\s*Topic$/i, '').replace(/\s+Official$/i, '').trim();
}

/** « Artiste – Titre » ou « Titre – Artiste » : l'artiste connu de la chaîne tranche. */
export function parseTitle(title: string | null | undefined, artist?: string | null): ParsedTitle {
  const a0 = cleanArtist(artist || '');
  // doublon voisin (« Nirvana - Nirvana - … ») ; une partie sans lettre ni chiffre (« ♪ ») n'en est jamais un
  const parts = cleanTitle(title || '').split(/\s+[-–—]\s+/)
    .filter((x, i, arr) => i === 0 || normTitle(x) === '' || normTitle(x) !== normTitle(arr[i - 1]));
  if (parts.length < 2) return { song: parts.join(' – '), artist: a0 };
  const a = parts[0], b = parts.slice(1).join(' – ');
  const na = normTitle(a0);
  return normTitle(b).includes(na) && !normTitle(a).includes(na) ? { song: a, artist: b } : { song: b, artist: a };
}
