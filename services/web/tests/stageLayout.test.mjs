import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const {
  solveStageLayout, stageCssVars, sameLayout, fOf, EXT, RHO, C_FULL, C_MAX, BELOW_GAP, R_MIN, HEART_GAP, nightBottom, fitNight,
} = await loadTs('../src/lib/stage/layout.ts');

// Les 8 tailles d'écran de DESIGN §12.4. Entrées mesurées sur le prototype (Chrome, ?clean&still) :
// colonne de scène (clientWidth × clientHeight) et bloc sous le portail (offsetHeight).
// `out` : ce que calcule le prototype ; `design` : le tableau de DESIGN §12.4 (vidéo, couronne).
const VIEWPORTS = [
  { vp: '1280×720',  in: { colW: 784,  colH: 624, belowH: 118, viewportW: 1280 }, out: { R: 291, vw: 560, crown: 155 }, design: [560, 154] },
  { vp: '1366×768',  in: { colW: 870,  colH: 672, belowH: 118, viewportW: 1366 }, out: { R: 291, vw: 560, crown: 203 }, design: [560, 202] },
  { vp: '1366×657',  in: { colW: 870,  colH: 561, belowH: 118, viewportW: 1366 }, out: { R: 272, vw: 523, crown: 114 }, design: [521, 114] },
  { vp: '1440×790',  in: { colW: 944,  colH: 694, belowH: 118, viewportW: 1440 }, out: { R: 293, vw: 563, crown: 223 }, design: [562, 222] },
  { vp: '1440×900',  in: { colW: 944,  colH: 804, belowH: 120, viewportW: 1440 }, out: { R: 349, vw: 671, crown: 265 }, design: [671, 265] },
  { vp: '1536×730',  in: { colW: 1040, colH: 634, belowH: 118, viewportW: 1536 }, out: { R: 291, vw: 560, crown: 165 }, design: [560, 164] },
  { vp: '1536×864',  in: { colW: 1040, colH: 768, belowH: 118, viewportW: 1536 }, out: { R: 331, vw: 637, crown: 252 }, design: [635, 251] },
  { vp: '1920×1080', in: { colW: 1424, colH: 984, belowH: 124, viewportW: 1920 }, out: { R: 439, vw: 844, crown: 334 }, design: [850, 336] },
];

for (const v of VIEWPORTS) {
  test(`mise en page ${v.vp} : identique au prototype, dans le tableau de DESIGN §12.4`, () => {
    const l = solveStageLayout(v.in);
    assert.deepEqual({ R: l.R, vw: l.vw, crown: l.crown }, v.out);
    assert.ok(Math.abs(l.vw - v.design[0]) <= 6, `vidéo ${l.vw} ≠ ${v.design[0]}`);
    assert.ok(Math.abs(l.crown - v.design[1]) <= 2, `couronne ${l.crown} ≠ ${v.design[1]}`);
    assert.equal(l.springs, 'spring');
    assert.equal(l.mobile, false);
  });
}

test('règles : c entre 0,3 et 0,64 ; vidéo ≥ 560 px tant que la couronne peut encore baisser ; tout tient', () => {
  for (const v of VIEWPORTS) {
    const l = solveStageLayout(v.in);
    assert.ok(l.c >= C_FULL - 1e-9 && l.c <= C_MAX + 1e-9, `${v.vp} c=${l.c}`);
    if (l.c < C_MAX - 1e-9) assert.ok(l.vw >= 559, `${v.vp} vw=${l.vw}`);
    const H = v.in.colH - v.in.belowH - 6;
    const used = l.R * (EXT - l.c) + 2 * fOf(l.R) + ((l.R / RHO) * 9) / 16;
    assert.ok(used <= H + 1, `${v.vp} ${used} > ${H}`);
  }
});

test('une colonne (≤ 900 px) : couronne à 0,42, R ≤ 260, temps en ligne sous le portail', () => {
  const phone = solveStageLayout({ colW: 358, colH: 548, belowH: 219, viewportW: 390 });
  assert.deepEqual({ R: phone.R, vw: phone.vw, crown: phone.crown, springs: phone.springs, mobile: phone.mobile },
    { R: 168, vw: 338, crown: 108, springs: 'row', mobile: true });
  const tablet = solveStageLayout({ colW: 736, colH: 827, belowH: 225, viewportW: 768 });
  assert.deepEqual({ R: tablet.R, vw: tablet.vw, crown: tablet.crown }, { R: 260, vw: 710, crown: 166 });
});

test('variables CSS de la scène (1440×900)', () => {
  const l = solveStageLayout(VIEWPORTS[4].in);
  assert.deepEqual(stageCssVars(l), {
    '--R': '349px', '--vw': '671px', '--f': '17px', '--crown': '265px', '--cR': '105px', '--heart': '160px',
    '--ring-h': '300.1px', '--clip-day': '466.4px', '--clip-night': '38.4px',
  });
});

test('sameLayout ignore un réveil sans changement', () => {
  const a = solveStageLayout(VIEWPORTS[0].in), b = solveStageLayout({ ...VIEWPORTS[0].in });
  assert.ok(sameLayout(a, b));
  assert.ok(!sameLayout(a, solveStageLayout(VIEWPORTS[4].in)));
  assert.ok(!sameLayout(null, a));
});

// ─── La nuit tient aussi (fitNight) ─────────────────────────────────────────────────────────────
// Mesuré dans Chrome sur la fausse API (tâche 8) : colonne de scène, bloc du dessous (masqué la nuit, mais
// en place) et `tail`, le texte sous l'oculus (.vl-inner moins l'oculus et sa marge). `R` : ce qu'affiche la
// scène ; `bottom` : bas du texte de nuit mesuré, en px depuis le haut de la scène. Déconnecté, le panneau
// est masqué : la colonne a toute la largeur.
const NIGHTS = [
  { vp: '1280×720, rien en lecture', in: { colW: 784, colH: 593, belowH: 136, viewportW: 1280 }, tail: 188.04, R: 244, bottom: 585 },
  { vp: '1366×657, rien en lecture', in: { colW: 870, colH: 530, belowH: 136, viewportW: 1366 }, tail: 188.3, R: 205, bottom: 522 },
  { vp: '1280×720, déconnecté', in: { colW: 1232, colH: 593, belowH: 136, viewportW: 1280 }, tail: 243.6, R: 210, bottom: 585 },
  { vp: '1366×657, déconnecté', in: { colW: 1318, colH: 530, belowH: 136, viewportW: 1366 }, tail: 243.2, R: 170, bottom: 523 },
  { vp: '1440×900, rien en lecture', in: { colW: 944, colH: 773, belowH: 143, viewportW: 1440 }, tail: 187.86, R: 321 },
  { vp: '1024×768, rien en lecture', in: { colW: 588, colH: 641, belowH: 216, viewportW: 1024 }, tail: 187.94, R: 209 },
];
const room = (input) => input.colH - BELOW_GAP;

for (const n of NIGHTS) {
  test(`nuit ${n.vp} : son texte tient dans la colonne, rose jamais plus grande que le jour`, () => {
    const day = solveStageLayout(n.in), l = fitNight(n.in, n.tail);
    assert.equal(l.R, n.R);
    assert.ok(nightBottom(l, n.tail) <= room(n.in), `bas de la nuit ${nightBottom(l, n.tail)} > ${room(n.in)}`);
    assert.ok(l.R <= day.R, `R de nuit ${l.R} > R du jour ${day.R}`);
    assert.equal(l.mobile, false);
    if (n.bottom != null) assert.ok(Math.abs(nightBottom(l, n.tail) - n.bottom) <= 1, `calculé ${nightBottom(l, n.tail)}, mesuré ${n.bottom}`);
  });
}

test('nuit : la plus grande rose qui la fasse tenir (aucun bloc du dessous plus petit ne tient)', () => {
  for (const n of NIGHTS) {
    const l = fitNight(n.in, n.tail);
    for (let belowH = n.in.belowH; belowH <= n.in.colH; belowH += 1) {
      const bigger = solveStageLayout({ ...n.in, belowH });
      if (bigger.R > l.R) assert.ok(nightBottom(bigger, n.tail) > room(n.in), `${n.vp} : R ${bigger.R} tenait aussi`);
    }
  }
});

test('nuit : rien ne change quand elle tient déjà', () => {
  for (const n of NIGHTS.filter((x) => x.bottom == null)) {
    assert.deepEqual(fitNight(n.in, n.tail), solveStageLayout(n.in), n.vp);
  }
  assert.deepEqual(fitNight(NIGHTS[0].in, 0), solveStageLayout(NIGHTS[0].in), 'sans texte, la mise en page du jour');
});

test('nuit en une colonne (≤ 900 px) : la mise en page du jour, la page défile', () => {
  const phone = { colW: 348, colH: 543, belowH: 233, viewportW: 390 };
  assert.deepEqual(fitNight(phone, 176.24), solveStageLayout(phone));
  assert.deepEqual(fitNight(phone, 5000), solveStageLayout(phone), 'même si elle déborde');
});

test('nuit : si même la plus petite rose déborde, la plus petite rose (le filet de sécurité fait défiler)', () => {
  const input = NIGHTS[0].in;
  const l = fitNight(input, 2000);
  assert.equal(l.R, R_MIN);
  assert.deepEqual(l, solveStageLayout({ ...input, belowH: input.colH }));
  assert.ok(nightBottom(l, 2000) > room(input));
});

test('nuit : plus de texte, jamais une plus grande rose ; elle tient ou la rose est au plus petit', () => {
  for (const n of NIGHTS) {
    let prev = Infinity;
    for (let tail = 0; tail <= 700; tail += 20) {
      const l = fitNight(n.in, tail);
      assert.ok(l.R <= prev, `${n.vp}, texte ${tail} : R ${l.R} après ${prev}`);
      assert.ok(nightBottom(l, tail) <= room(n.in) || l.R === R_MIN, `${n.vp}, texte ${tail} : déborde avec R ${l.R}`);
      prev = l.R;
    }
  }
});

test('nightBottom : l’oculus centré sur la rose, sa marge, puis le texte (night.css)', () => {
  const l = solveStageLayout(VIEWPORTS[4].in);
  const top = l.crown + l.cR - l.heart / 2;   // .night { top: calc(var(--crown) + var(--cR) - var(--heart) / 2) }
  assert.equal(nightBottom(l, 100), top + l.heart + HEART_GAP * l.R + 100);
});
