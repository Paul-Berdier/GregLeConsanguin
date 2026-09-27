// Le Héraut (étape 3) : durées de vie, fusion ×N, survol, annulation, répliques espacées, pile.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';

const H = await loadTs('../src/lib/herald.ts');
const { createHerald, stackLayout, stackHeight, spokenText, deckToast, errorToast, LIFE, ACTION_LIFE, RELEASE_MS, LEAVE_MS, UNDO_MS, QUIP_EVERY_MS } = H;

// Horloge et minuteurs factices : advance(ms) déclenche dans l'ordre ce qui échoit.
function clock() {
  let now = 0, n = 0;
  const due = new Map();
  return {
    now: () => now,
    setTimer: (fn, ms) => { const h = ++n; due.set(h, { at: now + ms, fn }); return h; },
    clearTimer: (h) => { due.delete(h); },
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const next = [...due.entries()].filter(([, d]) => d.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        due.delete(next[0]);
        now = next[1].at;
        next[1].fn();
      }
      now = end;
    },
  };
}
const make = () => { const c = clock(); const announced = []; const h = createHerald({ ...c, announce: (t) => announced.push(t.fact + (t.n > 1 ? ` ×${t.n}` : '')) }); return { h, c, announced }; };
const facts = (h) => h.getSnapshot().filter((t) => !t.leaving).map((t) => t.fact);

test('durées de vie par sorte ; la plus récente en tête ; sortie puis retrait', () => {
  const { h, c } = make();
  h.notify({ kind: 'ok', fact: 'A' });
  h.notify({ kind: 'err', fact: 'B' });
  assert.deepEqual(facts(h), ['B', 'A']);
  c.advance(LIFE.ok);
  assert.deepEqual(facts(h), ['B']);
  assert.equal(h.getSnapshot().length, 2, 'A sort (leaving) avant d’être retirée');
  c.advance(LEAVE_MS);
  assert.equal(h.getSnapshot().length, 1);
  c.advance(LIFE.err - LIFE.ok - LEAVE_MS);
  assert.deepEqual(facts(h), []);
});

test('un même fait sans action devient ×2 et repart pour sa durée ; une action ne fusionne jamais', () => {
  const { h, c, announced } = make();
  const a = h.notify({ kind: 'info', fact: 'Ce titre est déjà le prochain.' });
  c.advance(3000);
  const b = h.notify({ kind: 'info', fact: 'Ce titre est déjà le prochain.' });
  assert.equal(a, b);
  assert.equal(h.getSnapshot()[0].n, 2);
  c.advance(3000);
  assert.deepEqual(facts(h), ['Ce titre est déjà le prochain.'], 'minuteur relancé');
  assert.deepEqual(announced, ['Ce titre est déjà le prochain.', 'Ce titre est déjà le prochain. ×2']);
  const run = () => {};
  h.notify({ kind: 'info', fact: 'Retiré : X', action: { label: 'Annuler', run } });
  h.notify({ kind: 'info', fact: 'Retiré : X', action: { label: 'Annuler', run } });
  assert.equal(facts(h).filter((f) => f === 'Retiré : X').length, 2);
});

test('action : durée de vie allongée ; Ctrl+Z rejoue la dernière pendant 15 s', () => {
  const { h, c } = make();
  let undone = 0;
  const id = h.notify({ kind: 'info', fact: 'Retiré : X', action: { label: 'Annuler', run: () => undone++ } });
  c.advance(LIFE.info);
  assert.deepEqual(facts(h), ['Retiré : X'], 'une action reste plus longtemps');
  assert.equal(h.undo(), true);
  assert.equal(undone, 1);
  assert.equal(h.getSnapshot().find((t) => t.id === id).leaving, true);
  assert.equal(h.undo(), false, 'une seule fois');
  h.notify({ kind: 'info', fact: 'Retiré : Y', action: { label: 'Annuler', run: () => undone++ } });
  c.advance(UNDO_MS + 1);
  assert.equal(h.undo(), false, 'trop tard');
  assert.equal(undone, 1);
  assert.ok(ACTION_LIFE > LIFE.info);
});

test('bouton d’action : l’action puis la sortie ; Ctrl+Z ne la rejoue pas', () => {
  const { h } = make();
  let n = 0;
  const id = h.notify({ kind: 'ok', fact: 'Ajouté : X', action: { label: 'Annuler', run: () => n++ } });
  h.act(id);
  h.act(id);
  assert.equal(n, 1);
  assert.equal(h.undo(), false);
});

test('survol : les minuteurs s’arrêtent ; à la sortie, chacune repart pour 2,4 s', () => {
  const { h, c } = make();
  h.notify({ kind: 'err', fact: 'E' });
  h.hold();
  c.advance(60_000);
  assert.deepEqual(facts(h), ['E']);
  h.notify({ kind: 'ok', fact: 'N' });
  c.advance(60_000);
  assert.deepEqual(facts(h), ['N', 'E'], 'une notification arrivée pendant le survol attend aussi');
  h.release();
  c.advance(RELEASE_MS - 1);
  assert.equal(facts(h).length, 2);
  c.advance(1);
  assert.deepEqual(facts(h), []);
});

test('répliques : au plus une toutes les 30 s', () => {
  const { h, c } = make();
  h.notify({ fact: 'A', quip: 'Bien, Sire.' });
  h.notify({ fact: 'B', quip: 'Encore, Sire ?' });
  const [b, a] = h.getSnapshot();
  assert.equal(a.quip, 'Bien, Sire.');
  assert.equal(b.quip, null);
  c.advance(QUIP_EVERY_MS);
  h.notify({ fact: 'C', quip: 'Me revoilà.' });
  assert.equal(h.getSnapshot()[0].quip, 'Me revoilà.');
});

test('abonnés prévenus, instantané immuable', () => {
  const { h } = make();
  let calls = 0;
  const off = h.subscribe(() => calls++);
  const s0 = h.getSnapshot();
  h.notify({ fact: 'A' });
  assert.notEqual(h.getSnapshot(), s0);
  assert.ok(calls >= 1);
  off();
  const c1 = calls;
  h.notify({ fact: 'B' });
  assert.equal(calls, c1);
});

test('pile : repliée (14 px, −5 %, 3 visibles) ou dépliée (hauteurs réelles + 8 px)', () => {
  const hs = [60, 80, 70, 50];
  assert.deepEqual(stackLayout(hs, false).map((p) => [p.y, +p.s.toFixed(2), p.o]), [[0, 1, 1], [14, 0.95, 1], [28, 0.9, 1], [42, 0.85, 0]]);
  assert.deepEqual(stackLayout(hs, true).map((p) => p.y), [0, 68, 156, 234]);
  assert.equal(stackHeight(hs), 60 + 2 * 14);
  assert.equal(stackHeight([]), 0);
});

test('pile repliée : derrière, la hauteur de la plaque de devant (Sonner) ; au-delà de 3, ni visibles ni actives', () => {
  const hs = [50, 90, 70, 60];
  const folded = stackLayout(hs, false);
  assert.deepEqual(folded.map((p) => p.fold), [null, 50, 50, 50]);
  assert.deepEqual(stackLayout(hs, true).map((p) => p.fold), [null, null, null, null], 'dépliée : les hauteurs réelles');
  assert.deepEqual(folded.map((p) => p.hidden), [false, false, false, true]);
  assert.deepEqual(stackLayout(hs, true).map((p) => p.hidden), [false, false, false, true]);
  // une plaque plus haute derrière ne dépasse plus : la place gardée par la file (stackHeight) couvre la pile
  const tops = folded.filter((p) => !p.hidden).map((p) => p.y + (p.fold ?? hs[0]) * p.s);
  assert.ok(Math.max(...tops) <= stackHeight(hs), `${tops} > ${stackHeight(hs)}`);
});

test('onglet caché : les minuteurs reprennent où ils en étaient ; une notification arrivée entre-temps garde toute sa durée', () => {
  const { h, c } = make();
  h.notify({ kind: 'warn', fact: 'W' });
  c.advance(1000);
  h.hold('tab');
  h.notify({ kind: 'err', fact: 'E' });
  c.advance(60_000);
  assert.deepEqual(facts(h), ['E', 'W']);
  h.release('tab');
  c.advance(LIFE.warn - 1000 - 1);
  assert.deepEqual(facts(h), ['E', 'W'], 'W reprend ses 5 s restantes, pas 2,4 s');
  c.advance(1);
  assert.deepEqual(facts(h), ['E']);
  c.advance(LIFE.err - (LIFE.warn - 1000) - 1);
  assert.deepEqual(facts(h), ['E'], 'E, jamais vue, garde ses 8 s');
  c.advance(1);
  assert.deepEqual(facts(h), []);
});

test('onglet et survol se cumulent ; l’onglet ne compte qu’une fois ; un relâchement en trop ne raccourcit rien', () => {
  const { h, c } = make();
  h.notify({ kind: 'err', fact: 'E' });
  h.hold('tab');
  h.hold('tab');
  h.hold();
  h.release('tab');
  c.advance(60_000);
  assert.deepEqual(facts(h), ['E'], 'le survol retient encore');
  h.release();
  c.advance(RELEASE_MS - 1);
  assert.deepEqual(facts(h), ['E']);
  c.advance(1);
  assert.deepEqual(facts(h), []);
  h.notify({ kind: 'err', fact: 'F' });
  h.release();
  h.release('tab');
  c.advance(LIFE.err - 1);
  assert.deepEqual(facts(h), ['F'], 'ni 2,4 s ni reprise sans arrêt');
  c.advance(1);
  assert.deepEqual(facts(h), []);
});

test('annonce : le fait, ×N, puis l’annulation, séparés par un point quand le fait n’en a pas', () => {
  const hint = (label) => `${label} avec Ctrl+Z.`;
  const undo = { label: 'Annuler', run() {} };
  const base = { id: 1, kind: 'info', quip: null, action: null, n: 1, leaving: false };
  assert.equal(spokenText({ ...base, fact: 'Retiré : Bohemian Rhapsody', action: undo }, hint), 'Retiré : Bohemian Rhapsody. Annuler avec Ctrl+Z.');
  assert.equal(spokenText({ ...base, fact: 'Titre passé.', action: undo }, hint), 'Titre passé. Annuler avec Ctrl+Z.');
  assert.equal(spokenText({ ...base, fact: 'Hugo a ajouté « X »', action: undo }, hint), 'Hugo a ajouté « X ». Annuler avec Ctrl+Z.', '« » ne clôt pas la phrase');
  assert.equal(spokenText({ ...base, fact: 'Est-ce « X ? »', action: undo }, hint), 'Est-ce « X ? » Annuler avec Ctrl+Z.');
  assert.equal(spokenText({ ...base, fact: 'Ce titre est déjà le prochain.', n: 3 }, hint), 'Ce titre est déjà le prochain. ×3');
  assert.equal(spokenText({ ...base, fact: 'Déplacé en position 2.' }, hint), 'Déplacé en position 2.');
});

// Deck factice : t remplit {clés}, has dit si le chemin existe, quip rend « clé#graine ».
const DECK = {
  'toast.removed.text': 'Retiré : {title}', 'toast.removed.kind': 'info',
  'toast.added.text': 'Ajouté : {title}', 'toast.added.kind': 'ok',
  'toast.bare.text': 'Sans sorte',
  'toast.odd.text': 'Sorte inconnue', 'toast.odd.kind': 'bizarre',
  'toast.stale.text': 'Greg est occupé.', 'toast.stale.kind': 'warn',
  'error.PRIORITY_FORBIDDEN.text': 'Ajouté par {name}.', 'error.PRIORITY_FORBIDDEN.kind': 'err',
  'error.NOKIND.text': 'Erreur sans sorte.',
  'error.UNKNOWN.text': 'Quelque chose a échoué.', 'error.UNKNOWN.kind': 'err',
};
const reader = {
  t: (p, v = {}) => (DECK[p] ?? p).replace(/\{(\w+)\}/g, (m, k) => (k in v ? String(v[k]) : m)),
  has: (p) => p in DECK,
  quip: (k, seed) => `${k}#${seed}`,
  seedOf: (s) => s.length,
};

test('say : sorte demandée, sinon celle du deck, sinon « info » ; fait rendu ou donné ; réplique de l’entrée', () => {
  const run = () => {};
  assert.deepEqual(deckToast('toast.added', { vars: { title: 'X' } }, reader),
    { kind: 'ok', fact: 'Ajouté : X', quip: `toast.added#${'Ajouté : X'.length}`, action: null });
  assert.equal(deckToast('toast.added', { vars: { title: 'X' }, kind: 'warn' }, reader).kind, 'warn');
  assert.equal(deckToast('toast.bare', {}, reader).kind, 'info');
  assert.equal(deckToast('toast.odd', {}, reader).kind, 'info', 'une sorte hors liste ne passe pas');
  const r = deckToast('toast.removed', { text: 'Retiré : Déjà rendu', action: { label: 'Annuler', run } }, reader);
  assert.equal(r.fact, 'Retiré : Déjà rendu');
  assert.equal(r.kind, 'info');
  assert.equal(r.action.run, run);
});

test('sayError : texte du deck (ou de l’API), sa sorte, « err » quand l’entrée n’en dit pas', () => {
  const p = errorToast({ key: 'error.PRIORITY_FORBIDDEN', path: 'error.PRIORITY_FORBIDDEN.text', vars: { name: 'Hugo' } }, reader);
  assert.deepEqual([p.kind, p.fact], ['err', 'Ajouté par Hugo.']);
  assert.equal(errorToast({ key: 'toast.stale', path: 'toast.stale.text' }, reader).kind, 'warn', 'la sorte du deck');
  assert.equal(errorToast({ key: 'error.NOKIND', path: 'error.NOKIND.text' }, reader).kind, 'err', 'pas « info »');
  const api = errorToast({ key: 'error.UNKNOWN', text: 'Message de l’API.' }, reader);
  assert.deepEqual([api.kind, api.fact, api.quip], ['err', 'Message de l’API.', `error.UNKNOWN#${'Message de l’API.'.length}`]);
  assert.equal(api.action, null);
});
