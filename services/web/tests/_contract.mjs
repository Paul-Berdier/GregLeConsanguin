// Aides des tests de contrat de l'étape 3 (pas un fichier de test) : propriétés animées d'une feuille, clés de texte citées.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';

const { EXTRA } = await loadTs('../src/theme/copy.extra.ts');
export const path = (p) => fileURLToPath(new URL(`../${p}`, import.meta.url));
export const read = (p) => readFileSync(path(p), 'utf8');
const deck = JSON.parse(read('src/theme/copy.v2.json'));
const at = (root, p) => p.split('.').reduce((o, k) => (o == null ? undefined : o[k]), root);

/** Propriétés animées : premières valeurs de chaque `transition:` et déclarations des @keyframes. */
export function animated(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const props = [];
  for (const [, value] of clean.matchAll(/(?<![-\w])transition\s*:\s*([^;}]+)/g)) {
    for (const item of value.split(/,(?![^(]*\))/)) props.push(item.trim().split(/\s+/)[0]);
  }
  for (const [, body] of clean.matchAll(/@keyframes\s+[\w-]+\s*\{([\s\S]*?\})\s*\}/g)) {
    for (const [, prop] of body.matchAll(/([\w-]+)\s*:/g)) props.push(prop);
  }
  return props;
}

/** Clés t('…'), quip('…') et tx('…') citées dans `files` : chacune mène à un texte du deck ou de ses compléments. */
export function assertKeys(files) {
  const SECTIONS = Object.keys(deck).filter((k) => !k.startsWith('_'));
  const KEY = new RegExp(`\\b(t|quip|tx)\\(\\s*(['"\`])((?:${SECTIONS.join('|')})\\.[\\w.]+)\\2`, 'g');
  let seen = 0;
  for (const f of files) {
    for (const [, fn, , key] of read(f).matchAll(KEY)) {
      seen++;
      const node = fn === 'tx' ? at(EXTRA, key) : at(deck, key);
      const ok = typeof node === 'string' || typeof node?.other === 'string' || typeof node?.text === 'string'
        || Array.isArray(node?.quips) || Array.isArray(node);
      assert.ok(ok, `${f} : ${fn}('${key}') introuvable`);
    }
  }
  return seen;
}
