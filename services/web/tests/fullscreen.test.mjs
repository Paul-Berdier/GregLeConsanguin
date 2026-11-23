// La vidéo en plein écran, « La Grand-Salle » (conception du 2026-11-23, §2) : la logique pure de lib/stage/fullscreen.ts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const F = await loadTs('../src/lib/stage/fullscreen.ts');
const { shortcutFor } = await loadTs('../src/lib/keys.ts');

/** Horloge factice : les minuteries partent quand on avance le temps. */
function fakeTimers() {
  let now = 0, seq = 0;
  const pending = new Map();
  return {
    set: (fn, ms) => { const h = ++seq; pending.set(h, { fn, at: now + ms }); return h; },
    clear: (h) => { pending.delete(h); },
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...pending.entries()].filter(([, p]) => p.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        pending.delete(due[0]);
        now = due[1].at;
        due[1].fn();
      }
      now = end;
    },
    get size() { return pending.size; },
  };
}

test('repos : les commandes s’effacent après 3 s sans activité, reviennent à la première', () => {
  const tm = fakeTimers(), seen = [];
  const idle = F.createIdle(F.FS_IDLE_MS, (v) => seen.push(v), () => false, tm);
  assert.equal(F.FS_IDLE_MS, 3000);
  idle.wake();
  tm.advance(2999);
  assert.deepEqual(seen, [], 'pas avant 3 s');
  tm.advance(1);
  assert.deepEqual(seen, [true]);
  assert.equal(idle.idle, true);
  idle.wake();
  assert.deepEqual(seen, [true, false], 'réveil immédiat');
  tm.advance(3000);
  assert.deepEqual(seen, [true, false, true]);
});

test('repos : chaque activité repousse l’échéance ; une activité sans repos ne dit rien', () => {
  const tm = fakeTimers(), seen = [];
  const idle = F.createIdle(3000, (v) => seen.push(v), () => false, tm);
  idle.wake();
  for (let i = 0; i < 5; i++) { tm.advance(2000); idle.wake(); }
  assert.deepEqual(seen, [], 'souris qui bouge toutes les 2 s : jamais effacées');
  assert.equal(tm.size, 1, 'une seule minuterie en attente');
  tm.advance(3000);
  assert.deepEqual(seen, [true]);
});

test('repos : retenu tant qu’un dialogue est ouvert (hold), puis effacé', () => {
  const tm = fakeTimers(), seen = [];
  let open = true;
  const idle = F.createIdle(3000, (v) => seen.push(v), () => open, tm);
  idle.wake();
  tm.advance(9000);
  assert.deepEqual(seen, [], 'dialogue ouvert : les commandes restent');
  open = false;
  tm.advance(3000);
  assert.deepEqual(seen, [true]);
});

test('repos : arrêté, plus rien ne part', () => {
  const tm = fakeTimers(), seen = [];
  const idle = F.createIdle(3000, (v) => seen.push(v), () => false, tm);
  idle.wake();
  idle.stop();
  tm.advance(10000);
  idle.wake();
  tm.advance(10000);
  assert.deepEqual(seen, []);
  assert.equal(tm.size, 0);
});

test('Tab piégé : en boucle dans la surcouche, depuis la surcouche elle-même au premier ou au dernier', () => {
  assert.equal(F.trapIndex(4, 0, false), 1);
  assert.equal(F.trapIndex(4, 3, false), 0, 'après le dernier : le premier');
  assert.equal(F.trapIndex(4, 0, true), 3, 'Maj+Tab sur le premier : le dernier');
  assert.equal(F.trapIndex(4, 2, true), 1);
  assert.equal(F.trapIndex(4, -1, false), 0, 'focus sur la surcouche : le premier arrêt');
  assert.equal(F.trapIndex(4, -1, true), 3);
  assert.equal(F.trapIndex(4, 9, false), 0, 'rang inconnu : comme hors des arrêts');
  assert.equal(F.trapIndex(1, 0, false), 0);
  assert.equal(F.trapIndex(0, -1, false), -1, 'aucun arrêt : le focus reste');
});

test('fin de lecture : sortie après 1,5 s sans titre, seulement en plein écran', () => {
  assert.equal(F.FS_EXIT_MS, 1500);
  assert.equal(F.fsExitDelay(true, false), 1500);
  assert.equal(F.fsExitDelay(true, true), null);
  assert.equal(F.fsExitDelay(false, false), null);
});

test('fullscreenchange : l’API entre et sort ; le repli ne dépend pas d’elle', () => {
  assert.equal(F.fsModeAfterChange(null, true), 'native');
  assert.equal(F.fsModeAfterChange('native', false), null, 'Échap, sortie imposée par le navigateur');
  assert.equal(F.fsModeAfterChange('pseudo', false), 'pseudo');
  assert.equal(F.fsModeAfterChange(null, false), null);
  // demande restée sans réponse : repli après FS_ASK_MS ; l'accord tardif du navigateur l'emporte
  assert.equal(F.FS_ASK_MS, 1000);
  assert.equal(F.fsModeAfterChange('pseudo', true), 'native');
});

test('API : préfixes webkit, autorisation du document, élément sans API (iPhone)', () => {
  const fn = () => {};
  assert.equal(F.canNativeFs({ fullscreenEnabled: true }, { requestFullscreen: fn }), true);
  assert.equal(F.canNativeFs({ webkitFullscreenEnabled: true }, { webkitRequestFullscreen: fn }), true);
  assert.equal(F.canNativeFs({ fullscreenEnabled: false }, { requestFullscreen: fn }), false, 'refusée (permissions, iframe)');
  assert.equal(F.canNativeFs({}, { requestFullscreen: fn }), false);
  assert.equal(F.canNativeFs({ fullscreenEnabled: true }, {}), false, 'élément sans API : repli');
  const el = {};
  assert.equal(F.fsElement({ fullscreenElement: el }), el);
  assert.equal(F.fsElement({ webkitFullscreenElement: el }), el);
  assert.equal(F.fsElement({ fullscreenElement: null }), null);
});

test('API : demande et sortie rendent une promesse, même préfixées ou en échec', async () => {
  const calls = [];
  await F.requestFs({ requestFullscreen: (o) => { calls.push(['std', o]); return Promise.resolve(); } });
  await F.requestFs({ webkitRequestFullscreen: () => { calls.push(['webkit']); } });
  await F.exitFs({ exitFullscreen: () => { calls.push(['exit']); } });
  await F.exitFs({ webkitExitFullscreen: () => { calls.push(['webkit-exit']); } });
  assert.deepEqual(calls, [['std', { navigationUI: 'hide' }], ['webkit'], ['exit'], ['webkit-exit']]);
  await assert.rejects(F.requestFs({ requestFullscreen: () => Promise.reject(new TypeError('denied')) }));
  await assert.rejects(F.requestFs({ requestFullscreen: () => { throw new TypeError('denied'); } }));
});

test('file mémorisée : clé, montrée par défaut, stockage bloqué sans erreur', () => {
  assert.equal(F.FS_QUEUE_KEY, 'greg.webplayer.fsQueue');
  assert.deepEqual([null, undefined, 'on', 'off', ''].map((v) => F.fsQueueOn(v)), [true, true, true, false, true]);
  const map = new Map();
  const store = () => ({ getItem: (k) => map.get(k) ?? null, setItem: (k, v) => { map.set(k, v); } });
  assert.equal(F.loadFsQueue(store), true);
  F.saveFsQueue(store, false);
  assert.equal(map.get('greg.webplayer.fsQueue'), 'off');
  assert.equal(F.loadFsQueue(store), false);
  F.saveFsQueue(store, true);
  assert.equal(F.loadFsQueue(store), true);
  const blocked = () => { throw new Error('SecurityError'); };
  assert.equal(F.loadFsQueue(blocked), true);
  assert.doesNotThrow(() => F.saveFsQueue(blocked, false));
});

test('au doigt, l’appui sur des commandes effacées les réveille seulement : le clic qui suit est avalé', () => {
  const tap = F.createWakeTap();
  tap.down('touch', true);
  assert.equal(tap.eats(1), true, 'pause, « Retirer », cœur effacés sous le doigt : rien ne part');
  assert.equal(tap.eats(1), false, 'un seul clic avalé');
  tap.down('touch', false);
  assert.equal(tap.eats(1), false, 'commandes affichées : l’appui agit');
  tap.down('mouse', true);
  assert.equal(tap.eats(1), false, 'la souris les a réveillées en bougeant');
  tap.down('pen', true);
  assert.equal(tap.eats(1), true, 'le stylet comme le doigt');
  tap.down('touch', true);
  tap.cancel();
  assert.equal(tap.eats(1), false, 'défilement (pointercancel) : le clic d’après passe');
  tap.down('touch', true);
  assert.equal(tap.eats(0), false, 'appui long sans clic, puis Entrée au clavier (detail 0) : jamais avalée');
  assert.equal(tap.eats(1), false, 'l’appui est oublié');
});

test('clavier en plein écran : saisie, « / » et « ? » ignorés ; Espace et Maj+→/← restent', () => {
  const ctx = { enabled: true, loggedIn: true, inField: false, inPopover: false, onRow: false, onControl: false, dragging: false };
  const act = (ev) => shortcutFor(ev, ctx);
  for (const ev of [{ key: 'a' }, { key: '/' }, { key: '?' }]) assert.equal(F.fsSkips(act(ev)), true, ev.key);
  for (const ev of [{ key: ' ', code: 'Space' }, { key: 'ArrowRight', shiftKey: true }, { key: 'ArrowLeft', shiftKey: true }]) {
    assert.equal(F.fsSkips(act(ev)), false, ev.key);
  }
});

test('ligne jouée ou retirée : le focus passe à la suivante, sinon à la précédente', () => {
  assert.equal(F.neighbourKey(['a', 'b', 'c'], 'b'), 'c');
  assert.equal(F.neighbourKey(['a', 'b', 'c'], 'c'), 'b');
  assert.equal(F.neighbourKey(['a'], 'a'), null);
  assert.equal(F.neighbourKey(['a'], 'z'), null);
});

test('progression : bornée de 0 à 1, durée inconnue à 0', () => {
  assert.equal(F.progressOf(30, 120), 0.25);
  assert.equal(F.progressOf(150, 120), 1);
  assert.equal(F.progressOf(-2, 120), 0);
  assert.equal(F.progressOf(30, 0), 0);
  assert.equal(F.progressOf(30, NaN), 0);
});

test('surcouche tout juste parue : la suite d’un double-clic est ignorée, un clic simple ou au clavier passe', () => {
  assert.equal(F.FS_DBLCLICK_MS, 500);
  assert.equal(F.fsSwallowClick(2, 120), true, 'second clic du double-clic sur « Plein écran »');
  assert.equal(F.fsSwallowClick(3, 499), true, 'triple clic');
  assert.equal(F.fsSwallowClick(1, 120), false, 'un clic simple, même aussitôt');
  assert.equal(F.fsSwallowClick(0, 120), false, 'au clavier (Entrée, Espace)');
  assert.equal(F.fsSwallowClick(2, 500), false, 'un double-clic voulu, plus tard : sortie');
});
