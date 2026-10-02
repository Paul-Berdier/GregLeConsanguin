import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const {
  coverNext, coverVisible, revealIn, loadStart, rewound, parseOffset, fmtOffset, posterUrl, isPlaceholderThumb, muteCaptions,
  COVERED, YT_STATE, REVEAL_AFTER_PLAYING_MS, REWIND_S, OFFSET_MIN, OFFSET_MAX, OFFSET_STEP,
} = await loadTs('../src/lib/stage/cover.ts');
const R = REVEAL_AFTER_PLAYING_MS;

const yt = (state, now = 0) => ({ type: 'yt', state, now });
const run = (events, from = COVERED) => events.reduce(coverNext, from);

test('poster : couvert → armé à PLAYING → révélé à +REVEAL_AFTER_PLAYING_MS (spec §4, tech.md §5.3)', () => {
  const armed = run([{ type: 'track' }, yt(YT_STATE.BUFFERING, 100), yt(YT_STATE.PLAYING, 1000)]);
  assert.deepEqual(armed, { phase: 'armed', armedAt: 1000, bySeek: false, playing: true });
  assert.equal(revealIn(armed, 2000), R - 1000);
  assert.equal(coverNext(armed, yt(YT_STATE.PLAYING, 2000)), armed);          // pas de réarmement
  assert.equal(coverNext(armed, { type: 'reveal', now: 3000 }), armed);       // trop tôt : minuterie périmée
  assert.equal(coverNext(armed, { type: 'reveal', now: 1000 + R }).phase, 'revealed');
});

test('poster : révélé seulement si YouTube joue encore quand la minuterie tombe (tech.md §5.3)', () => {
  const stalled = run([yt(YT_STATE.PLAYING, 1000), yt(YT_STATE.BUFFERING, 2000)]);
  assert.deepEqual(stalled, { phase: 'armed', armedAt: 1000, bySeek: false, playing: false });
  assert.equal(coverNext(stalled, yt(YT_STATE.BUFFERING, 2100)), stalled);
  assert.equal(coverNext(stalled, { type: 'reveal', now: 1000 + R + 100 }), stalled);   // en BUFFERING : le poster reste
  // la lecture reprend après l'échéance : révélé tout de suite
  assert.deepEqual(coverNext(stalled, yt(YT_STATE.PLAYING, 1000 + R + 500)), { phase: 'revealed', armedAt: 1000, bySeek: false, playing: true });
  // la lecture reprend avant l'échéance : toujours armé, la minuterie révèle ensuite
  const resumed = coverNext(stalled, yt(YT_STATE.PLAYING, 3000));
  assert.deepEqual(resumed, { phase: 'armed', armedAt: 1000, bySeek: false, playing: true });
  assert.equal(coverNext(resumed, { type: 'reveal', now: 1000 + R }).phase, 'revealed');
});

test('poster : un BUFFERING tardif ne le remet pas ; pause, fin, arrêt, erreur, nouveau titre le remettent', () => {
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false, playing: true };
  assert.deepEqual(coverNext(shown, yt(YT_STATE.BUFFERING, 9000)), { ...shown, playing: false });   // noté, poster levé
  const evs = [yt(YT_STATE.PAUSED), yt(YT_STATE.ENDED), yt(YT_STATE.UNSTARTED), yt(YT_STATE.CUED),
    { type: 'pause' }, { type: 'stop' }, { type: 'error' }, { type: 'track' }];
  for (const ev of evs) {
    assert.equal(coverNext(shown, ev).phase, 'covered', JSON.stringify(ev));
    assert.equal(coverNext({ ...shown, phase: 'armed' }, ev).phase, 'covered', `armé : ${JSON.stringify(ev)}`);
  }
});

test('poster : révélé, l\'état de lecture reste suivi ; un saut pendant un calage attend la reprise', () => {
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false, playing: true };
  const stalled = coverNext(shown, yt(YT_STATE.BUFFERING, 9000));
  assert.equal(coverNext(stalled, yt(YT_STATE.BUFFERING, 9100)), stalled);                         // rien de neuf : même objet
  assert.deepEqual(coverNext(stalled, yt(YT_STATE.PLAYING, 9500)), shown);                         // reprise : toujours révélé
  assert.equal(coverNext(shown, yt(YT_STATE.PLAYING, 9500)), shown);
  // saut de correction alors que YouTube cale encore : réarmé, mais la minuterie ne révèle pas
  const reArmed = coverNext(stalled, { type: 'seek', now: 20000 });
  assert.deepEqual(reArmed, { phase: 'armed', armedAt: 20000, bySeek: true, playing: false });
  assert.equal(coverNext(reArmed, { type: 'reveal', now: 20000 + R }), reArmed);
  assert.equal(coverNext(reArmed, yt(YT_STATE.PLAYING, 20000 + R + 500)).phase, 'revealed');                 // reprise après l'échéance
});

test('poster levé après le repli de l’habillage YouTube (mesuré, étape 4), jamais avant 3,5 s', () => {
  assert.ok(R >= 3500 && R <= 5000 && R % 250 === 0, String(R));
});

test('sous-titres de l’iframe muette : piste vidée puis module déchargé, sans jamais lever', () => {
  const calls = [];
  muteCaptions({ setOption: (...a) => calls.push(['set', ...a]), unloadModule: (m) => calls.push(['unload', m]) });
  assert.deepEqual(calls, [['set', 'captions', 'track', {}], ['unload', 'captions'], ['set', 'cc', 'track', {}], ['unload', 'cc']]);
  assert.doesNotThrow(() => muteCaptions({}));
  assert.doesNotThrow(() => muteCaptions({ setOption: () => { throw new Error('x'); }, unloadModule: () => { throw new Error('y'); } }));
});

test('poster : une minuterie périmée ne révèle ni un poster couvert ni un poster déjà révélé', () => {
  assert.equal(coverNext(COVERED, { type: 'reveal', now: 1e6 }), COVERED);
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false, playing: true };
  assert.equal(coverNext(shown, { type: 'reveal', now: 1e6 }), shown);
});

test('poster : un saut de correction réarme (YouTube remontre son habillage)', () => {
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false, playing: true };
  const reArmed = coverNext(shown, { type: 'seek', now: 20000 });
  assert.deepEqual(reArmed, { phase: 'armed', armedAt: 20000, bySeek: true, playing: true });
  assert.equal(coverNext(COVERED, { type: 'seek', now: 5 }), COVERED);        // couvert : rien à réarmer
});

test('poster : pause puis reprise après un saut, réarmé par le vrai départ', () => {
  const back = run([yt(YT_STATE.PLAYING, 0), { type: 'seek', now: 10 }, { type: 'pause' }, yt(YT_STATE.PLAYING, 20)]);
  assert.deepEqual(back, { phase: 'armed', armedAt: 20, bySeek: false, playing: true });
});

test('poster visible pendant la pause, même révélé', () => {
  assert.equal(coverVisible({ phase: 'revealed', armedAt: 0, bySeek: false, playing: true }, false), false);
  assert.equal(coverVisible({ phase: 'revealed', armedAt: 0, bySeek: false, playing: true }, true), true);
  assert.equal(coverVisible({ phase: 'armed', armedAt: 0, bySeek: false, playing: true }, false), true);
});

test('chargement : compensé du temps de loadVideoById, jamais négatif', () => {
  assert.equal(loadStart(42, 1.5), 43.9);
  assert.equal(loadStart(0, -3), 0);
});

test('recul du son sur la même vidéo (reprendre au début, boucle, même titre deux fois) : vidéo rechargée', () => {
  assert.equal(REWIND_S, 3);
  const tb = { pos: 100, at: 1000 };                                   // 100 s, 2 s avant le nouvel état
  assert.equal(rewound(tb, false, { pos: 0, at: 3000 }), true);        // reprise au début
  assert.equal(rewound(tb, false, { pos: 101, at: 3000 }), false);     // tick ordinaire, arrondi à la seconde
  assert.equal(rewound(tb, false, { pos: 99.5, at: 3000 }), false);    // sous le seuil : la dérive s'en charge
  assert.equal(rewound(tb, true, { pos: 98, at: 60000 }), false);      // en pause, la position n'avance pas
  assert.equal(rewound(tb, true, { pos: 0, at: 60000 }), true);
  assert.equal(rewound(tb, false, { pos: Number.NaN, at: 3000 }), false);
});

test('décalage : borné à ±3 s, pas de 50 ms, 0 si illisible ; un ancien réglage est ramené', () => {
  assert.deepEqual([OFFSET_MIN, OFFSET_MAX, OFFSET_STEP], [-3, 3, 0.05]);
  assert.equal(parseOffset('0.15'), 0.15);
  assert.equal(parseOffset('1.3'), 1.3);
  assert.equal(parseOffset('0.123'), 0.1);
  assert.equal(parseOffset('-0.27'), -0.25);
  assert.equal(parseOffset('7.5'), 3, 'ancien réglage (±10 s) : borné');
  assert.equal(parseOffset('-11'), -3);
  assert.equal(parseOffset('abc'), 0);
  assert.equal(parseOffset(null), 0);
  assert.equal(parseOffset(''), 0);
  assert.ok(Object.is(parseOffset('-0.01'), 0));
});

test('décalage : arrondi au pas symétrique autour de 0, sans reste flottant', () => {
  assert.equal(parseOffset('0.025'), 0.05);                  // demi-pas : loin de 0, des deux côtés
  assert.equal(parseOffset('-0.025'), -0.05);
  assert.equal(parseOffset('0.075'), 0.1);
  assert.equal(parseOffset('-0.075'), -0.1);
  assert.equal(parseOffset(1.15), 1.15);
  assert.equal(parseOffset(2.95), 2.95);
});

test('décalage affiché à la française', () => {
  assert.equal(fmtOffset(0), '0\u00a0s');
  assert.equal(fmtOffset(1.5), '+1,5\u00a0s');
  assert.equal(fmtOffset(-2), '−2\u00a0s');
  assert.equal(fmtOffset(0.15), '+0,15\u00a0s');
  assert.equal(fmtOffset(-0.05), '−0,05\u00a0s');
  assert.equal(fmtOffset(3), '+3\u00a0s');
});

test('posters : maxresdefault puis hqdefault si vignette grise', () => {
  assert.equal(posterUrl('dQw4w9WgXcQ'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg');
  assert.equal(posterUrl('dQw4w9WgXcQ', 'hq'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
  assert.equal(isPlaceholderThumb(120), true);
  assert.equal(isPlaceholderThumb(1280), false);
  assert.equal(isPlaceholderThumb(0), false);
});
