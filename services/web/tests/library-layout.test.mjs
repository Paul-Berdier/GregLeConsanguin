// Chansonnier du Roi (spec 2026-11-23 §3) : la place que ses boutons prennent aux lignes qu'ils rejoignent.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';

const css = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '');
/** Corps de la première règle `sel { … }` (sélecteur exact) d'une feuille. */
const rule = (src, sel) => {
  const i = src.indexOf(`${sel} {`);
  assert.ok(i >= 0, `règle ${sel}`);
  return src.slice(i + sel.length + 2, src.indexOf('}', i));
};

test('titre en cours : le demandeur cède avec l’artiste (le cœur et « Ajouter à une playlist » lui prennent 70 px)', () => {
  const now = css('src/components/Stage/now.css');
  const by = rule(now, '.meta-slot .by');
  assert.match(by, /flex: 0 4 auto;/, 'le demandeur cède d’abord, comme dans la file');
  assert.match(by, /min-width: 0;/);
  assert.ok(!/flex: none/.test(by), 'un demandeur rigide laissait une lettre à l’artiste');
  assert.match(rule(now, '.meta-slot .by-txt'), /overflow: hidden; text-overflow: ellipsis;/);
  assert.match(rule(now, '.meta-slot .artist'), /min-width: 0;/);
  assert.match(read('src/components/Stage/NowPlaying.tsx'), /<span className="by-txt">\{t\(keys\.plain, vars\)\}<\/span>/);
  // « Ajouter à une playlist » désactivé (chansonnier pas encore lu) : il le paraît
  assert.match(rule(now, '.nbtn:disabled'), /opacity: \.4;/);
});

test('file au toucher : le cœur (quatrième bouton) ne prend plus 42 px au titre', () => {
  const q = css('src/components/Queue/queue.css');
  const touch = q.slice(q.indexOf('@media (hover: none) {'));
  assert.match(touch, /^@media \(hover: none\) \{[^@]*\n\s*\.act \{ width: 32px; height: 40px; \}/, '40 px de haut pour le doigt, 32 de large');
});

test('file au survol ou au focus : le titre cède la place à la puce de quatre boutons', () => {
  const q = css('src/components/Queue/queue.css');
  const px = (re) => Number(q.match(re)?.[1]);
  const act = px(/\n\.act \{ width: (\d+)px;/), gap = px(/\n\.acts \{[^}]*gap: (\d+)px;/), pad = px(/\n\.acts \{[^}]*padding: (\d+)px;/);
  const right = px(/\n\.acts \{[^}]*right: (\d+)px;/);
  const cols = q.match(/\n\.row \.card \{[^}]*grid-template-columns: 24px 72px minmax\(0, 1fr\) (\d+)px; align-items: center; gap: (\d+)px;/);
  const side = Number(cols?.[1]), colGap = Number(cols?.[2]), cardPad = px(/\n\.row \.card \{[^}]*padding: 0 (\d+)px 0 2px;/);
  // la puce déborde sur la colonne du titre de ce qu'elle a de plus que la durée et son espace
  const over = right + 4 * act + 3 * gap + 2 * pad - (cardPad + side + colGap);
  assert.equal(over, 40);
  const reserve = px(/@media \(hover: hover\) \{\s*\.qcontent > \.qlist > \.row:not\(\.dragging\):hover \.meta, \.qcontent > \.qlist > \.row:focus-within \.meta \{ padding-right: (\d+)px; \}/);
  assert.ok(reserve >= over && reserve <= over + 8, `réservé ${reserve} px pour ${over} px`);
  // seulement la file (.qcontent > .qlist) : ni « Souvent demandés ici » (dans sa section) ni le chansonnier (deux boutons)
  assert.ok(!/\n\.row:focus-within \.meta|\n\.row:hover \.meta/.test(q));
  // fenêtre étroite : sans « Jouer ensuite », trois boutons, et 10 px entre les colonnes
  const narrow = px(/@media \(hover: hover\) and \(max-width: 520px\) \{\s*[^{]+\{ padding-right: (\d+)px; \}/);
  const overNarrow = right + 3 * act + 2 * gap + 2 * pad - (cardPad + side + 10);
  assert.ok(narrow >= overNarrow && narrow <= overNarrow + 8, `étroit : réservé ${narrow} px pour ${overNarrow} px`);
});

test('chansonnier à 320 px : le nom en ligne n’élargit plus le volet ; la confirmation de suppression reste à l’écran', () => {
  // une piste « auto » prenait la largeur propre du champ (≈ 163 px) : volet de 334 à 366 px dans un panneau de 278
  assert.match(rule(css('src/components/panel.css'), '.panes'), /grid-template-columns: minmax\(0, 1fr\);/);
  // ancrée à droite du bouton, au bout de .lhead (18 px de chaque côté) : la marge de la page et celles de .lhead laissées
  const w = rule(css('src/components/Library/library.css'), '.ldel .lconfirm').match(/width: min\(290px, calc\(100vw - 2 \* var\(--page-x, 16px\) - (\d+)px\)\);/);
  assert.ok(w, 'largeur bornée à la place à gauche du bouton');
  const vw = 320, pageX = 16, scrollbar = 10, right = vw - scrollbar - pageX - 18;
  const width = Math.max(250, Math.min(290, vw - 2 * pageX - Number(w[1])));   // .pop : min-width 250 px
  assert.ok(right - width >= 0, `bord gauche à ${right - width} px`);
});
