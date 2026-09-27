// Textes de la scène : chaque clé du deck citée par la scène existe (étape 2).
// Parcourt src/components/Stage/*.tsx, src/lib/stage/*.ts et src/hooks/useStage*.ts : toute chaîne 'section.clé…' d'une section du deck
// doit mener à un texte, un pluriel ou une liste de répliques de copy.v2.json. Les fichiers absents sont ignorés :
// le test grandit avec les tâches.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

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

test('les répliques de la scène ne touchent pas au casting (pas de couronne sur Greg)', () => {
  const texts = ['now.idle', 'loading.boot', 'auth', 'now.order.mine', 'now.order.other', 'confirm.stop']
    .flatMap((k) => at(k)?.quips ?? []);
  for (const q of texts) assert.ok(!/Greg[^.]*\b(roi|couronne|Rex)\b/i.test(q), q);
});
