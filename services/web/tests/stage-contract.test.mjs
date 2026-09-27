// Contrats entre les morceaux de la scène (étape 2) : variables CSS, imports, mouvement, fichiers retirés.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';

const layout = await loadTs('../src/lib/stage/layout.ts');
const client = await loadTs('../src/lib/rose/client.ts');
const path = (p) => fileURLToPath(new URL(`../${p}`, import.meta.url));
const read = (p) => readFileSync(path(p), 'utf8');
const STAGE_CSS = ['stage', 'rose', 'portal', 'now', 'clock', 'night'].map((f) => `src/components/Stage/${f}.css`);

test('le recadrage de l’anneau est le même pour la peinture et la mise en page', () => {
  assert.equal(client.RING_TO, layout.RING_TO);
});

test('globals.css importe les six feuilles de la scène', () => {
  const css = read('src/app/globals.css');
  for (const f of STAGE_CSS) assert.ok(css.includes(`@import '../components/Stage/${f.split('/').pop()}';`), f);
});

test('chaque variable posée par Stage.tsx a une valeur par défaut dans stage.css et est lue quelque part', () => {
  const vars = [...Object.keys(layout.stageCssVars(layout.solveStageLayout({ colW: 944, colH: 804, belowH: 120, viewportW: 1440 }))), '--a0'];
  const stage = read('src/components/Stage/stage.css');
  const all = STAGE_CSS.map(read).join('\n');
  for (const v of vars) {
    assert.match(stage, new RegExp(`\\.stage \\{[^}]*${v}:`), `défaut de ${v}`);
    assert.ok(all.includes(`var(${v})`), `${v} jamais lue`);
  }
});

// Blocs de premier niveau d'une feuille, avec accolades imbriquées (@media, @keyframes).
function keyframeBodies(css) {
  const out = [];
  const re = /@keyframes\s+[\w-]+\s*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1, i = re.lastIndex;
    while (depth && i < css.length) { if (css[i] === '{') depth++; else if (css[i] === '}') depth--; i++; }
    out.push(css.slice(re.lastIndex, i - 1));
  }
  return out;
}

/** Propriétés animées d'une feuille : premières valeurs de chaque `transition:` et déclarations des @keyframes. */
function animated(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const props = [];
  for (const [, value] of clean.matchAll(/(?<![-\w])transition\s*:\s*([^;}]+)/g)) {
    for (const item of value.split(/,(?![^(]*\))/)) props.push(item.trim().split(/\s+/)[0]);
  }
  for (const body of keyframeBodies(clean)) for (const [, prop] of body.matchAll(/([\w-]+)\s*:/g)) props.push(prop);
  return props;
}

test('mouvement : transitions et keyframes de la scène sur transform et opacity seulement, jamais « all »', () => {
  for (const f of STAGE_CSS) {
    for (const prop of animated(read(f))) assert.ok(['transform', 'opacity', 'none'].includes(prop), `${f} : anime « ${prop} »`);
  }
});

test('mouvement réduit prévu dans chaque feuille qui déplace ou met à l’échelle', () => {
  for (const f of STAGE_CSS) {
    const css = read(f);
    if (animated(css).includes('transform')) assert.match(css, /prefers-reduced-motion:\s*reduce/, f);
  }
});

test('le lecteur provisoire et la progression par image sont retirés', () => {
  assert.ok(!existsSync(path('src/components/Stage/VideoPlayer.tsx')));
  assert.ok(!existsSync(path('src/hooks/useProgress.ts')));
  const globals = read('src/app/globals.css');
  for (const cls of ['.video-frame', '.progress-track', '.ctrl-main', '.wave-bar', '.artwork-hero']) assert.ok(!globals.includes(cls), cls);
});

test('casting : le portrait de Greg porte le bonnet de valet, jamais la couronne ni le sceau du Roi', () => {
  const night = read('src/components/Stage/NightState.tsx');
  const valet = night.match(/<div className="heart valet">[\s\S]*?<\/div>/)?.[0] ?? '';
  assert.ok(valet.includes('jester-cap'), 'le bonnet de valet');
  assert.ok(!/crown|king-seal/.test(valet), 'ni couronne ni sceau sur le portrait de Greg');
});

test('vidéo qui joue : ni filtre sur le portail, ni mode de mélange dans la scène (tech.md §6.2)', () => {
  const noComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
  const rule = (css, sel) => css.match(new RegExp(`(?:^|\\n)${sel.replace(/[.[\]]/g, '\\$&')}\\s*\\{([^}]*)\\}`))?.[1] ?? '';
  const portal = noComments(read('src/components/Stage/portal.css'));
  for (const sel of ['.portal', '.video', '.video .yt']) {
    assert.ok(rule(portal, sel), `règle ${sel} introuvable`);
    assert.ok(!/\bfilter\s*:/.test(rule(portal, sel)), `${sel} : un filtre sur l'iframe ou son ancêtre`);
  }
  assert.ok(!/mix-blend-mode/.test(noComments(read('src/components/Stage/stage.css'))), 'stage.css : mode de mélange');
});

test('la scène ne se rend pas à chaque tick : page.tsx lit tout le store, Stage est mémoïsée', () => {
  assert.match(read('src/components/Stage/Stage.tsx'), /export default memo\(Stage\);/);
});

test('déconnecté : un seul « Se connecter avec Discord », celui de la nuit ; pas de saut de grille au chargement', () => {
  assert.ok(read('src/components/Stage/NightState.tsx').includes('api.getLoginUrl()'), 'la nuit « déconnecté » porte le bouton');
  assert.ok(!read('src/components/Header/Header.tsx').includes('getLoginUrl'), "l'en-tête n'a plus son propre bouton");
  assert.match(read('src/app/page.tsx'), /data-scene=\{booted && !me \? 'out' : 'in'\}/);
});

// ─── Correctifs après revue (tâche 8) ───────────────────────────────────────────────────────────

/** Corps des blocs `@…` dont l'en-tête correspond à `head` (accolades imbriquées comprises). */
function atBodies(css, head) {
  const out = [];
  const re = new RegExp(`${head.source}\\s*\\{`, 'g');
  let m;
  while ((m = re.exec(css))) {
    let depth = 1, i = re.lastIndex;
    while (depth && i < css.length) { if (css[i] === '{') depth++; else if (css[i] === '}') depth--; i++; }
    out.push(css.slice(re.lastIndex, i - 1));
  }
  return out;
}
const noComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
/** Déclarations d'une règle de premier niveau (ou d'un bloc) dont le sélecteur est exactement `sel`. */
const ruleBody = (css, sel) => css.match(new RegExp(`(?:^|[\\n{}])\\s*${sel.replace(/[.[\]=()]/g, '\\$&')}\\s*\\{([^}]*)\\}`))?.[1] ?? '';

test('la nuit compte dans la mise en page : Stage.tsx reprend la géométrie de l’oculus de night.css', () => {
  const night = noComments(read('src/components/Stage/night.css'));
  const stage = read('src/components/Stage/Stage.tsx');
  assert.match(ruleBody(night, '.night'), /top:\s*calc\(var\(--crown\) \+ var\(--cR\) - var\(--heart\) \/ 2\)/, "haut de la nuit : centre de la rose moins un demi-oculus");
  const cssGap = Number(ruleBody(night, '.heart').match(/margin-bottom:\s*calc\(var\(--R\) \* ([\d.]+)\)/)?.[1]);
  const tsGap = Number(stage.match(/const HEART_GAP = ([\d.]+);/)?.[1]);
  assert.ok(cssGap > 0 && cssGap === tsGap, `marge sous l'oculus : night.css ${cssGap} R, Stage.tsx ${tsGap} R`);
  assert.match(stage, /l\.crown \+ l\.cR \+ l\.heart \/ 2 \+ HEART_GAP \* l\.R \+ tail/, 'bas de la nuit calculé comme night.css le pose');
  assert.match(stage, /minHeight:/, 'la scène contient sa nuit (centrage et filet de sécurité)');
});

test('transport sous le titre quand la colonne est étroite, à côté aux tailles de référence (DESIGN §12.4)', () => {
  const css = noComments(read('src/components/Stage/stage.css'));
  // la requête porte sur la colonne (largeur donnée par la grille), jamais sur la scène : empiler rapetisse
  // la scène, une requête sur sa largeur aurait deux états stables (à côté et R grand, dessous et R petit)
  assert.match(ruleBody(css, '.stage-col'), /container:\s*stage-col\s*\/\s*inline-size/, '.stage-col est le conteneur');
  assert.doesNotMatch(ruleBody(css, '.stage'), /container/, '.stage n’est pas un conteneur');
  const q = [...css.matchAll(/@container\s+stage-col\s*\(max-width:\s*([\d.]+)px\)\s*\{/g)].map((m) => Number(m[1]));
  assert.equal(q.length, 1, 'une requête sur la colonne');
  assert.equal([...css.matchAll(/@container/g)].length, 1, 'aucune autre requête de conteneur');
  const body = atBodies(css, /@container\s+stage-col\s*\(max-width:\s*[\d.]+px\)/)[0];
  assert.match(ruleBody(body, '.now'), /grid-template-columns:\s*minmax\(0, 1fr\)/, 'le transport passe sous le titre');
  // largeurs de colonne mesurées en navigateur (1440×900 : panneau à droite ; 1180 px et moins : panneau de 360 px)
  for (const [name, colW] of [['1280×720', 784], ['1366×657', 870], ['1536×730', 1040], ['1440×900', 944]]) {
    assert.ok(colW > q[0], `${name} : colonne de ${colW} px, le transport reste à côté du titre`);
  }
  for (const [name, colW] of [['1024×768', 588], ['901×800', 465]]) {
    assert.ok(colW <= q[0], `${name} : colonne de ${colW} px, le transport passe sous le titre`);
  }
  // juste au-dessus du seuil, la rose se règle sur la largeur : il reste au titre ~180 px à côté du transport (~280 px, écart 24)
  const l = layout.solveStageLayout({ colW: q[0] + 1, colH: 900, belowH: 140, viewportW: 1200 });
  assert.ok(l.vw + 2 * l.f - 280 - 24 >= 180, `titre : ${l.vw + 2 * l.f - 304} px`);
});

test('la nuit garde la largeur de son texte quand la rose rapetisse, sans sortir de la colonne', () => {
  const night = noComments(read('src/components/Stage/night.css'));
  const css = noComments(read('src/components/Stage/stage.css'));
  const maxW = Number(ruleBody(night, '.night .vl-inner').match(/max-width:\s*(\d+)px/)?.[1]);
  const desktop = atBodies(css, /@media \(min-width: 901px\)/).join('\n');
  const rule = ruleBody(desktop, '.stage > .night');
  for (const side of ['left', 'right']) {
    const m = rule.match(new RegExp(`${side}:\\s*max\\(-(\\d+)px, min\\(0px, 50% - (\\d+)px\\)\\)`));
    assert.ok(m, `${side} de la nuit`);
    assert.equal(Number(m[2]) * 2, maxW, 'demi-largeur du texte de nuit (night.css)');
    assert.equal(Number(m[1]), layout.SPRING_ROOM, 'jamais plus que la place que la colonne garde de chaque côté');
  }
});

test('sur ordinateur, la page ne défile pas : le cadre rogne les deux axes, une colonne défile en hauteur', () => {
  const css = noComments(read('src/app/globals.css'));
  assert.match(ruleBody(css, '.page-shell'), /(?:^|;)\s*overflow:\s*clip/, '.page-shell rogne x et y');
  const mobile = atBodies(css, /@media \(max-width: 900px\)/).join('\n');
  assert.match(ruleBody(mobile, '.page-shell'), /overflow-y:\s*visible/, 'une colonne : la page défile');
});

test('la scène ne se rend pas à chaque charge utile : sélecteurs de primitives, pas d’objets du store', () => {
  const stage = read('src/components/Stage/Stage.tsx');
  assert.doesNotMatch(stage, /useStore\(\(s\) => s\.(?:player\.current|me)\)/, 'player.current et me sont recréés à chaque charge utile');
});

test('la région de la scène ne s’appelle « En lecture » que le jour', () => {
  const stage = read('src/components/Stage/Stage.tsx');
  assert.ok(!stage.includes("aria-label={t('now.kicker')}"), 'nom constant, même la nuit');
  assert.match(stage, /aria-label=\{day \? t\('now\.kicker'\) : undefined\}/);
});

test('déconnecté sur téléphone : ni recherche ni rangée vide dans l’en-tête', () => {
  const css = noComments(read('src/components/Header/header.css'));
  const mobile = atBodies(css, /@media \(max-width: 900px\)/).join('\n');
  assert.match(ruleBody(mobile, '.top[data-auth=out] .search'), /display:\s*none/);
  assert.match(ruleBody(mobile, '.top[data-auth=out]'), /grid-template-areas:\s*"brand \. right"/);
  assert.match(ruleBody(css, '.top[data-auth=out] .search'), /visibility:\s*hidden/, "sur ordinateur, l'en-tête ne saute pas");
});
