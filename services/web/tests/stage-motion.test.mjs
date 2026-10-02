// La scène après la revue (lot C) : portail et lumière en FLIP, nuit remontée par état, reflet annulé,
// densité de pixels suivie, lecteur YouTube créé quand un titre peut jouer et API rechargée après un échec.
// La logique pure est testée ici ; le reste lit le texte source (garde-fous, comme stage-contract.test.mjs).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';

const code = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const layout = await loadTs('../src/lib/stage/layout.ts');
const FB = await loadTs('../src/components/Stage/flipBox.ts');

// ─── C12 : jour → nuit quand R change, le portail et la lumière suivent la rose ─────────────────
test('jour → nuit à 1280 × 720 (R 280 → 244) : portail et lumière ramenés sur leur boîte du jour pendant le fondu', () => {
  const input = { colW: 784, colH: 593, belowH: 136, viewportW: 1280 };
  const day = layout.solveStageLayout(input), night = layout.fitNight(input, 188.04);
  assert.ok(day.R - night.R > 30, `précondition : la rose rapetisse (${day.R} → ${night.R})`);
  // boîtes dans le repère de la rose (centre et haut de la scène), posées comme portal.css et stage.css
  const portal = (l) => ({ x: 0, y: l.crown, w: l.vw + 2 * l.f, h: (l.vw * 9) / 16 + 2 * l.f });
  const pool = (l) => ({ x: 0, y: l.crown - 0.2 * l.R, w: 3.4 * l.R, h: 2.6 * l.R });
  for (const box of [portal, pool]) {
    const from = box(day), to = box(night), f = FB.flipBox(from, to);
    assert.ok(from.w - to.w > 40, 'la boîte rapetisse');
    // origine au centre : le centre de la boîte de nuit revient sur celui du jour, sa taille aussi
    assert.ok(Math.abs(to.x + f.x - from.x) < 1e-9, 'centre horizontal');
    assert.ok(Math.abs(to.y + to.h / 2 + f.y - (from.y + from.h / 2)) < 1e-9, 'centre vertical');
    assert.ok(Math.abs(to.w * f.sx - from.w) < 1e-9 && Math.abs(to.h * f.sy - from.h) < 1e-9, 'taille');
  }
  const k = FB.flipFrames(FB.flipBox(portal(day), portal(night)));
  // translate et scale à part : un transform animé remplacerait la transition CSS du portail (transform → scale(.97))
  assert.ok(k.every((f) => !('transform' in f)), 'pas de transform');
  assert.match(k[0].translate, /^-?[\d.]+px -?[\d.]+px$/);
  assert.match(k[0].scale, /^[\d.]+ [\d.]+$/);
  assert.deepEqual(k[1], { translate: '0px 0px', scale: '1' });
});

test('Stage.tsx : le FLIP de R passe aussi au portail et à la lumière quand la nuit tombe', () => {
  const stage = code('src/components/Stage/Stage.tsx');
  assert.match(stage, /import \{[^}]*\bflipBox\b[^}]*\} from '\.\/flipBox'/);
  assert.match(stage, /'\.portal'/);
  assert.match(stage, /'\.lightpool'/);
  assert.match(stage, /\.animate\(flipFrames\(flipBox\(/);
});

// ─── C26 : chaque nuit monte à neuf, son entrée rejoue ; l'attente de la rose seulement après le jour ───
test('nuit : un état par montage (chargement → rien en lecture rejoue night-in), +320 ms seulement après le jour', () => {
  const stage = code('src/components/Stage/Stage.tsx');
  assert.match(stage, /<NightState key=\{scene\} kind=\{scene\} afterDay=\{[^}]+\}\/>/);
  const night = code('src/components/Stage/NightState.tsx');
  assert.equal((night.match(/<div className="night" data-kind="\w+"[^>]*data-after=\{after\}/g) || []).length, 3, 'les trois nuits');
  const css = code('src/components/Stage/night.css');
  assert.match(css, /\.night\[data-after=day\] \.vl-inner\s*\{\s*animation-delay:\s*320ms;\s*\}/);
  assert.doesNotMatch(css, /\.night\[data-kind=empty\] \.vl-inner\s*\{[^}]*animation-delay/, 'pas d’attente au sortir du chargement');
});

// ─── C25 : le reflet de l'ancien titre part avec lui ────────────────────────────────────────────
test('reflet d’or : runGlint rend son annulation, NowPlaying l’appelle quand le titre change', () => {
  const glint = code('src/components/Stage/glint.ts');
  assert.match(glint, /export function runGlint\(slot: HTMLElement\): \(\) => void/);
  assert.match(glint, /return \(\) => \{[^}]*\.cancel\(\)[^}]*g\.remove\(\);?\s*\};/, 'annulé : animations coupées, reflet retiré');
  const now = code('src/components/Stage/NowPlaying.tsx');
  assert.match(now, /stopGlint\.current = runGlint\(titleRef\.current\)/);
  assert.match(now, /useEffect\(\(\) => \(\) => \{ stopGlint\.current\?\.\(\); stopGlint\.current = null; \}, \[key\]\);/);
});

// ─── C18 : la rosace repeinte quand la densité de pixels change sans que R change ───────────────
test('Rose.tsx : un changement de densité seul (autre écran, zoom) repeint à la même taille', () => {
  const rose = code('src/components/Stage/Rose.tsx');
  assert.match(rose, /import \{[^}]*\bwatchDpr\b[^}]*\} from '@\/lib\/rose\/client'/);
  assert.match(rose, /useEffect\(\(\) => \{\s*if \(!R\) return;\s*client\.current\?\.resize\(R\);\s*return watchDpr\(\(\) => client\.current\?\.resize\(R\)\);\s*\}, \[R\]\);/);
});

// ─── C27 / C19 : lecteur YouTube créé quand un titre peut jouer, API rechargée après un échec ────
test('lecteur YouTube : rien avant un titre (déconnecté, rien en lecture), puis le même lecteur pour toute la session', () => {
  const hook = code('src/hooks/useYouTubePlayer.ts');
  assert.match(hook, /export function useYouTubePlayer\(wrapRef: RefObject<HTMLDivElement>, handlers: YTHandlers, enabled: boolean\): YTPlayer \| null/);
  assert.match(hook, /if \(enabled && !wanted\) setWanted\(true\);/, 'collant : jamais détruit entre deux titres');
  assert.match(hook, /if \(!wanted \|\| !wrap\) return;/);
  assert.match(hook, /\}, \[wrapRef, wanted\]\);/);
  const portal = code('src/components/Stage/Portal.tsx');
  assert.match(portal, /useYouTubePlayer\(wrapRef, \{[\s\S]*?\}, !!\(videoId \|\| nextId\)\);/);
});

test('API YouTube en échec (réseau, portail captif) : nouvel essai, de plus en plus rare, et au retour du réseau', () => {
  const hook = code('src/hooks/useYouTubePlayer.ts');
  assert.match(hook, /retry = setTimeout\(load, Math\.min\(API_RETRY_MAX_MS, API_RETRY_MS \* 2 \*\* tries\+\+\)\);/);
  assert.match(hook, /window\.addEventListener\('online', online\);/);
  assert.match(hook, /window\.removeEventListener\('online', online\);/);
  assert.match(hook, /clearTimeout\(retry\);/);
  // le lecteur créé après coup : la note « vidéo indisponible » part
  assert.match(code('src/components/Stage/Portal.tsx'), /useEffect\(\(\) => \{ if \(player\) setNoApi\(false\); \}, \[player\]\);/);
});

// ─── Synchro son/vidéo (spec §6.2) : régulateur, démarrage gardé, plus de sauts à seuils fixes ───
test('Portal : régulateur à 4 Hz, démarrage gardé par play_id, attente, plus d’ancien correcteur', () => {
  const portal = code('src/components/Stage/Portal.tsx');
  assert.match(portal, /const id = setInterval\(tick, CTL_TICK_MS\);/);
  assert.match(portal, /if \(awaiting\.current\) return;[\s\S]*?if \(ytState\.current !== YT_STATE\.PLAYING\) return;/);
  assert.match(portal, /if \(!gateLoad\(clock, extractVideoId\(clock\.url\), videoId, loaded\.current\)\) return;/);
  assert.match(portal, /hold\.current = nextHold\(prevClock\.current, clock, performance\.now\(\), hold\.current\);/);
  assert.match(portal, /const still = paused \|\| clock\.status === 'stalled';/);
  assert.match(portal, /ctl\.current = CTL_INIT;\s*rateOk\.current = true;/, 'vitesse réappliquée après loadVideoById, retentée à chaque vidéo');
  assert.match(portal, /if \(extractVideoId\(useStore\.getState\(\)\.clock\.url\) !== videoId\) return;/, 'jamais calée sur un autre titre');
  assert.match(portal, /loadStart\(here \? targetPos\(0\) \?\? 0 : 0, offsetRef\.current\)/, 'horloge d’un autre titre : départ au début');
  assert.doesNotMatch(portal, /driftSeek|alignDue|RUN_THRESHOLD_S|MIN_SEEK_GAP_MS|DRIFT_CHECK_MS|SEEK_COMP_S|clockPos\(/);
  const cover = code('src/lib/stage/cover.ts');
  assert.doesNotMatch(cover, /DRIFT_CHECK_MS|SEEK_COMP_S|RUN_THRESHOLD_S|ALIGN_THRESHOLD_S|MIN_SEEK_GAP_MS/);
  assert.match(code('src/hooks/useYouTubePlayer.ts'), /setPlaybackRate\(rate: number\): void;\s*getPlaybackRate\(\): number;/);
});

test('Portal : onglet caché, la vitesse revient à ×1 ; au retour, recalage tout de suite', () => {
  const portal = code('src/components/Stage/Portal.tsx');
  // caché : plus de correction, mais une vitesse ×0,90 à ×1,10 laissée là creuserait l'écart jusqu'au retour
  assert.match(portal, /if \(document\.visibilityState !== 'visible'\) \{ const d = whenHidden\(ctl\.current\); if \(d\) apply\(d, performance\.now\(\)\); return; \}/);
  // les deux sens : ×1 dès que l'onglet est caché, recalage dès son retour
  assert.match(portal, /const onVisibility = \(\): void => \{ if \(document\.visibilityState === 'visible'\) hold\.current = 0; tick\(\); \};/);
  assert.match(portal, /document\.addEventListener\('visibilitychange', onVisibility\);/);
  assert.match(portal, /document\.removeEventListener\('visibilitychange', onVisibility\);/);
  // une seule application des décisions : vitesse à confirmer (asked), état du régulateur suivi
  assert.match(portal, /const apply = \(d: Decision, now: number\): void => \{[\s\S]*?asked\.current = \{ rate: d\.rate, at: now \};[\s\S]*?ctl\.current = afterDecision\(ctl\.current, d, now\);/);
  assert.match(portal, /if \(d\) apply\(d, now\);/);
});
