// Le panneau, l'historique et le Héraut (étape 3, tâche 7) : mouvement, textes, casting, nettoyage legacy.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { animated, assertKeys, path, read } from './_contract.mjs';

const SHEETS = ['src/components/panel.css', 'src/components/History/history.css', 'src/components/Herald/herald.css'];
const FILES = [
  ...['src/components/History', 'src/components/Herald'].flatMap((d) => readdirSync(path(d)).filter((f) => /\.tsx?$/.test(f)).map((f) => `${d}/${f}`)),
  'src/components/Sidebar.tsx',
];

test('mouvement : transform et opacity seulement, mouvement réduit prévu', () => {
  for (const f of SHEETS) {
    const css = read(f);
    for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), `${f} : anime « ${prop} »`);
    if (animated(css).includes('transform')) assert.match(css, /prefers-reduced-motion:\s*reduce/, f);
  }
});

test('globals.css importe les feuilles du panneau ; les classes legacy ont disparu', () => {
  const css = read('src/app/globals.css');
  for (const f of SHEETS) assert.ok(css.includes(`@import '../${f.replace('src/', '')}';`), f);
  for (const cls of ['.glass', '.glass-subtle', '.btn-accent', '.q-item', '.q-thumb', '.tab-active', '.status-ok', '.status-err', '.loading-spin']) {
    assert.ok(!new RegExp(`\\${cls}\\b`).test(css), `${cls} encore dans globals.css`);
  }
});

test('alias Tailwind legacy supprimés, et plus aucune classe qui s’en sert', () => {
  const cfg = read('tailwind.config.js');
  for (const alias of ['surface', 'accent', 'teal', 'rose', 'txt', 'border']) assert.ok(!new RegExp(`\\b${alias}\\s*:`).test(cfg), `alias ${alias}`);
  const walk = (dir) => readdirSync(path(dir), { withFileTypes: true }).flatMap((e) => (e.isDirectory()
    ? walk(`${dir}/${e.name}`) : /\.tsx?$/.test(e.name) ? [`${dir}/${e.name}`] : []));
  // classes des attributs className (chaînes et gabarits), variantes retirées (hover:, max-[900px]:…)
  const LEGACY = /^(?:(?:bg|text|border|ring)-(?:surface|accent|teal|rose|txt|border)(?:-\S+)?|glass|glass-subtle|q-item|q-thumb|tab-active|btn|btn-accent|status-ok|status-err|loading-spin)$/;
  const classes = (src) => [...src.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)]
    .flatMap((m) => (m[1] ?? m[2]).replace(/\$\{[^}]*\}/g, ' ').split(/\s+/)).filter(Boolean).map((c) => c.split(':').pop());
  for (const f of walk('src')) for (const c of classes(read(f))) assert.ok(!LEGACY.test(c), `${f} : classe legacy « ${c} »`);
});

test('textes du panneau, de l’historique et du Héraut : chaque clé citée existe', () => {
  assert.ok(assertKeys(FILES) >= 15);
});

test('casting : Greg parle avec son portrait de valet ; ni couronne ni « Rex » dans le panneau et le Héraut', () => {
  assert.ok(read('src/components/Herald/Herald.tsx').includes('/gothique/greg-face-96.webp'));
  for (const f of FILES) assert.ok(!/crown|couronne|\bRex\b/i.test(read(f)), `${f} : couronne`);
});

test('historique : « + » ou double-clic, un seul ajout par 500 ms (createDedupe)', () => {
  const src = read('src/components/History/useRequeue.ts');
  assert.match(src, /createDedupe\(\)/);
  assert.equal(src.match(/\badd\(it\)/g)?.length, 2, '« + » et double-clic passent par la garde');
  assert.ok(!/requeue\(it\)/.test(src), 'aucun ajout sans la garde');
});

test('onglets : pendant le fondu de sortie, le dernier choix (clic ou flèche) l’emporte', () => {
  const src = read('src/components/Sidebar.tsx');
  assert.equal(src.match(/\(target\.current \?\? tab\)/g)?.length, 2, 'le clic et les flèches partent de l’onglet visé, pas de l’onglet encore affiché');
  assert.match(src, /if \(next === tab\) \{ target\.current = null; incoming\.current = null; setTab\(next\); return; \}/,
    'revenir à l’onglet affiché pendant son fondu le rend, et efface un changement en attente');
  assert.match(src, /useLayoutEffect\(\(\) => \{\s*target\.current = null;/, 'la cible s’efface quand le volet a changé');
});

test('historique : une réponse dépassée (autre serveur, ou chargement plus récent) ne s’écrit plus', () => {
  const src = read('src/components/History/HistoryPanel.tsx');
  assert.match(src, /useEffect\(\(\) => \{ seq\.current\+\+;[^\n]*setRecent\(null\);[^\n]*setLoading\(false\); \}, \[guildId\]\)/,
    'un changement de serveur périme les chargements en cours');
  const load = src.slice(src.indexOf('const load ='), src.indexOf('const refresh ='));
  assert.match(load, /const id = \+\+seq\.current;/);
  assert.equal(load.match(/setRecent\(/g)?.length, 2);
  assert.equal(load.match(/live\(\)\) setRecent\(/g)?.length, 2, 'chaque liste reçue vérifie qu’elle est encore attendue');
  assert.equal(load.match(/setLoading\(false\)/g)?.length, 1);
  assert.match(load, /if \(live\(\)\) setLoading\(false\)/, 'seul le dernier chargement éteint l’attente');
});
