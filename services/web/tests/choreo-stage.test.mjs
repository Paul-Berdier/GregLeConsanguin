// La scène de l'étape 4 : Couronnement, légendes, reflet, Révérence, posters, pierre différée.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';
const code = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const { createQueueEngine, viewOf } = await loadTs('../src/lib/queue/optimistic.ts');
const { NEXT, createOrders, crownMode } = await loadTs('../src/lib/stage/coronation.ts');

test('Couronnement : décidé au changement du store, vol à l’image suivante, un seul fantôme', () => {
  const src = code('src/components/Stage/coronation.ts');
  for (const re of [/useStore\.subscribe\(/, /kingOrders\.take\(/, /crownMode\(\{/, /watchReducedMotion\(/,
    /requestAnimationFrame\(\(\) => \{[\s\S]*?animate\(flightFrames\(/]) assert.match(src, re);
  assert.equal((src.match(/createElement\('div'\)/g) || []).length, 1, 'un fantôme réutilisé');
  assert.ok(!/crown-|king-seal|greg-face/.test(src), 'la pochette du titre, rien du Roi ni de Greg');
  assert.match(src, /decodedPosters\.get\(/, 'le poster déjà décodé, sinon la pochette');
  assert.match(read('src/components/Stage/Portal.tsx'), /decodedPosters\.set\(nextId, im\.src\)/);
});

test('légendes croisées (Swap) pour le titre et le demandeur, reflet d’or', () => {
  const now = read('src/components/Stage/NowPlaying.tsx');
  assert.equal((now.match(/<Swap /g) || []).length, 2);
  assert.match(now, /runGlint\(/);
  const css = code('src/components/Stage/now.css');
  assert.match(css, /\.title-slot > \.line, \.meta-slot > \.line\s*\{[^}]*grid-area:\s*1 \/ 1/);
  assert.match(css, /\.glint-text\s*\{[^}]*mask:/);
});

test('Révérence : la vidéo s’incline à .97 (--spring-settle) ; mouvement réduit : non', () => {
  const css = code('src/components/Stage/portal.css');
  assert.match(css, /\.stage\[data-paused=true\] \.video\s*\{\s*transform:\s*scale\(\.97\);\s*\}/);
  assert.match(css, /\.video\s*\{[^}]*transition:\s*transform var\(--spring-settle-dur\) var\(--spring-settle\)/);
  assert.match(css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)')), /\.stage\[data-paused=true\] \.video\s*\{[^}]*transform:\s*none/);
});

test('posters : le nouveau attend l’atterrissage, l’ancien part en scale(1.03) ; le fantôme est fixe', () => {
  assert.match(read('src/components/Stage/Portal.tsx'), /data-held=\{held \|\| undefined\}/);
  const css = code('src/components/Stage/portal.css');
  assert.match(css, /\.video \.poster\[data-leaving\]\s*\{[^}]*scale\(1\.03\)/);
  assert.match(css, /\.video \.poster\[data-held\]\s*\{\s*opacity:\s*0;\s*\}/);
  assert.match(code('src/components/Stage/stage.css'), /\.ghost\s*\{[^}]*position:\s*fixed[^}]*transform-origin:\s*0 0/);
});

test('ordres notés, Héraut après l’atterrissage, pierre au premier temps mort, nuit en 240 ms', () => {
  assert.match(read('src/components/Stage/Transport.tsx'), /kingOrders\.mark\(NEXT, e\.detail === 0 \? 'key' : 'pointer'/);
  assert.match(read('src/hooks/usePlayer.ts'), /setTimeout\(\(\) => say\('toast\.playNow'[\s\S]*?\), wait\)/);
  const rose = read('src/components/Stage/Rose.tsx');
  for (const re of [/const start = \(\) => \{ if \(client\.current === c\) c\.start\(\); \};/, /requestIdleCallback/, /NIGHT_ROSE_FADE_MS/, /c\.hold\(BUSY_MS\)/]) {
    assert.match(rose, re);
  }
});

// Relecture de la tâche 3 : bruit des annonces, rosace d'un titre sans vidéo, légende qui part, garde-fous.
const track = (key) => ({ key, url: `https://youtu.be/${key}`, title: key, duration: 200, addedBy: null });
const snap = (cur, queue) => ({
  player: { current: track(cur), queue: queue.map(track), paused: false, repeat: false, position: 0, duration: 200 },
  tickBase: { pos: 0, at: 0, dur: 200 },
});

test('refus de « jouer maintenant » : dans onRefused, la vue à venir est déjà le retour ; noté, il est rapide et muet', async () => {
  const orders = createOrders(), shown = [];
  let engine = null;
  engine = createQueueEngine({
    initial: snap('A', ['B', 'C']), now: () => 0,
    send: () => Promise.reject(Object.assign(new Error('refus'), { payload: { error: 'PRIORITY_FORBIDDEN' } })),
    onView: (v) => shown.push(v.player.current?.key),
    // le corps d'onRefused de usePlayer.ts (upcoming() = viewOf(engine.latest(), engine.pending()))
    onRefused: () => {
      const back = viewOf(engine.latest(), engine.pending()).player.current?.key;
      if (back && back !== engine.view().player.current?.key) orders.mark(back, 'key', 10);
    },
  });
  assert.equal(await engine.dispatch({ kind: 'playAt', key: 'B', fromKey: 'A' }), false);
  assert.deepEqual(shown, ['B', 'A'], 'la scène revient au titre qui n’a jamais cessé de jouer');
  const o = orders.take('A', 'C', 20);
  assert.ok(o && o.target !== NEXT, 'un ordre nommé : le chef de cérémonie ne l’annonce pas (le refus a déjà parlé)');
  assert.equal(crownMode({ via: o.via, sinceLast: 5000, reduced: false, canFly: true, fromNight: false }), 'quick', 'jamais un vol');
  const src = read('src/hooks/usePlayer.ts');
  const refused = src.slice(src.indexOf('onRefused:'), src.indexOf('\n});', src.indexOf('onRefused:')));
  assert.match(refused, /const back = upcoming\(\)\.player\.current\?\.key;/);
  assert.match(refused, /if \(back && back !== useStore\.getState\(\)\.player\.current\?\.key\) kingOrders\.mark\(back, 'key', performance\.now\(\)\);/);
});

test('chef de cérémonie : muet au premier état reçu, mouvement réduit en direct coupe le vol, débranché il se pose', () => {
  const src = code('src/components/Stage/coronation.ts');
  assert.match(src, /let unloaded: unknown = useStore\.getState\(\)\.player;/, 'la vue d’avant le premier état reçu');
  assert.match(src, /const boot = prev\.player === unloaded;/);
  assert.match(src, /if \(!quiet && \(!order \|\| order\.target === NEXT\)\) speak\(/, 'le chargement n’est pas un changement de titre');
  assert.match(src, /watchReducedMotion\(\(r\) => \{ if \(r\) abort\(\); \}\)/, 'vol coupé, poster retenu relâché');
  assert.match(src, /return \(\) => \{[^}]*unsub\(\); unwatch\(\); abort\(\);\s*\};/, 'débranché en plein vol : la cérémonie se pose');
});

test('Swap : la ligne qui part garde son dernier contenu rendu et part de l’opacité affichée', () => {
  const src = code('src/components/Stage/Swap.tsx');
  assert.match(src, /useLayoutEffect\(\(\) => \{ rendered\.current = children; \}\);/, 'contenu du dernier rendu validé');
  assert.match(src, /l\.key === shownK && !l\.leaving \? \{ \.\.\.l, item: \{ k: l\.key, node: rendered\.current \} \} : l/);
  assert.match(src, /const from = running\.length \? Number\(getComputedStyle\(el\)\.opacity\) : 1;/, 'sortie sans éclair');
});

test('rosace : la lune en 240 ms la nuit seulement ; un titre sans vidéo suit son Couronnement', () => {
  const rose = code('src/components/Stage/Rose.tsx');
  assert.doesNotMatch(rose, /const plan = videoId \?/, 'un titre SoundCloud a aussi son plan');
  assert.match(rose, /const plan = crownRef\.current\?\.plan \?\? null;/);
  assert.match(rose, /const fade = plan \? plan\.roseFade : was \? NIGHT_ROSE_FADE_MS : undefined;/);
});

test('posters décodés : l’image elle-même est gardée avec son url, même borne', () => {
  const portal = code('src/components/Stage/Portal.tsx');
  assert.match(portal, /decodedImages\.set\(nextId, im\);/);
  assert.match(portal, /decodedPosters\.delete\(old\); decodedImages\.delete\(old\);/);
});
