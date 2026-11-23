// Chansonnier du Roi (spec 2026-11-23 §3) : gestes répétés (Entrée maintenue, double-clic) et focus gardé.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const GUARD = 'onKeyDownCapture={(e) => { if (heldEnter(e)) e.preventDefault(); }}';

test('Entrée maintenue : « Ajouter à une playlist » et tout le volet n’agissent qu’une fois', () => {
  const add = read('src/components/Library/AddToPlaylist.tsx');
  // sur l'enveloppe : le bouton, les playlists, « Nouvelle playlist… » et le champ du nom ; Échap (wrapProps) intact
  assert.ok(add.includes(`<div className="ladd" {...pop.wrapProps} ${GUARD}>`), 'menu du titre en lecture');
  assert.match(add, /import \{ heldEnter \} from '@\/lib\/keys';/);
  const panel = read('src/components/Library/LibraryPanel.tsx');
  // « Tout jouer », « Ajouter le titre en cours », renommer, supprimer, retour, nouvelle playlist… : sous .lpane
  assert.ok(panel.includes(`<div className="lpane" ref={paneRef} ${GUARD}`), 'volet du chansonnier');
  assert.match(panel, /<PlaylistView key=/);
});

test('double-clic sur une carte : la vue ouverte ignore la suite (« Tout jouer », une ligne remise dans la file)', async () => {
  const panel = read('src/components/Library/LibraryPanel.tsx');
  assert.ok(panel.includes(`${GUARD}\n      onClickCapture={swallow} onDoubleClickCapture={swallow}>`), 'en capture, sur le volet qui garde les deux vues');
  assert.match(panel, /if \(!fsSwallowClick\(e\.detail, performance\.now\(\) - switchedAt\.current\)\) return;\s*e\.preventDefault\(\);\s*e\.stopPropagation\(\);/);
  // l'heure du changement de vue est prise au rendu qui l'affiche (aller comme retour)
  const effect = panel.slice(panel.indexOf('useLayoutEffect(() => {\n    const want'), panel.indexOf('}, [view]);'));
  assert.match(effect, /switchedAt\.current = performance\.now\(\);/);
  assert.ok(effect.indexOf('switchedAt.current') < effect.indexOf('if (!root) return;'));
  // la salve d'un double-clic (2e clic, dblclick : detail 2) tout juste après l'ouverture ; jamais un clic du clavier
  const { fsSwallowClick } = await loadTs('../src/lib/stage/fullscreen.ts');
  assert.deepEqual([fsSwallowClick(2, 120), fsSwallowClick(1, 0), fsSwallowClick(0, 0), fsSwallowClick(2, 900)], [true, false, false, false]);
});

test('« Ajouter le titre en cours » : le titre ajouté, il garde le focus (aria-disabled) ; dans les coups de cœur, annoncé', () => {
  const view = read('src/components/Library/PlaylistView.tsx');
  const i = view.indexOf("aria-label={tx('library.addCurrent')}");
  const btn = view.slice(view.lastIndexOf('<button', i), view.indexOf('>', i));
  assert.match(btn, /aria-disabled=\{!canAdd\}/);
  assert.ok(!/\sdisabled=/.test(btn), 'désactivé, il perdait le focus sur <body> (Espace : pause pour tout le salon)');
  assert.match(view, /const canAdd = !!current && !\(curKey && keys\.includes\(curKey\)\);/);
  assert.match(view, /onClick=\{\(\) => \{ if \(canAdd && current\) void libraryActions\.addTo\(id, current\); \}\}/, 'désactivé : le clic ne fait rien');
  const css = read('src/components/Library/library.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(css, /\.lbtn:is\(:disabled, \[aria-disabled=true\]\) \{ opacity: \.4; cursor: default; \}/);
  for (const sel of ['.lbtn:active', '.lbtn:not', '.lbtn.primary:not', '.lbtn.danger:not']) {
    for (const m of css.matchAll(new RegExp(`${sel.replace(/[.:]/g, '\\$&')}[^{]*\\{`, 'g'))) assert.match(m[0], /:not\(:disabled, \[aria-disabled=true\]\)/, m[0]);
  }
  const lib = read('src/hooks/useLibrary.ts');
  const add = lib.slice(lib.indexOf('function addTo('), lib.indexOf('\n}\n', lib.indexOf('function addTo(')));
  assert.match(add, /if \(refused\(lib, op\)\) return Promise\.resolve\(false\);[^\n]*\n\s*const done = engine\.dispatch\(op\);/);
  assert.match(add, /const toast = say\('library\.toast\.liked', \{ vars: \{ title: songOf\(tr\) \}, kind: 'ok' \}\);/);
  assert.match(add, /void done\.then\(\(ok\) => \{ if \(!ok\) herald\.retract\(toast\); \}\);/, 'refusé par l’API : l’annonce part, Ctrl+Z n’y est pas');
});

test('focus gardé : « Réessayer » reste pendant la relecture, puis la liste ; un nouvel échec est dit', () => {
  const panel = read('src/components/Library/LibraryPanel.tsx');
  const off = panel.slice(panel.indexOf('if (!lib) {'), panel.indexOf('\n  }\n', panel.indexOf('if (!lib) {')));
  // une seule région annoncée, de l'ouverture à l'échec (avant : l'échec hors de toute région)
  assert.match(off, /<p role="status">\{status === 'off' \? '' : tx\(failed \? 'library\.failed' : 'library\.loading'\)\}<\/p>/);
  assert.equal((off.match(/role="status"/g) || []).length, 1);
  assert.match(off, /\{status !== 'off' && \(failed \|\| retried\) && \(\s*<button type="button" className="lbtn" aria-disabled=\{!failed\}/, 'gardé (désactivé) pendant la relecture');
  assert.match(panel, /if \(status !== 'error'\) return;\s*\/\/[^\n]*\n\s*setRetried\(true\);\s*void libraryActions\.load\(\);/);
  // lu : le focus (tombé avec le bouton) va à la ligne active ; jamais volé, jamais dans un volet caché
  assert.match(panel, /if \(!lib \|\| !root \|\| \(at && at !== document\.body\) \|\| root\.closest\('\[aria-hidden="true"\]'\)\) return;\s*root\.querySelector<HTMLElement>\('\.lcards > \.row\[tabindex="0"\], \.lback'\)\?\.focus\(\);/);
});

test('création refusée par l’API (indisponible) : le nom tapé revient dans son champ rouvert', () => {
  const panel = read('src/components/Library/LibraryPanel.tsx');
  const submit = panel.slice(panel.indexOf('const submit = (raw: string): boolean => {'), panel.indexOf('const cancel = '));
  assert.match(submit, /void made\.done\.then\(\(ok\) => \{/);
  // ni pendant qu'un autre nom s'écrit, ni vue partie, ni volet caché, ni focus parti hors du volet
  assert.match(submit, /if \(ok \|\| formRef\.current \|\| !list \|\| !root \|\| root\.closest\('\[aria-hidden="true"\]'\)\s*\|\| \(at && at !== document\.body && !root\.contains\(at\)\)\) return;\s*setDraft\(raw\);\s*setForm\(kind\);/);
  assert.match(panel, /<NameForm initial=\{draft \?\? \(form === 'queue' \? tx\('library\.queueName', \{ date: today \}\) : ''\)\}/);
  assert.match(panel, /const cancel = \(\) => \{ backTo\.current = form; setForm\(null\); setDraft\(null\); \};/, 'annulé : le nom proposé la fois suivante');
  // NameForm reprend `initial` à chaque ouverture (démonté fermé), le champ prend le focus et sélectionne le nom
  const form = read('src/components/Library/NameForm.tsx');
  assert.match(form, /const \[value, setValue\] = useState\(initial\);/);
  assert.match(form, /useLayoutEffect\(\(\) => \{ ref\.current\?\.focus\(\); ref\.current\?\.select\(\); \}, \[\]\);/);
});

test('focus gardé : Suppr sur la dernière ligne d’une playlist l’envoie au retour', () => {
  const view = read('src/components/Library/PlaylistView.tsx');
  assert.match(view, /emptied\.current = act\.kind === 'remove' && keys\.length === 1;/);
  assert.match(view, /if \(was && !tracks\.length && \(!at \|\| at === document\.body \|\| at\.getAttribute\('role'\) === 'tab'\)\) backRef\.current\?\.focus\(\);/);
  assert.match(view, /\}, \[tracks\.length\]\);/);
  // après useRoving (son propre secours, vers l'onglet, passe d'abord)
  assert.ok(view.indexOf('const roving = useRoving(') < view.indexOf('if (was && !tracks.length'));
  assert.match(view, /<button ref=\{backRef\} type="button" className="lback"/);
});

test('« Retirer » doublé : la ligne remontée sous le pointeur n’est ni retirée ni remise dans la file', () => {
  const view = read('src/components/Library/PlaylistView.tsx');
  assert.match(view, /const settleRef = useRef\(createSettle\(\)\);/);
  assert.match(view, /list\?\.classList\.add\('settling'\);/, 'la puce sans pointeur pendant l’accalmie (.qlist.settling, queue.css)');
  assert.match(view, /if \(!x \|\| settling\(\)\) return;/, 'clics ignorés');
  assert.match(view, /else if \(act === 'del'\) \{ settle\(\); void remove\(x\); \}/);
  assert.match(view, /if \(settling\(\) \|\| \(e\.target as HTMLElement\)\.closest\('\[data-act\]'\)\) return;/, 'double-clic ignoré');
  assert.match(view, /<ol className="qlist lrows"/, 'la règle .qlist.settling de queue.css s’y applique');
  assert.match(read('src/components/Queue/queue.css'), /\.qlist\.settling \.row \.acts \{ opacity: 0 !important; pointer-events: none !important;/);
});
