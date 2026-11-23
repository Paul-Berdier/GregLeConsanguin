// Choix du serveur (spec 2026-11-23 §1) : textes (EXTRA.guildFilter), motif combobox du popover, feuille de l'en-tête.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read, animated } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const { EXTRA, tx } = await loadTs('../src/theme/copy.extra.ts');
const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const picker = read('src/components/Header/GuildPicker.tsx');
const css = strip(read('src/components/Header/header.css'));

test('textes : chaque tx(\'guildFilter.…\') du popover mène à un texte d’EXTRA', () => {
  const keys = [...picker.matchAll(/\btx\(\s*'(guildFilter\.[\w.]+)'/g)].map((m) => m[1]);
  assert.ok(keys.length >= 7, `clés vues : ${keys.join(', ')}`);
  const at = (p) => p.split('.').reduce((o, k) => (o == null ? undefined : o[k]), EXTRA);
  for (const k of keys) {
    const node = at(k);
    assert.ok(typeof node === 'string' || typeof node?.other === 'string', `${k} introuvable`);
  }
});

test('textes : présence de Greg, intertitres, état vide et décompte (typographie du deck)', () => {
  assert.equal(tx('guildFilter.present'), 'Greg présent');
  assert.equal(tx('guildFilter.absent'), 'Greg absent');
  assert.equal(tx('guildFilter.group.present'), 'Greg présent');
  assert.equal(tx('guildFilter.group.absent'), 'Sans Greg');
  assert.equal(tx('guildFilter.empty', { q: 'gueux' }), 'Aucun serveur ne correspond à «\u00a0gueux\u00a0».');
  assert.equal(tx('guildFilter.count', { n: 1 }), '1 serveur trouvé');
  assert.equal(tx('guildFilter.count', { n: 214 }), '214 serveurs trouvés');
  assert.notEqual(tx('guildFilter.label'), 'guildFilter.label');
  assert.match(tx('guildFilter.placeholder'), /…$/);
  // plus de libellé écrit en dur dans le composant
  assert.ok(!/'Greg (présent|absent)'/.test(picker));
});

test('champ à partir de 8 serveurs (lib/guilds), en tête du popover, hors du listbox', () => {
  assert.match(picker, /import \{[^}]*\bfilterGuilds\b[^}]*\} from '@\/lib\/guilds'/);
  assert.match(picker, /const withField = searchable\(guilds\.length\);/);
  const field = picker.indexOf('className="guild-find"'), list = picker.indexOf('role="listbox"');
  assert.ok(field > 0 && list > field, 'le champ précède la liste, en dehors d’elle');
  // page.tsx trouve le champ des titres par `.top .field input` : le champ des serveurs n'en prend pas la classe
  assert.ok(!/className="[^"]*\bfield\b/.test(picker));
});

test('combobox : focus gardé dans le champ, option active par aria-activedescendant, options identifiées', () => {
  for (const re of [/role="combobox"/, /aria-autocomplete="list"/, /aria-controls=\{listId\}/, /aria-expanded=\{open\}/,
    /id=\{optId\(g\.id\)\} role="option"/, /onMouseDown=\{\(e\) => e\.preventDefault\(\)\}/, /role="status"/]) {
    assert.match(picker, re);
  }
  // l'option active est désignée depuis le champ ET depuis la liste (moins de 8 serveurs : focus sur la liste)
  assert.equal(picker.match(/aria-activedescendant=\{activeOpt\}/g)?.length, 2);
  assert.equal(picker.match(/onKeyDown=\{onKey\}/g)?.length, 2, 'même modèle clavier dans le champ et sur la liste');
  assert.match(picker, /role="listbox"[^>]*tabIndex=\{-1\}/, 'liste focalisable par script, hors de l’ordre de tabulation');
  // plus de focus DOM promené d'une option à l'autre
  assert.ok(!/<button[^>]*role="option"/.test(picker));
  assert.ok(!picker.includes("querySelectorAll<HTMLButtonElement>('button[role=option]')"));
});

test('clavier : Échap vide le champ sans fermer ; vide, il remonte à usePopover qui ferme et rend le focus', () => {
  assert.match(picker, /guildKey\(e, \{ field: inField, query \}\)/);
  assert.match(picker, /if \(act === 'clear'\) \{\s*e\.stopPropagation\(\);/);
  assert.match(picker, /if \(e\.key === 'Escape' && open && !e\.defaultPrevented\) \{ e\.preventDefault\(\); e\.stopPropagation\(\); close\(true\); \}/);
  // composition (IME) : ni choix ni déplacement, et l'Échap qui l'annule ne remonte pas jusqu'à usePopover
  assert.match(picker, /if \(imeKey\(e\.nativeEvent\)\) \{ e\.stopPropagation\(\); return; \}/);
});

test('usePopover reste exporté pour le menu du compte', () => {
  assert.match(picker, /export function usePopover\(\)/);
  assert.match(read('src/components/Header/AccountMenu.tsx'), /import \{ usePopover \} from '\.\/GuildPicker';/);
});

test('icônes de la liste chargées à la demande ; intertitres groupés (role=group)', () => {
  assert.match(picker, /loading=\{lazy \? 'lazy' : undefined\}/);
  assert.match(picker, /<GuildIcon guild=\{g\} lazy\/>/);
  assert.match(picker, /role="group" aria-labelledby=\{headId\(key\)\}/);
  assert.match(picker, /className="guild-group" id=\{headId\(key\)\} role="presentation"/);
});

test('feuille : champ fixe, la liste défile seule ; `.top .pop` inchangé ; aucune transition ajoutée', () => {
  assert.match(css, /\.top \.pop\s*\{[^}]*max-height:\s*calc\(100dvh[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;?\s*\}/);
  assert.match(css, /\.top \.guild-pop\[data-open=true\]\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*overflow-y:\s*hidden;/);
  assert.match(css, /\.guild-find\s*\{[^}]*flex:\s*none;/);
  assert.match(css, /\.guild-list\s*\{[^}]*position:\s*relative;[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;/);
  assert.match(css, /@media \(pointer: coarse\)\s*\{\s*\.guild-find input\s*\{\s*font-size:\s*16px;/);
  const rules = [...css.matchAll(/[^{}]*\.guild-[\w-]+[^{}]*\{[^}]*\}/g)].map((m) => m[0]).join('\n');
  assert.ok(rules.includes('.guild-opt[data-active=true]'));
  assert.deepEqual(animated(rules), []);
});
