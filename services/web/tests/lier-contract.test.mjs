// Page /lier et entrée « Appareils liés » (spec 2026-11-25 §5) : balisage, ordre du montage, retour après connexion.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const { tx } = await loadTs('../src/theme/copy.extra.ts');
const page = read('src/app/lier/page.tsx'), menu = read('src/components/Header/AccountMenu.tsx');
const player = read('src/hooks/usePlayer.ts');

test('/lier : client, sans lecteur, jamais d’autorisation automatique', () => {
  assert.match(page, /^'use client';/);
  assert.ok(!page.includes('usePlayerInit'));
  assert.equal(page.match(/api\.deviceDecide\(/g)?.length, 1);
  assert.deepEqual(page.match(/decide\('(approve|deny)'\)/g), ["decide('approve')", "decide('deny')"]);
  for (const m of page.matchAll(/decide\('(approve|deny)'\)/g)) assert.match(page.slice(m.index - 20, m.index), /onClick=\{\(\) => $/);
  assert.match(page, /className="btn-solid"[^>]*onClick=\{\(\) => decide\('approve'\)\}/);
  assert.match(page, /className="btn-ghost"[^>]*onClick=\{\(\) => decide\('deny'\)\}/);
});

test('/lier : « Autoriser » s’arme 1 s après l’appareil, et de nouveau à chaque retour sur la fenêtre', () => {
  assert.match(page, /const ARMEMENT_MS = 1000;/);
  assert.match(page, /setTimeout\([^;]*armedRef\.current = true;[^;]*setArmed\(true\);[^;]*, ARMEMENT_MS\)/);
  assert.match(page, /window\.addEventListener\('focus', /);
  assert.match(page, /document\.addEventListener\('visibilitychange', /);
  assert.match(page, /visibilityState === 'visible'/);
  const approve = page.match(/<button[^>]*onClick=\{\(\) => decide\('approve'\)\}/)?.[0] ?? '';
  assert.match(approve, /aria-disabled=\{busy \|\| !armed\}/, 'inerte, mais focusable (aria-disabled)');
  assert.ok(!/\sdisabled=/.test(approve), 'jamais disabled : le focus clavier reste');
  const body = page.slice(page.indexOf('async function decide('), page.indexOf('async function unlink('));
  assert.match(body, /decision === 'approve' && !armedRef\.current\) return;/, 'le clic est ignoré tant qu’il n’est pas armé');
});

test('/lier consomme le code en attente au montage et nettoie l’URL', () => {      // Review Focus 5
  assert.match(page, /takePendingCode\(browserSession\(\), Date\.now\(\)\)/);
  assert.match(page, /history\.replaceState\(null, '', '\/lier'\)/);
  assert.match(page, /savePendingCode\(browserSession\(\)/);
});

test('/lier lit ?code= sans useSearchParams et prend le code avant les appels /overlay', () => {   // Review Focus 5
  assert.ok(!page.includes('useSearchParams'));
  assert.match(page, /new URLSearchParams\(window\.location\.search\)\.get\('code'\)/);
  assert.equal(page.match(/takePendingCode\(/g)?.length, 1);
  const me = page.indexOf('api.getMe()'), take = page.indexOf('takePendingCode(browserSession(), Date.now())');
  assert.ok(me >= 0 && me < take, 'le code se prend une fois getMe() réussi');
  assert.equal(page.match(/api\.deviceGuilds\(\)/g)?.length, 1); assert.equal(page.match(/api\.deviceTokens\(\)/g)?.length, 1);
  assert.ok(take < page.indexOf('api.deviceGuilds()') && take < page.indexOf('api.deviceTokens()'),
    'et avant /overlay/guilds et /overlay/tokens : un échec de l’un ne fait pas tourner « / » ↔ /lier');
});

test('/lier : tout connecté, sans branche propriétaire, avec l’avertissement sous l’appareil', () => {
  assert.ok(!/is_owner|NOT_OWNER|notAllowed|deviceMe/.test(page));
  const device = page.indexOf("tx('devices.device'"), warning = page.indexOf("tx('devices.warning')");
  assert.ok(device >= 0 && device < warning, 'l’avertissement suit le nom de l’appareil');
});

test('/lier : dialogue de « Délier » au motif de Transport, textes présents', () => {
  assert.match(page, /role="dialog"/);
  const dialog = page.indexOf('role="dialog"');
  const ghost = page.indexOf('btn-ghost', dialog), danger = page.indexOf('btn-danger', dialog);
  assert.ok(ghost >= 0 && danger >= 0, '« Garder » (btn-ghost) et « Délier » (btn-danger) dans le dialogue');
  assert.ok(ghost < danger, '« Garder » avant « Délier »');
  for (const src of [page, menu]) for (const [, k] of src.matchAll(/tx\('(devices\.[\w.]+)'/g)) assert.notEqual(tx(k), k, k);
});

test('menu du compte : « Appareils liés » pour tout connecté, sans appel ni contrôle de propriétaire', () => {
  assert.match(menu, /tx\('devices\.menu'\)/); assert.match(menu, /location\.assign\('\/lier'\)/);
  assert.ok(!/deviceMe|is_owner/.test(menu));
  assert.ok(menu.indexOf('if (!me) return null;') >= 0 && menu.indexOf('if (!me) return null;') < menu.indexOf("tx('devices.menu')"));
});

test('boot renvoie vers /lier quand un code attend', () => {
  const boot = player.slice(player.indexOf('async function boot()'), player.indexOf('export const playerActions'));
  assert.match(boot, /peekPendingCode\(browserSession\(\), Date\.now\(\)\)/);
  assert.match(boot, /location\.replace\('\/lier'\)/);
});

test('feuille de /lier importée', () => {
  assert.match(read('src/app/globals.css'), /@import '\.\.\/components\/Lier\/lier\.css';/);
});
