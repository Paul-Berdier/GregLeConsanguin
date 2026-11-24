// Chansonnier du Roi (spec 2026-11-23 §3) : contrats du balisage, du clavier, des textes et du mouvement.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { animated, assertKeys, path, read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const { EXTRA } = await loadTs('../src/theme/copy.extra.ts');
const LIB = readdirSync(path('src/components/Library')).filter((f) => /\.tsx?$/.test(f)).map((f) => `src/components/Library/${f}`);
const code = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const at = (root, p) => p.split('.').reduce((o, k) => (o == null ? undefined : o[k]), root);

/** Balises `<name …>` d'un source JSX : attributs lus jusqu'au `>` hors des accolades (les `=>` des gestionnaires restent dedans). */
function tags(src, name) {
  const out = [];
  for (let i = src.indexOf(`<${name}`); i >= 0; i = src.indexOf(`<${name}`, i + 1)) {
    if (/[\w-]/.test(src[i + name.length + 1] ?? '')) continue;   // <buttonX, <button-…
    let depth = 0, j = i + name.length + 1;
    for (; j < src.length; j++) {
      const c = src[j];
      if (c === '{') depth++;
      else if (c === '}') depth--;
      else if (c === '>' && depth === 0) break;
    }
    out.push(src.slice(i, j + 1));
  }
  return out;
}

test('la garde des balises lit les attributs jusqu’au bon chevron', () => {
  assert.deepEqual(tags('<button type="button" onClick={() => a > b} aria-label="x">t</button><buttons/>', 'button'),
    ['<button type="button" onClick={() => a > b} aria-label="x">']);
});

test('onglets : trois, chacun relié à son volet (ids, aria-controls, aria-labelledby, aria-selected, tabindex itinérant)', () => {
  const src = read('src/components/Sidebar.tsx');
  assert.match(src, /type Tab = 'queue' \| 'hist' \| 'lib';/);
  assert.match(src, /const TABS: readonly Tab\[\] = \['queue', 'hist', 'lib'\];/);
  const tabs = tags(src, 'button').filter((b) => b.includes('role="tab"'));
  assert.equal(tabs.length, 3);
  for (const id of ['queue', 'hist', 'lib']) {
    const b = tabs.find((x) => x.includes(`id="tab-${id}"`));
    assert.ok(b, `onglet ${id}`);
    for (const attr of [`aria-controls="pane-${id}"`, `aria-selected={tab === '${id}'}`, `tabIndex={tab === '${id}' ? 0 : -1}`, 'type="button"']) {
      assert.ok(b.includes(attr), `tab-${id} : ${attr}`);
    }
    assert.match(src, new RegExp(`id="pane-${id}" role="tabpanel" aria-labelledby="tab-${id}" data-pane="${id}" aria-hidden=\\{tab !== '${id}'\\}`), `pane-${id}`);
    assert.match(src, new RegExp(`className="ptitle" data-pane="${id}" aria-hidden=\\{tab !== '${id}'\\}`), `titre ${id}`);
    assert.match(src, new RegExp(`className="psub[^"]*" data-pane="${id}" aria-hidden=\\{tab !== '${id}'\\}`), `résumé ${id}`);
  }
  assert.match(src, /role="tablist" aria-label=\{tx\('panel\.tabs'\)\} data-tab=\{tab\} onKeyDown=\{onTabsKey\}/);
  assert.match(src, /<LibraryPanel\/>/);
  assert.match(src, /useLibraryInit\(\);/, 'le chansonnier suit le Roi connecté, sans toucher à page.tsx');
  assert.ok(!/LibraryPanel|useLibrary/.test(read('src/app/page.tsx')), 'page.tsx inchangée');
});

test('onglets : ← → en boucle depuis l’onglet visé, Début et Fin aux bouts ; relais 60 ms / 140 ms gardé', () => {
  const src = read('src/components/Sidebar.tsx');
  const keys = src.slice(src.indexOf('const onTabsKey'), src.indexOf('return (', src.indexOf('const onTabsKey')));
  assert.match(keys, /const at = TABS\.indexOf\(target\.current \?\? tab\);/);
  assert.match(keys, /e\.key === 'ArrowRight' \? 1 : e\.key === 'ArrowLeft' \? TABS\.length - 1 : 0/, 'en boucle dans les deux sens');
  assert.match(keys, /TABS\[\(at \+ step\) % TABS\.length\]/);
  assert.match(keys, /e\.key === 'Home' \? TABS\[0\] : e\.key === 'End' \? TABS\[TABS\.length - 1\]/);
  assert.match(keys, /if \(!next\) return;\s*e\.preventDefault\(\);/, 'les autres touches restent à la page');
  assert.match(src, /duration: 60, easing: 'ease-out'/);
  assert.match(src, /duration: 140, easing: EASE\.out/);
  // simulation du cycle : la même arithmétique que onTabsKey
  const TABS = ['queue', 'hist', 'lib'];
  const step = (from, key) => TABS[(TABS.indexOf(from) + (key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
  assert.deepEqual(['queue', 'hist', 'lib'].map((x) => step(x, 'ArrowRight')), ['hist', 'lib', 'queue']);
  assert.deepEqual(['queue', 'hist', 'lib'].map((x) => step(x, 'ArrowLeft')), ['lib', 'queue', 'hist']);
});

test('panel.css : trois colonnes, pilule d’un tiers qui glisse en transform ; rangée propre aux onglets ; library.css importée', () => {
  const css = code('src/components/panel.css');
  assert.match(read('src/components/panel.css'), /^(?:\/\*[^]*?\*\/\s*)?@import '\.\/Library\/library\.css';/, '@import en tête de feuille');
  assert.match(css, /\.tabs \{[^}]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(css, /\.tabs \.pill \{[^}]*width: calc\(\(100% - 6px\) \/ 3\)/);
  assert.match(css, /\.tabs\[data-tab=hist\] \.pill \{ transform: translateX\(100%\); \}/);
  assert.match(css, /\.tabs\[data-tab=lib\] \.pill \{ transform: translateX\(200%\); \}/);
  assert.match(css, /\.panel-head \{[^}]*grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(css, /\.panel-head > \.tabs \{ grid-row: 3; \}/);
  assert.match(css, /@media \(max-width: 359px\) \{ \.tab \{ padding: 0 4px; \} \}/, '320 px : « Chansonnier » entier');
});

test('library.css : transform et opacity seulement, mouvement réduit prévu, pas de flou', () => {
  const css = read('src/components/Library/library.css');
  for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), `anime « ${prop} »`);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /:root\[data-motion=reduced\]/);
  assert.ok(!/\bfilter\s*:|transition:\s*all|transition-property:\s*all/.test(code('src/components/Library/library.css')));
  // les lignes du chansonnier l'emportent sur queue.css quel que soit l'ordre des feuilles
  assert.match(css, /\.lpane \.lrow \.card \{/);
});

test('boutons du chansonnier : un type et un nom accessible chacun ; ceux des lignes hors de la tabulation', () => {
  let n = 0;
  for (const f of LIB) {
    for (const b of tags(read(f), 'button')) {
      n++;
      assert.match(b, /type="(?:button|submit)"/, `${f} : ${b.slice(0, 80)}`);
      assert.match(b, /aria-label=/, `${f} : bouton sans nom : ${b.slice(0, 80)}`);
    }
  }
  assert.ok(n >= 15, `${n} boutons vus`);
  const row = read('src/components/Library/LibraryRow.tsx');
  const rowBtns = tags(row, 'button');
  assert.ok(rowBtns.length === 2 && rowBtns.every((b) => b.startsWith('<button type="button" tabIndex={-1}')), 'ligne : boutons hors tabulation');
  assert.match(row, /tabIndex=\{tabIndex\}/);
  const panel = read('src/components/Library/LibraryPanel.tsx');
  const play = tags(panel, 'button').filter((b) => b.includes('data-act="play"'));
  assert.ok(play.length === 1 && play[0].startsWith('<button type="button" tabIndex={-1}'), '« Tout jouer » d’une carte : hors tabulation');
  // toutes les icônes du chansonnier sont muettes
  for (const svg of tags(read('src/components/Library/glyphs.tsx'), 'svg')) assert.match(svg, /aria-hidden="true"/);
});

test('listes du chansonnier : des .qlist > .row (raccourcis de page muets), un arrêt de Tab, touches décrites', () => {
  for (const f of ['LibraryPanel', 'PlaylistView']) {
    const src = read(`src/components/Library/${f}.tsx`);
    assert.match(src, /useRoving\(listRef, keys, 'key',/, f);
    assert.match(src, /<ol className="qlist [^"]+" ref=\{listRef\}[^>]*aria-describedby=\{keysId\}/, f);
    assert.match(src, /onKeyDown=\{roving\.onKeyDown\} onFocus=\{roving\.onFocus\}/, f);
    assert.match(src, /<p id=\{keysId\} className="sr">/, f);
  }
  assert.match(read('src/components/Library/LibraryPanel.tsx'), /className="row lrow" data-key=\{c\.key\}/);
  assert.match(read('src/components/Library/LibraryRow.tsx'), /className="row trow" data-key=\{trackKey\(track\.url\)\}/);
  const view = read('src/components/Library/PlaylistView.tsx');
  assert.match(view, /if \(act\.kind === 'activate'\) \{ add\(x\); return null; \}/, 'Entrée : dans la file');
  assert.match(view, /if \(act\.kind === 'remove'\) \{ void remove\(x\); return keys\[i \+ 1\] \?\? keys\[i - 1\] \?\? null; \}/, 'Suppr : la voisine prend le focus');
  assert.match(view, /if \(act\.kind !== 'move' \|\| likes\) return undefined;/, 'Alt+↑↓ : pas dans les coups de cœur');
  assert.match(view, /libraryActions\.moveInPlaylist\(id, x, i \+ act\.dir\)/);
  assert.match(view, /if \(ok && n === moves\.current\) speak\(t\('queue\.dnd\.liveMoved'/, 'seul le dernier déplacement est annoncé');
  assert.match(view, /requeue\(itemOf\(x\), sourceOf\(trackKey\(x\.url\)\)\)/, '« + » : comme l’historique, avec Le Sceau');
  assert.match(view, /once\.current\('add', performance\.now\(\)\)/, 'un ajout par 500 ms');
  assert.match(view, /tx\(likes \? 'library\.keysLikes' : 'library\.keys'\)/);
  // durées inconnues (ou toutes sous 30 s) : le nombre de titres seul, jamais « 0 min »
  assert.match(read('src/components/Library/meta.ts'), /return s >= 30 \? `\$\{tx\('library\.count\.tracks', \{ n \}\)\} · \$\{fmtLong\(s\)\}` : tx\('library\.count\.tracks', \{ n \}\);/);
  // vue disparue sans geste (supprimée ailleurs, création refusée) : le focus tombé sur la page revient à la liste
  const panel = read('src/components/Library/LibraryPanel.tsx');
  assert.match(panel, /const lost = !want && !!was && !view && \(!at \|\| at === document\.body\) && !root\.closest\('\[aria-hidden="true"\]'\);/);
  assert.match(panel, /const to = want \?\? \(lost \? was : null\);/);
});

test('suppression d’une playlist : confirmée (dialogue nommé et décrit), le focus sur « Garder »', () => {
  const view = read('src/components/Library/PlaylistView.tsx');
  assert.match(view, /const confirm = usePopover\(\);/);
  assert.match(view, /useEffect\(\(\) => \{ if \(confirm\.open\) noRef\.current\?\.focus\(\); \}, \[confirm\.open\]\);/);
  assert.match(view, /className="pop plaque lconfirm" role="dialog" aria-labelledby=\{titleId\} aria-describedby=\{bodyId\} data-open=\{confirm\.open\}/);
  assert.match(view, /aria-haspopup="dialog" aria-expanded=\{confirm\.open\}/);
  assert.match(view, /<button ref=\{noRef\} type="button" className="btn-ghost"/);
});

test('cœurs : bouton à bascule (aria-pressed) sous le titre en lecture, dans la file et l’historique', () => {
  const like = read('src/components/Library/LikeButton.tsx');
  assert.match(like, /aria-pressed=\{liked\}/);
  assert.match(like, /aria-label=\{tx\('library\.like\.aria', \{ title: song \}\)\}/, 'libellé constant, l’état dit par aria-pressed');
  const now = read('src/components/Stage/NowPlaying.tsx');
  assert.match(now, /<LikeButton track=\{current\}\/>/);
  assert.match(now, /<AddToPlaylist track=\{current\}\/>/);
  assert.match(now, /className="now-acts" data-shown=\{!!current && !!me\}/, 'toujours rendus : la hauteur de la scène ne change pas');
  for (const f of ['Queue/QueueRow', 'History/HistoryRow']) {
    const b = tags(read(`src/components/${f}.tsx`), 'button').find((x) => x.includes('data-act="like"'));
    assert.ok(b, f);
    assert.ok(b.startsWith('<button type="button" tabIndex={-1}'), `${f} : hors tabulation`);
    for (const attr of ['aria-pressed={liked}', "aria-label={tx('library.like.aria', { title: song })}", 'title=']) assert.ok(b.includes(attr), `${f} : ${attr}`);
  }
  assert.match(read('src/components/Queue/QueuePanel.tsx'), /if \(act === 'like'\) \{ const item = byKey\.current\.get\(key\); if \(item\) libraryActions\.toggleLike\(item\); return; \}/);
  assert.match(read('src/components/Queue/QueuePanel.tsx'), /liked=\{liked\.has\(trackKey\(item\.url\)\)\}/);
  const rq = read('src/components/History/useRequeue.ts');
  assert.match(rq, /if \(act === 'like'\) libraryActions\.toggleLike\(it\);/);
  assert.match(rq, /onDoubleClick = \(e: MouseEvent\) => \{\s*if \(\(e\.target as HTMLElement\)\.closest\('\[data-act\]'\)\) return;/, 'double-clic sur le cœur : pas de remise dans la file');
  for (const f of ['HistoryPanel', 'Suggestions']) assert.match(read(`src/components/History/${f}.tsx`), /liked=\{liked\.has\(trackKey\(it\.url\)\)\}/, f);
  for (const css of ['src/components/Queue/queue.css', 'src/components/History/history.css', 'src/components/Stage/now.css']) {
    assert.match(read(css), /\[aria-pressed=true\] svg \{ fill: currentColor; \}/, `${css} : cœur pressé rempli`);
  }
});

test('« Ajouter à une playlist » : dialogue depuis son bouton, flèches entre les choix, nom en ligne', () => {
  const src = read('src/components/Library/AddToPlaylist.tsx');
  assert.match(src, /const pop = usePopover\(\);/);
  assert.match(src, /aria-haspopup="dialog" aria-expanded=\{open\}/);
  assert.match(src, /className="pop plaque lmenu" ref=\{panelRef\} role="dialog" aria-labelledby=\{titleId\} data-open=\{open\}/);
  assert.match(src, /const MOVES = new Set\(\['ArrowDown', 'ArrowUp', 'Home', 'End'\]\);/);
  assert.match(src, /aria-disabled=\{!it\.sub \|\| undefined\}/, 'une playlist qui l’a déjà le dit');
  // la plaque reste dans la fenêtre (téléphone : le bouton finit la ligne du demandeur, elle sortait à droite)
  assert.match(src, /el\.style\.setProperty\('--lmenu-dx', `\$\{Math\.round\(Math\.max\(16 - x, Math\.min\(0, vw - 16 - x - el\.offsetWidth\)\)\)\}px`\);/);
  assert.match(read('src/components/Library/library.css'), /\.ladd \.lmenu \{[^}]*left: var\(--lmenu-dx, 0px\);/);
  assert.match(src, /if \(!track \|\| !open\) return;/, 'un second clic pendant le fondu de fermeture n’ajoute rien');
  assert.match(src, /close\(!!at && at !== btnRef\.current && !!wrapRef\.current\?\.contains\(at\)\);/, 'titre changé : le focus revient au bouton');
  const form = read('src/components/Library/NameForm.tsx');
  assert.match(form, /if \(e\.key === 'Escape'\) \{ e\.preventDefault\(\); e\.stopPropagation\(\); onCancel\(\); \}/, 'Échap ferme le champ, pas le popover');
  assert.match(form, /<label className="sr" htmlFor=\{id\}>/);
});

test('usePlayer.enqueueMany : comme un ajout (un tour, relecture, toast annulable, voix), 100 titres par appel', () => {
  const src = read('src/hooks/usePlayer.ts');
  const i = src.indexOf('async function enqueueMany(');
  const fn = src.slice(i, src.indexOf('\n}\n', i));
  for (const re of [
    /const items = tracks\.filter\(\(x\) => x\?\.url\)\.slice\(0, ADD_MANY_MAX\);/,
    /const ok = await addTurn\(async \(\) => \{\n\s+const before = upcoming\(\)\.player\.queue\.map\(\(x\) => x\.key\);/,
    /const fromHere = here\(\) && _queueOf === gid;/,
    /res = await api\.queueAddMany\(gid, meId, items, label\);/,
    /if \(here\(\)\) await refreshPlaylist\(\{ quiet: true \}\)/,
    /const keys = fromHere && here\(\) \? addedKeys\(before, upcoming\(\)\.player\.queue, meId\) : \[\];/,
    /addedCopy\(\{ playlist: true, added: res\?\.added, requested, truncated: res\?\.truncated \}, label, 'playlist'\)/,
    /tx\('library\.toast\.played\.text', \{ n: c\.vars\.n, name: label \}\)/,
    /run: boundUndo\(gid, guildNow, \(\) => \{ for \(const k of keys\) void removeTrack\(k, \{ silent: true \}\); \}\)/,
    /if \(here\(\)\) await bestEffortVoiceJoin\('add'\);/,
  ]) assert.match(fn, re);
  assert.ok(!fn.includes('engine.view()'), 'la vue à venir, jamais la vue affichée');
  assert.match(src, /enqueue, enqueueMany,/);
  assert.match(read('src/hooks/useLibrary.ts'), /playerActions\.enqueueMany\(tracks\.map\(wireTrack\), label\)/);
});

test('useLibrary : lu à la connexion, vidé à la déconnexion (401 compris), refus dits par le Héraut', () => {
  const src = read('src/hooks/useLibrary.ts');
  assert.match(src, /return useStore\.subscribe\(\(s\) => sync\(s\.me\?\.id \?\? ''\)\);/);
  assert.match(src, /clear\(\);\n\s+if \(id\) void load\(\);/);
  const clear = src.slice(src.indexOf('function clear('), src.indexOf('\n}\n', src.indexOf('function clear(')));
  assert.match(clear, /_loadSeq\+\+;/, 'une lecture en vol ne s’écrit plus');
  assert.match(clear, /engine\.reset\(\);/);
  // une création n'envoie que ce que l'API garde : l'API refuse en entier une liste de plus de 500 titres
  const create = src.slice(src.indexOf('function createPlaylist('), src.indexOf('\n}\n', src.indexOf('function createPlaylist(')));
  assert.match(create, /const tracks = addPlan\(\[\], items\.map\(trackOf\)\.filter\([^)]*\)[^)]*\), lib\.limits\.tracks\)\.added;/);
  const failed = src.slice(src.indexOf('function failed('), src.indexOf('\n}\n', src.indexOf('function failed(')));
  assert.match(failed, /if \(code === 'NOT_AUTHENTICATED'\) return;/, 'la perte de session parle seule');
  assert.match(failed, /if \(n\) say\(n\.key, \{ vars: n\.vars, kind: n\.kind \}\);\s*else sayError\(e\);/);
});

test('textes : chaque clé citée existe (deck, et library.* dans copy.extra.ts) ; ni couronne ni « Rex »', () => {
  const files = [...LIB, 'src/lib/library.ts', 'src/hooks/useLibrary.ts', 'src/hooks/usePlayer.ts', 'src/components/Sidebar.tsx',
    'src/components/Stage/NowPlaying.tsx', 'src/components/Queue/QueueRow.tsx', 'src/components/History/HistoryRow.tsx'];
  assertKeys(files);   // clés du deck (t, quip) et des sections du deck dans EXTRA (tx)
  let n = 0;
  for (const f of files) {
    for (const [, key] of code(f).matchAll(/['"`](library\.[\w.]+)['"`]/g)) {
      n++;
      const node = at(EXTRA, key);
      const ok = typeof node === 'string' || typeof node?.other === 'string' || typeof node?.text === 'string' || typeof node?.text?.other === 'string';
      assert.ok(ok, `${f} : « ${key} » absente de copy.extra.ts`);
    }
  }
  assert.ok(n >= 40, `${n} clés du chansonnier vues`);
  for (const f of LIB) assert.ok(!/crown|couronne|\bRex\b/i.test(read(f)), `${f} : couronne`);
});
