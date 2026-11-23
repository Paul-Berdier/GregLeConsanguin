// Choix du serveur (spec 2026-11-23 §1) : texte plié, recherche et ordre des serveurs, intertitres, modèle clavier.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const {
  SEARCH_FROM, searchable, foldText, rankName, filterGuilds, groupGuilds, openingActive, guildKey, imeKey, moveIndex,
} = await loadTs('../src/lib/guilds.ts');

const g = (id, name, bot_present) => (bot_present === undefined ? { id, name } : { id, name, bot_present });
const ids = (list) => list.map((x) => x.id);

test('foldText : minuscules, sans accents, espaces réduits', () => {
  assert.equal(foldText('  Les  Gueux\td’ÉTÉ \n'), 'les gueux d\'ete');
  assert.equal(foldText('Ça GAZE à Noël'), 'ca gaze a noel');
  assert.equal(foldText('Ñandú Çà Øk'), 'nandu ca øk');   // ø n'est pas une lettre accentuée en Unicode : gardée
  assert.equal(foldText(''), '');
  assert.equal(foldText('   '), '');
});

test('foldText : ligatures, apostrophes courbes, lettres de fantaisie des noms Discord', () => {
  assert.equal(foldText('Cœur d’Or'), 'coeur d\'or');
  assert.equal(foldText('Æther STRAẞE'), 'aether strasse');
  assert.equal(foldText('l‘ost ʼici'), 'l\'ost \'ici');
  assert.equal(foldText('𝔊𝔯𝔢𝔤'), 'greg');          // gothique mathématique
  assert.equal(foldText('ｇｒｅｇ'), 'greg');          // pleine chasse
  assert.equal(foldText('𝐆𝐫𝐞𝐠 le 𝓒𝓸𝓷𝓼𝓪𝓷𝓰𝓾𝓲𝓷'), 'greg le consanguin');
  assert.equal(foldText('İstanbul'), 'istanbul');
  // une écriture non latine reste lisible et comparable
  assert.equal(foldText('ギルド'), foldText('ギルド'.normalize('NFD')));
  assert.equal(foldText('Сервер'), 'сервер');
});

test('champ de recherche : à partir de 8 serveurs', () => {
  assert.equal(SEARCH_FROM, 8);
  assert.deepEqual([0, 1, 7, 8, 9, 200].map(searchable), [false, false, false, true, true, true]);
});

test('sans requête : Greg présent d’abord, ordre de Discord gardé dans chaque groupe', () => {
  const list = [g('1', 'Zeta', false), g('2', 'Alpha', true), g('3', 'Mu', false), g('4', 'Beta', true), g('5', 'Nu', false)];
  assert.deepEqual(ids(filterGuilds(list, '')), ['2', '4', '1', '3', '5']);
  assert.deepEqual(ids(filterGuilds(list, '   ')), ['2', '4', '1', '3', '5'], 'des espaces seuls ne sont pas une requête');
});

test('sans requête, présence inconnue de l’API : l’ordre de Discord tel quel', () => {
  const list = [g('1', 'Zeta'), g('2', 'Alpha'), g('3', 'Mu')];
  assert.deepEqual(ids(filterGuilds(list, '')), ['1', '2', '3']);
});

test('filterGuilds rend un nouveau tableau des mêmes objets, sans toucher l’entrée', () => {
  const list = [g('1', 'Zeta', false), g('2', 'Alpha', true)];
  const before = [...list];
  const out = filterGuilds(list, '');
  assert.notEqual(out, list);
  assert.deepEqual(list, before);
  assert.equal(out[0], list[1], 'mêmes objets (le composant lit id, icône, présence)');
  assert.deepEqual(filterGuilds([], 'x'), []);
});

test('requête : sans casse ni accents, des deux côtés', () => {
  const list = [g('1', 'Les Gueux d’Été'), g('2', 'Taverne'), g('3', 'CAFÉ CRÈME')];
  assert.deepEqual(ids(filterGuilds(list, 'ete')), ['1']);
  assert.deepEqual(ids(filterGuilds(list, 'ÉTÉ')), ['1']);
  assert.deepEqual(ids(filterGuilds(list, 'cafe creme')), ['3']);
  assert.deepEqual(ids(filterGuilds(list, 'café')), ['3']);
  assert.deepEqual(ids(filterGuilds(list, "d'ete")), ['1'], 'apostrophe droite tapée, courbe dans le nom');
  assert.deepEqual(ids(filterGuilds(list, 'introuvable')), []);
});

test('requête de plusieurs mots : tous doivent apparaître, dans n’importe quel ordre', () => {
  const list = [g('1', 'Les Gueux d’Alsace'), g('2', 'Gueux de Paris'), g('3', 'Alsace Moselle')];
  assert.deepEqual(ids(filterGuilds(list, 'gueux alsace')), ['1']);
  assert.deepEqual(ids(filterGuilds(list, 'alsace gueux')), ['1']);
  assert.deepEqual(ids(filterGuilds(list, '  GUEUX   ')), ['2', '1'], 'espaces autour et en trop ignorés');
  assert.deepEqual(ids(filterGuilds(list, 'gueux lyon')), [], 'un mot manque : écarté');
});

test('rang : nom exact > début du nom > début d’un mot > ailleurs', () => {
  assert.equal(rankName('greg', 'greg'), 0);
  assert.equal(rankName('greg le consanguin', 'greg'), 1);
  assert.equal(rankName('greg le consanguin', 'greg le c'), 1);
  assert.equal(rankName('chez greg', 'greg'), 2);
  assert.equal(rankName('les amis-de-greg', 'greg'), 2, 'un tiret sépare les mots');
  assert.equal(rankName('l\'antre de greg', 'antre'), 2, 'une apostrophe aussi');
  assert.equal(rankName('consanguin greg', 'greg cons'), 2, 'chaque mot au début d’un mot');
  assert.equal(rankName('gregoire', 'goire'), 3);
  assert.equal(rankName('xab ab', 'ab'), 2, 'une occurrence au début d’un mot suffit');
  assert.equal(rankName('greg le consanguin', 'greg sanguin'), 3, 'un des mots au milieu d’un mot');
  assert.equal(rankName('greg', 'grog'), -1);
});

test('requête : classement par rang, puis Greg présent, puis l’ordre de Discord', () => {
  const list = [
    g('a', 'Le Repaire de Greg', false),   // début d'un mot
    g('b', 'Gregorien', false),            // début du nom
    g('c', 'Greg', false),                 // exact
    g('d', 'Les Gregoriens', true),        // début d'un mot, Greg présent
    g('e', 'Pigregor', true),              // ailleurs
    g('f', 'Gregory', true),               // début du nom, Greg présent
    g('g', 'Mégrégeois', false),           // ailleurs (accents pliés)
    g('h', 'Repaire', true),               // écarté
  ];
  assert.deepEqual(ids(filterGuilds(list, 'greg')), ['c', 'f', 'b', 'd', 'a', 'e', 'g']);
});

test('requête : ordre stable à rang et présence égaux', () => {
  const list = Array.from({ length: 30 }, (_, i) => g(String(i), `Salle ${i % 3 ? 'des' : 'du'} trône ${i}`, i % 2 === 0));
  const out = ids(filterGuilds(list, 'salle'));
  const even = list.filter((x) => x.bot_present).map((x) => x.id), odd = list.filter((x) => !x.bot_present).map((x) => x.id);
  assert.deepEqual(out, [...even, ...odd]);
  assert.deepEqual(ids(filterGuilds(list, 'salle')), out, 'même entrée, même sortie');
});

test('noms absents ou vides : jamais d’exception, jamais trouvés par une requête', () => {
  const list = [{ id: '1', name: '' }, { id: '2', name: undefined }, g('3', 'Taverne')];
  assert.deepEqual(ids(filterGuilds(list, '')), ['1', '2', '3']);
  assert.deepEqual(ids(filterGuilds(list, 'tav')), ['3']);
});

test('intertitres : présence connue et aucune requête ; groupes vides omis', () => {
  const list = filterGuilds([g('1', 'Zeta', false), g('2', 'Alpha', true), g('3', 'Mu', false)], '');
  assert.deepEqual(groupGuilds(list, '').map((x) => [x.key, ids(x.guilds)]), [['present', ['2']], ['absent', ['1', '3']]]);
  const none = filterGuilds([g('1', 'Zeta', false), g('3', 'Mu', false)], '');
  assert.deepEqual(groupGuilds(none, '').map((x) => [x.key, ids(x.guilds)]), [['absent', ['1', '3']]]);
  const all = filterGuilds([g('1', 'Zeta', true)], '');
  assert.deepEqual(groupGuilds(all, '').map((x) => x.key), ['present']);
});

test('intertitres : aucun avec une requête, ni quand la présence est inconnue', () => {
  const known = [g('1', 'Zeta', false), g('2', 'Zorro', true)];
  const found = filterGuilds(known, 'z');
  assert.deepEqual(groupGuilds(found, 'z').map((x) => [x.key, ids(x.guilds)]), [['all', ['2', '1']]]);
  assert.deepEqual(groupGuilds(filterGuilds(known, '  '), '  ').map((x) => x.key), ['present', 'absent'], 'espaces seuls : pas une requête');
  const unknown = [g('1', 'Zeta'), g('2', 'Alpha')];
  assert.deepEqual(groupGuilds(unknown, '').map((x) => [x.key, ids(x.guilds)]), [['all', ['1', '2']]]);
  assert.deepEqual(groupGuilds([], ''), []);
  assert.deepEqual(groupGuilds([], 'x'), []);
});

test('groupes : leur suite redonne exactement l’ordre parcouru au clavier', () => {
  const list = filterGuilds([g('1', 'A', false), g('2', 'B', true), g('3', 'C'), g('4', 'D', true)], '');
  assert.deepEqual(groupGuilds(list, '').flatMap((x) => ids(x.guilds)), ids(list));
});

test('ouverture : le serveur choisi, sinon le premier (le dernier par ↑) ; liste vide : aucun', () => {
  const list = [g('1', 'A'), g('2', 'B'), g('3', 'C')];
  assert.equal(openingActive(list, '2', 'first'), '2');
  assert.equal(openingActive(list, '2', 'last'), '2');
  assert.equal(openingActive(list, '', 'first'), '1');
  assert.equal(openingActive(list, '9', 'last'), '3');
  assert.equal(openingActive([], '2', 'first'), null);
});

test('clavier : ↑ ↓ Début Fin parcourent, Entrée choisit, Espace seulement sur la liste', () => {
  const field = { field: true, query: '' }, list = { field: false, query: '' };
  assert.deepEqual(['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter'].map((key) => guildKey({ key }, field)),
    ['next', 'prev', 'first', 'last', 'choose']);
  assert.deepEqual(['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].map((key) => guildKey({ key }, list)),
    ['next', 'prev', 'first', 'last', 'choose', 'choose']);
  assert.equal(guildKey({ key: ' ' }, field), null, 'dans le champ, Espace tape une espace');
  for (const key of ['a', 'Tab', 'Backspace', 'ArrowLeft', 'ArrowRight', 'PageDown']) assert.equal(guildKey({ key }, field), null, key);
});

test('clavier : Échap vide un champ non vide (sans fermer) ; champ vide : la touche remonte et ferme', () => {
  assert.equal(guildKey({ key: 'Escape' }, { field: true, query: 'gue' }), 'clear');
  assert.equal(guildKey({ key: 'Escape' }, { field: true, query: '   ' }), 'clear', 'des espaces se voient : vidés d’abord');
  assert.equal(guildKey({ key: 'Escape' }, { field: false, query: 'gue' }), 'clear', 'aussi depuis la liste');
  assert.equal(guildKey({ key: 'Escape' }, { field: true, query: '' }), null);
});

test('clavier : les touches modifiées suivent leur cours (sélection du texte, raccourcis du navigateur)', () => {
  const field = { field: true, query: 'x' };
  assert.equal(guildKey({ key: 'Home', shiftKey: true }, field), null);
  assert.equal(guildKey({ key: 'End', shiftKey: true }, field), null);
  assert.equal(guildKey({ key: 'ArrowDown', shiftKey: true }, field), null);
  assert.equal(guildKey({ key: 'ArrowDown', altKey: true }, field), null);
  assert.equal(guildKey({ key: 'Home', ctrlKey: true }, field), null);
  assert.equal(guildKey({ key: 'Enter', metaKey: true }, field), null);
  assert.equal(guildKey({ key: 'Enter', shiftKey: true }, field), 'choose');
});

test('composition (IME) : la touche lui appartient, Entrée de Safari après compositionend comprise', () => {
  assert.equal(imeKey({ isComposing: true, keyCode: 13 }), true);
  assert.equal(imeKey({ isComposing: false, keyCode: 229 }), true, 'Safari : Entrée qui valide, isComposing déjà faux');
  assert.equal(imeKey({ isComposing: true, keyCode: 27 }), true, 'Échap qui annule la composition');
  assert.equal(imeKey({ isComposing: false, keyCode: 13 }), false);
  assert.equal(imeKey({ isComposing: false, keyCode: 27 }), false);
  assert.equal(imeKey({}), false);
});

test('déplacement : bouclage aux deux bouts, départ sans option active, liste vide', () => {
  assert.deepEqual([0, 1, 2].map((i) => moveIndex(i, 3, 'next')), [1, 2, 0]);
  assert.deepEqual([0, 1, 2].map((i) => moveIndex(i, 3, 'prev')), [2, 0, 1]);
  assert.equal(moveIndex(-1, 3, 'next'), 0);
  assert.equal(moveIndex(-1, 3, 'prev'), 2);
  assert.equal(moveIndex(7, 3, 'next'), 0, 'index hors liste (liste raccourcie) : repart d’un bout');
  assert.equal(moveIndex(1, 3, 'first'), 0);
  assert.equal(moveIndex(1, 3, 'last'), 2);
  for (const m of ['next', 'prev', 'first', 'last']) assert.equal(moveIndex(-1, 0, m), -1, m);
});
