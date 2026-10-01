// Tests du module de textes « valet du Roi » (deck v2, src/theme/copy.v2.json).
// Lancer : npm test   (Node >= 22.18 natif ; Node 20 : après `npm install`, voir _loadTs.mjs)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { loadTs } from './_loadTs.mjs';

// copy.ts importe son deck JSON (seul import runtime). Le type stripping natif le résout ;
// la transpilation de secours de _loadTs charge le module depuis une URL data:, qui ne sait
// pas résoudre un import relatif : dans ce cas, on pointe l'import vers l'URL absolue du JSON.
async function loadCopy() {
  if (process.features?.typescript && !process.env.GREG_TEST_TRANSPILE) return loadTs('../src/theme/copy.ts');
  const ts = (await import('typescript')).default;
  const url = new URL('../src/theme/copy.ts', import.meta.url);
  const json = new URL('./copy.v2.json', url).href;
  const src = (await readFile(url, 'utf8')).replace(/(['"])\.\/copy\.v2\.json\1/, JSON.stringify(json));
  const out = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(out.outputText).toString('base64')}`);
}

const { t, fill, quip, deck, has, kingAddress, SIRE_DEFAULT } = await loadCopy();

// Toutes les chaînes du deck avec leur chemin (« glossary.2.where »).
function* strings(node, path = '') {
  if (typeof node === 'string') { yield [path, node]; return; }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) yield* strings(v, path ? `${path}.${k}` : k);
  }
}

test('fill remplace les jetons connus et garde les inconnus', () => {
  assert.equal(fill('Salut {sire}, {x}', { sire: 'Sire' }), 'Salut Sire, {x}');
  assert.equal(fill('{n} titres', { n: 0 }), '0 titres');
  assert.equal(fill('{sire}'), '{sire}');
  // Seules les clés propres de vars comptent (pas Object.prototype).
  assert.equal(fill('{constructor} {toString}', {}), '{constructor} {toString}');
});

test('t lit un chemin du deck', () => {
  assert.equal(t('search.submit.playlist'), 'Ajouter la playlist');
  assert.match(t('search.placeholder'), /YouTube/);
  assert.equal(t('shortcuts.items.0.1'), 'Lecture / pause');
});

test('quip est déterministe et remplit {sire}', () => {
  const a = quip('header.welcome', 3, { sire: 'Sire' });
  assert.equal(a, quip('header.welcome', 3, { sire: 'Sire' }));
  assert.ok(a && !a.includes('{sire}'));
});

test('casting : aucun texte ne fait de Greg un roi', () => {
  const all = JSON.stringify(deck);
  for (const bad of ['GREGORIVS · REX', 'Greg, roi', 'le roi Greg']) assert.ok(!all.includes(bad), bad);
  // « Yo el Rey » et REX sont la formule et le titre du Roi, c'est-à-dire de l'utilisateur
  // (persona v2, glossaire « Signature » et « Cartouche latin royal ») : admis seulement comme
  // valeurs de ses jetons d'adresse, dans la documentation des jetons (_meta) et dans le
  // glossaire de ce qui appartient au Roi. Les textes affichés passent par {yoElRey} / {REX}.
  const kingOwned = (path) => {
    if (/^address\.king\.options\.\w+\.(yoElRey|REX)$/.test(path) || path.startsWith('_meta.')) return true;
    const g = /^glossary\.(\d+)\./.exec(path);
    return Boolean(g && deck.glossary[Number(g[1])].owner === 'king');
  };
  for (const [path, s] of strings(deck)) {
    if (/Yo el Rey|\bRe[xy]\b/i.test(s.replace(/\{\w+\}/g, ''))) assert.ok(kingOwned(path), `${path} : ${s}`);
  }
  // Le cartouche latin de Greg le dit serviteur du Roi, jamais roi.
  assert.match(deck.brand.latin.greg, /SERVVS/);
  assert.doesNotMatch(deck.brand.latin.greg, /REX|yoElRey/);
  assert.match(t('brand.latin.greg'), /· REGIS · SERVVS$/);
});

test('connexion : Greg se présente en valet, plus de formule royale au-dessus de lui', () => {
  assert.equal(t('auth.kicker'), t('brand.tagline'));
  assert.equal(t('auth.kicker'), 'Valet de musique de Sa Majesté');
  assert.doesNotMatch(t('auth.kicker'), /grâce|\bRe[xy]\b|\broi\b/i);
});

test('t : message { text }, pluriels ({n} ou count) et renvois { ref }', () => {
  assert.equal(t('toast.added', { title: 'X' }), fill(deck.toast.added.text, { title: 'X' }));
  assert.equal(t('header.welcome'), ''); // text null : réplique seule, sans fait
  assert.equal(t('queue.subtitle', { n: 3 }), 'File d’attente · 3 titres');
  assert.equal(t('queue.subtitle', { count: 1 }), 'File d’attente · 1 titre');
  // « one » écrit « 1 » en dur : pour 0, other plutôt qu'un compte faux.
  assert.equal(t('queue.subtitle', { count: '0' }), 'File d’attente · 0 titres');
  assert.equal(t('queue.tab', { n: 0 }), 'File d’attente'); // zero
  assert.equal(t('queue.tab', { n: 1 }), 'File d’attente (1)'); // pas de « one » : other
  assert.match(t('toast.playlistAdded', { n: 5 }), /5 titres$/); // pluriel dans text
  assert.equal(t('loading.search'), t('search.searching'));
  assert.equal(t('loading.search'), 'Recherche…');
});

test('t : jetons d’adresse du Roi par défaut, surchargés par l’appelant', () => {
  assert.equal(SIRE_DEFAULT, 'Sire');
  assert.equal(t('header.account.crownTip'), 'C’est vous, le Roi.');
  assert.equal(t('header.account.crownTip', { theKing: 'Votre Majesté' }), 'C’est vous, Votre Majesté.');
  assert.equal(t('header.account.crownTip', { theKing: undefined }), 'C’est vous, le Roi.');
  assert.equal(t('header.account.aria', { kingName: 'Paul' }), fill(deck.header.account.aria, { kingName: 'Paul' }));
  assert.equal(kingAddress().sire, SIRE_DEFAULT);
  assert.equal(kingAddress('madame').theKing, 'la Reine');
  assert.equal(kingAddress('inconnu').sire, SIRE_DEFAULT);
  assert.ok(!('label' in kingAddress('majeste')));
});

test('t / has : une clé absente rend son chemin', () => {
  assert.equal(t('brand.absente'), 'brand.absente');
  assert.equal(t('search'), 'search'); // section, pas un texte
  assert.equal(t('search.constructor'), 'search.constructor');
  assert.equal(has('brand.absente'), false);
  assert.equal(has('search.placeholder'), true);
  assert.equal(has('loading.search'), true);
});

test('has : vrai seulement pour un texte que t sait rendre', () => {
  // Motif des appelants : has(k) ? t(k) : repli. Une section ou une liste n'est pas un texte.
  for (const k of ['search', 'shortcuts.items', 'header.welcome.quips', '_meta.shape']) {
    assert.equal(has(k), false, k);
  }
  for (const k of ['header.welcome', 'queue.subtitle', 'toast.added', 'shortcuts.items.0.1']) {
    assert.equal(has(k), true, k);
  }
  // Partout dans le deck : has(k) ⇔ t(k) rend autre chose que le chemin.
  // (Les clés contenant un point, dans _meta.migration, ne sont pas adressables.)
  function* nodes(node, path = '') {
    if (path) yield path;
    if (node && typeof node === 'object') {
      for (const [k, v] of Object.entries(node)) if (!k.includes('.')) yield* nodes(v, path ? `${path}.${k}` : k);
    }
  }
  for (const k of nodes(deck)) assert.equal(has(k), t(k) !== k, k);
});

test('renvois { ref } suivis à chaque segment ; _meta.shape n’est pas un renvoi', () => {
  assert.equal(t('loading.search.text'), 'Recherche…');
  assert.equal(has('loading.search.text'), true);
  assert.equal(t('loading.history.text'), t('history.loading'));
  assert.deepEqual(quip('loading.search.quips', 1), quip('search.searching', 1));
  // _meta.shape documente la forme { ref } sous une clé « ref » : objet à plusieurs clés, pas un renvoi.
  assert.equal(t('_meta.shape.plural'), deck._meta.shape.plural);
  assert.equal(t('_meta.shape.ref'), deck._meta.shape.ref);
  // Un cycle de renvois se termine (le deck n'en a pas : on en pose un le temps du test).
  deck.__cycle = { a: { ref: '__cycle.b' }, b: { ref: '__cycle.a.text' } };
  try {
    assert.equal(t('__cycle.a'), '__cycle.a');
    assert.equal(has('__cycle.b'), false);
    assert.equal(quip('__cycle.a', 0), null);
  } finally {
    delete deck.__cycle;
  }
});

test('quip : listes directes, graines quelconques, null sans répliques', () => {
  assert.equal(quip('quips.grumble', 0), fill(deck.quips.grumble[0], { sire: SIRE_DEFAULT }));
  const n = deck.header.welcome.quips.length;
  assert.equal(quip('header.welcome', n + 1), quip('header.welcome', 1));
  for (const seed of [-1, 2.7, Number.NaN, 1e12]) assert.equal(typeof quip('header.welcome', seed), 'string', String(seed));
  assert.equal(quip('loading.search', 1), quip('search.searching', 1));
  assert.equal(quip('search.placeholder', 1), null);
  assert.equal(quip('brand.absente', 1), null);
  assert.equal(quip('shortcuts.items', 0), null); // liste sans chaînes
});
