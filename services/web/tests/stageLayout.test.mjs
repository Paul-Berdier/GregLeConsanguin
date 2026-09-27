import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { solveStageLayout, stageCssVars, sameLayout, fOf, EXT, RHO, C_FULL, C_MAX } = await loadTs('../src/lib/stage/layout.ts');

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
