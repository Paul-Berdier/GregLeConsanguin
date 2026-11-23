/**
 * Choix du serveur (spec 2026-11-23 §1) : un Roi peut siéger sur des centaines de serveurs Discord. Recherche sans
 * casse ni accents, ordre « Greg présent d'abord », intertitres et modèle clavier du popover (Header/GuildPicker.tsx).
 * Pur, sans import runtime (tests/guilds.test.mjs).
 */

import type { GuildInfo } from './types';

/** Ce que le tri lit d'un serveur : son nom, et la présence de Greg (absente quand l'API ne la connaît pas). */
export type GuildLike = Pick<GuildInfo, 'name' | 'bot_present'>;

/** Le champ de recherche n'apparaît qu'à partir de ce nombre de serveurs : en dessous, la liste se lit d'un coup d'œil. */
export const SEARCH_FROM = 8;

export const searchable = (count: number): boolean => count >= SEARCH_FROM;

/**
 * Forme comparable d'un texte : minuscules, sans accents (NFD) ni autres signes combinants, espaces réduits.
 * NFKD plutôt que NFD (il fait aussi tout ce que fait NFD) : les lettres de fantaisie des noms Discord (𝔊𝔯𝔢𝔤, ｇｒｅｇ,
 * 𝐆𝐫𝐞𝐠) redeviennent des lettres simples. Ligatures œ, æ et ß dépliées, apostrophes courbes ramenées à la droite :
 * « Cœur d’Or » se trouve en tapant « coeur d'or ».
 */
export function foldText(s: string): string {
  return s.normalize('NFKD').toLowerCase().replace(/\p{M}+/gu, '')
    .replace(/œ/g, 'oe').replace(/æ/g, 'ae').replace(/ß/g, 'ss')
    .replace(/[‘’ʼ]/g, "'")
    .replace(/\s+/g, ' ').trim();
}

// Une lettre ou un chiffre, de toute écriture : ce qui précède le début d'un mot n'en est pas un.
const WORD_CHAR = /[\p{L}\p{N}]/u;

/** `word` commence-t-il un mot de `name` (début du nom, ou après une espace, un tiret, une apostrophe…) ? Toutes les
 * occurrences comptent : « ab » commence un mot de « xab ab ». Sans lookbehind (Safari < 16.4). */
function atWordStart(name: string, word: string): boolean {
  for (let i = name.indexOf(word); i >= 0; i = name.indexOf(word, i + 1)) {
    if (i === 0 || !WORD_CHAR.test(name[i - 1])) return true;
  }
  return false;
}

/**
 * Rang d'un nom plié pour une requête pliée non vide : 0 nom exact, 1 début du nom, 2 chaque mot de la requête au
 * début d'un mot du nom, 3 ailleurs ; -1 : un mot de la requête manque (le serveur est écarté).
 */
export function rankName(name: string, q: string): number {
  const words = q.split(' ');
  if (!words.every((w) => name.includes(w))) return -1;
  if (name === q) return 0;
  if (name.startsWith(q)) return 1;
  return words.every((w) => atWordStart(name, w)) ? 2 : 3;
}

const present = (g: GuildLike): number => (g.bot_present === true ? 1 : 0);

/**
 * Serveurs à montrer pour la requête `query`, dans l'ordre du popover (un nouveau tableau, `guilds` intact).
 * - Sans requête : ceux où Greg est présent d'abord, puis les autres ; l'ordre de Discord est gardé dans chaque groupe.
 * - Avec requête : tous ses mots doivent apparaître dans le nom ; rang exact > début du nom > début d'un mot > ailleurs ;
 *   à rang égal, Greg présent d'abord, puis l'ordre de Discord.
 */
export function filterGuilds<G extends GuildLike>(guilds: readonly G[], query: string): G[] {
  const q = foldText(query);
  const rows: { g: G; rank: number; i: number }[] = [];
  guilds.forEach((g, i) => {
    const rank = q ? rankName(foldText(g.name || ''), q) : 0;
    if (rank >= 0) rows.push({ g, rank, i });
  });
  rows.sort((a, b) => a.rank - b.rank || present(b.g) - present(a.g) || a.i - b.i);
  return rows.map((r) => r.g);
}

export type GuildGroup<G> = { key: 'present' | 'absent' | 'all'; guilds: G[] };

/**
 * Groupes du popover, dans l'ordre de `sorted` (sortie de filterGuilds). Intertitres « Greg présent » / « Sans Greg »
 * seulement sans requête et quand l'API connaît la présence de Greg ; sinon un seul groupe `all`, sans intertitre.
 * Groupe vide omis ; aucun serveur : aucun groupe.
 */
export function groupGuilds<G extends GuildLike>(sorted: readonly G[], query: string): GuildGroup<G>[] {
  if (!sorted.length) return [];
  if (foldText(query) || !sorted.some((g) => typeof g.bot_present === 'boolean')) return [{ key: 'all', guilds: [...sorted] }];
  const groups: GuildGroup<G>[] = [
    { key: 'present', guilds: sorted.filter((g) => g.bot_present === true) },
    { key: 'absent', guilds: sorted.filter((g) => g.bot_present !== true) },
  ];
  return groups.filter((x) => x.guilds.length > 0);
}

/** Serveur actif à l'ouverture : le serveur choisi s'il est dans la liste, sinon le premier (le dernier, ouvert par ↑). */
export function openingActive(list: readonly { id: string }[], currentId: string, from: 'first' | 'last'): string | null {
  if (list.some((g) => g.id === currentId)) return currentId;
  return (from === 'last' ? list[list.length - 1] : list[0])?.id ?? null;
}

/**
 * Touche qui appartient à une composition en cours (IME : japonais, chinois, coréen…) : ni choix, ni déplacement, ni
 * fermeture du popover. Safari lance le keydown de l'Entrée qui valide la composition après compositionend, avec
 * isComposing faux mais keyCode 229 : sans ce second test, valider « サーバー » choisirait le serveur actif.
 */
export function imeKey(e: { isComposing?: boolean; keyCode?: number }): boolean {
  return e.isComposing === true || e.keyCode === 229;
}

export type ListMove = 'next' | 'prev' | 'first' | 'last';
export type GuildKeyAct = ListMove | 'choose' | 'clear';
export type KeyLike = { key: string; altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean };

/**
 * Touche reçue par le popover, focus dans le champ (`field`) ou sur la liste ; même modèle des deux côtés.
 * ↑ ↓ Début Fin parcourent, Entrée choisit (Espace aussi sur la liste : dans le champ, elle tape une espace),
 * Échap vide le champ s'il contient du texte. null : la touche suit son cours (Échap sur un champ vide remonte à
 * usePopover, qui ferme ; Tab sort ; Maj+Début sélectionne le texte ; les lettres tapent dans le champ).
 */
export function guildKey(e: KeyLike, o: { field: boolean; query: string }): GuildKeyAct | null {
  if (e.altKey || e.ctrlKey || e.metaKey) return null;
  const nav = !e.shiftKey;
  switch (e.key) {
    case 'ArrowDown': return nav ? 'next' : null;
    case 'ArrowUp': return nav ? 'prev' : null;
    case 'Home': return nav ? 'first' : null;
    case 'End': return nav ? 'last' : null;
    case 'Enter': return 'choose';
    case ' ': return o.field ? null : 'choose';
    case 'Escape': return o.query ? 'clear' : null;
    default: return null;
  }
}

/** Index après un déplacement dans une liste de `n` options, avec bouclage ; depuis aucune (-1), ↓ va à la première et ↑
 * à la dernière. Liste vide : -1. */
export function moveIndex(i: number, n: number, move: ListMove): number {
  if (n <= 0) return -1;
  if (move === 'first') return 0;
  if (move === 'last') return n - 1;
  if (i < 0 || i >= n) return move === 'next' ? 0 : n - 1;
  return (i + (move === 'next' ? 1 : -1) + n) % n;
}
