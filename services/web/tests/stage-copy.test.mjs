// Textes de la scène : chaque clé du deck citée par la scène existe (étape 2).
// Parcourt src/components/Stage/*.tsx, src/lib/stage/*.ts et src/hooks/useStage*.ts : toute chaîne 'section.clé…' d'une section du deck
// doit mener à un texte, un pluriel ou une liste de répliques de copy.v2.json. Les fichiers absents sont ignorés :
// le test grandit avec les tâches. Les répliques citées (quip(…), clés à `quips`, demandeur) ne couronnent jamais Greg.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';
const { requesterKeys } = await loadTs('../src/lib/stage/scene.ts');

const root = (p) => fileURLToPath(new URL(`../${p}`, import.meta.url));
const deck = JSON.parse(readFileSync(root('src/theme/copy.v2.json'), 'utf8'));
const SECTIONS = Object.keys(deck).filter((k) => !k.startsWith('_'));
// Guillemets simples, doubles (attribut JSX) ou gabarit sans ${…} : la clé est le 2e groupe.
const KEY = new RegExp(`(['"\`])((?:${SECTIONS.join('|')})\\.[\\w.]+)\\1`, 'g');
const keysIn = (src) => [...src.matchAll(KEY)].map((m) => m[2]);

const at = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);
const usable = (node) => typeof node === 'string'
  || (node && typeof node === 'object' && ('text' in node || typeof node.other === 'string' || Array.isArray(node.quips)));

function sources() {
  const out = [];
  for (const [dir, only] of [['src/components/Stage', /\.tsx?$/], ['src/lib/stage', /\.ts$/], ['src/hooks', /^useStage\w*\.ts$/]]) {
    if (!existsSync(root(dir))) continue;
    for (const f of readdirSync(root(dir))) if (only.test(f)) out.push(`${dir}/${f}`);
  }
  return out;
}

test('la garde voit les clés quel que soit le guillemet', () => {
  assert.deepEqual(keysIn(`t('now.kicker') <X k="now.state.paused"/> t(\`now.idle\`) t('now.kicker") t(\`now.\${x}\`)`),
    ['now.kicker', 'now.state.paused', 'now.idle']);
});

test('chaque clé du deck citée par la scène existe et donne un texte', () => {
  let seen = 0;
  for (const f of sources()) {
    for (const key of keysIn(readFileSync(root(f), 'utf8'))) {
      seen++;
      assert.ok(usable(at(key)), `${f} : clé « ${key} » absente ou vide`);
    }
  }
  assert.ok(seen > 0, 'aucune clé trouvée : la garde ne vérifie rien');
});

// Clé littérale passée à quip(…) : seule façon de voir une section entière (« auth »), que KEY ne voit pas.
const QUIP = /\bquip\(\s*(['"`])([\w.]+)\1/g;
const quipKeysIn = (src) => [...src.matchAll(QUIP)].map((m) => m[2]);
// quip() accepte une liste ou un nœud qui porte `quips` (theme/copy.ts).
const pool = (key) => { const n = at(key); return Array.isArray(n) ? n : Array.isArray(n?.quips) ? n.quips : null; };

test('la garde voit les répliques citées par quip(…), même d\'une section entière', () => {
  assert.deepEqual(quipKeysIn(`quip('auth', s) quip("now.idle", s) quip(\`loading.boot\`, s) quip(keys.quips, s) quip('x", s)`),
    ['auth', 'now.idle', 'loading.boot']);
});

test('les répliques de la scène ne touchent pas au casting (pas de couronne sur Greg)', () => {
  const FLOOR = ['now.idle', 'loading.boot', 'auth', 'now.order.mine', 'now.order.other', 'confirm.stop'];   // citées à la tâche 4
  const called = sources().flatMap((f) => quipKeysIn(readFileSync(root(f), 'utf8')));
  for (const k of called) assert.ok(pool(k)?.length, `quip('${k}') : aucune réplique dans le deck`);
  const cited = sources().flatMap((f) => keysIn(readFileSync(root(f), 'utf8')));
  const byRequester = ['mine', 'other'].map((kind) => requesterKeys({ kind, name: 'Arthur' }).quips);
  const keys = [...new Set([...FLOOR, ...called, ...cited, ...byRequester])].filter((k) => pool(k));
  for (const k of FLOOR) assert.ok(keys.includes(k), `« ${k} » n'a plus de répliques`);
  for (const k of keys) for (const q of pool(k)) assert.ok(!/Greg[^.]*\b(roi|couronne|Rex)\b/i.test(q), `${k} : ${q}`);
});
