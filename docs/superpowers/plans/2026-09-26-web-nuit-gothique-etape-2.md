# Nuit gothique, étape 2 : la scène, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** remplacer le lecteur provisoire (`components/Stage/VideoPlayer.tsx`) par la scène « Nuit gothique » de la spec §4 :
- le portail de pierre (9 tranches, rendu Blender) autour de la vidéo ;
- la rosace peinte dans un module worker, vitrée aux couleurs de la miniature, qui donne `--lumiere` ;
- la mise en page pilotée par R (`useStageLayout`, testée sur les 8 tailles de DESIGN §12.4) ;
- l'horloge de 48 panneaux en lecture seule, avec le temps au survol ;
- les états de nuit (rien en lecture, chargement, déconnecté) dans l'oculus ;
- le titre en Grenze et le demandeur, le transport et sa rondelle de verre ;
- le poster au-dessus d'un lecteur YouTube persistant, jusqu'à PLAYING + 3,5 s et pendant la pause ;
- la synchro vidéo (décalage) qui continue de marcher, désormais gardée dans `localStorage`.

**Architecture:** Next.js 14 (App Router, React 18, Tailwind 3), aucune nouvelle dépendance npm.
- Toute la logique est pure et testée avec `node:test` : géométrie et palette de la rose, mise en page, horloge, scène, poster, titres. Les modules chargés par les tests n'ont aucun import runtime.
- Le verre est peint hors du fil principal. `lib/rose/rose.worker.ts` est un module worker créé par `new Worker(new URL('./rose.worker.ts', import.meta.url), { type: 'module' })` ; il renvoie des `ImageBitmap` que `RoseClient` pose dans des canevas `bitmaprenderer`.
- La scène est pilotée par des variables CSS posées sur `.stage` (`--R`, `--vw`…). React ne rend qu'aux changements d'état : `page.tsx` lit tout le store (`usePlayer()`) et se rend à chaque tick du bot, donc `Stage` est mémoïsée et ne lit le store que par sélecteurs. Le temps et l'horloge passent par un minuteur de 250 ms, jamais par une boucle par image.
- Rien de filtré ni de mélangé autour de la vidéo qui joue : ni `filter` sur le portail, ni `mix-blend-mode` dans la scène de jour (tech.md §6.2). `tests/stage-contract.test.mjs` le vérifie.
- Une feuille de style par composant, importée par `globals.css`.

**Tech Stack:** Next.js 14.2, React 18, TypeScript 5, Tailwind 3, `node:test`, API IFrame YouTube, OffscreenCanvas et Web Worker, Playwright (Chrome installé) pour la vérification.

**Spec:** `docs/superpowers/specs/2026-09-26-web-nuit-gothique-design.md` (§4 « La scène », §6.2). Plan de référence : `docs/superpowers/plans/2026-09-26-web-nuit-gothique-etape-1.md`.

## Global Constraints

- **Ressources.** `S` = `C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad` et `P` = `S\design`.
  - Le prototype `P\proto-gothique` fait foi pour les valeurs : son `DESIGN.md` et ses sources `work\refine\src\styles.css`, `body.html`, `app.js` et `work\refine\rose-worker.js`.
  - Mouvement : `P\research\motion.md`. Technique : `P\research\tech.md` (§5.2 à §5.4). Textes : `services/web/src/theme/copy.v2.json`, par `theme/copy.ts` (`t`, `quip`, `has`). Guide : `P\research\persona-v2.md`.
- **Casting** (spec §1, qui fait foi). Le Roi, c'est l'utilisateur connecté ; Greg est son valet.
  - Aucune couronne, aucun sceau royal, aucun « Rex » attribué à Greg.
  - La couronne de l'oculus attend le Roi. Le sceau `king-seal-<L>.webp` n'accompagne que « Demandé par vous ». Le portrait de Greg porte le bonnet à grelots.
- **Mouvement.**
  - Animer uniquement `transform` et `opacity`, jamais `transition: all` ni un `clip-path` animé ; les couleurs de survol changent sans transition.
  - Survols derrière `@media (hover:hover) and (pointer:fine)`.
  - `prefers-reduced-motion` respecté : opacité seule, couronne immobile.
- **Textes.** En français, depuis le deck v2 (Greg vouvoie le Roi).
  - Les répliques sont en `aria-hidden`, en or, et coupées par `<html data-quips="off">` (réglage « Répliques de Greg » de l'étape 1).
  - Aucun humour dans un `aria-label`.
- **Compatibilité.**
  - Les 71 tests web existants restent verts : `cd services/web && npm test`. `GREG_TEST_TRANSPILE=1 npm test` passe aussi (chemin Node 20 de l'image Docker).
  - `npx tsc --noEmit` et `npx next build` passent.
  - Aucune nouvelle dépendance npm. `services/web/node_modules` est une jonction vers une copie installée : ne jamais lancer `npm install`.
  - Aucun changement dans `services/bot`, `services/api` ni `packages/shared`.
- **Modules purs.** Chaque module chargé par `tests/_loadTs.mjs` :
  - n'a aucun import runtime (seulement `import type`) ;
  - n'utilise que de la syntaxe TypeScript effaçable : pas d'`enum`, pas de `namespace`, pas de paramètres de constructeur `private x`.
  - Exception existante : `theme/copy.ts` importe son JSON. Un test qui a besoin du deck lit `copy.v2.json` directement.
- **Fins de ligne.** `core.autocrlf=true` : dans l'arbre de travail, certains fichiers sont en CRLF (`src/lib/playerUtils.ts`, `src/lib/api.ts`, `src/lib/types.ts`…), les autres en LF. Modifier un fichier existant avec l'outil d'édition, sans le réécrire en entier, pour garder ses fins de ligne.
- **Commandes.** Elles sont écrites pour Git Bash, lancées depuis la racine du dépôt sauf `cd services/web` explicite.
  - Sous PowerShell, `GREG_TEST_TRANSPILE=1 npm test` s'écrit `$env:GREG_TEST_TRANSPILE=1; npm test; Remove-Item Env:GREG_TEST_TRANSPILE`.
- **Parallélisme.** Les tâches d'une même vague partagent le même `services/web`.
  - `npm test` peut tourner en même temps.
  - `npx tsc --noEmit` et `npx next build` non : un seul dossier `.next`, et `tsc` voit les fichiers à moitié écrits des voisines.
  - Quand des tâches tournent en parallèle dans le même dossier, chacune lance `npm test` ; l'orchestrateur lance `tsc` et `next build` une fois la vague finie, avant d'ouvrir la suivante.
- **Git.**
  - Les agents ne font ni commit, ni push, ni stash, ni reset, ni checkout. L'orchestrateur fait un commit et un push à la fin de l'étape (tâche 8, étape 11).
  - Ne jamais committer `services/web/tsconfig.json` ni `services/web/next-env.d.ts`.
- **Serveurs de vérification.**
  - Fausse API : `node S\uimock\mock_api.js` (port 3999 ; `services/web/.env.local` pointe déjà `API_URL` dessus). Elle n'a pas de Socket.IO : les erreurs WebSocket de la console sont attendues.
  - Web : `npx next build && npx next start -p 3100` dans `services/web`, jamais `next dev`.
  - Toujours arrêter les serveurs lancés. Fichiers temporaires sous `S`.

## Écarts assumés (mesurés avant d'écrire ce plan)

Tout le code de ce plan a été monté dans une copie jetable de `services/web` (`S\etape2-fix\web`, reprise de `S\etape2-plan\web` après une relecture critique) :
- 140 tests verts, dans les deux modes de chargement ; chaque test ajouté par la relecture échoue sur le code d'avant ;
- `tsc` et `next build` passent, et le worker sort en chunk séparé ;
- 30 contrôles sur 30 passent dans Chrome, sur la fausse API.

Ces mesures justifient neuf écarts avec le prototype :

1. **Jour ↔ nuit sans `clip-path` animé.**
   - Le prototype anime le `clip-path` du calque de verre pendant 900 ms. Ici, chaque fenêtre porte sa coupe : `data-kind="song"`, coupée au linteau, ou `data-kind="moon"`, la rose entière.
   - Le passage jour ↔ nuit devient le fondu d'opacité de `RoseClient`. Quand les deux coupes diffèrent, l'ancienne fenêtre s'efface aussi.
2. **Un saut de correction remet le poster.**
   - Mesure : l'habillage YouTube (titre, icône pause, « Plus de vidéos ») revient pendant environ 4 s après chaque `seekTo`, pas seulement après PLAYING.
   - L'alignement à +1,2 s (tech.md §5.4) réarme donc le poster (`coverNext` : événement `seek`), sans nouvel alignement.
   - Un changement de décalage demandé par le Roi saute sans poster, puisqu'il regarde la vidéo.
3. **Posters.**
   - `maxresdefault` manque pour certaines vidéos (Bohemian Rhapsody dans la fausse API) : le poster retombe sur `hqdefault`, et la vidéo est notée pour ne plus être redemandée.
   - Le 404 journalisé par le navigateur est du bruit attendu, filtré par la vérification au même titre que les erreurs internes de l'iframe YouTube.
4. **Hors étape 2** (spec §6) :
   - la révérence (la scène s'incline), le couronnement, les info-bulles « chaudes », les raccourcis Maj+→ / Maj+← et le lent zoom du poster qui attend sa révélation (tech.md §5.3, « keep the cover alive ») relèvent de l'étape 4 ; ici, fondus simples ;
   - accessibilité (étape 4) : après « Tout arrêter », le bouton d'arrêt disparaît avec le bas de la scène et le focus retombe sur la page ; l'étape 4 le posera sur « Ajouter un titre » ;
   - `Transport` prend ses actions dans `usePlayer()`, qui s'abonne à tout le store : il se rend à chaque tick (cinq boutons, aucun changement du DOM). L'étape 3 réécrit `usePlayer` pour les actions optimistes et resserrera cet abonnement.
5. **Sous-titres YouTube.** L'iframe muette peut afficher des sous-titres. On garde `cc_load_policy: 0` comme le lecteur actuel (parité), sans appel d'API non documentée.
6. **Ni filtre ni mélange autour de la vidéo.** Le prototype n'avait qu'un poster ; ici, une iframe YouTube joue sous le portail.
   - tech.md §6.2 a mesuré, sur la vidéo qui joue, un `filter` persistant sur la scène (1,57 à 1,78 fois le travail GPU de la vidéo nue) et un calque en `mix-blend-mode` (1,76 à 2,18 fois). Un `drop-shadow` sur un ancêtre de l'iframe et un `plus-lighter` dans le même groupe relèvent des mêmes passes de rendu hors écran ; ces deux-là n'ont pas été mesurés à part, mais les retirer ne change pas l'image (captures de la tâche 8).
   - L'ombre du portail devient une `box-shadow` : le cadre de pierre est rectangulaire, l'ombre est la même.
   - La nappe de lumière (`.lightpool`) perd `mix-blend-mode: plus-lighter` : sur le mur presque noir, 11 % de lumière en mélange normal éclaire pareil.
7. **Déconnecté : un seul bouton de connexion.** Comme le prototype (`applyStateChrome` : « the hero carries the only CTA » ; DESIGN §10, tour 3), la nuit « déconnecté » porte le seul « Se connecter avec Discord ». L'en-tête perd le sien et masque la recherche ; à la déconnexion, le focus passe au bouton de la nuit. Pendant le chargement, la grille garde son panneau (`data-scene="in"`) : pas de saut de la rose quand la session arrive.
8. **Le son recule sur la même vidéo** (« Reprendre au début », boucle, même titre deux fois de suite) : la vidéo est rechargée sous le poster (`rewound`, tech.md §5.4 : nouvel alignement quand l'horloge saute). Sans ça, une vidéo finie restait sous son poster jusqu'au titre suivant, et une reprise au début attendait la correction de dérive, bloquée 15 s après un saut.
9. **Titres SoundCloud**, que le bot joue aussi : l'ancien lecteur montrait leur pochette, le portail la garde (`art` : image fixe, sans « Synchro vidéo »). La palette ne se lit que sur `i.ytimg.com` : pour ces titres, la rosace reste au clair de lune et l'anneau ne s'allume pas ; les temps restent aux naissances de l'arc.

## Carte des fichiers et vagues

Chaque fichier a un seul propriétaire. Les tâches d'une même vague touchent des fichiers disjoints et peuvent tourner en parallèle.

| Tâche | Crée | Modifie | Dépend de |
|---|---|---|---|
| 1. Géométrie et palette de la rose | `src/lib/rose/geometry.ts`, `src/lib/rose/palette.ts`, `tests/rose-geometry.test.mjs`, `tests/palette.test.mjs` | | aucune |
| 2. Worker, peinture, client et composant Rose | `src/lib/rose/paint.ts`, `src/lib/rose/rose.worker.ts`, `src/lib/rose/client.ts`, `src/components/Stage/Rose.tsx`, `src/components/Stage/rose.css`, `tests/rose-client.test.mjs` | | 1 |
| 3. Mise en page et horloge (pur) | `src/lib/stage/layout.ts`, `src/lib/stage/dial.ts`, `src/hooks/useStageLayout.ts`, `tests/stageLayout.test.mjs`, `tests/dial.test.mjs` | | aucune |
| 4. Titres, scène, poster (pur) | `src/lib/titles.ts`, `src/lib/stage/scene.ts`, `src/lib/stage/cover.ts`, `tests/titles.test.mjs`, `tests/scene.test.mjs`, `tests/cover.test.mjs`, `tests/stage-copy.test.mjs` | | aucune |
| 5. Portail, YouTube persistant, poster, synchro | `src/hooks/useYouTubePlayer.ts`, `src/hooks/useVideoOffset.ts`, `src/components/Stage/Portal.tsx`, `src/components/Stage/SyncOffset.tsx`, `src/components/Stage/portal.css` | | 4 |
| 6. Titre, demandeur, transport | `src/components/Stage/NowPlaying.tsx`, `src/components/Stage/Transport.tsx`, `src/components/Stage/now.css` | | 4 |
| 7. Horloge et nuit | `src/hooks/useStageClock.ts`, `src/components/Stage/Clock.tsx`, `src/components/Stage/NightState.tsx`, `src/components/Stage/clock.css`, `src/components/Stage/night.css`, `public/gothique/jester-cap-256.webp`, `public/gothique/jester-cap-512.webp` | `public/licenses/LICENSES.md`, `tests/assets.test.mjs` | 3, 4 |
| 8. Assemblage, page, nettoyage, navigateur | `src/components/Stage/Stage.tsx`, `src/components/Stage/stage.css`, `tests/stage-contract.test.mjs` | `src/app/page.tsx`, `src/app/globals.css`, `src/components/Sidebar.tsx`, `src/components/Queue/QueuePanel.tsx`, `src/components/History/HistoryPanel.tsx`, `src/components/Header/Header.tsx`, `src/components/Header/header.css`, `src/lib/playerUtils.ts` (commentaire) ; supprime `src/components/Stage/VideoPlayer.tsx`, `src/hooks/useProgress.ts` | 2, 3, 5, 6, 7 |

Tous les chemins sont relatifs à `services/web/`.

Vagues :
- **A** : tâches 1, 3 et 4 ;
- **B** : tâches 2, 5, 6 et 7 ;
- **C** : tâche 8.

Les composants des tâches 2, 5, 6 et 7 ne sont montés qu'à la tâche 8. Leurs feuilles CSS n'y sont importées dans `globals.css` qu'à ce moment-là.

## Contrats partagés

Les tâches ne se voient pas entre elles : voici tout ce qu'elles partagent.

- **Attributs de `.stage`** (posés par `Stage.tsx`, tâche 8) :
  - `data-scene="day|night"` ;
  - `data-paused="true|false"` (vrai seulement de jour) ;
  - `data-springs="spring|row"`.
  - Ils sont lus par `rose.css`, `portal.css`, `now.css`, `clock.css` et `night.css`.
- **Variables CSS sur `.stage`** : `--R --vw --f --crown --cR --heart --ring-h --clip-day --clip-night`, qui viennent de `stageCssVars(layout)` (tâche 3), plus `--a0`, qui vient de `dialGeometry(c).a0` (tâche 3). `stage.css` leur donne une valeur par défaut.
- **Variables sur `.rosace`** : `--p0` et `--p1` (degrés), posées par `Rose.tsx` depuis `paneMask(pane)` (tâche 3). `rose.css` leur donne 0 par défaut.
- **Classes partagées définies dans `stage.css`** (tâche 8) : `.quip` (réplique, or, italique), `.btn-ghost`, `.btn-danger`.
- **Classes de l'étape 1** (`header.css`, `globals.css`) : `.plaque`, `.pop` (avec `data-open`), `.btn-solid`, `.ico`, `.tnum`, `.sr`.
- **Id** : `NOW_TITLE_ID = 'now-title'` (exporté par `NowPlaying.tsx`). C'est le titre du morceau ; il nomme l'horloge (`aria-labelledby`).
- **Temps écrits hors de React** par `useStageClock` (tâche 7), sous la racine qu'on lui donne :
  - `[data-clock="cur"]` et `[data-clock="tot"]` reçoivent les textes ;
  - `[data-clock="aria"]` reçoit `aria-valuenow`, `aria-valuemax` et `aria-valuetext`.
  - React ne leur donne jamais de texte.
- **Code de l'étape 1 réutilisé tel quel** :
  - `useStore` et `usePlayer` (`hooks/usePlayer.ts`) ;
  - `livePosition` (`lib/playerUtils.ts`) ;
  - `fmt` et `extractVideoId` (`lib/format.ts`) ;
  - `usePopover` (`components/Header/GuildPicker.tsx`) ;
  - `kingName` (`components/Header/KingAvatar.tsx`) ;
  - `t`, `quip` (`theme/copy.ts`) et `api.getLoginUrl()` (`lib/api.ts`).

---

### Task 1 : géométrie et palette de la rose (pur)

**Files:**
- Create: `services/web/src/lib/rose/geometry.ts`, portage de `P\proto-gothique\work\refine\rose-worker.js` lignes 8–192, valeurs inchangées : la pierre Blender a été calculée sur cette géométrie
- Create: `services/web/src/lib/rose/palette.ts`, portage des lignes 194–272 ; l'analyse des pixels devient la fonction pure `paletteFromPixels`
- Test: `services/web/tests/rose-geometry.test.mjs`, `services/web/tests/palette.test.mjs`

**Interfaces:**
- Consumes : `contrast(a, b)` de `src/lib/color.ts` (étape 1, test seulement).
- Produces :

```ts
// src/lib/rose/geometry.ts
export type Pt = [number, number]; export type Poly = Pt[]; export type BBox = [number, number, number, number];
export type GlassRole = 'ground' | 'border' | 'figure' | 'accent' | 'pale' | 'ringA' | 'ringB';
export type Cell = { poly: Poly; role: GlassRole; bb: BBox; v: [number, number, number, number, number]; edge?: boolean; paint?: boolean };
export type Motif = 'crown' | 'fleur' | 'rose';
export type Medallion = { x: number; y: number; r: number; rimIn: number; cells: Cell[]; motif: Motif };
export type OpeningKind = 'ring' | 'lancet' | 'foil' | 'roundel' | 'heart';
export type Opening = { poly: Poly; kind: OpeningKind; index?: number; t1?: number; t2?: number; a?: number; cells: Cell[]; med?: Medallion };
export const TAU: number;
export const GEO: { readonly extent: 1.06; readonly stone: 1.045; readonly ringIn: 0.892; readonly ringOut: 0.958; readonly panes: 48;
  readonly paneGap: 0.0105; readonly beadR: 0.8755; readonly beads: 96; readonly lanIn: 0.33; readonly lanH: 0.655; readonly lanTip: 0.845;
  readonly lanGap: 0.038; readonly medR: 0.565; readonly medRad: 0.092; readonly qfR: 0.8; readonly qfLobe: 0.026; readonly rosR: 0.235;
  readonly rosRad: 0.066; readonly heart: 0.13 };
export const PANE_STEP: number; export const PANE_A0: number;
export function rng(seed: number): () => number; export const clamp: (x: number, a: number, b: number) => number;
export function clipPoly(poly: Poly, f: (x: number, y: number) => number): Poly;
export function inPoly(pt: Pt, poly: Poly): boolean; export function bbox(poly: Poly): BBox;
export function arcPts(cx: number, cy: number, r: number, t1: number, t2: number, n: number): Poly;
export function circlePoly(cx: number, cy: number, r: number, n?: number): Poly;
export function buildGeometry(seed?: number): Opening[];   // 89 ouvertures, 979 pièces de verre (graine 23)

// src/lib/rose/palette.ts
export type HSL = [number, number, number]; export type RGB = [number, number, number];
export type PaletteMode = 'color' | 'grisaille' | 'moon';
export type Palette = { mode: PaletteMode; hues?: number[]; lum: RGB; glassA: RGB; glassB: RGB } & Record<GlassRole, HSL>;
export function hslCss(c: HSL, dh?: number, dl?: number, ds?: number): string;
export function hsl2rgb(h: number, s: number, l: number): RGB; export function rgb2hsv(r: number, g: number, b: number): [number, number, number];
export const hueDist: (a: number, b: number) => number; export function jewelL(h: number): number;
export const GLAZIER: { cobalt: 222; ruby: 352; gold: 44; murrey: 322 }; export function harmony(main: number): [number, number];
export function lumiereOf(h: number): RGB; export function buildPalette(hues: number[]): Palette;
export const GRISAILLE: Palette; export const MOONLIGHT: Palette;           // MOONLIGHT.lum = [180, 196, 226]
export const SAMPLE_W = 48, SAMPLE_H = 27; export const thumbUrl: (id: string) => string;
export function paletteFromPixels(d: ArrayLike<number>): Palette;           // RGBA 48 × 27
```

- [ ] **Step 1 : écrire les tests qui échouent.**

`tests/rose-geometry.test.mjs` :

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { buildGeometry, GEO, PANE_A0, PANE_STEP, clipPoly, inPoly, circlePoly } = await loadTs('../src/lib/rose/geometry.ts');

const g = buildGeometry();
const kinds = (k) => g.filter((o) => o.kind === k);

test('ouvertures : 48 panneaux, 16 lancettes, 16 quadrilobes, 8 rondels, 1 cœur', () => {
  assert.equal(kinds('ring').length, GEO.panes);
  assert.equal(kinds('lancet').length, 16);
  assert.equal(kinds('foil').length, 16);
  assert.equal(kinds('roundel').length, 8);
  assert.equal(kinds('heart').length, 1);
});

test('géométrie identique au prototype (la pierre Blender a été calculée dessus)', () => {
  let s = 0, n = 0;
  for (const o of g) for (const c of [...o.cells, ...(o.med ? o.med.cells : [])]) for (const [x, y] of c.poly) { s += x + 2 * y; n++; }
  assert.equal(n, 8342);
  assert.ok(Math.abs(s - -2.374039) < 1e-6, `somme de contrôle ${s}`);
  const cells = g.reduce((t, o) => t + o.cells.length + (o.med ? o.med.cells.length : 0), 0);
  assert.equal(cells, 979);
});

test('déterministe pour une graine, différent pour une autre', () => {
  assert.deepEqual(buildGeometry(23), g);
  assert.notDeepEqual(buildGeometry(7), g);
});

test('le panneau 0 de l’horloge est centré en haut, les panneaux tournent dans le sens horaire', () => {
  const [p0, p1] = kinds('ring');
  assert.ok(Math.abs(((p0.t1 + p0.t2) / 2) + Math.PI / 2) < 1e-12);
  assert.ok(Math.abs(p1.t1 - p0.t1 - PANE_STEP) < 1e-12);
  assert.equal(p0.t1, PANE_A0);
});

test('tout le verre tient dans l’anneau extérieur, chaque pièce a au moins 3 sommets', () => {
  for (const o of g) {
    for (const [x, y] of o.poly) assert.ok(Math.hypot(x, y) <= GEO.ringOut + 1e-9);
    for (const c of o.cells) assert.ok(c.poly.length >= 3, o.kind);
  }
});

test('mosaïque : 34 à 36 pièces par lancette, un médaillon peint dans chacune', () => {
  for (const l of kinds('lancet')) {
    assert.ok(l.cells.length >= 34 && l.cells.length <= 36, String(l.cells.length));
    assert.equal(l.med.cells.filter((c) => c.paint).length, 2);
  }
  assert.deepEqual(kinds('lancet').slice(0, 4).map((l) => l.med.motif), ['crown', 'fleur', 'rose', 'fleur']);
});

test('clipPoly et inPoly', () => {
  const sq = [[0, 0], [2, 0], [2, 2], [0, 2]];
  const half = clipPoly(sq, (x) => x - 1);   // garde x ≤ 1
  assert.ok(half.every(([x]) => x <= 1 + 1e-12));
  assert.ok(inPoly([0.5, 0.5], half) && !inPoly([1.5, 0.5], half));
  assert.equal(circlePoly(0, 0, 1, 12).length, 12);
});
```

`tests/palette.test.mjs` :

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './_loadTs.mjs';
const P = await loadTs('../src/lib/rose/palette.ts');
const { contrast } = await loadTs('../src/lib/color.ts');
const { paletteFromPixels, buildPalette, lumiereOf, hueDist, hslCss, GRISAILLE, MOONLIGHT, SAMPLE_W, SAMPLE_H, thumbUrl } = P;

const N = SAMPLE_W * SAMPLE_H;
function image(fill) {            // fill(i) → [r, g, b] pour le pixel i
  const d = new Uint8ClampedArray(N * 4);
  for (let i = 0; i < N; i++) { const [r, g, b] = fill(i); d.set([r, g, b, 255], i * 4); }
  return d;
}
const hex = ([r, g, b]) => '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');

test('vidéo sans teinte exploitable : grisaille', () => {
  assert.equal(paletteFromPixels(image(() => [128, 128, 128])), GRISAILLE);
  assert.equal(paletteFromPixels(image(() => [20, 5, 5])), GRISAILLE);                       // trop sombre
  assert.equal(paletteFromPixels(image((i) => (i < 20 ? [200, 30, 30] : [120, 120, 120]))), GRISAILLE); // chroma < 0,02
  assert.equal(paletteFromPixels(new Uint8ClampedArray(0)), GRISAILLE);
});

test('miniature rouge : fond rubis, compléments du verrier (cobalt, or)', () => {
  const p = paletteFromPixels(image(() => [200, 30, 30]));
  assert.equal(p.mode, 'color');
  assert.ok(hueDist(p.hues[0], 0) < 1, String(p.hues[0]));
  assert.deepEqual(p.hues.slice(1), [222, 44]);
  assert.equal(p.ground[0], p.hues[0]);
});

test('deux teintes présentes : les deux sont gardées, la dominante d’abord', () => {
  const p = paletteFromPixels(image((i) => (i % 3 === 0 ? [30, 60, 200] : [200, 30, 30])));
  assert.ok(hueDist(p.hues[0], 0) < 1);
  assert.ok(hueDist(p.hues[1], 229) < 2, String(p.hues[1]));
});

test('pas de vert ajouté si la miniature n’en a pas', () => {
  for (let h = 0; h < 360; h += 15) {
    const p = buildPalette([h]);
    for (const x of p.hues.slice(1)) assert.ok(!(x >= 70 && x < 170), `${h} → ${x}`);
  }
});

test('troisième teinte trop proche de la principale : remplacée', () => {
  assert.deepEqual(buildPalette([20, 222]).hues, [20, 222, 44]);
  for (let h = 0; h < 360; h += 5) {
    const [m, , t] = buildPalette([h]).hues;
    assert.ok(hueDist(m, t) >= 30 || t === 44, `${h}`);
  }
});

test('--lumiere lisible sur --nef pour toute teinte (≥ 6:1, DESIGN §7)', () => {
  for (let h = 0; h < 360; h += 5) assert.ok(contrast(hex(lumiereOf(h)), '#14110e') >= 6.0, `teinte ${h}`);
  assert.ok(contrast(hex(GRISAILLE.lum), '#14110e') >= 6.0);
});

test('clair de lune = valeur par défaut de --lumiere dans tokens.css', () => {
  const css = readFileSync(new URL('../src/theme/tokens.css', import.meta.url), 'utf8');
  assert.match(css, new RegExp(`--lumiere-rgb:${MOONLIGHT.lum.join(' ')};`));
});

test('hslCss borne saturation et luminosité', () => {
  assert.equal(hslCss([10, 0.8, 0.33]), 'hsl(10 80% 33%)');
  assert.equal(hslCss([10, 0.8, 0.33], 5, 1, 1), 'hsl(15 100% 96%)');
  assert.equal(thumbUrl('dQw4w9WgXcQ'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
});
```

- [ ] **Step 2 : lancer** `cd services/web && npm test`. Attendu : FAIL, `Cannot find module …/src/lib/rose/geometry.ts`.
- [ ] **Step 3 : écrire `src/lib/rose/geometry.ts`.**

```ts
/**
 * La rosace, en coordonnées unitaires (centre 0,0, y vers le bas, R = 1 = rayon du vitrail).
 * Repris de proto-gothique/work/refine/rose-worker.js (lignes 8–192) sans changer une valeur :
 * la pierre Blender (public/gothique/stone-rose-2048.webp) a été calculée depuis CETTE géométrie.
 * Pur, sans import runtime (tests/rose-geometry.test.mjs).
 */

export type Pt = [number, number];
export type Poly = Pt[];
export type BBox = [number, number, number, number];
export type GlassRole = 'ground' | 'border' | 'figure' | 'accent' | 'pale' | 'ringA' | 'ringB';
export type Cell = { poly: Poly; role: GlassRole; bb: BBox; v: [number, number, number, number, number]; edge?: boolean; paint?: boolean };
export type Motif = 'crown' | 'fleur' | 'rose';
export type Medallion = { x: number; y: number; r: number; rimIn: number; cells: Cell[]; motif: Motif };
export type OpeningKind = 'ring' | 'lancet' | 'foil' | 'roundel' | 'heart';
export type Opening = { poly: Poly; kind: OpeningKind; index?: number; t1?: number; t2?: number; a?: number; cells: Cell[]; med?: Medallion };

export const TAU = Math.PI * 2;
export const GEO = {
  extent: 1.06,                 // carré peint = [-extent, extent]² (disque de pierre + moulure)
  stone: 1.045,                 // bord extérieur du disque de pierre
  ringIn: 0.892, ringOut: 0.958, // anneau des 48 panneaux : l'horloge du morceau
  panes: 48, paneGap: 0.0105,   // meneau de pierre entre deux panneaux
  beadR: 0.8755, beads: 96,     // perles sculptées (pierre seule)
  lanIn: 0.33, lanH: 0.655, lanTip: 0.845, lanGap: 0.038,
  medR: 0.565, medRad: 0.092,   // médaillon peint dans chaque lancette
  qfR: 0.8, qfLobe: 0.026,      // quadrilobes des écoinçons
  rosR: 0.235, rosRad: 0.066,   // couronne intérieure de rondels
  heart: 0.13,
} as const;
export const PANE_STEP = TAU / GEO.panes;
export const PANE_A0 = -Math.PI / 2 - PANE_STEP / 2;   // un panneau centré en haut

export function rng(seed: number): () => number {
  let s = (seed >>> 0) % 2147483647 || 1;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}
export const clamp = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));

export function clipPoly(poly: Poly, f: (x: number, y: number) => number): Poly {
  const out: Poly = [];
  for (let k = 0; k < poly.length; k++) {
    const a = poly[k], b = poly[(k + 1) % poly.length], fa = f(a[0], a[1]), fb = f(b[0], b[1]);
    if (fa <= 0) out.push(a);
    if ((fa < 0) !== (fb < 0) && fa !== fb) { const t = fa / (fa - fb); out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]); }
  }
  return out;
}
export function inPoly(pt: Pt, poly: Poly): boolean {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}
function segDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy || 1;
  const t = clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2, 0, 1);
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}
function edgeDist(p: Pt, poly: Poly): number {
  let d = Infinity;
  for (let i = 0; i < poly.length; i++) d = Math.min(d, segDist(p, poly[i], poly[(i + 1) % poly.length]));
  return d;
}
function voronoi(seeds: Pt[], poly: Poly): Poly[] {
  return seeds.map((p, i) => {
    let cell = poly.slice();
    for (let j = 0; j < seeds.length && cell.length > 2; j++) {
      if (j === i) continue;
      const q = seeds[j];
      const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2, nx = q[0] - p[0], ny = q[1] - p[1];
      cell = clipPoly(cell, (x, y) => (x - mx) * nx + (y - my) * ny);
    }
    return cell;
  });
}
export function bbox(poly: Poly): BBox {
  const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
export function arcPts(cx: number, cy: number, r: number, t1: number, t2: number, n: number): Poly {
  const o: Poly = [];
  for (let i = 0; i <= n; i++) { const t = t1 + ((t2 - t1) * i) / n; o.push([cx + Math.cos(t) * r, cy + Math.sin(t) * r]); }
  return o;
}
export function circlePoly(cx: number, cy: number, r: number, n = 48): Poly { return arcPts(cx, cy, r, 0, TAU, n).slice(0, n); }

function lancetPoly(a: number, w: number): Poly {
  const { lanIn: r1, lanH: rh, lanTip: r2 } = GEO;
  const P = (r: number, t: number): Pt => [Math.cos(t) * r, Math.sin(t) * r];
  const q = (p0: Pt, c: Pt, p1: Pt, n: number): Poly => {
    const o: Poly = [];
    for (let i = 1; i <= n; i++) { const t = i / n, u = 1 - t; o.push([u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1]]); }
    return o;
  };
  const L0 = P(r1, a - w), L1 = P(rh, a - w), T = P(r2, a), R1 = P(rh, a + w);
  const cL = P(rh + (r2 - rh) * 0.62, a - w * 0.98), cR = P(rh + (r2 - rh) * 0.62, a + w * 0.98);
  const pts: Poly = [L0];
  for (let i = 1; i <= 6; i++) { const r = r1 + ((rh - r1) * i) / 6; pts.push(P(r, a - w)); }
  pts.push(...q(L1, cL, T, 12), ...q(T, cR, R1, 12));
  for (let i = 5; i >= 0; i--) { const r = r1 + ((rh - r1) * i) / 6; pts.push(P(r, a + w)); }
  pts.push(...arcPts(0, 0, r1, a + w, a - w, 6).slice(1, -1));
  return pts;
}
function quatrefoilPoly(cx: number, cy: number, rl: number, rot: number): Poly {
  const d = rl * 0.92, pts: Poly = [];
  const t = d * Math.SQRT1_2 + Math.sqrt(Math.max(0, rl * rl - d * d * 0.5));
  for (let i = 0; i < 4; i++) {
    const phi = rot + (i * Math.PI) / 2, lx = cx + Math.cos(phi) * d, ly = cy + Math.sin(phi) * d;
    const pa: Pt = [cx + Math.cos(phi - Math.PI / 4) * t, cy + Math.sin(phi - Math.PI / 4) * t];
    const pb: Pt = [cx + Math.cos(phi + Math.PI / 4) * t, cy + Math.sin(phi + Math.PI / 4) * t];
    const a1 = Math.atan2(pa[1] - ly, pa[0] - lx);
    let a2 = Math.atan2(pb[1] - ly, pb[0] - lx);
    while (a2 < a1) a2 += TAU;
    pts.push(...arcPts(lx, ly, rl, a1, a2, 14).slice(0, -1));
  }
  return pts;
}

/** Toutes les ouvertures et leurs pièces de verre (des rôles, pas des couleurs : une géométrie sert toutes les palettes). */
export function buildGeometry(seed = 23): Opening[] {
  const rnd = rng(seed);
  const openings: Opening[] = [];
  const cellOf = (poly: Poly, role: GlassRole, extra: Partial<Cell> = {}): Cell =>
    ({ poly, role, bb: bbox(poly), v: [rnd(), rnd(), rnd(), rnd(), rnd()], ...extra });
  // 1. l'horloge : 48 panneaux en dents de scie
  for (let i = 0; i < GEO.panes; i++) {
    const r1 = GEO.ringIn, r2 = GEO.ringOut;
    const t1 = PANE_A0 + i * PANE_STEP, t2 = t1 + PANE_STEP;
    const g1 = GEO.paneGap / 2 / r1, g2 = GEO.paneGap / 2 / r2;
    const outer = arcPts(0, 0, r2, t1 + g2, t2 - g2, 5), inner = arcPts(0, 0, r1, t2 - g1, t1 + g1, 5);
    const poly = [...outer, ...inner];
    const A: Poly = [inner[inner.length - 1], ...outer];
    const B: Poly = [inner[inner.length - 1], outer[outer.length - 1], ...inner.slice(0, -1)];
    openings.push({ poly, kind: 'ring', index: i, t1, t2, cells: [cellOf(A, 'ringA'), cellOf(B, i % 4 === 0 ? 'figure' : 'ringB')] });
  }
  // 2. seize lancettes en mosaïque : petites pièces de bordure, grandes pièces de fond, un médaillon
  const N = 16, step = TAU / N, a0 = -Math.PI / 2;
  const MOTIFS: Motif[] = ['crown', 'fleur', 'rose', 'fleur'];
  for (let k = 0; k < N; k++) {
    const a = a0 + k * step, w = step / 2 - (GEO.lanGap / 2 / GEO.lanIn) * 0.9;
    const poly = lancetPoly(a, w);
    const med: Pt = [Math.cos(a) * GEO.medR, Math.sin(a) * GEO.medR];
    const seeds: Pt[] = [], kinds: ('edge' | 'ground')[] = [];
    const far = (p: Pt, s: number) => seeds.every((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) > s);
    let perim = 0;
    const segs: [Pt, Pt, number][] = [];
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      const l = Math.hypot(q[0] - p[0], q[1] - p[1]);
      segs.push([p, q, l]); perim += l;
    }
    const nb = Math.round(perim / 0.034);
    let acc = 0, si = 0;
    for (let j = 0; j < nb; j++) {
      const target = ((j + 0.5) * perim) / nb;
      while (si < segs.length - 1 && acc + segs[si][2] < target) { acc += segs[si][2]; si++; }
      const [p, q, l] = segs[si], t = (target - acc) / l;
      const x = p[0] + (q[0] - p[0]) * t, y = p[1] + (q[1] - p[1]) * t;
      const nx = -(q[1] - p[1]) / l, ny = (q[0] - p[0]) / l;
      let s: Pt = [x + nx * 0.017, y + ny * 0.017];
      if (!inPoly(s, poly)) s = [x - nx * 0.017, y - ny * 0.017];
      if (inPoly(s, poly) && far(s, 0.02)) { seeds.push(s); kinds.push('edge'); }
    }
    const bb = bbox(poly);
    for (let tries = 0; tries < 2400; tries++) {
      const s: Pt = [bb[0] + rnd() * (bb[2] - bb[0]), bb[1] + rnd() * (bb[3] - bb[1])];
      if (!inPoly(s, poly)) continue;
      if (Math.hypot(s[0] - med[0], s[1] - med[1]) < GEO.medRad + 0.03) continue;
      if (edgeDist(s, poly) < 0.031) continue;
      const sp = 0.04 + rnd() * 0.024;
      if (far(s, sp)) { seeds.push(s); kinds.push('ground'); }
    }
    const polys = voronoi(seeds, poly);
    let edgeN = 0;
    const cells: Cell[] = [];
    polys.forEach((pl, i) => {
      if (pl.length < 3) return;
      let role: GlassRole;
      if (kinds[i] === 'edge') role = edgeN++ % 4 === 3 ? 'pale' : 'border';
      else { const u = rnd(); role = u < 0.16 ? 'accent' : u < 0.22 ? 'figure' : 'ground'; }
      cells.push(cellOf(pl, role, { edge: kinds[i] === 'edge' }));
    });
    const mcells: Cell[] = [];
    const mr = GEO.medRad, rimIn = mr * 0.78, nrim = 10;
    for (let j = 0; j < nrim; j++) {
      const t1 = (j * TAU) / nrim + a, t2 = ((j + 1) * TAU) / nrim + a;
      mcells.push(cellOf([...arcPts(med[0], med[1], mr, t1, t2, 4), ...arcPts(med[0], med[1], rimIn, t2, t1, 4)], j % 2 ? 'figure' : 'border'));
    }
    const inner = circlePoly(med[0], med[1], rimIn, 40);
    const half1 = clipPoly(inner, (x, y) => (x - med[0]) * Math.cos(a) + (y - med[1]) * Math.sin(a) - rimIn * 0.42);
    const half2 = clipPoly(inner, (x, y) => -((x - med[0]) * Math.cos(a) + (y - med[1]) * Math.sin(a) - rimIn * 0.42));
    mcells.push(cellOf(half2, 'figure', { paint: true }), cellOf(half1, k % 2 ? 'accent' : 'ground', { paint: true }));
    openings.push({ poly, kind: 'lancet', index: k, a, cells, med: { x: med[0], y: med[1], r: mr, rimIn, cells: mcells, motif: MOTIFS[k % 4] } });
    // 3. quadrilobe de l'écoinçon : lobes vitrés, plombs en croix
    const qa = a + step / 2, qx = Math.cos(qa) * GEO.qfR, qy = Math.sin(qa) * GEO.qfR;
    const qpoly = quatrefoilPoly(qx, qy, GEO.qfLobe, qa);
    const qcells = [0, 1, 2, 3].map((l) => {
      const d1 = qa + (l * Math.PI) / 2 - Math.PI / 4, d2 = d1 + Math.PI / 2;
      let pl = clipPoly(qpoly, (x, y) => -((x - qx) * -Math.sin(d1) + (y - qy) * Math.cos(d1)));
      pl = clipPoly(pl, (x, y) => (x - qx) * -Math.sin(d2) + (y - qy) * Math.cos(d2));
      return cellOf(pl, l % 2 ? 'figure' : 'border');
    });
    qcells.push(cellOf(circlePoly(qx, qy, GEO.qfLobe * 0.42, 16), 'pale'));
    openings.push({ poly: qpoly, kind: 'foil', cells: qcells });
  }
  // 4. rondels intérieurs et cœur
  for (let k = 0; k < 8; k++) {
    const a = -Math.PI / 2 + (k * Math.PI) / 4 + Math.PI / 8, x = Math.cos(a) * GEO.rosR, y = Math.sin(a) * GEO.rosR, rr = GEO.rosRad;
    const poly = circlePoly(x, y, rr, 40);
    const cells = [0, 1, 2, 3].map((l) => cellOf([[x, y], ...arcPts(x, y, rr, a + (l * Math.PI) / 2 + Math.PI / 4, a + ((l + 1) * Math.PI) / 2 + Math.PI / 4, 8)], l % 2 ? 'figure' : 'ground'));
    cells.push(cellOf(circlePoly(x, y, rr * 0.38, 20), k % 2 ? 'border' : 'pale'));
    openings.push({ poly, kind: 'roundel', cells });
  }
  {
    const r = GEO.heart, poly = circlePoly(0, 0, r, 64);
    const cells: Cell[] = [];
    for (let l = 0; l < 8; l++) cells.push(cellOf([[0, 0], ...arcPts(0, 0, r, (l * TAU) / 8 - Math.PI / 2, ((l + 1) * TAU) / 8 - Math.PI / 2, 8)], l % 2 ? 'border' : 'ground'));
    cells.push(cellOf(circlePoly(0, 0, r * 0.36, 24), 'figure'));
    openings.push({ poly, kind: 'heart', cells });
  }
  return openings;
}
```

- [ ] **Step 4 : écrire `src/lib/rose/palette.ts`.**

```ts
/**
 * Palette du vitrail, tirée de la miniature du morceau (DESIGN §4 et §12.2).
 * Repris de proto-gothique/work/refine/rose-worker.js (lignes 194–272). L'analyse des pixels est
 * pure (`paletteFromPixels`) ; la lecture de la miniature (fetch, OffscreenCanvas) reste dans le worker.
 * Pur, sans import runtime (tests/palette.test.mjs).
 */
import type { GlassRole } from './geometry';

export type HSL = [number, number, number];
export type RGB = [number, number, number];
export type PaletteMode = 'color' | 'grisaille' | 'moon';
export type Palette = { mode: PaletteMode; hues?: number[]; lum: RGB; glassA: RGB; glassB: RGB } & Record<GlassRole, HSL>;

const clamp = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));

/** Couleur CSS d'un verre, avec décalages de teinte, de luminosité et de saturation. */
export function hslCss([h, s, l]: HSL, dh = 0, dl = 0, ds = 0): string {
  return `hsl(${Math.round(h + dh)} ${Math.round(clamp(s + ds, 0, 1) * 100)}% ${Math.round(clamp(l + dl, 0.04, 0.96) * 100)}%)`;
}
export function hsl2rgb(h: number, s: number, l: number): RGB {
  const k = (n: number) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}
export function rgb2hsv(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) {
    if (mx === r) h = ((g - b) / d) % 6; else if (mx === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
    h *= 60; if (h < 0) h += 360;
  }
  return [h, mx ? d / mx : 0, mx];
}
export const hueDist = (a: number, b: number): number => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

/** Luminosité « joyau » par teinte : cobalt et rubis profonds, jaune d'argent plus clair pour ne pas virer au brun. */
export function jewelL(h: number): number {
  h = ((h % 360) + 360) % 360;
  if (h >= 200 && h < 262) return 0.31;   // cobalt
  if (h >= 330 || h < 12) return 0.33;    // rubis
  if (h >= 12 && h < 38) return 0.33;     // vermillon, ambre
  if (h >= 38 && h < 70) return 0.45;     // jaune d'argent
  if (h >= 70 && h < 170) return 0.29;    // vert (seulement si le morceau en a)
  if (h >= 170 && h < 200) return 0.31;   // sarcelle
  return 0.3;                             // pourpre, violet
}
export const GLAZIER = { cobalt: 222, ruby: 352, gold: 44, murrey: 322 } as const;
/** Teintes de repli, prises chez le verrier médiéval selon l'harmonie avec la teinte principale ; jamais de vert. */
export function harmony(main: number): [number, number] {
  if (main >= 180 && main < 262) return [GLAZIER.ruby, GLAZIER.gold];
  if (main >= 262 && main < 330) return [GLAZIER.gold, GLAZIER.cobalt];
  if (main >= 70 && main < 180) return [GLAZIER.ruby, GLAZIER.gold];
  if (main >= 38 && main < 70) return [GLAZIER.cobalt, GLAZIER.ruby];
  return [GLAZIER.cobalt, GLAZIER.gold];
}
/** La lumière du morceau (--lumiere) : ≥ 6:1 sur --nef quelle que soit la teinte (DESIGN §7). */
export function lumiereOf(h: number): RGB {
  const l = h >= 190 && h < 280 ? 0.74 : h > 40 && h < 75 ? 0.64 : 0.69;
  return hsl2rgb(h, 0.78, l);
}
export function buildPalette(hues: number[]): Palette {
  const main = hues[0];
  const [f2, f3] = harmony(main);
  const second = hues[1] ?? f2;
  let third = hues[2] ?? (hueDist(f3, second) > 40 ? f3 : f2);
  if (hueDist(third, main) < 30) {
    third = [GLAZIER.gold, GLAZIER.ruby, GLAZIER.cobalt].find((h) => hueDist(h, main) > 40 && hueDist(h, second) > 40) ?? GLAZIER.gold;
  }
  const J = (h: number, s: number, dl = 0): HSL => [h, s, jewelL(h) + dl];
  return {
    mode: 'color', hues: [main, second, third],
    ground: J(main, 0.8), border: J(second, 0.78), figure: J(third, 0.76, 0.06), accent: J(main, 0.6, 0.1),
    pale: [44, 0.42, 0.58], ringA: J(second, 0.8), ringB: J(main, 0.84),
    lum: lumiereOf(main), glassA: hsl2rgb(main, 0.7, 0.45), glassB: hsl2rgb(second, 0.7, 0.45),
  };
}
/** Vidéo en noir et blanc : grisaille verdâtre chaude, feuillages peints, un seul accent jaune d'argent. */
export const GRISAILLE: Palette = {
  mode: 'grisaille', ground: [64, 0.09, 0.35], border: [54, 0.1, 0.39], figure: [44, 0.66, 0.5], accent: [66, 0.07, 0.44],
  pale: [56, 0.14, 0.55], ringA: [54, 0.1, 0.4], ringB: [64, 0.09, 0.36], lum: [222, 212, 178], glassA: [120, 116, 96], glassB: [150, 140, 110],
};
/** Rien en lecture : clair de lune à travers le verre clair et le jaune d'argent. */
export const MOONLIGHT: Palette = {
  mode: 'moon', ground: [218, 0.3, 0.37], border: [40, 0.2, 0.42], figure: [46, 0.46, 0.53], accent: [214, 0.16, 0.5],
  pale: [50, 0.2, 0.62], ringA: [40, 0.2, 0.42], ringB: [218, 0.3, 0.38], lum: [180, 196, 226], glassA: [110, 128, 170], glassB: [150, 150, 130],
};

/** Taille de l'échantillon : le milieu 16:9 de hqdefault réduit à 48 × 27. */
export const SAMPLE_W = 48, SAMPLE_H = 27;
/** URL de la miniature lue par le worker (i.ytimg.com répond `Access-Control-Allow-Origin: *`). */
export const thumbUrl = (id: string): string => `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;

/**
 * Pics de teinte d'un histogramme pondéré par la saturation (24 cases de 15°), trois au plus, écartés de 30°.
 * Pas de teinte exploitable (chroma moyen < 0,02) : grisaille.
 */
export function paletteFromPixels(d: ArrayLike<number>): Palette {
  const bins = Array.from({ length: 24 }, () => ({ w: 0, sx: 0, sy: 0 }));
  let chroma = 0, n = 0;
  for (let i = 0; i + 3 < d.length; i += 4) {
    const [h, s, v] = rgb2hsv(d[i], d[i + 1], d[i + 2]);
    n++;
    if (v < 0.16 || s < 0.22) continue;
    const w = Math.pow(s, 1.5) * v;
    chroma += w;
    const b = bins[Math.floor(h / 15) % 24];
    b.w += w; b.sx += Math.cos((h * Math.PI) / 180) * w; b.sy += Math.sin((h * Math.PI) / 180) * w;
  }
  if (!n || chroma / n < 0.02) return GRISAILLE;
  const peaks: { w: number; h: number }[] = [];
  bins.forEach((b, i) => {
    if (b.w) peaks.push({ w: b.w + (bins[(i + 23) % 24].w + bins[(i + 1) % 24].w) * 0.5, h: ((Math.atan2(b.sy, b.sx) * 180) / Math.PI + 360) % 360 });
  });
  peaks.sort((a, b) => b.w - a.w);
  const hues: number[] = [];
  for (const p of peaks) {
    if (hues.length >= 3) break;
    if (p.w < peaks[0].w * 0.12) break;
    if (hues.every((h) => hueDist(h, p.h) > 30)) hues.push(p.h);
  }
  return hues.length ? buildPalette(hues) : GRISAILLE;
}
```

- [ ] **Step 5 : lancer** `npm test`, puis `GREG_TEST_TRANSPILE=1 npm test` et `npx tsc --noEmit`. Attendu : 86 tests verts (71 + 15), aucune erreur de type.
  - Si la somme de contrôle `-2.374039` échoue, la géométrie a dérivé du prototype, et la pierre Blender ne tomberait plus sur les ouvertures. Il faut corriger le portage, pas la valeur attendue.

### Task 2 : worker, peinture, client et composant Rose

**Files:**
- Create: `services/web/src/lib/rose/paint.ts`, portage de `rose-worker.js` lignes 274–494 (texture de verre, géométrie en `Path2D`, motifs, feuillages, plombs, halo, pierre, bloom, anneau de l'horloge)
- Create: `services/web/src/lib/rose/rose.worker.ts` : protocole des lignes 496–514, plus le chargement de la pierre et de la miniature dans le worker
- Create: `services/web/src/lib/rose/client.ts`, portage de l'objet `Rose` de `app.js` (lignes 181–307)
- Create: `services/web/src/components/Stage/Rose.tsx`, `services/web/src/components/Stage/rose.css`
- Test: `services/web/tests/rose-client.test.mjs`

**Interfaces:**
- Consumes (tâche 1) : `buildGeometry`, `circlePoly`, `GEO`, `rng`, `TAU` et les types de `geometry.ts` ; `hslCss`, `paletteFromPixels`, `GRISAILLE`, `MOONLIGHT`, `SAMPLE_W`, `SAMPLE_H`, `thumbUrl` et `Palette` de `palette.ts`.
- Produces :

```ts
// src/lib/rose/paint.ts
export type PaintInput = { R: number; dpr: number; pal: Palette; stone: ImageBitmap | null; ringTo: number };
export type PaintOutput = { win: ImageBitmap; bloom: ImageBitmap; ring: ImageBitmap | null; head: ImageBitmap | null; W: number; BW: number; RH: number };
export function paintWindow(input: PaintInput): PaintOutput;
// src/lib/rose/rose.worker.ts
export type RoseIn = { type: 'init'; stoneUrl: string } | { type: 'paint'; key: string; id: string | null; R: number; dpr: number; ringTo: number };
export type RoseOut = ({ type: 'painted'; key: string; pal: { mode: PaletteMode; lum: RGB }; ms: [number, number] } & PaintOutput) | { type: 'failed'; key: string; error: string };
// src/lib/rose/client.ts
export const RING_TO = -0.2, READY_MAX = 3, KEEP_OTHERS = 2, FADE_MS = 900, FIRST_FADE_MS = 700, RESIZE_FADE_MS = 220, RESIZE_DEBOUNCE_MS = 200;
export const STONE_URL = '/gothique/stone-rose-2048.webp';
export const roseKey: (id: string | null, R: number, dpr: number) => string;   // 't:<id>@<R>x<dpr>' | 'moon@<R>x<dpr>'
export const keyFits: (key: string, R: number, dpr: number) => boolean; export const isMoonKey: (key: string) => boolean;
export function evictable(keys: string[], keep: (string | null | undefined)[], max?: number): string[];
export function setLumiere(rgb: RGB, el?: HTMLElement): void;   // --lumiere et --lumiere-rgb sur :root
export function roseSupported(): boolean;
export type RoseLayers = { bloom: HTMLElement; glass: HTMLElement };
export class RoseClient { constructor(layers: RoseLayers); start(): void; destroy(): void; resize(R: number): void; show(id: string | null, fade?: number): Promise<void>; prepare(id: string | null): void }
// src/components/Stage/Rose.tsx
export type RoseProps = { videoId: string | null; nextId: string | null; R: number; mask: { p0: number; p1: number } };
export default function Rose(props: RoseProps): JSX.Element;   // <div class="rosace" aria-hidden> … </div>
```

- [ ] **Step 1 : écrire le test qui échoue** (`tests/rose-client.test.mjs`). `client.ts` n'a aucun import runtime ; le `new Worker(new URL(...))` n'est évalué que dans `start()`.

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { roseKey, keyFits, isMoonKey, evictable, KEEP_OTHERS } = await loadTs('../src/lib/rose/client.ts');

test('clé d’une fenêtre : titre ou lune, à une taille et une densité', () => {
  assert.equal(roseKey('dQw4w9WgXcQ', 349, 2), 't:dQw4w9WgXcQ@349x2');
  assert.equal(roseKey(null, 349, 1), 'moon@349x1');
  assert.ok(isMoonKey('moon@349x1') && !isMoonKey('t:moon@349x1'));
});

test('une peinture arrivée pour une ancienne taille est jetée', () => {
  assert.ok(keyFits('t:a@349x2', 349, 2));
  assert.ok(!keyFits('t:a@349x2', 291, 2));
  assert.ok(!keyFits('t:a@349x2', 349, 1));
});

test('fenêtres montées : on garde la lune, l’affichée, la nouvelle et les 2 plus récentes', () => {
  assert.equal(KEEP_OTHERS, 2);
  const keys = ['moon@1x1', 't:a@1x1', 't:b@1x1', 't:c@1x1', 't:d@1x1', 't:e@1x1'];
  assert.deepEqual(evictable(keys, ['t:a@1x1', 't:e@1x1']), ['t:b@1x1']);
  assert.deepEqual(evictable(['moon@1x1', 't:a@1x1'], ['t:a@1x1']), []);
});
```

- [ ] **Step 2 : lancer** `npm test`. Attendu : FAIL (module absent).
- [ ] **Step 3 : écrire `src/lib/rose/paint.ts`.** Toutes les valeurs viennent du prototype ; seuls changent les types, le cache de géométrie (la base est gardée à part) et `paintMotif`, qui reçoit l'angle de la lancette.

```ts
/**
 * Peinture d'une fenêtre sur OffscreenCanvas (dans le worker). Repris de
 * proto-gothique/work/refine/rose-worker.js (lignes 274–494) sans changer une valeur.
 * Contextes 2D logiciels (`willReadFrequently`) : la peinture ne concurrence jamais le GPU du compositeur.
 */
import { buildGeometry, circlePoly, GEO, rng, TAU } from './geometry';
import type { BBox, Cell, Medallion, Motif, Opening, Poly } from './geometry';
import { hslCss } from './palette';
import type { Palette } from './palette';

type Ctx = OffscreenCanvasRenderingContext2D;
type PCell = Cell & { path: Path2D; bbp: BBox };
type PMed = Medallion & { px: number; py: number; pr: number; prIn: number; path: Path2D; cells: PCell[] };
type POpening = Omit<Opening, 'cells' | 'med'> & { path: Path2D; cells: PCell[]; med?: PMed };
type Resolved = { openings: POpening[]; all: Path2D; ring: Path2D };

function ctx(c: OffscreenCanvas): Ctx {
  const x = c.getContext('2d', { willReadFrequently: true });
  if (!x) throw new Error('OffscreenCanvas 2D indisponible');
  return x;
}

let TEX: OffscreenCanvas | null = null;
/** Verre « cylindre » : bruit flouté, stries, bulles d'air. Peint une fois. */
function glassTexture(): OffscreenCanvas {
  if (TEX) return TEX;
  const n = new OffscreenCanvas(64, 64), nx = ctx(n), id = nx.createImageData(64, 64);
  const r = rng(7);
  for (let i = 0; i < id.data.length; i += 4) { const v = 90 + r() * 110; id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 255; }
  nx.putImageData(id, 0, 0);
  const c = new OffscreenCanvas(512, 512), x = ctx(c);
  x.filter = 'blur(5px)'; x.drawImage(n, -16, -16, 544, 544); x.filter = 'none';
  x.globalAlpha = 0.09;
  for (let i = 0; i < 90; i++) {
    x.strokeStyle = r() > 0.5 ? '#fff' : '#000'; x.lineWidth = 1 + r() * 5; x.beginPath();
    const y = r() * 512;
    x.moveTo(0, y); x.bezierCurveTo(170, y + (r() - 0.5) * 60, 340, y + (r() - 0.5) * 60, 512, y + (r() - 0.5) * 40); x.stroke();
  }
  x.globalAlpha = 0.22; x.fillStyle = '#fff';
  for (let i = 0; i < 140; i++) { x.beginPath(); x.ellipse(r() * 512, r() * 512, 0.6 + r() * 1.4, 0.4 + r() * 0.8, r() * 3, 0, TAU); x.fill(); }
  x.globalAlpha = 1; TEX = c; return c;
}

function toPath(poly: Poly, S: number, cx: number, cy: number): Path2D {
  const p = new Path2D();
  poly.forEach(([x, y], i) => (i ? p.lineTo(cx + x * S, cy + y * S) : p.moveTo(cx + x * S, cy + y * S)));
  p.closePath();
  return p;
}
const resolveCell = (c: Cell, S: number, cx: number, cy: number): PCell =>
  ({ ...c, path: toPath(c.poly, S, cx, cy), bbp: [cx + c.bb[0] * S, cy + c.bb[1] * S, cx + c.bb[2] * S, cy + c.bb[3] * S] });

let BASE: Opening[] | null = null;
const GEOM_CACHE = new Map<string, Resolved>();
/** Géométrie résolue en Path2D pour une échelle de pixels (cache : R ne change qu'au redimensionnement). */
function geomAt(S: number, cx: number, cy: number): Resolved {
  const key = `${S.toFixed(2)}:${cx.toFixed(1)}:${cy.toFixed(1)}`;
  const hit = GEOM_CACHE.get(key);
  if (hit) return hit;
  BASE ??= buildGeometry();
  const all = new Path2D(), ring = new Path2D();
  const openings = BASE.map((o): POpening => {
    const path = toPath(o.poly, S, cx, cy);
    all.addPath(path);
    if (o.kind === 'ring') ring.addPath(path);
    const out: POpening = { ...o, path, cells: o.cells.map((c) => resolveCell(c, S, cx, cy)), med: undefined };
    if (o.med) {
      const m = o.med;
      out.med = { ...m, px: cx + m.x * S, py: cy + m.y * S, pr: m.r * S, prIn: m.rimIn * S,
        path: toPath(circlePoly(m.x, m.y, m.r, 48), S, cx, cy), cells: m.cells.map((c) => resolveCell(c, S, cx, cy)) };
    }
    return out;
  });
  const g = { openings, all, ring };
  GEOM_CACHE.set(key, g);
  if (GEOM_CACHE.size > 6) GEOM_CACHE.delete(GEOM_CACHE.keys().next().value as string);
  return g;
}

/** Figures peintes en grisaille (brun d'oxyde de fer) dans le cercle unité, « haut » = −y. */
function motif(x: Ctx, kind: Motif): void {
  x.beginPath();
  if (kind === 'crown') {
    x.moveTo(-0.62, 0.42); x.lineTo(-0.66, -0.18); x.lineTo(-0.36, 0.08); x.lineTo(0, -0.46); x.lineTo(0.36, 0.08); x.lineTo(0.66, -0.18); x.lineTo(0.62, 0.42); x.closePath();
    x.moveTo(-0.62, 0.28); x.lineTo(0.62, 0.28);
    for (const [px, py, r] of [[-0.66, -0.28, 0.09], [0, -0.58, 0.11], [0.66, -0.28, 0.09]]) { x.moveTo(px + r, py); x.arc(px, py, r, 0, TAU); }
  } else if (kind === 'fleur') {
    x.moveTo(0, -0.7); x.bezierCurveTo(0.3, -0.36, 0.22, -0.02, 0, 0.12); x.bezierCurveTo(-0.22, -0.02, -0.3, -0.36, 0, -0.7);
    x.moveTo(-0.08, 0.08); x.bezierCurveTo(-0.3, -0.26, -0.72, -0.22, -0.62, 0.08); x.bezierCurveTo(-0.56, 0.26, -0.34, 0.24, -0.3, 0.12);
    x.moveTo(0.08, 0.08); x.bezierCurveTo(0.3, -0.26, 0.72, -0.22, 0.62, 0.08); x.bezierCurveTo(0.56, 0.26, 0.34, 0.24, 0.3, 0.12);
    x.moveTo(-0.44, 0.16); x.lineTo(0.44, 0.16); x.moveTo(-0.44, 0.28); x.lineTo(0.44, 0.28);
    x.moveTo(-0.1, 0.28); x.bezierCurveTo(-0.12, 0.46, -0.28, 0.56, -0.38, 0.6); x.moveTo(0.1, 0.28); x.bezierCurveTo(0.12, 0.46, 0.28, 0.56, 0.38, 0.6); x.moveTo(0, 0.28); x.lineTo(0, 0.66);
  } else {
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + (i * TAU) / 5, px = Math.cos(a) * 0.36, py = Math.sin(a) * 0.36; x.moveTo(px + 0.3, py); x.arc(px, py, 0.3, 0, TAU); }
    x.moveTo(0.2, 0); x.arc(0, 0, 0.2, 0, TAU);
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + ((i + 0.5) * TAU) / 5; x.moveTo(Math.cos(a) * 0.5, Math.sin(a) * 0.5); x.lineTo(Math.cos(a) * 0.7, Math.sin(a) * 0.7); }
  }
}
function paintMotif(x: Ctx, m: PMed, ang: number, S: number): void {
  x.save(); x.beginPath(); x.arc(m.px, m.py, m.prIn, 0, TAU); x.clip();
  const g = x.createRadialGradient(m.px, m.py - m.prIn * 0.3, m.prIn * 0.1, m.px, m.py, m.prIn);
  g.addColorStop(0, 'rgb(40 26 14 / 0)'); g.addColorStop(0.7, 'rgb(40 26 14 / .22)'); g.addColorStop(1, 'rgb(30 18 10 / .5)');
  x.fillStyle = g; x.fillRect(m.px - m.prIn, m.py - m.prIn, m.prIn * 2, m.prIn * 2);
  x.translate(m.px, m.py); x.rotate(ang + Math.PI / 2);
  const s = m.prIn * 0.92; x.scale(s, s);
  motif(x, m.motif);
  x.lineJoin = 'round'; x.lineCap = 'round'; x.strokeStyle = 'rgb(34 20 10 / .82)'; x.lineWidth = Math.max(0.9, S * 0.0036) / s; x.stroke();
  x.fillStyle = 'rgb(34 20 10 / .18)'; x.fill('evenodd');
  x.restore();
}
/** Grisaille : un rinceau peint dans chaque lancette et des hachures croisées sur le fond. */
function paintFoliage(x: Ctx, o: POpening, S: number, cx: number, cy: number, alpha: number): void {
  x.save(); x.clip(o.path);
  const a = o.a ?? 0, ux = Math.cos(a), uy = Math.sin(a), vx = -uy, vy = ux;
  const P = (r: number, off: number): [number, number] => [cx + (ux * r + vx * off) * S, cy + (uy * r + vy * off) * S];
  x.strokeStyle = `rgb(38 26 14 / ${alpha})`; x.lineWidth = Math.max(0.8, S * 0.0028); x.lineCap = 'round';
  x.beginPath();
  for (let i = 0; i <= 40; i++) {
    const r = GEO.lanIn + 0.02 + ((GEO.lanTip - GEO.lanIn - 0.06) * i) / 40, off = Math.sin(i * 0.9) * 0.028;
    const [px, py] = P(r, off);
    if (i) x.lineTo(px, py); else x.moveTo(px, py);
  }
  x.stroke();
  for (let i = 2; i < 40; i += 4) {
    const r = GEO.lanIn + 0.02 + ((GEO.lanTip - GEO.lanIn - 0.06) * i) / 40, side = Math.sin(i * 0.9) > 0 ? 1 : -1;
    const [lx, ly] = P(r, Math.sin(i * 0.9) * 0.028 + side * 0.02);
    x.beginPath();
    for (let l = 0; l < 3; l++) { const t = a + (side * Math.PI) / 2 + (l - 1) * 0.9; x.moveTo(lx, ly); x.arc(lx + Math.cos(t) * S * 0.008, ly + Math.sin(t) * S * 0.008, S * 0.007, 0, TAU); }
    x.stroke();
  }
  x.globalAlpha = alpha * 0.45; x.lineWidth = Math.max(0.6, S * 0.0014); x.beginPath();
  const bb = o.cells.reduce<BBox>((b, c) => [Math.min(b[0], c.bbp[0]), Math.min(b[1], c.bbp[1]), Math.max(b[2], c.bbp[2]), Math.max(b[3], c.bbp[3])], [1e9, 1e9, -1e9, -1e9]);
  const sp = Math.max(3, S * 0.014);
  for (let t = bb[0] - (bb[3] - bb[1]); t < bb[2]; t += sp) { x.moveTo(t, bb[3]); x.lineTo(t + (bb[3] - bb[1]), bb[1]); }
  x.stroke(); x.restore();
}
function fillCells(x: Ctx, cells: PCell[], pal: Palette, S: number, { lit = false, dim = 0 } = {}): void {
  for (const c of cells) {
    const col = pal[c.role] || pal.ground;
    const u = c.v[0], dl = (u < 0.12 ? -0.09 : u > 0.9 ? 0.08 : (c.v[1] - 0.5) * 0.08) + (lit ? 0.2 : 0) - dim;
    x.fillStyle = hslCss(col, (c.v[2] - 0.5) * 10, dl, lit ? 0.06 : 0); x.fill(c.path);
    x.save(); x.clip(c.path);
    const bb = c.bbp, ang = c.v[3] * Math.PI;
    const mx = (bb[0] + bb[2]) / 2, my = (bb[1] + bb[3]) / 2, rad = Math.max(bb[2] - bb[0], bb[3] - bb[1]) * 0.62;
    const sg = x.createLinearGradient(mx - Math.cos(ang) * rad, my - Math.sin(ang) * rad, mx + Math.cos(ang) * rad, my + Math.sin(ang) * rad);
    sg.addColorStop(0, `rgb(255 248 230 / ${lit ? 0.3 : 0.13})`); sg.addColorStop(0.5, 'rgb(255 250 235 / 0)'); sg.addColorStop(1, 'rgb(0 0 0 / .2)');
    x.fillStyle = sg; x.fill(c.path);
    x.lineWidth = Math.max(2, S * 0.016); x.strokeStyle = 'rgb(12 7 4 / .32)'; x.stroke(c.path);
    x.restore();
  }
}
function leadCells(x: Ctx, cells: PCell[], base: number): void {
  for (const c of cells) { x.lineWidth = base * (0.72 + c.v[4] * 0.66); x.stroke(c.path); }
}

export type PaintInput = { R: number; dpr: number; pal: Palette; stone: ImageBitmap | null; ringTo: number };
export type PaintOutput = {
  win: ImageBitmap;           // verre, plombs, pierre, halo : carré de côté 2·1,06·R (résolution DPR)
  bloom: ImageBitmap;         // la lumière versée sur le mur : carré de côté 3R (DPR 1)
  ring: ImageBitmap | null;   // panneaux de l'horloge allumés (recadrage du haut) ; null au clair de lune
  head: ImageBitmap | null;   // les mêmes, plus lumineux : le panneau courant y est découpé par un masque CSS
  W: number; BW: number; RH: number;
};

/** Peint une fenêtre. Tous les canevas sont locaux : le résultat est transféré en ImageBitmap. */
export function paintWindow({ R, dpr, pal, stone, ringTo }: PaintInput): PaintOutput {
  const W = Math.round(2 * GEO.extent * R * dpr), S = R * dpr, cx = W / 2, cy = W / 2;
  const g = geomAt(S, cx, cy);
  const moon = pal.mode === 'moon', gris = pal.mode === 'grisaille';
  const base = Math.max(1.1, S * 0.0046);
  // 1. verre (les panneaux de l'horloge sont peints éteints ici ; les allumés forment leur propre calque)
  const A = new OffscreenCanvas(W, W), a = ctx(A);
  for (const o of g.openings) {
    a.save(); a.clip(o.path);
    fillCells(a, o.cells, pal, S, { dim: o.kind === 'ring' && !moon ? 0.16 : 0 });
    if (o.med) fillCells(a, o.med.cells, pal, S);
    if (o.kind === 'lancet' && (gris || moon)) paintFoliage(a, o, S, cx, cy, gris ? 0.5 : 0.28);
    a.restore();
  }
  for (const o of g.openings) if (o.med) paintMotif(a, o.med, o.a ?? 0, S);
  a.save(); a.globalCompositeOperation = 'overlay'; a.globalAlpha = 0.5; a.drawImage(glassTexture(), 0, 0, W, W); a.restore();
  a.save(); a.globalCompositeOperation = 'multiply';
  const fo = a.createRadialGradient(cx, cy, S * 0.2, cx, cy, S * 1.0);
  fo.addColorStop(0, 'rgb(242 240 236)'); fo.addColorStop(0.6, 'rgb(214 208 200)'); fo.addColorStop(1, 'rgb(140 130 120)');
  a.fillStyle = fo; a.fillRect(0, 0, W, W); a.restore();
  a.save(); a.globalCompositeOperation = 'screen';
  const hs = a.createRadialGradient(cx, cy - S * 0.95, S * 0.02, cx, cy - S * 0.6, S * 0.95);
  hs.addColorStop(0, moon ? 'rgb(200 214 240 / .3)' : 'rgb(255 238 210 / .34)'); hs.addColorStop(0.5, 'rgb(255 228 190 / .08)'); hs.addColorStop(1, 'rgb(255 230 200 / 0)');
  a.fillStyle = hs; a.fillRect(0, 0, W, W); a.restore();
  a.save(); a.globalCompositeOperation = 'destination-in'; a.fill(g.all); a.restore();
  // 2. plombs (1 à 2 px, jamais réguliers), anneaux des médaillons, barlotières
  const B = new OffscreenCanvas(W, W), b = ctx(B);
  b.drawImage(A, 0, 0);
  b.save(); b.lineJoin = 'round'; b.strokeStyle = 'rgb(10 7 5 / .96)';
  for (const o of g.openings) {
    b.save(); b.clip(o.path);
    if (o.cells.length > 1) leadCells(b, o.cells, base);
    if (o.med) {
      leadCells(b, o.med.cells, base);
      b.lineWidth = base * 1.9; b.stroke(o.med.path);
      b.beginPath(); b.arc(o.med.px, o.med.py, o.med.prIn, 0, TAU); b.lineWidth = base * 1.3; b.stroke();
    }
    b.restore();
    b.lineWidth = base * 2.2; b.stroke(o.path);
  }
  b.lineWidth = Math.max(1.8, S * 0.011); b.lineCap = 'butt';
  for (const o of g.openings) if (o.kind === 'lancet') for (const rr of [0.47, 0.75]) {
    const w = TAU / 16 / 2, oa = o.a ?? 0;
    b.beginPath();
    b.moveTo(cx + Math.cos(oa - w) * rr * S, cy + Math.sin(oa - w) * rr * S); b.lineTo(cx + Math.cos(oa + w) * rr * S, cy + Math.sin(oa + w) * rr * S); b.stroke();
  }
  b.restore();
  // 3. halo : le verre clair déborde sur le plomb sombre, dans les ouvertures
  b.save(); b.clip(g.all); b.globalCompositeOperation = 'lighter';
  b.filter = `blur(${(1.1 * dpr).toFixed(1)}px)`; b.globalAlpha = 0.26; b.drawImage(A, 0, 0); b.restore();
  // 4. la pierre (Blender), puis la lumière qui déborde sur ses arêtes (floutée à mi-taille)
  if (stone) b.drawImage(stone, 0, 0, W, W);
  const half = new OffscreenCanvas(Math.ceil(W / 2), Math.ceil(W / 2)), hx = ctx(half);
  hx.drawImage(A, 0, 0, half.width, half.height);
  b.save(); b.globalCompositeOperation = 'lighter';
  b.filter = `blur(${(1.2 * dpr).toFixed(1)}px)`; b.globalAlpha = moon ? 0.16 : 0.2; b.drawImage(half, 0, 0, W, W);
  b.filter = `blur(${(4.5 * dpr).toFixed(1)}px)`; b.globalAlpha = moon ? 0.1 : 0.13; b.drawImage(half, 0, 0, W, W);
  b.restore();
  const win = B.transferToImageBitmap();
  // la lumière sur le mur : DPR 1 (elle est floutée de toute façon), carré de côté 3R
  const BW = Math.round(3 * R), bc = BW / 2;
  const small = new OffscreenCanvas(Math.ceil(BW / 4), Math.ceil(BW / 4)), sx = ctx(small);
  sx.scale(0.25, 0.25);
  const gb = geomAt(R, bc, bc);
  for (const o of gb.openings) for (const c of o.cells) { sx.fillStyle = hslCss(pal[c.role] || pal.ground, 0, 0.1, -0.1); sx.fill(c.path); }
  const Bl = new OffscreenCanvas(BW, BW), bl = ctx(Bl);
  bl.globalCompositeOperation = 'lighter';
  bl.filter = `blur(${Math.round(R * 0.05)}px)`; bl.globalAlpha = 0.3; bl.drawImage(small, 0, 0, BW, BW);
  bl.filter = `blur(${Math.round(R * 0.14)}px)`; bl.globalAlpha = 0.4; bl.drawImage(small, 0, 0, BW, BW);
  bl.filter = `blur(${Math.round(R * 0.32)}px)`; bl.globalAlpha = 0.38; bl.drawImage(small, 0, 0, BW, BW);
  const bloom = Bl.transferToImageBitmap();
  // l'horloge : les panneaux de l'anneau allumés (recadrage du haut seulement), et les mêmes plus vifs
  let ring: ImageBitmap | null = null, head: ImageBitmap | null = null, RH = 0;
  if (!moon) {
    RH = Math.round((W * (GEO.extent + ringTo)) / (2 * GEO.extent));
    const rings = g.openings.filter((o) => o.kind === 'ring');
    const L = new OffscreenCanvas(W, RH), l = ctx(L);
    for (const o of rings) { l.save(); l.clip(o.path); fillCells(l, o.cells, pal, S, { lit: true }); l.restore(); }
    l.save(); l.globalCompositeOperation = 'overlay'; l.globalAlpha = 0.45; l.drawImage(glassTexture(), 0, 0, W, W); l.restore();
    l.save(); l.globalCompositeOperation = 'destination-in'; l.fill(g.ring); l.restore();
    const paintRing = (boost: boolean): ImageBitmap => {
      const Rg = new OffscreenCanvas(W, RH), r = ctx(Rg);
      if (boost) r.filter = 'brightness(1.6) saturate(1.2)';
      r.drawImage(L, 0, 0); r.filter = 'none';
      r.save(); r.strokeStyle = 'rgb(10 7 5 / .95)';
      for (const o of rings) { r.save(); r.clip(o.path); leadCells(r, o.cells, base); r.restore(); }
      r.restore();
      if (stone) r.drawImage(stone, 0, 0, W, W);
      r.save(); r.globalCompositeOperation = 'lighter';
      r.filter = `blur(${(1.2 * dpr).toFixed(1)}px)`; r.globalAlpha = boost ? 0.62 : 0.4; r.drawImage(L, 0, 0);
      r.filter = `blur(${(3 * dpr).toFixed(1)}px)`; r.globalAlpha = boost ? 0.56 : 0.3; r.drawImage(L, 0, 0);
      r.filter = `blur(${(10 * dpr).toFixed(1)}px)`; r.globalAlpha = boost ? 0.44 : 0.2; r.drawImage(L, 0, 0);
      r.restore();
      return Rg.transferToImageBitmap();
    };
    ring = paintRing(false); head = paintRing(true);
  }
  return { win, bloom, ring, head, W, BW, RH };
}
```

- [ ] **Step 4 : écrire `src/lib/rose/rose.worker.ts`.**
  - Le lib TypeScript du projet est `dom` : ne pas ajouter `/// <reference lib="webworker" />`, qui entre en conflit avec le DOM. La portée du worker est typée à la main (`Scope`).
  - La pierre est lue dans le worker : l'URL doit être absolue, car une URL relative se résoudrait contre le chunk du worker.

```ts
/**
 * Worker de la rosace (module worker, créé par client.ts avec `new Worker(new URL(...), import.meta.url)`).
 * Il lit la pierre et la miniature, extrait la palette, peint la fenêtre sur OffscreenCanvas et renvoie
 * des ImageBitmap transférées : le fil principal ne fait qu'échanger des canevas.
 * Protocole repris de proto-gothique/work/refine/rose-worker.js (lignes 496–514).
 */
import { paintWindow } from './paint';
import type { PaintOutput } from './paint';
import { GRISAILLE, MOONLIGHT, SAMPLE_H, SAMPLE_W, paletteFromPixels, thumbUrl } from './palette';
import type { Palette, PaletteMode, RGB } from './palette';

export type RoseIn =
  | { type: 'init'; stoneUrl: string }
  | { type: 'paint'; key: string; id: string | null; R: number; dpr: number; ringTo: number };
export type RoseOut =
  | ({ type: 'painted'; key: string; pal: { mode: PaletteMode; lum: RGB }; ms: [number, number] } & PaintOutput)
  | { type: 'failed'; key: string; error: string };

// Le lib TS du projet est « dom » : on type à la main la portée du worker.
type Scope = { onmessage: ((e: MessageEvent<RoseIn>) => void) | null; postMessage(m: RoseOut, transfer?: Transferable[]): void };
const scope = self as unknown as Scope;

let stone: Promise<ImageBitmap | null> = Promise.resolve(null);
const palettes = new Map<string, Palette>();

async function loadStone(url: string): Promise<ImageBitmap | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await createImageBitmap(await res.blob());
  } catch { return null; }
}

/** Milieu 16:9 de hqdefault (4:3 à bandes noires) réduit à 48 × 27, puis histogramme des teintes. */
async function extractPalette(id: string): Promise<Palette> {
  try {
    const res = await fetch(thumbUrl(id), { mode: 'cors' });
    if (!res.ok) return GRISAILLE;
    const bm = await createImageBitmap(await res.blob());
    const c = new OffscreenCanvas(SAMPLE_W, SAMPLE_H);
    const x = c.getContext('2d', { willReadFrequently: true });
    if (!x) { bm.close(); return GRISAILLE; }
    x.drawImage(bm, 0, bm.height * 0.125, bm.width, bm.height * 0.75, 0, 0, SAMPLE_W, SAMPLE_H);
    bm.close();
    return paletteFromPixels(x.getImageData(0, 0, SAMPLE_W, SAMPLE_H).data);
  } catch { return GRISAILLE; }
}

scope.onmessage = async (e) => {
  const m = e.data;
  if (m.type === 'init') { stone = loadStone(m.stoneUrl); return; }
  try {
    const t0 = performance.now();
    let pal: Palette;
    if (!m.id) pal = MOONLIGHT;
    else {
      const known = palettes.get(m.id);
      pal = known ?? (await extractPalette(m.id));
      if (!known) {
        palettes.set(m.id, pal);
        if (palettes.size > 64) palettes.delete(palettes.keys().next().value as string);
      }
    }
    const t1 = performance.now();
    const out = paintWindow({ R: m.R, dpr: m.dpr, pal, stone: await stone, ringTo: m.ringTo });
    const transfer: Transferable[] = [out.win, out.bloom];
    if (out.ring && out.head) transfer.push(out.ring, out.head);
    scope.postMessage({ type: 'painted', key: m.key, pal: { mode: pal.mode, lum: pal.lum }, ...out, ms: [Math.round(t1 - t0), Math.round(performance.now() - t1)] }, transfer);
  } catch (err) {
    scope.postMessage({ type: 'failed', key: m.key, error: String(err) });
  }
};
```

- [ ] **Step 5 : écrire `src/lib/rose/client.ts`.**

```ts
/**
 * Côté fil principal de la rosace : pilote le worker et échange des canevas `bitmaprenderer`.
 * Repris de l'objet `Rose` (proto-gothique/work/refine/src/app.js, lignes 181–307).
 * - Une fenêtre est peinte une fois par titre et par taille, dans le worker.
 * - La fenêtre du PROCHAIN titre est préparée pendant les temps morts, puis montée invisible
 *   (textures déjà envoyées au GPU le moment venu).
 * - Tant qu'une fenêtre n'est pas prête, l'ancienne reste affichée.
 * Sans import runtime : les fonctions exportées sont testées (tests/rose-client.test.mjs).
 */
import type { RoseIn, RoseOut } from './rose.worker';
import type { RGB } from './palette';

export const RING_TO = -0.2;          // bas du recadrage de l'anneau (même valeur que lib/stage/layout.ts)
export const READY_MAX = 3;           // fenêtres peintes pas encore montées
export const KEEP_OTHERS = 2;         // fenêtres montées gardées en plus de la lune et de l'affichée
export const STONE_URL = '/gothique/stone-rose-2048.webp';
export const FADE_MS = 900;           // --dur-ambient : la rosace se rallume
export const FIRST_FADE_MS = 700;
export const RESIZE_FADE_MS = 220;
export const RESIZE_DEBOUNCE_MS = 200;

export type Painted = Extract<RoseOut, { type: 'painted' }>;
type Slot = { key: string; lum: RGB; bloom: HTMLDivElement; glass: HTMLDivElement };
export type RoseLayers = { bloom: HTMLElement; glass: HTMLElement };

/** Clé d'une fenêtre : un titre (ou la lune) à une taille et une densité de pixels. */
export const roseKey = (id: string | null, R: number, dpr: number): string => `${id ? `t:${id}` : 'moon'}@${R}x${dpr}`;
export const keyFits = (key: string, R: number, dpr: number): boolean => key.endsWith(`@${R}x${dpr}`);
export const isMoonKey = (key: string): boolean => key.startsWith('moon@');

/** Fenêtres montées à retirer : ni la lune, ni celles à garder, au-delà des `max` plus récentes. */
export function evictable(keys: string[], keep: (string | null | undefined)[], max = KEEP_OTHERS): string[] {
  const others = keys.filter((k) => !isMoonKey(k) && !keep.includes(k));
  return others.slice(0, Math.max(0, others.length - max));
}

/** La lumière du morceau, posée sur :root (--lumiere et --lumiere-rgb, tokens.css). */
export function setLumiere([r, g, b]: RGB, el: HTMLElement = document.documentElement): void {
  el.style.setProperty('--lumiere-rgb', `${r} ${g} ${b}`);
  el.style.setProperty('--lumiere', `rgb(${r} ${g} ${b})`);
}

/** Moteur capable de peindre hors du fil principal ? Sinon, rosace statique (spec §7). */
export function roseSupported(): boolean {
  return typeof Worker !== 'undefined' && typeof OffscreenCanvas !== 'undefined' && typeof createImageBitmap === 'function';
}

const idle = (fn: () => void): void => {
  const ric = (globalThis as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
  if (ric) ric(fn, { timeout: 1500 }); else setTimeout(fn, 1);
};

export class RoseClient {
  private layers: RoseLayers;
  private worker: Worker | null = null;
  private R = 0;
  private dpr = 1;
  private gen = 0;
  private want: string | null = null;              // titre voulu à l'écran (null = clair de lune)
  private cur: Slot | null = null;
  private pre: Slot | null = null;
  private built = new Map<string, Slot>();
  private ready = new Map<string, Painted>();
  private waits = new Map<string, { p: Promise<Painted | null>; res: (d: Painted | null) => void }>();
  private busyUntil = 0;
  private resizeTimer: ReturnType<typeof setTimeout> | undefined;
  private dead = false;

  constructor(layers: RoseLayers) { this.layers = layers; }

  start(): void {
    if (this.worker || this.dead) return;
    this.worker = new Worker(new URL('./rose.worker.ts', import.meta.url), { type: 'module' });
    this.worker.onmessage = (e: MessageEvent<RoseOut>) => this.onMessage(e.data);
    this.post({ type: 'init', stoneUrl: new URL(STONE_URL, location.origin).href });
  }

  destroy(): void {
    this.dead = true;
    clearTimeout(this.resizeTimer);
    this.worker?.terminate(); this.worker = null;
    for (const d of this.ready.values()) this.close(d);
    this.ready.clear();
    for (const w of this.waits.values()) w.res(null);
    this.waits.clear();
    for (const s of this.built.values()) { s.bloom.remove(); s.glass.remove(); }
    this.built.clear(); this.cur = null; this.pre = null;
  }

  /** Nouvelle taille : la fenêtre affichée est mise à l'échelle par la CSS jusqu'à la nouvelle peinture. */
  resize(R: number): void {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (!R || (R === this.R && dpr === this.dpr)) return;
    const first = !this.R;
    this.R = R; this.dpr = dpr;
    for (const d of this.ready.values()) this.close(d);
    this.ready.clear();
    for (const [k, s] of this.built) if (s !== this.cur) { s.bloom.remove(); s.glass.remove(); this.built.delete(k); }
    clearTimeout(this.resizeTimer);
    this.resizeTimer = setTimeout(() => {
      void this.request(null).then((d) => { if (d) this.build(d); });   // la lune, prête d'avance
      void this.show(this.want, first ? 0 : RESIZE_FADE_MS);
    }, first ? 0 : RESIZE_DEBOUNCE_MS);
  }

  /** Affiche la fenêtre d'un titre (null = clair de lune). L'ancienne reste tant que la nouvelle n'est pas peinte. */
  async show(id: string | null, fade = FADE_MS): Promise<void> {
    this.want = id;
    if (!this.R || !this.worker) return;
    const key = roseKey(id, this.R, this.dpr), my = ++this.gen;
    if (this.cur?.key === key) { setLumiere(this.cur.lum); return; }
    let slot = this.built.get(key);
    if (!slot) {
      const d = await this.request(id);
      if (my !== this.gen || !d || this.dead) return;
      slot = this.build(d);
    }
    if (my !== this.gen) return;
    this.swap(slot, fade);
  }

  /** Peint d'avance la fenêtre d'un titre (le prochain), jamais pendant une cérémonie. */
  prepare(id: string | null): void {
    if (!id || !this.R || !this.worker) return;
    const key = roseKey(id, this.R, this.dpr);
    if (this.built.has(key) || this.ready.has(key) || this.waits.has(key)) return;
    const go = (): void => {
      const wait = this.busyUntil - performance.now();
      if (wait > 0) { setTimeout(go, wait + 30); return; }
      idle(() => { void this.request(id); });
    };
    go();
  }

  private post(m: RoseIn): void { this.worker?.postMessage(m); }

  private request(id: string | null): Promise<Painted | null> {
    const key = roseKey(id, this.R, this.dpr);
    const ready = this.ready.get(key);
    if (ready) return Promise.resolve(ready);
    const waiting = this.waits.get(key);
    if (waiting) return waiting.p;
    let res!: (d: Painted | null) => void;
    const p = new Promise<Painted | null>((r) => { res = r; });
    this.waits.set(key, { p, res });
    this.post({ type: 'paint', key, id, R: this.R, dpr: this.dpr, ringTo: RING_TO });
    return p;
  }

  private onMessage(m: RoseOut): void {
    const w = this.waits.get(m.key);
    this.waits.delete(m.key);
    if (m.type === 'failed') { console.warn('rosace : peinture impossible', m.error); w?.res(null); return; }
    if (this.dead || !keyFits(m.key, this.R, this.dpr)) { this.close(m); w?.res(null); return; }   // peinte pour une ancienne taille
    this.ready.set(m.key, m);
    while (this.ready.size > READY_MAX) {
      const [k, d] = this.ready.entries().next().value as [string, Painted];
      this.ready.delete(k); this.close(d);
    }
    w?.res(m);
    if (!isMoonKey(m.key)) this.premount(m.key);
  }

  /** Monte une fenêtre prête, invisible, pendant un temps mort : ses textures partent au GPU avant la cérémonie. */
  private premount(key: string): void {
    idle(() => {
      const d = this.ready.get(key);
      if (!d || this.dead || this.cur?.key === key || performance.now() < this.busyUntil) return;
      const slot = this.build(d);
      if (this.pre && this.pre !== this.cur && this.pre !== slot) { this.pre.bloom.remove(); this.pre.glass.remove(); }
      this.pre = slot;
      for (const el of [slot.bloom, slot.glass]) { el.style.opacity = '.001'; el.style.zIndex = '0'; }
      this.layers.bloom.appendChild(slot.bloom);
      this.layers.glass.appendChild(slot.glass);
    });
  }

  private close(d: Painted): void { for (const b of [d.win, d.bloom, d.ring, d.head]) b?.close(); }

  private build(d: Painted): Slot {
    const known = this.built.get(d.key);
    if (known) return known;
    this.ready.delete(d.key);
    const cv = (bm: ImageBitmap, cls: string): HTMLCanvasElement => {
      const c = document.createElement('canvas');
      c.className = cls; c.width = bm.width; c.height = bm.height;
      const r = c.getContext('bitmaprenderer');
      if (r) r.transferFromImageBitmap(bm); else { c.getContext('2d')?.drawImage(bm, 0, 0); bm.close(); }
      return c;
    };
    const bloom = document.createElement('div');
    bloom.className = 'slot'; bloom.appendChild(cv(d.bloom, 'bloom'));
    const glass = document.createElement('div');
    glass.className = 'slot'; glass.dataset.kind = isMoonKey(d.key) ? 'moon' : 'song';
    glass.appendChild(cv(d.win, 'win'));
    if (d.ring && d.head) glass.append(cv(d.ring, 'ring'), cv(d.head, 'head'));
    const slot: Slot = { key: d.key, lum: d.pal.lum, bloom, glass };
    this.built.set(d.key, slot);
    // on garde : la lune, l'affichée, la nouvelle, et les deux plus récentes (retour arrière, annulation)
    for (const k of evictable([...this.built.keys()], [this.cur?.key, d.key])) {
      const s = this.built.get(k);
      if (s && s !== this.pre) { s.bloom.remove(); s.glass.remove(); }
      this.built.delete(k);
    }
    return slot;
  }

  private swap(slot: Slot, fade: number): void {
    const old = this.cur;
    this.cur = slot;
    if (this.pre === slot) this.pre = null;
    if (!slot.glass.isConnected) { this.layers.bloom.appendChild(slot.bloom); this.layers.glass.appendChild(slot.glass); }
    for (const el of [slot.bloom, slot.glass]) { el.style.opacity = ''; el.style.zIndex = '2'; }
    if (old) for (const el of [old.bloom, old.glass]) el.style.zIndex = '1';
    setLumiere(slot.lum);   // instantané : caché dans le fondu de la rosace (DESIGN §5, écart 4)
    const done = (): void => { if (old && old !== this.cur) { old.bloom.remove(); old.glass.remove(); } };
    if (fade && old) {
      this.busyUntil = performance.now() + fade + 60;
      // Jour ↔ nuit : la lune (rose entière) et un titre (rose coupée au linteau) ne se recouvrent pas,
      // l'ancienne s'efface donc aussi ; entre deux titres, elle reste opaque dessous (pas de creux de lumière).
      const out = old.glass.dataset.kind !== slot.glass.dataset.kind ? 0 : 1;
      for (const el of [slot.bloom, slot.glass]) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: fade, easing: 'ease', fill: 'backwards' });
      old.bloom.animate([{ opacity: 1 }, { opacity: 0 }], { duration: fade, easing: 'ease', fill: 'forwards' });
      old.glass.animate([{ opacity: 1 }, { opacity: out }], { duration: fade, easing: 'ease', fill: 'forwards' }).finished.then(done, done);
    } else if (!old) {
      for (const el of [slot.bloom, slot.glass]) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FIRST_FADE_MS, easing: 'ease', fill: 'backwards' });
    } else done();
  }
}
```

- [ ] **Step 6 : écrire `src/components/Stage/Rose.tsx` et `src/components/Stage/rose.css`.** La feuille n'est importée dans `globals.css` qu'à la tâche 8.

```tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { RoseClient, roseSupported } from '@/lib/rose/client';

export type RoseProps = {
  videoId: string | null;              // titre dont le verre est affiché ; null = clair de lune
  nextId: string | null;               // prochain titre : sa fenêtre est peinte d'avance
  R: number;                           // rayon du vitrail (useStageLayout) ; 0 tant qu'inconnu
  mask: { p0: number; p1: number };    // panneaux de l'horloge déjà joués / courant (paneMask, degrés)
};

/**
 * La rosace (spec §4) : bloom et verre, deux calques remplis par RoseClient (canevas bitmaprenderer).
 * Décorative : aria-hidden. Moteur sans OffscreenCanvas : la pierre seule, immobile (spec §7).
 * Styles : rose.css. Le masque de l'horloge passe par --p0 / --p1 sur la racine.
 */
export default function Rose({ videoId, nextId, R, mask }: RoseProps) {
  const bloomRef = useRef<HTMLDivElement>(null);
  const glassRef = useRef<HTMLDivElement>(null);
  const client = useRef<RoseClient | null>(null);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    if (!roseSupported() || !bloomRef.current || !glassRef.current) { setSupported(false); return; }
    const c = new RoseClient({ bloom: bloomRef.current, glass: glassRef.current });
    client.current = c;
    c.start();
    return () => { c.destroy(); client.current = null; };
  }, []);

  useEffect(() => { if (R) client.current?.resize(R); }, [R]);
  useEffect(() => { void client.current?.show(videoId); }, [videoId]);
  useEffect(() => { client.current?.prepare(nextId); }, [nextId, R]);

  const style = { '--p0': mask.p0, '--p1': mask.p1 } as CSSProperties;
  return (
    <div className="rosace" aria-hidden="true" style={style}>
      <div className="dim">
        <div className="bloom-layer" ref={bloomRef}/>
        <div className="glass-layer" ref={glassRef}>
          {!supported && (
            <div className="slot" data-kind={videoId ? 'song' : 'moon'}>
              <img className="stone-still" src="/gothique/stone-rose-2048.webp" alt="" decoding="async"/>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

```css
/* ═══════════════════════════════════════════════════════════════════════════
   NUIT GOTHIQUE : la rosace (pierre Blender + verre peint dans un worker, lib/rose).
   Repris de proto-gothique/work/refine/src/styles.css (lignes 205–233). Écarts voulus :
   - la coupe jour / nuit est portée par chaque fenêtre (data-kind), jamais animée : le passage
     jour ↔ nuit est le fondu d'opacité de RoseClient (on n'anime que transform et opacity) ;
   - --p0 / --p1 (masque de l'horloge) valent 0 par défaut : sans eux, le masque serait invalide
     et tout l'anneau s'allumerait.
   Variables lues : --R --clip-day --clip-night --ring-h --a0 (posées sur .stage), --p0 --p1 (Rose.tsx).
   ═══════════════════════════════════════════════════════════════════════════ */
.rosace {
  --p0: 0; --p1: 0;
  position: absolute; left: 50%; top: 0; z-index: 0; pointer-events: none;
  width: calc(2.12 * var(--R)); height: calc(2.12 * var(--R)); margin-left: calc(-1.06 * var(--R));
}
.rosace .dim { position: absolute; inset: 0; transition: opacity 700ms ease; }
.stage[data-paused=true] .rosace .dim { opacity: .42; }
.rosace .slot { position: absolute; inset: 0; }

/* chaque calque isole sa pile : le z-index d'une fenêtre (la nouvelle sur l'ancienne) ne passe jamais le bloom devant le verre */
.rosace .bloom-layer { position: absolute; left: 50%; top: 50%; width: 0; height: 0; z-index: 0; isolation: isolate; }
.rosace .bloom-layer canvas {
  position: absolute; left: calc(-1.5 * var(--R)); top: calc(-1.5 * var(--R));
  width: calc(3 * var(--R)); height: calc(3 * var(--R));
}
/* la nuit, pas de halo laiteux sous le texte : le bas du bloom s'efface */
.stage[data-scene=night] .rosace .bloom-layer canvas {
  -webkit-mask: linear-gradient(#000 48%, transparent 66%); mask: linear-gradient(#000 48%, transparent 66%);
}

/* le bas de la rose s'enfonce dans l'ombre sous le texte de nuit (masque fixe : le jour, cette partie est coupée) */
.rosace .glass-layer {
  position: absolute; inset: 0; z-index: 1; isolation: isolate;
  -webkit-mask: linear-gradient(#000 calc(1.14 * var(--R)), transparent calc(1.74 * var(--R)));
  mask: linear-gradient(#000 calc(1.14 * var(--R)), transparent calc(1.74 * var(--R)));
}
/* un titre : la rose coupée au linteau ; la lune : la rose entière (coupe rectangulaire, jamais animée) */
.rosace .glass-layer .slot { clip-path: inset(0 0 var(--clip-day) 0); }
.rosace .glass-layer .slot[data-kind=moon] { clip-path: inset(0 0 var(--clip-night) 0); }
.rosace .glass-layer canvas, .rosace .stone-still { position: absolute; left: 0; top: 0; width: 100%; }
.rosace canvas.win, .rosace .stone-still { height: 100%; }

/* l'horloge : les panneaux joués (ring) et le panneau courant, plus vif (head), découpés par deux masques
   coniques centrés sur la rose ; les masques ne changent qu'une fois par panneau (Rose.tsx) */
.rosace canvas.ring, .rosace canvas.head { height: var(--ring-h); }
.rosace canvas.ring {
  -webkit-mask: conic-gradient(from calc(var(--a0) * 1deg) at 50% calc(1.06 * var(--R)), #000 calc(var(--p0) * 1deg), transparent 0);
  mask: conic-gradient(from calc(var(--a0) * 1deg) at 50% calc(1.06 * var(--R)), #000 calc(var(--p0) * 1deg), transparent 0);
}
.rosace canvas.head {
  -webkit-mask: conic-gradient(from calc(var(--a0) * 1deg) at 50% calc(1.06 * var(--R)), transparent calc(var(--p0) * 1deg), #000 0 calc(var(--p1) * 1deg), transparent 0);
  mask: conic-gradient(from calc(var(--a0) * 1deg) at 50% calc(1.06 * var(--R)), transparent calc(var(--p0) * 1deg), #000 0 calc(var(--p1) * 1deg), transparent 0);
}
.stage[data-scene=night] .rosace canvas.ring, .stage[data-scene=night] .rosace canvas.head { visibility: hidden; }

@media (prefers-reduced-motion: reduce) { .rosace .dim { transition-duration: 200ms; } }
```

- [ ] **Step 7 : lancer** `npm test`, `npx tsc --noEmit`, puis `npx next build`. Attendu : tests verts, aucune erreur de type, build réussi.
  - `Rose` n'est monté qu'à la tâche 8 : le chunk du worker n'apparaît qu'à ce moment-là (vérifié à la tâche 8, étape 8).

### Task 3 : mise en page et horloge (pur) et `useStageLayout`

**Files:**
- Create: `services/web/src/lib/stage/layout.ts`, portage de `layout()` (`app.js` lignes 364–406)
- Create: `services/web/src/lib/stage/dial.ts`, portage de `Dial` (`app.js` lignes 309–337), en lecture seule
- Create: `services/web/src/hooks/useStageLayout.ts`
- Test: `services/web/tests/stageLayout.test.mjs`, `services/web/tests/dial.test.mjs`

**Interfaces:**
- Consumes : rien.
- Produces :

```ts
// src/lib/stage/layout.ts
export const EXT = 1.06, RHO = 0.52, RING_TO = -0.2, C_FULL = 0.3, C_MAX = 0.64, C_MOBILE = 0.42, VIDEO_PREF = 560,
  SPRING_ROOM = 72, MOBILE_MAX = 900, R_MIN = 110, R_MOBILE_MAX = 260, BELOW_GAP = 6;
export type StageInput = { colW: number; colH: number; belowH: number; viewportW: number };
export type StageLayout = { mobile: boolean; R: number; c: number; vw: number; f: number; crown: number; cR: number; heart: number;
  ringH: number; clipDay: number; clipNight: number; springs: 'spring' | 'row' };
export const fOf: (R: number) => number;
export function solveStageLayout(i: StageInput): StageLayout;
export function stageCssVars(l: StageLayout): Record<string, string>;   // --R --vw --f --crown --cR --heart --ring-h --clip-day --clip-night
export function sameLayout(a: StageLayout | null, b: StageLayout | null): boolean;
// src/lib/stage/dial.ts
export const PANES = 48, PANE_DEG = 7.5, RING_MID = 0.925;
export type DialGeometry = { K: number; n: number; a0: number };
export function dialGeometry(c: number): DialGeometry;
export function clockPane(pos: number, dur: number, n: number): number;          // -1 sans durée
export function paneMask(i: number): { p0: number; p1: number };                 // degrés
export function paneAtPoint(dx: number, dy: number, dial: DialGeometry): number;
export function paneTime(i: number, n: number, dur: number): number;
export function hitArcPath(dial: DialGeometry): string;                           // SVG, viewBox -1.06 -1.06 2.12 2.12
export function fmtSpoken(sec: number | null | undefined): string;               // « 1 min 32 »
// src/hooks/useStageLayout.ts
export function useStageLayout(colRef: RefObject<HTMLElement>, belowRef: RefObject<HTMLElement>): StageLayout | null;
```

- [ ] **Step 1 : écrire les tests qui échouent.**
  - Les entrées des 8 tailles d'écran ont été **mesurées sur le prototype** dans Chrome (`?clean&still`) : `clientWidth` et `clientHeight` de `#stage-col`, `offsetHeight` de `#below`.
  - `out` est ce que calcule le prototype. `design` est le tableau de DESIGN §12.4 : le prototype en diffère de 6 px au plus sur la vidéo et de 2 px sur la couronne.

`tests/stageLayout.test.mjs` :

```js
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
```

`tests/dial.test.mjs` :

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { dialGeometry, clockPane, paneMask, paneAtPoint, paneTime, hitArcPath, fmtSpoken, PANE_DEG } = await loadTs('../src/lib/stage/dial.ts');

test('arc visible selon la corde (valeurs du prototype)', () => {
  assert.deepEqual(dialGeometry(0.3), { K: 9, n: 19, a0: -71.25 });
  assert.deepEqual(dialGeometry(0.42), { K: 8, n: 17, a0: -63.75 });
  assert.deepEqual(dialGeometry(0.64), { K: 5, n: 11, a0: -41.25 });
  assert.equal(dialGeometry(0.95).K, 3);   // jamais moins de 7 panneaux
});

test('panneau courant : un par tranche de durée, −1 sans durée', () => {
  assert.equal(clockPane(0, 213, 19), 0);
  assert.equal(clockPane(41, 213, 19), 3);
  assert.equal(clockPane(213, 213, 19), 18);   // fin : dernier panneau, jamais n
  assert.equal(clockPane(500, 213, 19), 18);
  assert.equal(clockPane(10, 0, 19), -1);
  assert.equal(clockPane(Number.NaN, 213, 19), -1);
});

test('le masque ne change qu’au changement de panneau (≈ 11 s pour 3 min 30)', () => {
  const dur = 210, n = 19;
  let changes = 0, last = clockPane(0, dur, n);
  for (let t = 0; t <= dur; t += 0.25) { const i = clockPane(t, dur, n); if (i !== last) { changes++; last = i; } }
  assert.equal(changes, n - 1);
  assert.deepEqual(paneMask(3), { p0: 3 * PANE_DEG, p1: 4 * PANE_DEG });
  assert.deepEqual(paneMask(-1), { p0: 0, p1: 0 });
});

test('survol : panneau sous le pointeur et temps affiché', () => {
  const dial = dialGeometry(0.3);
  assert.equal(paneAtPoint(0, -100, dial), 9);          // en haut : le panneau du milieu
  assert.equal(paneAtPoint(-100, -30, dial), 0);        // loin à gauche : borné au premier
  assert.equal(paneAtPoint(100, -30, dial), 18);        // loin à droite : borné au dernier
  assert.equal(paneTime(9, 19, 190), 90);
  assert.equal(paneTime(3, 19, 0), 0);
});

test('zone de survol : un arc SVG le long des panneaux visibles', () => {
  assert.equal(hitArcPath(dialGeometry(0.3)), 'M-0.8759 -0.2973A0.925 0.925 0 0 1 0.8759 -0.2973');
});

test('durée dite pour les lecteurs d’écran', () => {
  assert.equal(fmtSpoken(45), '45 s');
  assert.equal(fmtSpoken(92), '1 min 32');
  assert.equal(fmtSpoken(3725), '1 h 02 min 05');
  assert.equal(fmtSpoken(null), '');
  assert.equal(fmtSpoken(-1), '');
});
```

- [ ] **Step 2 : lancer** `npm test`. Attendu : FAIL (modules absents).
- [ ] **Step 3 : écrire `src/lib/stage/layout.ts`.**

```ts
/**
 * Mise en page de la scène : tout découle d'un nombre, R, le rayon du vitrail (DESIGN §12.4).
 * Repris de `layout()` (proto-gothique/work/refine/src/app.js, lignes 364–406) : même algorithme,
 * mêmes constantes. Pur, sans import runtime (tests/stageLayout.test.mjs).
 *
 * 1. Couronne pleine (c = 0,3 : 70 % du rayon visible) aussi grande que possible.
 * 2. Si la vidéo passerait sous 560 px : on abaisse d'abord la couronne (c jusqu'à 0,64).
 * 3. Seulement ensuite, on réduit la vidéo.
 */

export const EXT = 1.06;          // demi-côté du carré peint (disque de pierre + moulure), en R
export const RHO = 0.52;          // R = RHO × largeur de la vidéo : la base de la rose touche le linteau
export const RING_TO = -0.2;      // bas du recadrage de l'anneau des panneaux (en R, depuis le centre)
export const C_FULL = 0.3;        // corde de coupe : 70 % du rayon visible
export const C_MAX = 0.64;        // couronne la plus basse avant de réduire la vidéo
export const C_MOBILE = 0.42;
export const VIDEO_PREF = 560;    // largeur de vidéo sous laquelle on abaisse d'abord la couronne
export const SPRING_ROOM = 72;    // place d'un libellé de temps à chaque naissance de l'arc
export const MOBILE_MAX = 900;    // une colonne (même seuil que la CSS)
export const R_MIN = 110;
export const R_MOBILE_MAX = 260;
export const BELOW_GAP = 6;

export type StageInput = {
  colW: number;       // largeur intérieure de la colonne de scène (clientWidth)
  colH: number;       // hauteur intérieure de la colonne de scène (clientHeight)
  belowH: number;     // hauteur du bloc sous le portail (titre, transport, note)
  viewportW: number;  // innerWidth
};
export type StageLayout = {
  mobile: boolean;
  R: number;          // rayon du vitrail (px)
  c: number;          // hauteur de la corde de coupe, en R au-dessus du centre
  vw: number;         // largeur de la vidéo (px)
  f: number;          // épaisseur des piédroits de pierre (px)
  crown: number;      // hauteur de rose visible au-dessus du linteau (px)
  cR: number;         // c·R arrondi (px)
  heart: number;      // diamètre de l'oculus (couronne, portrait) la nuit (px)
  ringH: number;      // hauteur du recadrage de l'anneau (px)
  clipDay: number;    // rognage bas du vitrail le jour (px)
  clipNight: number;  // rognage bas du vitrail la nuit (px)
  springs: 'spring' | 'row';  // temps aux naissances de l'arc, ou en ligne sous le portail
};

export const fOf = (R: number): number => Math.max(10, Math.round(0.05 * R));

export function solveStageLayout({ colW, colH, belowH, viewportW }: StageInput): StageLayout {
  const mobile = viewportW <= MOBILE_MAX;
  let R: number, c: number, vw: number;
  if (mobile) {
    c = C_MOBILE;
    R = Math.floor(Math.min(colW / 2.12, R_MOBILE_MAX));
    vw = Math.round(colW - 2 * fOf(R));
  } else {
    const H = colH - belowH - BELOW_GAP;
    const total = (r: number, cc: number) => r * (EXT - cc) + 2 * fOf(r) + ((r / RHO) * 9) / 16;
    const solveR = (cc: number) => {
      let lo = 80, hi = 1200;
      for (let i = 0; i < 32; i++) { const m = (lo + hi) / 2; if (total(m, cc) <= H) lo = m; else hi = m; }
      return lo;
    };
    const Rw = (colW - 2 * SPRING_ROOM) / 2.12;   // la rose et la place des deux libellés de temps
    c = C_FULL;
    R = Math.min(solveR(C_FULL), Rw);
    const Rpref = VIDEO_PREF * RHO;
    if (R < Rpref && Rw > R) {
      R = Math.min(Rw, Rpref);
      c = EXT - (H - 2 * fOf(R) - ((R / RHO) * 9) / 16) / R;
      if (c > C_MAX) { c = C_MAX; R = solveR(C_MAX); }
      c = Math.max(C_FULL, c);
    }
    R = Math.max(R_MIN, Math.floor(R));
    vw = Math.round(R / RHO);
  }
  const f = fOf(R), crown = Math.round(R * (EXT - c));
  return {
    mobile, R, c, vw, f, crown,
    cR: Math.round(c * R),
    heart: Math.round(Math.max(84, Math.min(160, R * 0.46))),
    ringH: Number((R * (EXT + RING_TO)).toFixed(1)),
    clipDay: Number((2.12 * R - (crown + f * 0.5)).toFixed(1)),
    clipNight: Number((0.11 * R).toFixed(1)),
    springs: mobile || colW < 2.12 * R + 2 * SPRING_ROOM ? 'row' : 'spring',
  };
}

/** Variables CSS posées sur `.stage` (stage.css, rose.css, portal.css, now.css les lisent). */
export function stageCssVars(l: StageLayout): Record<string, string> {
  return {
    '--R': `${l.R}px`, '--vw': `${l.vw}px`, '--f': `${l.f}px`, '--crown': `${l.crown}px`, '--cR': `${l.cR}px`,
    '--heart': `${l.heart}px`, '--ring-h': `${l.ringH}px`, '--clip-day': `${l.clipDay}px`, '--clip-night': `${l.clipNight}px`,
  };
}

/** Même mise en page à l'écran ? (évite un rendu React quand l'observateur se réveille pour rien) */
export function sameLayout(a: StageLayout | null, b: StageLayout | null): boolean {
  return !!a && !!b && a.R === b.R && a.c === b.c && a.vw === b.vw && a.springs === b.springs && a.mobile === b.mobile;
}
```

- [ ] **Step 4 : écrire `src/lib/stage/dial.ts`.**

```ts
/**
 * L'horloge : l'anneau des 48 panneaux du vitrail, en lecture seule (le bot n'a pas de `seek`).
 * Seul l'arc visible au-dessus du linteau compte (19 panneaux à c = 0,3, 11 à c = 0,64). Le masque
 * change une fois par panneau (environ toutes les 11 s pour 3 min 30), jamais à chaque image.
 * Repris de `Dial` (proto-gothique/work/refine/src/app.js, lignes 309–337). Pur, sans import runtime
 * (tests/dial.test.mjs).
 */

export const PANES = 48;
export const PANE_DEG = 360 / PANES;   // 7,5°
export const RING_MID = 0.925;         // rayon médian de l'anneau, en R

export type DialGeometry = {
  K: number;   // panneaux de part et d'autre du panneau du haut
  n: number;   // panneaux visibles = 2K + 1
  a0: number;  // angle (degrés, 0 = en haut, sens horaire) du bord gauche du premier panneau visible
};

export function dialGeometry(c: number): DialGeometry {
  const phi = (Math.acos(Math.min(0.99, c / RING_MID)) * 180) / Math.PI;
  const K = Math.max(3, Math.floor((phi - 2) / PANE_DEG));
  return { K, n: 2 * K + 1, a0: -K * PANE_DEG - PANE_DEG / 2 };
}

/** Panneau courant (0…n−1) ; −1 sans durée connue. */
export function clockPane(pos: number, dur: number, n: number): number {
  if (!(dur > 0) || !Number.isFinite(pos)) return -1;
  const p = Math.min(0.9999, Math.max(0, pos / dur));
  return Math.floor(p * n);
}

/** Angles des masques coniques : `--p0` (panneaux déjà joués) et `--p1` (fin du panneau courant). */
export function paneMask(i: number): { p0: number; p1: number } {
  return { p0: Math.max(0, i) * PANE_DEG, p1: i < 0 ? 0 : (i + 1) * PANE_DEG };
}

/** Panneau sous le pointeur ; dx, dy : écart au centre de la rose (px, y vers le bas). */
export function paneAtPoint(dx: number, dy: number, dial: DialGeometry): number {
  const ang = (Math.atan2(dx, -dy) * 180) / Math.PI;
  return Math.max(0, Math.min(dial.n - 1, Math.floor((ang - dial.a0) / PANE_DEG)));
}

/** Temps (s) au début d'un panneau, pour l'info-bulle de survol. */
export function paneTime(i: number, n: number, dur: number): number {
  return dur > 0 ? (i / n) * dur : 0;
}

/** Tracé SVG de la zone de survol le long de l'arc visible (viewBox en unités R, centre 0,0). */
export function hitArcPath(dial: DialGeometry): string {
  const a1 = ((dial.a0 - 90) * Math.PI) / 180, a2 = ((dial.a0 + dial.n * PANE_DEG - 90) * Math.PI) / 180;
  const p = (a: number) => `${(Math.cos(a) * RING_MID).toFixed(4)} ${(Math.sin(a) * RING_MID).toFixed(4)}`;
  return `M${p(a1)}A${RING_MID} ${RING_MID} 0 0 1 ${p(a2)}`;
}

/** Durée dite (lecteurs d'écran) : « 45 s », « 1 min 32 », « 1 h 02 min 05 ». Vide si inconnue. */
export function fmtSpoken(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return '';
  const s = Math.floor(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const ss = String(r).padStart(2, '0');
  if (h) return `${h} h ${String(m).padStart(2, '0')} min ${ss}`;
  if (m) return `${m} min ${ss}`;
  return `${r} s`;
}
```

- [ ] **Step 5 : écrire `src/hooks/useStageLayout.ts`.**
  - Il observe la colonne et le bloc du dessous. Un changement du bloc du dessous inférieur à 2 px est ignoré : sa hauteur dépend faiblement de `--vw` par la taille du titre, et ce seuil coupe tout aller-retour.

```ts
'use client';

import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import { sameLayout, solveStageLayout } from '@/lib/stage/layout';
import type { StageLayout } from '@/lib/stage/layout';

/** Écart de hauteur du bloc sous le portail en deçà duquel on ne recalcule pas (évite un aller-retour). */
const BELOW_EPS = 2;

/**
 * Mise en page de la scène (DESIGN §12.4) : observe la colonne de scène et le bloc sous le portail,
 * recalcule R au plus une fois par image, et ne rend que si la mise en page change.
 * null tant que rien n'a été mesuré (rendu serveur, premier rendu) : la CSS garde ses valeurs par défaut.
 */
export function useStageLayout(colRef: RefObject<HTMLElement>, belowRef: RefObject<HTMLElement>): StageLayout | null {
  const [layout, setLayout] = useState<StageLayout | null>(null);

  useEffect(() => {
    const col = colRef.current;
    if (!col) return;
    let raf = 0, lastBelow = -1;
    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const belowH = belowRef.current?.offsetHeight ?? 0;
        lastBelow = belowH;
        const next = solveStageLayout({ colW: col.clientWidth, colH: col.clientHeight, belowH, viewportW: window.innerWidth });
        setLayout((prev) => (sameLayout(prev, next) ? prev : next));
      });
    };
    const ro = new ResizeObserver((entries) => {
      // le bloc du dessous ne compte que s'il a vraiment changé (police chargée, une ligne de plus)
      const onlyBelow = entries.every((e) => e.target !== col);
      if (onlyBelow && Math.abs((belowRef.current?.offsetHeight ?? 0) - lastBelow) < BELOW_EPS) return;
      measure();
    });
    ro.observe(col);
    if (belowRef.current) ro.observe(belowRef.current);
    window.addEventListener('resize', measure);
    document.fonts?.ready.then(measure).catch(() => {});
    measure();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener('resize', measure); };
  }, [colRef, belowRef]);

  return layout;
}
```

- [ ] **Step 6 : lancer** `npm test`, `GREG_TEST_TRANSPILE=1 npm test` et `npx tsc --noEmit`. Attendu : tous verts.

### Task 4 : titres, scène et poster (pur)

**Files:**
- Create: `services/web/src/lib/titles.ts` : `cleanTitle` et `parse` du prototype (`app.js` lignes 129–147), plus les mentions françaises
- Create: `services/web/src/lib/stage/scene.ts` : état de nuit, surtitre, demandeur, sceau du Roi, graine des répliques
- Create: `services/web/src/lib/stage/cover.ts` : machine à états du poster (tech.md §5.3), dérive (§5.4), décalage, posters
- Test: `services/web/tests/titles.test.mjs`, `services/web/tests/scene.test.mjs`, `services/web/tests/cover.test.mjs`, `services/web/tests/stage-copy.test.mjs`

**Interfaces:**
- Consumes : `copy.v2.json` (tests), `public/gothique/seals/king-seal-*.webp` (étape 1).
- Produces :

```ts
// src/lib/titles.ts
export type ParsedTitle = { song: string; artist: string };
export const normTitle: (x: string) => string; export function cleanTitle(t: string): string; export function cleanArtist(a: string): string;
export function parseTitle(title: string | null | undefined, artist?: string | null): ParsedTitle;
// src/lib/stage/scene.ts
export type Scene = 'day' | 'empty' | 'loading' | 'out'; export type NightKind = Exclude<Scene, 'day'>;
export function stageScene(s: { booted: boolean; loggedIn: boolean; hasCurrent: boolean }): Scene;
export function kickerKey(s: { paused: boolean; repeat: boolean }): 'now.kicker' | 'now.state.paused' | 'now.state.looping';
export type Requester = { kind: 'mine' } | { kind: 'other'; name: string } | { kind: 'unknown' };
export function requesterOf(addedBy: { id?: string; name?: string } | null | undefined, meId: string | null | undefined): Requester;
export function requesterKeys(r: Requester): { plain: string; quips: string | null };
export function sealInitial(name: string | null | undefined): string;       // 'A'…'Z' ou 'fleur'
export const kingSealSrc: (name: string | null | undefined) => string;      // /gothique/seals/king-seal-<L>.webp
export function seedOf(s: string): number;
// src/lib/stage/cover.ts
export type CoverPhase = 'covered' | 'armed' | 'revealed'; export type Cover = { phase: CoverPhase; armedAt: number; bySeek: boolean };
export type CoverEvent = { type: 'track' } | { type: 'stop' } | { type: 'error' } | { type: 'pause' }
  | { type: 'yt'; state: number; now: number } | { type: 'seek'; now: number } | { type: 'reveal'; now: number };
export const COVERED: Cover; export const YT_STATE: { UNSTARTED: -1; ENDED: 0; PLAYING: 1; PAUSED: 2; BUFFERING: 3; CUED: 5 };
export const REVEAL_AFTER_PLAYING_MS = 3500, ALIGN_AFTER_PLAYING_MS = 1200, DRIFT_CHECK_MS = 4000, MIN_SEEK_GAP_MS = 15000,
  ALIGN_THRESHOLD_S = 0.25, RUN_THRESHOLD_S = 1.2, SEEK_COMP_S = 0.45, LOAD_COMP_S = 0.4;
export function coverNext(c: Cover, ev: CoverEvent): Cover;
export const coverVisible: (c: Cover, paused: boolean) => boolean; export const revealIn: (c: Cover, now: number) => number;
export const alignDue: (c: Cover) => boolean;
export function driftSeek(ytTime: number, clockPos: number, offset: number, threshold: number): number | null;
export const loadStart: (clockPos: number, offset: number) => number;
export const REWIND_S = 3;   // recul du son (s) au-delà duquel la même vidéo est rechargée
export function rewound(prev: { pos: number; at: number }, prevPaused: boolean, next: { pos: number; at: number }): boolean;
export const OFFSET_KEY = 'greg.webplayer.video_offset', OFFSET_MIN = -10, OFFSET_MAX = 10, OFFSET_STEP = 0.5;
export function parseOffset(raw: string | number | null | undefined): number; export function fmtOffset(v: number): string;
export const posterUrl: (id: string, size?: 'maxres' | 'hq') => string; export const isPlaceholderThumb: (w: number) => boolean;
```

- `tests/stage-copy.test.mjs` parcourt `src/components/Stage/*`, `src/lib/stage/*` et `src/hooks/useStage*.ts`. Toute chaîne `'section.clé'` d'une section du deck doit y mener à un texte, un pluriel ou une liste de répliques.
  - Les fichiers absents sont ignorés : ce test garde aussi les tâches 5, 6, 7 et 8.
  - N'écrire les clés du deck qu'en littéraux (pas de gabarit `${…}`), pour qu'il les voie.

- [ ] **Step 1 : écrire les tests qui échouent.** `scene.test.mjs` lit le deck directement, car `copy.ts` importe son JSON (voir `loadCopy` dans `copy.test.mjs`).

`tests/titles.test.mjs` :

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { cleanTitle, cleanArtist, parseTitle } = await loadTs('../src/lib/titles.ts');

test('cleanTitle retire les mentions entre parenthèses ou crochets', () => {
  assert.equal(cleanTitle('Bohemian Rhapsody (Official Video Remastered)'), 'Bohemian Rhapsody');
  assert.equal(cleanTitle('Take On Me (Official Video) [4K]'), 'Take On Me');
  assert.equal(cleanTitle('Alors on danse (Clip officiel)'), 'Alors on danse');
  assert.equal(cleanTitle('Papaoutai (Vidéo officielle)'), 'Papaoutai');
  assert.equal(cleanTitle('Formidable (Paroles)'), 'Formidable');
  assert.equal(cleanTitle('Song (feat. X)'), 'Song (feat. X)');   // rien à retirer
});

test('cleanArtist retire VEVO, « - Topic » et « Official »', () => {
  assert.equal(cleanArtist('RickAstleyVEVO'), 'RickAstley');
  assert.equal(cleanArtist('Queen - Topic'), 'Queen');
  assert.equal(cleanArtist('Queen Official'), 'Queen');
});

test('parseTitle : « Artiste – Titre » (DESIGN §6)', () => {
  assert.deepEqual(parseTitle('Queen – Bohemian Rhapsody (Official Video Remastered)', 'Queen Official'), { song: 'Bohemian Rhapsody', artist: 'Queen' });
  assert.deepEqual(parseTitle('Rick Astley - Never Gonna Give You Up (Official Music Video)', 'Rick Astley'), { song: 'Never Gonna Give You Up', artist: 'Rick Astley' });
  assert.deepEqual(parseTitle('a-ha - Take On Me (Official Video) [4K]', 'a-ha'), { song: 'Take On Me', artist: 'a-ha' });
});

test('parseTitle : « Titre – Artiste » reconnu grâce à la chaîne', () => {
  assert.deepEqual(parseTitle('Bohemian Rhapsody - Queen', 'Queen'), { song: 'Bohemian Rhapsody', artist: 'Queen' });
});

test('parseTitle : titre seul, doublons, vide', () => {
  assert.deepEqual(parseTitle('Never Gonna Give You Up', 'RickAstleyVEVO'), { song: 'Never Gonna Give You Up', artist: 'RickAstley' });
  assert.deepEqual(parseTitle('Nirvana - Nirvana - Smells Like Teen Spirit', 'Nirvana'), { song: 'Smells Like Teen Spirit', artist: 'Nirvana' });
  assert.deepEqual(parseTitle('', null), { song: '', artist: '' });
  assert.deepEqual(parseTitle(undefined, undefined), { song: '', artist: '' });
});
```

`tests/scene.test.mjs` :

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './_loadTs.mjs';
const { stageScene, kickerKey, requesterOf, requesterKeys, sealInitial, kingSealSrc, seedOf } = await loadTs('../src/lib/stage/scene.ts');
// Deck lu directement (copy.ts importe son JSON : voir loadCopy dans copy.test.mjs).
const deck = JSON.parse(readFileSync(new URL('../src/theme/copy.v2.json', import.meta.url), 'utf8'));
const at = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);

test('scène : chargement, déconnecté, rien en lecture, jour', () => {
  assert.equal(stageScene({ booted: false, loggedIn: true, hasCurrent: true }), 'loading');
  assert.equal(stageScene({ booted: true, loggedIn: false, hasCurrent: false }), 'out');
  assert.equal(stageScene({ booted: true, loggedIn: true, hasCurrent: false }), 'empty');
  assert.equal(stageScene({ booted: true, loggedIn: true, hasCurrent: true }), 'day');
});

test('surtitre : en lecture, en pause, en boucle (textes du deck)', () => {
  assert.equal(at(kickerKey({ paused: false, repeat: false })), 'En lecture');
  assert.equal(at(kickerKey({ paused: true, repeat: true })), 'En pause');
  assert.equal(at(kickerKey({ paused: false, repeat: true })), 'En boucle');
});

test('demandeur : le Roi (l’utilisateur), un courtisan, inconnu', () => {
  assert.deepEqual(requesterOf({ id: '101', name: 'Paul' }, '101'), { kind: 'mine' });
  assert.deepEqual(requesterOf({ id: '102', name: ' Léa ' }, '101'), { kind: 'other', name: 'Léa' });
  assert.deepEqual(requesterOf({ id: '99', name: '' }, '101'), { kind: 'unknown' });
  assert.deepEqual(requesterOf(null, '101'), { kind: 'unknown' });
  assert.deepEqual(requesterOf({ id: '101', name: 'Paul' }, null), { kind: 'other', name: 'Paul' });
});

test('demandeur : clés du deck présentes', () => {
  assert.equal(at(requesterKeys({ kind: 'mine' }).plain), 'Demandé par vous');
  assert.equal(at(requesterKeys({ kind: 'other', name: 'Léa' }).plain), 'Demandé par {name}');
  assert.equal(at(requesterKeys({ kind: 'unknown' }).plain), 'Ajouté depuis Discord');
  assert.equal(requesterKeys({ kind: 'unknown' }).quips, null);
  for (const k of ['mine', 'other']) assert.ok(Array.isArray(at(`${requesterKeys({ kind: k, name: 'x' }).quips}.quips`)), k);
});

test('sceau du Roi : initiale A–Z sans accent, sinon fleur de lys ; le fichier existe', () => {
  assert.equal(sealInitial('Élodie'), 'E');
  assert.equal(sealInitial('paul'), 'P');
  assert.equal(sealInitial('42paul'), 'P');
  assert.equal(sealInitial('☆☆'), 'fleur');
  assert.equal(sealInitial(''), 'fleur');
  assert.equal(sealInitial(null), 'fleur');
  for (const n of ['Élodie', '☆']) {
    const f = fileURLToPath(new URL(`../public${kingSealSrc(n)}`, import.meta.url));
    assert.ok(existsSync(f), f);
  }
});

test('graine de réplique stable et répartie', () => {
  assert.equal(seedOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), seedOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ'));
  assert.notEqual(seedOf('a'), seedOf('b'));
  assert.ok(Number.isInteger(seedOf('x')) && seedOf('x') >= 0);
});
```

`tests/cover.test.mjs` :

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const {
  coverNext, coverVisible, revealIn, alignDue, driftSeek, loadStart, rewound, parseOffset, fmtOffset, posterUrl, isPlaceholderThumb,
  COVERED, YT_STATE, REVEAL_AFTER_PLAYING_MS, REWIND_S,
} = await loadTs('../src/lib/stage/cover.ts');

const yt = (state, now = 0) => ({ type: 'yt', state, now });
const run = (events, from = COVERED) => events.reduce(coverNext, from);

test('poster : couvert → armé à PLAYING → révélé à +3,5 s (spec §4, tech.md §5.3)', () => {
  assert.equal(REVEAL_AFTER_PLAYING_MS, 3500);
  const armed = run([{ type: 'track' }, yt(YT_STATE.BUFFERING, 100), yt(YT_STATE.PLAYING, 1000)]);
  assert.deepEqual(armed, { phase: 'armed', armedAt: 1000, bySeek: false });
  assert.equal(revealIn(armed, 2000), 2500);
  assert.equal(coverNext(armed, yt(YT_STATE.PLAYING, 2000)), armed);          // pas de réarmement
  assert.equal(coverNext(armed, { type: 'reveal', now: 3000 }), armed);       // trop tôt : minuterie périmée
  assert.equal(coverNext(armed, { type: 'reveal', now: 4500 }).phase, 'revealed');
});

test('poster : un BUFFERING tardif ne le remet pas ; pause, fin, arrêt, erreur, nouveau titre le remettent', () => {
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false };
  assert.equal(coverNext(shown, yt(YT_STATE.BUFFERING, 9000)), shown);
  for (const ev of [yt(YT_STATE.PAUSED), yt(YT_STATE.ENDED), { type: 'pause' }, { type: 'stop' }, { type: 'error' }, { type: 'track' }]) {
    assert.equal(coverNext(shown, ev).phase, 'covered', JSON.stringify(ev));
  }
});

test('poster : un saut de correction réarme (YouTube remontre son habillage), sans réalignement', () => {
  const shown = { phase: 'revealed', armedAt: 1000, bySeek: false };
  const reArmed = coverNext(shown, { type: 'seek', now: 20000 });
  assert.deepEqual(reArmed, { phase: 'armed', armedAt: 20000, bySeek: true });
  assert.equal(alignDue(reArmed), false);
  assert.equal(alignDue({ phase: 'armed', armedAt: 1000, bySeek: false }), true);
  assert.equal(coverNext(COVERED, { type: 'seek', now: 5 }), COVERED);        // couvert : rien à réarmer
});

test('poster visible pendant la pause, même révélé', () => {
  assert.equal(coverVisible({ phase: 'revealed', armedAt: 0, bySeek: false }, false), false);
  assert.equal(coverVisible({ phase: 'revealed', armedAt: 0, bySeek: false }, true), true);
  assert.equal(coverVisible({ phase: 'armed', armedAt: 0, bySeek: false }, false), true);
});

test('dérive : saut seulement au-delà du seuil, compensé de 0,45 s', () => {
  assert.equal(driftSeek(10.1, 10, 0, 0.25), null);
  assert.equal(driftSeek(11, 10, 0, 0.25), 10.45);
  assert.equal(driftSeek(9, 10, 0.5, 1.2), 10.95);
  assert.equal(driftSeek(9.5, 10, 0.5, 1.2), null);
  assert.equal(driftSeek(5, 0, -2, 0.25), 0);                 // jamais négatif
  assert.equal(driftSeek(Number.NaN, 10, 0, 0.25), null);
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

test('décalage : borné à ±10 s, pas de 0,5 s, 0 si illisible', () => {
  assert.equal(parseOffset('1.5'), 1.5);
  assert.equal(parseOffset('1.3'), 1.5);
  assert.equal(parseOffset('42'), 10);
  assert.equal(parseOffset('-11'), -10);
  assert.equal(parseOffset('abc'), 0);
  assert.equal(parseOffset(null), 0);
  assert.equal(parseOffset(''), 0);
  assert.ok(Object.is(parseOffset('-0.1'), 0));
});

test('décalage affiché à la française', () => {
  assert.equal(fmtOffset(0), '0 s');
  assert.equal(fmtOffset(1.5), '+1,5 s');
  assert.equal(fmtOffset(-2), '−2 s');
});

test('posters : maxresdefault puis hqdefault si vignette grise', () => {
  assert.equal(posterUrl('dQw4w9WgXcQ'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg');
  assert.equal(posterUrl('dQw4w9WgXcQ', 'hq'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
  assert.equal(isPlaceholderThumb(120), true);
  assert.equal(isPlaceholderThumb(1280), false);
  assert.equal(isPlaceholderThumb(0), false);
});
```

`tests/stage-copy.test.mjs` :

```js
// Textes de la scène : chaque clé du deck citée par la scène existe (étape 2).
// Parcourt src/components/Stage/*.tsx, src/lib/stage/*.ts et src/hooks/useStage*.ts : toute chaîne 'section.clé…' d'une section du deck
// doit mener à un texte, un pluriel ou une liste de répliques de copy.v2.json. Les fichiers absents sont ignorés :
// le test grandit avec les tâches.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = (p) => fileURLToPath(new URL(`../${p}`, import.meta.url));
const deck = JSON.parse(readFileSync(root('src/theme/copy.v2.json'), 'utf8'));
const SECTIONS = Object.keys(deck).filter((k) => !k.startsWith('_'));
const KEY = new RegExp(`'((?:${SECTIONS.join('|')})\\.[\\w.]+)'`, 'g');

const at = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);
const usable = (node) => typeof node === 'string'
  || (node && typeof node === 'object' && ('text' in node || typeof node.other === 'string' || Array.isArray(node.quips)));

function sources() {
  const out = [];
  for (const [dir, only] of [['src/components/Stage', /\.tsx?$/], ['src/lib/stage', /\.ts$/], ['src/hooks', /^useStage\w*\.ts$/]]) {
    if (!existsSync(root(dir))) continue;
    for (const f of readdirSync(root(dir))) if (only.test(f)) out.push(`${dir}/${f}`);
  }
  return out;
}

test('chaque clé du deck citée par la scène existe et donne un texte', () => {
  for (const f of sources()) {
    for (const [, key] of readFileSync(root(f), 'utf8').matchAll(KEY)) {
      assert.ok(usable(at(key)), `${f} : clé « ${key} » absente ou vide`);
    }
  }
});

test('les répliques de la scène ne touchent pas au casting (pas de couronne sur Greg)', () => {
  const texts = ['now.idle', 'loading.boot', 'auth', 'now.order.mine', 'now.order.other', 'confirm.stop']
    .flatMap((k) => at(k)?.quips ?? []);
  for (const q of texts) assert.ok(!/Greg[^.]*\b(roi|couronne|Rex)\b/i.test(q), q);
});
```

- [ ] **Step 2 : lancer** `npm test`. Attendu : FAIL (modules absents).
- [ ] **Step 3 : écrire `src/lib/titles.ts`.**

```ts
/**
 * Titres YouTube nettoyés pour l'affichage (DESIGN §6) : « Queen – Bohemian Rhapsody (Official Video
 * Remastered) » devient Bohemian Rhapsody / Queen. Le titre brut reste en info-bulle.
 * Repris de `cleanTitle` / `parse` (proto-gothique/work/refine/src/app.js, lignes 129–147), plus les
 * mentions françaises (« Clip officiel », « Vidéo officielle », « Paroles »).
 * Pur, sans import runtime (tests/titles.test.mjs).
 */

export type ParsedTitle = { song: string; artist: string };

const NOISE = /\s*[([][^)\]]*\b(official|officiel(?:le)?|video|vidéo|audio|remaster(?:ed)?|4k|hd|lyrics?|paroles|clip|upgrade|version|visualizer)\b[^)\]]*[)\]]/gi;

/** Forme comparable : minuscules, sans accents, lettres et chiffres seulement. */
export const normTitle = (x: string): string =>
  x.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]/g, '');

export function cleanTitle(t: string): string {
  return t.normalize('NFC').replace(NOISE, '').replace(/\s+/g, ' ').trim();
}

export function cleanArtist(a: string): string {
  return a.replace(/VEVO$/i, '').replace(/\s*-\s*Topic$/i, '').replace(/\s+Official$/i, '').trim();
}

/** « Artiste – Titre » ou « Titre – Artiste » : l'artiste connu de la chaîne tranche. */
export function parseTitle(title: string | null | undefined, artist?: string | null): ParsedTitle {
  const a0 = cleanArtist(artist || '');
  const parts = cleanTitle(title || '').split(/\s+[-–—]\s+/)
    .filter((x, i, arr) => i === 0 || normTitle(x) !== normTitle(arr[i - 1]));
  if (parts.length < 2) return { song: parts.join(' – '), artist: a0 };
  const a = parts[0], b = parts.slice(1).join(' – ');
  const na = normTitle(a0);
  return normTitle(b).includes(na) && !normTitle(a).includes(na) ? { song: a, artist: b } : { song: b, artist: a };
}
```

- [ ] **Step 4 : écrire `src/lib/stage/scene.ts`.**

```ts
/**
 * État de la scène et textes qui en découlent (spec §4 « Nuit », casting du Roi).
 * Pur, sans import runtime (tests/scene.test.mjs) : les composants passent les clés rendues à `t()`.
 */

/** Jour : un titre joue (ou est en pause). Nuit : rien en lecture, chargement, ou déconnecté. */
export type Scene = 'day' | 'empty' | 'loading' | 'out';
export type NightKind = Exclude<Scene, 'day'>;

export function stageScene(s: { booted: boolean; loggedIn: boolean; hasCurrent: boolean }): Scene {
  if (!s.booted) return 'loading';
  if (!s.loggedIn) return 'out';
  return s.hasCurrent ? 'day' : 'empty';
}

/** Surtitre au-dessus du titre : état de lecture seulement (les répliques vont à côté). */
export function kickerKey(s: { paused: boolean; repeat: boolean }): 'now.kicker' | 'now.state.paused' | 'now.state.looping' {
  if (s.paused) return 'now.state.paused';
  return s.repeat ? 'now.state.looping' : 'now.kicker';
}

/** Qui a demandé le titre : le Roi lui-même (l'utilisateur), un courtisan, ou inconnu. */
export type Requester = { kind: 'mine' } | { kind: 'other'; name: string } | { kind: 'unknown' };

export function requesterOf(addedBy: { id?: string; name?: string } | null | undefined, meId: string | null | undefined): Requester {
  if (addedBy?.id && meId && String(addedBy.id) === String(meId)) return { kind: 'mine' };
  const name = (addedBy?.name || '').trim();
  return name ? { kind: 'other', name } : { kind: 'unknown' };
}

/** Clé du deck pour la ligne « Demandé par… » et, s'il y en a, pour la réplique du surtitre. */
export function requesterKeys(r: Requester): { plain: string; quips: string | null } {
  if (r.kind === 'mine') return { plain: 'now.order.mine.plain', quips: 'now.order.mine' };
  if (r.kind === 'other') return { plain: 'now.order.other.plain', quips: 'now.order.other' };
  return { plain: 'now.order.unknown.plain', quips: null };
}

/**
 * Initiale du sceau du Roi : 1re lettre A–Z du pseudo, accents retirés (deck `_meta.tokens.kingInitial`) ;
 * sinon la fleur de lys (`king-seal-fleur.webp`, public/licenses/LICENSES.md).
 */
export function sealInitial(name: string | null | undefined): string {
  const m = (name || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase().match(/[A-Z]/);
  return m ? m[0] : 'fleur';
}
export const kingSealSrc = (name: string | null | undefined): string => `/gothique/seals/king-seal-${sealInitial(name)}.webp`;

/** Graine stable d'une réplique (FNV-1a 32 bits) : la même pour un même titre, d'un rendu à l'autre. */
export function seedOf(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}
```

- [ ] **Step 5 : écrire `src/lib/stage/cover.ts`.**

```ts
/**
 * Le poster au-dessus du lecteur YouTube persistant (tech.md §5.3) et la synchro de la vidéo (§5.4).
 * Le poster couvre l'iframe jusqu'à PLAYING + 3,5 s, et pendant la pause : YouTube montre son habillage
 * (titre, chaîne, icône, « Plus de vidéos ») à chaque départ, à chaque pause et à chaque saut.
 * Un saut de correction (seekTo) réarme donc le poster (mesuré : l'habillage revient ~4 s).
 * Pur, sans import runtime (tests/cover.test.mjs).
 */

export type CoverPhase = 'covered' | 'armed' | 'revealed';
/** armedAt : instant (performance.now) de l'armement ; bySeek : armé par notre propre saut (pas de nouvel alignement). */
export type Cover = { phase: CoverPhase; armedAt: number; bySeek: boolean };
export type CoverEvent =
  | { type: 'track' } | { type: 'stop' } | { type: 'error' } | { type: 'pause' }
  | { type: 'yt'; state: number; now: number }   // YT.PlayerState reçu par onStateChange
  | { type: 'seek'; now: number }                // saut de correction automatique
  | { type: 'reveal'; now: number };             // minuterie de révélation écoulée

export const COVERED: Cover = { phase: 'covered', armedAt: 0, bySeek: false };
export const YT_STATE = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 } as const;
export const REVEAL_AFTER_PLAYING_MS = 3500;   // spec §4 : PLAYING + 3,5 s
export const ALIGN_AFTER_PLAYING_MS = 1200;    // alignement initial, encore sous le poster
export const DRIFT_CHECK_MS = 4000;
export const MIN_SEEK_GAP_MS = 15000;
export const ALIGN_THRESHOLD_S = 0.25;
export const RUN_THRESHOLD_S = 1.2;
export const SEEK_COMP_S = 0.45;               // seekTo met ~474 ms à reprendre
export const LOAD_COMP_S = 0.4;                // loadVideoById met ~404 ms à jouer
const TIMER_SLACK_MS = 50;

export function coverNext(c: Cover, ev: CoverEvent): Cover {
  switch (ev.type) {
    case 'track': case 'stop': case 'error':
      return c.phase === 'covered' && !c.bySeek ? c : COVERED;
    case 'pause':
      return c.phase === 'covered' ? c : { ...c, phase: 'covered' };
    case 'seek':
      return c.phase === 'covered' ? c : { phase: 'armed', armedAt: ev.now, bySeek: true };
    case 'reveal':
      return c.phase === 'armed' && ev.now - c.armedAt >= REVEAL_AFTER_PLAYING_MS - TIMER_SLACK_MS ? { ...c, phase: 'revealed' } : c;
    case 'yt':
      if (ev.state === YT_STATE.PLAYING) return c.phase === 'covered' ? { phase: 'armed', armedAt: ev.now, bySeek: false } : c;
      if (ev.state === YT_STATE.BUFFERING) return c;          // un BUFFERING tardif ne remet pas le poster
      return c.phase === 'covered' ? c : { ...c, phase: 'covered' };   // ENDED, PAUSED, UNSTARTED, CUED
  }
}

/** Le poster est visible tant que la vidéo n'est pas révélée, et toujours pendant la pause. */
export const coverVisible = (c: Cover, paused: boolean): boolean => c.phase !== 'revealed' || paused;
/** Délai avant la révélation d'un poster armé. */
export const revealIn = (c: Cover, now: number): number => Math.max(0, c.armedAt + REVEAL_AFTER_PLAYING_MS - now);
/** Alignement initial dû : armé par un vrai départ (pas par notre propre saut, sinon on bouclerait). */
export const alignDue = (c: Cover): boolean => c.phase === 'armed' && !c.bySeek;

/** Cible d'un seekTo si l'écart vidéo ↔ son (+ décalage) dépasse le seuil ; null sinon. */
export function driftSeek(ytTime: number, clockPos: number, offset: number, threshold: number): number | null {
  const target = clockPos + offset;
  const drift = ytTime - target;
  if (!Number.isFinite(drift) || Math.abs(drift) <= threshold) return null;
  return Math.max(0, target + SEEK_COMP_S);
}

/** Position de départ d'un loadVideoById, compensée du temps de chargement. */
export const loadStart = (clockPos: number, offset: number): number => Math.max(0, clockPos + offset + LOAD_COMP_S);

/** Recul du son (s) au-delà duquel la même vidéo est rechargée : les ticks du bot, arrondis à la seconde, n'y arrivent jamais. */
export const REWIND_S = 3;

/**
 * Le son est reparti en arrière sur la même vidéo (« Reprendre au début », boucle, même titre deux fois
 * de suite) : la nouvelle position est à plus de REWIND_S sous celle qu'on attendait. tech.md §5.4 :
 * nouvel alignement quand l'horloge saute. Sans ça, une vidéo finie (ENDED) resterait sous son poster.
 */
export function rewound(prev: { pos: number; at: number }, prevPaused: boolean, next: { pos: number; at: number }): boolean {
  const expected = prev.pos + (prevPaused ? 0 : Math.max(0, next.at - prev.at) / 1000);
  return Number.isFinite(next.pos) && next.pos < expected - REWIND_S;
}

// ── Décalage de la vidéo (réglage du Roi, gardé dans localStorage) ──
export const OFFSET_KEY = 'greg.webplayer.video_offset';
export const OFFSET_MIN = -10, OFFSET_MAX = 10, OFFSET_STEP = 0.5;

export function parseOffset(raw: string | number | null | undefined): number {
  const v = typeof raw === 'number' ? raw : raw == null || String(raw).trim() === '' ? NaN : Number(raw);
  if (!Number.isFinite(v)) return 0;
  const stepped = Math.round(Math.min(OFFSET_MAX, Math.max(OFFSET_MIN, v)) / OFFSET_STEP) * OFFSET_STEP;
  return stepped + 0;   // pas de −0
}

/** « 0 s », « +1,5 s », « −2 s » : virgule décimale, signe moins U+2212, espace insécable avant l'unité. */
export function fmtOffset(v: number): string {
  const x = parseOffset(v);
  const n = Math.abs(x).toFixed(1).replace(/\.0$/, '').replace('.', ',');
  return `${x > 0 ? '+' : x < 0 ? '−' : ''}${n} s`;
}

// ── Posters ──
export const posterUrl = (id: string, size: 'maxres' | 'hq' = 'maxres'): string =>
  `https://i.ytimg.com/vi/${id}/${size === 'maxres' ? 'maxresdefault' : 'hqdefault'}.jpg`;
/** maxresdefault absent : YouTube renvoie une vignette grise de 120 × 90 (ou un 404). */
export const isPlaceholderThumb = (naturalWidth: number): boolean => naturalWidth > 0 && naturalWidth <= 120;
```

- [ ] **Step 6 : lancer** `npm test`, `GREG_TEST_TRANSPILE=1 npm test` et `npx tsc --noEmit`. Attendu : tous verts.

### Task 5 : portail de pierre, lecteur YouTube persistant, poster, synchro

**Files:**
- Create: `services/web/src/hooks/useYouTubePlayer.ts` (tech.md §5.2)
- Create: `services/web/src/hooks/useVideoOffset.ts`
- Create: `services/web/src/components/Stage/Portal.tsx`, `services/web/src/components/Stage/SyncOffset.tsx`, `services/web/src/components/Stage/portal.css`

**Interfaces:**
- Consumes :
  - tâche 4 : tout `cover.ts`, dont `rewound` ;
  - étape 1 : `useStore` (et `useStore.subscribe((state, prev) => …)`, zustand 4.5), `livePosition`, `usePopover` et `t`.
- Produces :

```ts
// src/hooks/useYouTubePlayer.ts
export type YTPlayer = { loadVideoById(o: { videoId: string; startSeconds?: number }): void; playVideo(): void; pauseVideo(): void; stopVideo(): void;
  seekTo(s: number, allowSeekAhead: boolean): void; getCurrentTime(): number; mute(): void; getIframe(): HTMLIFrameElement; destroy(): void };
export type YTHandlers = { onState: (state: number) => void; onError: (code: number) => void };
export function loadYouTubeApi(): Promise<{ Player: new (el: HTMLElement, opts: Record<string, unknown>) => YTPlayer }>;
export function useYouTubePlayer(wrapRef: RefObject<HTMLDivElement>, handlers: YTHandlers): YTPlayer | null;
// src/hooks/useVideoOffset.ts
export function useVideoOffset(): [number, (v: number) => void];
// src/components/Stage/Portal.tsx
export type PortalProps = { videoId: string | null; nextId: string | null; paused: boolean; offset: number; art: string | null };
export default function Portal(p: PortalProps): JSX.Element;       // <div class="portal"><div class="video">…
// src/components/Stage/SyncOffset.tsx
export default function SyncOffset(p: { value: number; onChange: (v: number) => void }): JSX.Element;
```

Le comportement de synchro existant est gardé :
- le curseur de −10 à +10 s, par pas de 0,5 s, qui fait sauter la vidéo tout de suite ;
- la relance de l'iframe si elle se met en pause seule ;
- l'iframe inerte (`pointer-events: none`).

Nouveau :
- le décalage est gardé dans `localStorage` ;
- le lecteur est persistant (`loadVideoById`) au lieu d'être détruit à chaque titre ;
- le poster ;
- l'alignement initial et la correction de dérive ;
- la même vidéo rechargée sous le poster quand le son recule (« Reprendre au début », boucle, même titre deux fois : `rewound`) ;
- la pochette d'un titre sans vidéo YouTube (SoundCloud), en image fixe comme l'ancien lecteur (`art`) ;
- l'ombre du portail en `box-shadow`, jamais un `filter` sur l'ancêtre de l'iframe (écart 6).

Pas de test unitaire propre : toute la logique est dans `cover.ts` (tâche 4, `rewound` compris). Les garde-fous sont `tests/stage-copy.test.mjs`, `tsc` et `next build`, puis `tests/stage-contract.test.mjs` (pas de filtre sur le portail) et le navigateur à la tâche 8.

- [ ] **Step 1 : écrire `src/hooks/useYouTubePlayer.ts`.** `destroy()` n'est appelé qu'au démontage. React ne possède que l'enveloppe vide : l'iframe remplace un enfant créé par le hook.

```ts
'use client';

import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

/**
 * Un seul lecteur YouTube pour toute la session (tech.md §5.2) : créé une fois, les titres passent par
 * loadVideoById dans la même iframe (≈ 400 ms au lieu de ≈ 690 ms, sans iframe recréée).
 * React ne possède que l'enveloppe vide : l'iframe remplace un enfant créé ici, jamais un nœud React.
 */

export type YTPlayer = {
  loadVideoById(o: { videoId: string; startSeconds?: number }): void;
  playVideo(): void;
  pauseVideo(): void;
  stopVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  mute(): void;
  getIframe(): HTMLIFrameElement;
  destroy(): void;
};
type YTNamespace = { Player: new (el: HTMLElement, opts: Record<string, unknown>) => YTPlayer };
type YTWindow = Window & { YT?: YTNamespace; onYouTubeIframeAPIReady?: () => void };
export type YTHandlers = { onState: (state: number) => void; onError: (code: number) => void };

const API_SRC = 'https://www.youtube.com/iframe_api';
let apiPromise: Promise<YTNamespace> | null = null;

/** Charge l'API une seule fois ; enchaîne un onYouTubeIframeAPIReady déjà posé. */
export function loadYouTubeApi(): Promise<YTNamespace> {
  const w = window as YTWindow;
  if (w.YT?.Player) return Promise.resolve(w.YT);
  apiPromise ??= new Promise<YTNamespace>((resolve) => {
    const prev = w.onYouTubeIframeAPIReady;
    w.onYouTubeIframeAPIReady = () => { prev?.(); if (w.YT) resolve(w.YT); };
    if (!document.querySelector(`script[src="${API_SRC}"]`)) {
      const tag = document.createElement('script');
      tag.src = API_SRC;
      tag.async = true;
      document.head.appendChild(tag);
    }
  });
  return apiPromise;
}

/** Crée le lecteur dans `wrapRef` au montage, le détruit au démontage. Renvoie null tant qu'il n'est pas prêt. */
export function useYouTubePlayer(wrapRef: RefObject<HTMLDivElement>, handlers: YTHandlers): YTPlayer | null {
  const [player, setPlayer] = useState<YTPlayer | null>(null);
  const h = useRef(handlers);
  h.current = handlers;

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    let alive = true;
    let created: YTPlayer | null = null;
    const host = document.createElement('div');
    wrap.appendChild(host);
    loadYouTubeApi().then((YT) => {
      if (!alive) return;
      created = new YT.Player(host, {
        width: '100%', height: '100%',
        playerVars: {
          autoplay: 1, mute: 1, controls: 0, rel: 0, iv_load_policy: 3, disablekb: 1,
          playsinline: 1, fs: 0, cc_load_policy: 0, enablejsapi: 1, origin: location.origin,
        },
        events: {
          onReady: () => {
            if (!alive || !created) return;
            created.mute();
            try { created.getIframe().tabIndex = -1; } catch {}   // image seule : jamais dans l'ordre de tabulation
            setPlayer(created);
          },
          onStateChange: (e: { data: number }) => { if (alive) h.current.onState(e.data); },
          onError: (e: { data: number }) => { if (alive) h.current.onError(e.data); },
        },
      });
    }).catch(() => {});
    return () => {
      alive = false;
      try { created?.destroy(); } catch {}
      wrap.replaceChildren();
      setPlayer(null);
    };
  }, [wrapRef]);

  return player;
}
```

- [ ] **Step 2 : écrire `src/hooks/useVideoOffset.ts`.**

```ts
'use client';

import { useCallback, useEffect, useState } from 'react';
import { OFFSET_KEY, parseOffset } from '@/lib/stage/cover';

/** Décalage vidéo ↔ son du Roi, gardé dans localStorage (tech.md §5.4). 0 par défaut. */
export function useVideoOffset(): [number, (v: number) => void] {
  const [offset, setOffsetState] = useState(0);

  useEffect(() => {
    try { setOffsetState(parseOffset(localStorage.getItem(OFFSET_KEY))); } catch {}
  }, []);

  const setOffset = useCallback((v: number) => {
    const x = parseOffset(v);
    setOffsetState(x);
    try { if (x) localStorage.setItem(OFFSET_KEY, String(x)); else localStorage.removeItem(OFFSET_KEY); } catch {}
  }, []);

  return [offset, setOffset];
}
```

- [ ] **Step 3 : écrire `src/components/Stage/Portal.tsx`.**

```tsx
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { useYouTubePlayer } from '@/hooks/useYouTubePlayer';
import type { YTPlayer } from '@/hooks/useYouTubePlayer';
import { livePosition } from '@/lib/playerUtils';
import {
  ALIGN_AFTER_PLAYING_MS, ALIGN_THRESHOLD_S, COVERED, DRIFT_CHECK_MS, MIN_SEEK_GAP_MS, RUN_THRESHOLD_S, YT_STATE,
  alignDue, coverNext, coverVisible, driftSeek, isPlaceholderThumb, loadStart, posterUrl, revealIn, rewound,
} from '@/lib/stage/cover';
import type { Cover, CoverEvent } from '@/lib/stage/cover';
import { t } from '@/theme/copy';

export type PortalProps = {
  videoId: string | null;   // titre en cours (null : rien, le portail s'efface la nuit)
  nextId: string | null;    // prochain titre : son poster est décodé d'avance
  paused: boolean;
  offset: number;           // décalage vidéo ↔ son (s), useVideoOffset
  art: string | null;       // pochette d'un titre sans vidéo YouTube (SoundCloud) : image fixe, comme l'ancien lecteur
};

/** Vidéos sans maxresdefault (vu au préchargement) : leur poster part directement en hqdefault. */
const noMaxres = new Set<string>();

/** Position du son (s) d'après le store, comme l'horloge. */
function clockPos(): number {
  const s = useStore.getState();
  return livePosition(s.tickBase, s.player.paused, performance.now());
}

/** Poster maxresdefault, repli hqdefault (404 ou vignette grise 120 × 90). Visible une fois chargé. */
function Poster({ id, leaving }: { id: string; leaving: boolean }) {
  const hq = posterUrl(id, 'hq');
  const [src, setSrc] = useState(() => (noMaxres.has(id) ? hq : posterUrl(id)));
  const [ready, setReady] = useState(false);
  const fallBack = () => { noMaxres.add(id); setSrc(hq); };
  return (
    <img className="poster" src={src} alt="" decoding="async" draggable={false}
      data-ready={ready} data-leaving={leaving || undefined}
      onLoad={(e) => { if (src !== hq && isPlaceholderThumb(e.currentTarget.naturalWidth)) fallBack(); else setReady(true); }}
      onError={() => { if (src !== hq) fallBack(); }}/>
  );
}

/**
 * Le portail de pierre (9 tranches, rendu Blender) et la vidéo : lecteur YouTube persistant sous un poster
 * qui le couvre jusqu'à PLAYING + 3,5 s et pendant la pause (tech.md §5.3). Styles : portal.css.
 */
export default function Portal({ videoId, nextId, paused, offset, art }: PortalProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [cover, setCover] = useState<Cover>(COVERED);
  const [unavailable, setUnavailable] = useState(false);
  const [posters, setPosters] = useState<{ id: string; leaving: boolean }[]>([]);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const videoRef = useRef(videoId);
  videoRef.current = videoId;
  const playerRef = useRef<YTPlayer | null>(null);
  const ytState = useRef<number>(YT_STATE.UNSTARTED);
  const lastSeek = useRef(0);

  const dispatch = useCallback((ev: CoverEvent) => setCover((c) => coverNext(c, ev)), []);
  const seek = useCallback((to: number) => {
    try { playerRef.current?.seekTo(to, true); lastSeek.current = performance.now(); } catch {}
  }, []);
  /** Saut de correction : YouTube remontre son habillage, le poster revient le temps qu'il parte. */
  const correct = useCallback((threshold: number) => {
    const p = playerRef.current;
    if (!p) return;
    const to = driftSeek(p.getCurrentTime(), clockPos(), offsetRef.current, threshold);
    if (to == null) return;
    seek(to);
    dispatch({ type: 'seek', now: performance.now() });
  }, [dispatch, seek]);

  const player = useYouTubePlayer(wrapRef, {
    onState: (s) => {
      ytState.current = s;
      dispatch({ type: 'yt', state: s, now: performance.now() });
      // l'iframe ne suit que le son : relancée si elle s'arrête seule, arrêtée si elle part pendant la pause
      if (s === YT_STATE.PAUSED && !pausedRef.current) playerRef.current?.playVideo();
      if (s === YT_STATE.PLAYING && pausedRef.current) playerRef.current?.pauseVideo();
    },
    onError: () => { setUnavailable(true); dispatch({ type: 'error' }); },
  });
  playerRef.current = player;

  // Changement de titre : le poster couvre, puis loadVideoById dans la même iframe.
  useEffect(() => {
    setUnavailable(false);
    dispatch({ type: videoId ? 'track' : 'stop' });
    if (!player) return;
    try {
      if (videoId) player.loadVideoById({ videoId, startSeconds: loadStart(clockPos(), offsetRef.current) });
      else player.stopVideo();
    } catch {}
  }, [videoId, player, dispatch]);

  // Le son recule sur la même vidéo (« Reprendre au début », boucle, même titre deux fois de suite) : la vidéo
  // est rechargée sous le poster (tech.md §5.4). Un changement de titre passe par l'effet ci-dessus.
  useEffect(() => useStore.subscribe((s, prev) => {
    const p = playerRef.current, id = videoRef.current;
    if (!p || !id || s.tickBase === prev.tickBase || s.player.current?.url !== prev.player.current?.url) return;
    if (!rewound(prev.tickBase, prev.player.paused, s.tickBase)) return;
    dispatch({ type: 'track' });
    try { p.loadVideoById({ videoId: id, startSeconds: loadStart(s.tickBase.pos, offsetRef.current) }); } catch {}
  }), [dispatch]);

  // Pause et reprise suivent le son ; le poster revient pendant la pause.
  useEffect(() => {
    if (!player || !videoId) return;
    try { if (paused) player.pauseVideo(); else player.playVideo(); } catch {}
    if (paused) dispatch({ type: 'pause' });
  }, [paused, player, videoId, dispatch]);

  // Armé : alignement à +1,2 s (encore caché), révélation à armedAt + 3,5 s.
  useEffect(() => {
    if (cover.phase !== 'armed') return;
    const reveal = setTimeout(() => dispatch({ type: 'reveal', now: performance.now() }), revealIn(cover, performance.now()));
    const align = alignDue(cover) ? setTimeout(() => correct(ALIGN_THRESHOLD_S), ALIGN_AFTER_PLAYING_MS) : undefined;
    return () => { clearTimeout(reveal); clearTimeout(align); };
  }, [cover, correct, dispatch]);   // coverNext rend le même objet tant que rien ne change

  // Révélé : dérive vérifiée toutes les 4 s (onglet visible, pas en BUFFERING, pas de saut depuis 15 s).
  useEffect(() => {
    if (cover.phase !== 'revealed' || paused) return;
    const check = () => {
      if (document.visibilityState !== 'visible' || ytState.current === YT_STATE.BUFFERING) return;
      if (performance.now() - lastSeek.current < MIN_SEEK_GAP_MS) return;
      correct(RUN_THRESHOLD_S);
    };
    const id = setInterval(check, DRIFT_CHECK_MS);
    document.addEventListener('visibilitychange', check);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', check); };
  }, [cover.phase, paused, correct]);

  // Réglage du décalage : la vidéo saute tout de suite à la nouvelle position, sans poster (on la regarde).
  const firstOffset = useRef(true);
  useEffect(() => {
    if (firstOffset.current) { firstOffset.current = false; return; }
    if (videoRef.current) seek(Math.max(0, clockPos() + offset));
  }, [offset, seek]);

  // Posters : le nouveau s'allume une fois chargé, l'ancien s'efface en 200 ms.
  useEffect(() => {
    setPosters((list) => {
      const old = list.filter((p) => p.id !== videoId).map((p) => ({ ...p, leaving: true }));
      return videoId ? [...old, { id: videoId, leaving: false }] : old;
    });
    const tm = setTimeout(() => setPosters((list) => list.filter((p) => !p.leaving)), 260);
    return () => clearTimeout(tm);
  }, [videoId]);

  // Poster du prochain titre préchargé et décodé (motion.md P7 : décoder avant d'échanger).
  useEffect(() => {
    if (!nextId || noMaxres.has(nextId)) return;
    const im = new Image();
    im.decoding = 'async';
    im.src = posterUrl(nextId);
    im.decode().then(() => { if (isPlaceholderThumb(im.naturalWidth)) noMaxres.add(nextId); }, () => { noMaxres.add(nextId); });
  }, [nextId]);

  return (
    <div className="portal">
      <div className="video">
        <div className="yt" ref={wrapRef} aria-hidden="true"/>
        <div className="posters" data-covered={coverVisible(cover, paused)}>
          {posters.map((p) => <Poster key={p.id} id={p.id} leaving={p.leaving}/>)}
          {!videoId && art && <img className="poster art" src={art} alt="" decoding="async" draggable={false} data-ready="true"/>}
        </div>
        <div className="veil"/>
        <div className="paused-badge plaque" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6.5" y="5" width="4" height="14"/><rect x="13.5" y="5" width="4" height="14"/></svg>
          {t('now.state.paused')}
        </div>
        {unavailable && <p className="video-note plaque">{t('now.videoUnavailable')}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4 : écrire `src/components/Stage/SyncOffset.tsx`.**

```tsx
'use client';

import { useId } from 'react';
import { usePopover } from '@/components/Header/GuildPicker';
import { OFFSET_MAX, OFFSET_MIN, OFFSET_STEP, fmtOffset } from '@/lib/stage/cover';
import { t } from '@/theme/copy';

/**
 * Réglage « Synchro vidéo » : décale l'image par rapport au son de Discord (−10 à +10 s, pas de 0,5 s).
 * Popover plaque hors de la vidéo (tech.md §5.4 : jamais de flou d'arrière-plan sur l'iframe).
 */
export default function SyncOffset({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const { open, setOpen, btnRef, wrapProps } = usePopover();
  const popId = useId();
  const helpId = useId();
  const shown = fmtOffset(value);

  return (
    <div className="sync" {...wrapProps}>
      <button ref={btnRef} type="button" className="sync-btn" aria-haspopup="dialog" aria-expanded={open}
        aria-controls={popId} onClick={() => setOpen((o) => !o)}>
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><path d="M14 4.5v5M6 14.5v5"/></svg>
        {t('now.sync.button')}
        {value !== 0 && <span className="tnum">{shown}</span>}
      </button>
      <div id={popId} className="pop plaque sync-pop" role="dialog" aria-label={t('now.sync.label')} data-open={open}>
        <label className="sync-row">
          <span>{t('now.sync.label')}</span>
          <output className="tnum" aria-live="off">{t('now.sync.value', { value: shown })}</output>
          <input type="range" min={OFFSET_MIN} max={OFFSET_MAX} step={OFFSET_STEP} value={value}
            aria-valuetext={shown} aria-describedby={helpId} onChange={(e) => onChange(Number(e.target.value))}/>
        </label>
        <p className="sync-help" id={helpId}>{t('now.sync.help')}</p>
        <button type="button" className="sync-reset" disabled={value === 0} onClick={() => onChange(0)}>{t('now.sync.reset')}</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5 : écrire `src/components/Stage/portal.css`.**

```css
/* ═══════════════════════════════════════════════════════════════════════════
   NUIT GOTHIQUE : le portail de pierre et la vidéo (lecteur YouTube persistant sous un poster).
   Repris de proto-gothique/work/refine/src/styles.css (lignes 253–270, 327–328). Écarts voulus :
   - couches de tech.md §5.3 : iframe, posters, voile de pause, badge ; le poster couvre jusqu'à
     PLAYING + 3,5 s et pendant la pause (data-covered, Portal.tsx) ;
   - la révérence (la scène s'incline à .97) arrive à l'étape 4 : ici, seuls le voile et le badge ;
   - « Synchro vidéo » : popover plaque hors de la vidéo, jamais de flou sur l'iframe ;
   - l'ombre du portail est une box-shadow, pas le `filter: drop-shadow` du prototype : un filtre sur un
     ancêtre de l'iframe rejoue une passe de rendu à chaque image de la vidéo (tech.md §6.2) ; le cadre
     de pierre est rectangulaire, l'ombre est la même ;
   - un titre sans vidéo YouTube (SoundCloud) montre sa pochette entière (.poster.art).
   Variables lues : --vw --f (posées sur .stage).
   ═══════════════════════════════════════════════════════════════════════════ */
.portal {
  position: relative; z-index: 2; width: calc(var(--vw) + 2 * var(--f));
  border: var(--f) solid transparent; border-image: url(/gothique/stone-frame-640.webp) 96 / var(--f) stretch;
  box-shadow: 0 18px 30px rgb(0 0 0 / .6);
  transition: opacity 500ms ease;
}
.stage[data-scene=night] .portal { opacity: 0; pointer-events: none; }
.video { position: relative; width: var(--vw); aspect-ratio: 16 / 9; overflow: hidden; background: #050404; }
.video .yt { position: absolute; inset: 0; z-index: 1; pointer-events: none; }
.video .yt iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }

.video .posters { position: absolute; inset: 0; z-index: 2; opacity: 1; transition: opacity 200ms ease; }
.video .posters[data-covered=false] { opacity: 0; transition-duration: var(--dur-reveal); }
.video .poster {
  position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
  opacity: 0; transition: opacity var(--dur-reveal) var(--ease-out);
}
.video .poster[data-ready=true] { opacity: 1; }
.video .poster[data-leaving] { opacity: 0; transition-duration: 200ms; }
.video .poster.art { object-fit: contain; }

.video .veil { position: absolute; inset: 0; z-index: 3; background: #000; opacity: 0; transition: opacity 300ms ease; pointer-events: none; }
.stage[data-paused=true] .video .veil { opacity: .36; }
.paused-badge {
  position: absolute; left: 50%; top: 50%; z-index: 4; display: flex; align-items: center; gap: 10px;
  padding: 10px 16px 10px 12px; font: 700 13px/1 var(--f-ui); letter-spacing: .1em; text-transform: uppercase;
  transform: translate(-50%, -50%) scale(.96); opacity: 0; pointer-events: none;
  transition: opacity 200ms ease, transform 300ms var(--ease-out);
}
.paused-badge svg { width: 15px; height: 15px; }
.stage[data-paused=true] .paused-badge { opacity: 1; transform: translate(-50%, -50%); }
.video-note { position: absolute; left: 12px; right: 12px; bottom: 12px; z-index: 4; margin: 0; padding: 8px 12px; font-size: 14px; color: var(--os-2); }

/* sous le portail : « Image seulement… » et le réglage de synchro */
.muted-note { display: flex; align-items: center; gap: 6px; margin: 0; min-width: 0; font-size: 13px; color: var(--cendre); }
.muted-note svg { width: 14px; height: 14px; flex: none; }
.sync { position: relative; flex: none; }
.sync-btn {
  display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border-radius: 7px; corner-shape: bevel;
  font: 600 13px/1 var(--f-ui); color: var(--cendre); box-shadow: inset 0 0 0 1px var(--hair);
  transition: transform var(--dur-press) var(--ease-out);
}
.sync-btn svg { width: 15px; height: 15px; }
.sync-btn .tnum { color: rgb(var(--lumiere-rgb)); }
.sync-btn:active { transform: scale(.97); }
@media (hover: hover) and (pointer: fine) { .sync-btn:hover { color: var(--os); box-shadow: inset 0 0 0 1px var(--hair-2); } }
.sync-pop { top: auto; right: 0; bottom: calc(100% + 8px); transform-origin: bottom right; min-width: 300px; padding: 12px; }
.sync-row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px 12px; font-size: 14px; color: var(--os-2); }
.sync-row output { font-weight: 700; color: var(--os); }
.sync-row input { grid-column: 1 / -1; width: 100%; accent-color: rgb(var(--lumiere-rgb)); }
.sync-help { margin: 8px 0 10px; font-size: 13px; color: var(--cendre); }
.sync-reset {
  height: 34px; padding: 0 12px; border-radius: 7px; corner-shape: bevel; font-weight: 700; font-size: 14px;
  box-shadow: inset 0 0 0 1px var(--hair-2); transition: transform var(--dur-press) var(--ease-out);
}
.sync-reset:active { transform: scale(.97); }
.sync-reset:disabled { opacity: .4; cursor: default; }

@media (prefers-reduced-motion: reduce) {
  .paused-badge, .stage[data-paused=true] .paused-badge { transform: translate(-50%, -50%); }
  .sync-btn, .sync-reset { transition: none; }
}
```

- [ ] **Step 6 : lancer** `npm test` (clés du deck de `Portal` et `SyncOffset` comprises), `npx tsc --noEmit`, puis `npx next build`. Attendu : tout vert.

### Task 6 : ce qui joue (titre Grenze, demandeur) et transport

**Files:**
- Create: `services/web/src/components/Stage/NowPlaying.tsx`, `services/web/src/components/Stage/Transport.tsx`, `services/web/src/components/Stage/now.css`

**Interfaces:**
- Consumes :
  - tâche 4 : `parseTitle` ; `kickerKey`, `requesterOf`, `requesterKeys`, `kingSealSrc` et `seedOf` ;
  - étape 1 : `useStore`, `usePlayer` (`player`, `togglePause`, `skip`, `stop`, `toggleRepeat`, `restartTrack`), `usePopover`, `kingName`, `t` et `quip`.
- Produces :

```ts
// src/components/Stage/NowPlaying.tsx
export const NOW_TITLE_ID = 'now-title';
export default function NowPlaying(): JSX.Element;   // .now-text > .kicker, h2.title-slot#now-title, p.meta-slot ; pose document.title
// src/components/Stage/Transport.tsx
export default function Transport(): JSX.Element;    // .transport (role=group) : arrêt + confirmation, début, lecture/pause, suivant, boucle
```

- Le Roi, c'est l'utilisateur : `requesterOf(addedBy, me.id)` vaut `mine` pour ses propres titres, qui affichent son sceau et « Demandé par vous ».
- Les emplacements du titre gardent leur hauteur sans texte (`--title-size`), pour que `useStageLayout` ne dépende pas du contenu.
- L'arrêt demande confirmation si la file a des titres (`confirm.stop.*`), et le focus va sur « Garder la musique » (DESIGN §7).

Pas de test unitaire propre : les garde-fous sont `tests/stage-copy.test.mjs` (clés `controls.*`, `confirm.stop.*`, `brand.docTitle.*`), `tsc` et `next build`.

- [ ] **Step 1 : écrire `src/components/Stage/NowPlaying.tsx`.**

```tsx
'use client';

import { useEffect } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { kingName } from '@/components/Header/KingAvatar';
import { parseTitle } from '@/lib/titles';
import { kickerKey, kingSealSrc, requesterKeys, requesterOf, seedOf } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';

/** Id du titre du morceau : il nomme l'horloge (role=progressbar, aria-labelledby). */
export const NOW_TITLE_ID = 'now-title';

/**
 * Ce qui joue, sous le portail : surtitre (état + réplique de Greg), titre en Grenze, artiste et demandeur.
 * Le Roi, c'est l'utilisateur : son propre titre porte son sceau et « Demandé par vous ».
 * Les emplacements gardent leur hauteur sans titre (la mise en page de la scène n'en dépend pas).
 * Styles : now.css.
 */
export default function NowPlaying() {
  const current = useStore((s) => s.player.current);
  const paused = useStore((s) => s.player.paused);
  const repeat = useStore((s) => s.player.repeat);
  const me = useStore((s) => s.me);
  const parsed = current ? parseTitle(current.title, current.artist) : null;
  const song = parsed?.song || current?.title || '';

  useEffect(() => {
    document.title = current
      ? t(paused ? 'brand.docTitle.paused' : 'brand.docTitle.playing', { title: song })
      : t('brand.docTitle.idle');
  }, [current, paused, song]);

  if (!current || !parsed) {
    return (
      <div className="now-text" aria-hidden="true">
        <div className="kicker"/><div className="title-slot"/><div className="meta-slot"/>
      </div>
    );
  }

  const req = requesterOf(current.addedBy, me?.id);
  const keys = requesterKeys(req);
  const vars = req.kind === 'other' ? { name: req.name } : undefined;
  const q = keys.quips ? quip(keys.quips, seedOf(current.url || current.title), vars) : null;

  return (
    <div className="now-text">
      <div className="kicker">
        <span className="eq" aria-hidden="true"><i/><i/><i/></span>
        <span className="kk">{t(kickerKey({ paused, repeat }))}</span>
        {q && <span className="kq quip" aria-hidden="true">— {q}</span>}
      </div>
      <h2 className="title-slot" id={NOW_TITLE_ID} title={current.title}>{song}</h2>
      <p className="meta-slot">
        {parsed.artist && <><span className="artist">{parsed.artist}</span><span className="dot-sep" aria-hidden="true"/></>}
        <span className="by">
          {req.kind === 'mine' && <img className="seal" src={kingSealSrc(kingName(me))} alt="" width={20} height={20} decoding="async"/>}
          {t(keys.plain, vars)}
        </span>
      </p>
    </div>
  );
}
```

- [ ] **Step 2 : écrire `src/components/Stage/Transport.tsx`.** Chaque action attrape son rejet : `usePlayer` a déjà affiché l'erreur dans le statut. Les mises à jour optimistes arrivent à l'étape 3.

```tsx
'use client';

import { useEffect, useId, useRef } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { usePopover } from '@/components/Header/GuildPicker';
import { seedOf } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';

const I = {
  stop: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="6.5" width="11" height="11"/></svg>,
  restart: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5.5v13"/><path d="M18.5 6.5v11L9.5 12z"/></svg>,
  skip: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5.5v13"/><path d="M5.5 6.5v11l9-5.5z"/></svg>,
  repeat: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M16.5 3.5l3 3-3 3"/><path d="M4.5 12V10a3.5 3.5 0 0 1 3.5-3.5h11"/><path d="M7.5 20.5l-3-3 3-3"/><path d="M19.5 12v2a3.5 3.5 0 0 1-3.5 3.5H5"/></svg>,
};

/**
 * Transport : tout arrêter (confirmé si la file a des titres), reprendre au début, lecture/pause
 * (une rondelle du verre du morceau, en --lumiere), suivant, boucle. Libellés : deck `controls.*`.
 * Les actions passent par usePlayer (les mises à jour optimistes arrivent à l'étape 3). Styles : now.css.
 */
export default function Transport() {
  const { player, togglePause, skip, stop, toggleRepeat, restartTrack } = usePlayer();
  const on = !!player.current;
  const queued = player.queue.length;
  const confirm = usePopover();
  const noRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Le dialogue d'arrêt met le focus sur le choix sûr (DESIGN §7).
  useEffect(() => { if (confirm.open) noRef.current?.focus(); }, [confirm.open]);

  const onStop = () => {
    if (!on && !queued) return;
    if (queued) confirm.setOpen((o) => !o);
    else stop().catch(() => {});
  };
  const confirmStop = () => { confirm.close(true); stop().catch(() => {}); };

  return (
    <div className="transport" role="group" aria-label={t('controls.group')}>
      <div className="stop-wrap" {...confirm.wrapProps}>
        <button ref={confirm.btnRef} type="button" className="tbtn" disabled={!on && !queued} onClick={onStop}
          aria-label={t('controls.stop.aria')} aria-haspopup={queued ? 'dialog' : undefined} aria-expanded={queued ? confirm.open : undefined}>
          {I.stop}<span className="tip plaque" aria-hidden="true">{t('controls.stop.tip')}</span>
        </button>
        <div className="pop plaque confirm" role="dialog" aria-labelledby={titleId} data-open={confirm.open}>
          <h3 id={titleId}>{t('confirm.stop.title')}</h3>
          <p>{t('confirm.stop.body', { n: queued })}</p>
          <p className="quip" aria-hidden="true">{quip('confirm.stop', seedOf(String(queued)))}</p>
          <div className="row-btns">
            <button ref={noRef} type="button" className="btn-ghost" onClick={() => confirm.close(true)}>{t('confirm.stop.cancel')}</button>
            <button type="button" className="btn-danger" onClick={confirmStop}>{t('confirm.stop.confirm')}</button>
          </div>
        </div>
      </div>
      <button type="button" className="tbtn" disabled={!on} onClick={() => restartTrack().catch(() => {})} aria-label={t('controls.restart.aria')}>
        {I.restart}<span className="tip plaque" aria-hidden="true">{t('controls.restart.tip')}</span>
      </button>
      <button type="button" className="tbtn main" disabled={!on} onClick={() => togglePause().catch(() => {})} aria-label={t(player.paused ? 'controls.play.aria' : 'controls.pause.aria')}>
        <svg className="ic-pause" data-shown={on && !player.paused} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6.5" y="4.8" width="4.2" height="14.4"/><rect x="13.3" y="4.8" width="4.2" height="14.4"/></svg>
        <svg className="ic-play" data-shown={!on || player.paused} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8.3 4.8v14.4L19.6 12z"/></svg>
        <span className="tip plaque" aria-hidden="true">{t(player.paused ? 'controls.play.tip' : 'controls.pause.tip')}</span>
      </button>
      <button type="button" className="tbtn" disabled={!on} onClick={() => skip().catch(() => {})} aria-label={t('controls.skip.aria')}>
        {I.skip}<span className="tip plaque" aria-hidden="true">{t('controls.skip.tip')}</span>
      </button>
      <button type="button" className="tbtn" disabled={!on} aria-pressed={player.repeat} onClick={() => toggleRepeat().catch(() => {})} aria-label={t('controls.repeat.aria')}>
        {I.repeat}<span className="tip plaque" aria-hidden="true">{t('controls.repeat.tip')}</span>
      </button>
    </div>
  );
}
```

- [ ] **Step 3 : écrire `src/components/Stage/now.css`.**

```css
/* ═══════════════════════════════════════════════════════════════════════════
   NUIT GOTHIQUE : ce qui joue (surtitre, titre Grenze, demandeur) et le transport.
   Repris de proto-gothique/work/refine/src/styles.css (lignes 300–368). Écarts voulus :
   - le titre garde sa hauteur même vide : la mise en page de la scène (useStageLayout) n'en dépend pas ;
   - transitions sur transform et opacity seulement : les survols changent de couleur sans animation ;
   - l'icône lecture/pause se croise en opacité et échelle, sans flou (le flou vient avec la révérence, étape 4) ;
   - « Demandé par vous » porte le sceau du Roi (l'utilisateur) : jamais Greg.
   ═══════════════════════════════════════════════════════════════════════════ */
.now-text { min-width: 0; }
.kicker {
  display: flex; align-items: baseline; gap: 8px; min-width: 0; height: 18px;
  font: 700 12px/1 var(--f-ui); letter-spacing: .12em; text-transform: uppercase; color: rgb(var(--lumiere-rgb));
}
.kicker .kk { flex: none; }
.kicker .kq {
  flex: 1; min-width: 0; font: italic 400 15px/1 var(--f-voice); letter-spacing: 0; text-transform: none;
  color: var(--cendre); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kicker .eq { display: flex; gap: 2px; align-items: flex-end; height: 11px; flex: none; transform-origin: bottom; transition: transform 300ms var(--ease-out), opacity 300ms ease; }
.kicker .eq i { width: 2px; height: 100%; background: currentColor; transform-origin: bottom; animation: eq 900ms ease-in-out infinite alternate; }
.kicker .eq i:nth-child(2) { animation-duration: 700ms; animation-delay: -300ms; }
.kicker .eq i:nth-child(3) { animation-duration: 1100ms; animation-delay: -600ms; }
@keyframes eq { 0% { transform: scaleY(.25); } 100% { transform: scaleY(1); } }
.stage[data-paused=true] .kicker .eq { transform: scaleY(.3); opacity: .6; }
.stage[data-paused=true] .kicker .eq i { animation-play-state: paused; }

/* le titre du morceau : Grenze 600, sa propre voix ; la hauteur suit la taille, avec ou sans texte */
.title-slot {
  --title-size: clamp(28px, calc(var(--vw) * .055), 40px);
  margin: 8px 0 0; min-height: calc(var(--title-size) * 1.08 + 2px); padding-bottom: 2px;
  font: 600 var(--title-size)/1.08 var(--f-title); letter-spacing: -.015em; color: var(--os);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.meta-slot {
  display: flex; align-items: center; gap: 7px; margin: 4px 0 0; min-height: 22px;
  font-size: 15.5px; color: var(--cendre); white-space: nowrap; overflow: hidden;
}
.meta-slot .artist { overflow: hidden; text-overflow: ellipsis; }
.meta-slot .by { display: inline-flex; align-items: center; gap: 6px; flex: none; color: var(--os-2); }
.meta-slot .seal { width: 20px; height: 20px; flex: none; filter: drop-shadow(0 1px 1px rgb(0 0 0 / .6)); }
.dot-sep { width: 3px; height: 3px; border-radius: 50%; background: var(--cendre-2); flex: none; }

/* transport */
.transport { display: flex; align-items: center; gap: 6px; }
.stop-wrap { position: relative; }
.tbtn {
  position: relative; width: 44px; height: 44px; border-radius: 9px; corner-shape: bevel;
  display: grid; place-items: center; color: var(--os-2);
  transition: transform var(--dur-press) var(--ease-out);
}
.tbtn svg { width: 22px; height: 22px; }
.tbtn:active:not(:disabled) { transform: scale(.95); }
@media (hover: hover) and (pointer: fine) { .tbtn:not(:disabled):hover { background: var(--voute); color: var(--os); } }
.tbtn[aria-pressed=true] { color: rgb(var(--lumiere-rgb)); }
.tbtn[aria-pressed=true]::after {
  content: ""; position: absolute; left: 50%; bottom: 4px; width: 4px; height: 4px; margin-left: -2px;
  background: currentColor; transform: rotate(45deg);
}
.tbtn:disabled { opacity: .35; cursor: default; }
/* lecture / pause : une rondelle du verre du morceau, cerclée d'un plomb */
.tbtn.main {
  width: 66px; height: 66px; margin: 0 6px; border-radius: 50%; corner-shape: round; color: #1a120b;
  background:
    radial-gradient(60% 45% at 50% 22%, rgb(255 252 244 / .55), transparent 70%),
    repeating-linear-gradient(104deg, rgb(255 255 255 / .06) 0 3px, transparent 3px 9px),
    radial-gradient(circle at 50% 42%, rgb(var(--lumiere-rgb)) 0 34%, color-mix(in oklab, rgb(var(--lumiere-rgb)) 58%, #0b0908) 100%);
  box-shadow: inset 0 0 0 3px var(--plomb), inset 0 0 0 4px rgb(255 255 255 / .18), 0 0 0 1px rgb(var(--pierre-rgb) / .7),
    0 0 0 4px rgb(11 9 8 / .9), 0 0 0 5px rgb(var(--pierre-rgb) / .28), 0 0 34px -6px rgb(var(--lumiere-rgb) / .7),
    inset 0 -8px 14px rgb(0 0 0 / .22);
}
@media (hover: hover) and (pointer: fine) { .tbtn.main:not(:disabled):hover { background-color: transparent; color: #1a120b; filter: brightness(1.08); } }
.tbtn.main svg {
  width: 26px; height: 26px; position: absolute; left: 50%; top: 50%; margin: -13px 0 0 -13px;
  transition: opacity var(--dur-micro) ease, transform var(--dur-micro) var(--ease-out);
}
.tbtn.main svg[data-shown=false] { opacity: 0; transform: scale(.6); }

/* info-bulles : la première attend 400 ms, jamais au toucher */
.tip {
  position: absolute; bottom: calc(100% + 10px); left: 50%; z-index: 5; white-space: nowrap; pointer-events: none;
  font: 600 13px/1 var(--f-ui); color: var(--os); padding: 7px 9px; border-radius: 6px;
  opacity: 0; transform: translateX(-50%) translateY(2px);
  transition: opacity 125ms var(--ease-out), transform 125ms var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .tbtn:not(:disabled):hover .tip { opacity: 1; transform: translateX(-50%); transition-delay: 400ms; }
}

/* « Tout arrêter ? » s'ouvre depuis le bouton */
.confirm {
  top: auto; right: auto; bottom: calc(100% + 12px); left: 50%; margin-left: -155px; width: 310px; padding: 14px;
  transform-origin: 50% calc(100% + 12px);
}
.confirm h3 { margin: 0 0 6px; font-size: 17px; font-weight: 700; }
.confirm p { margin: 0 0 4px; font-size: 15px; color: var(--os-2); }
.confirm .quip { font-size: 15px; margin: 6px 0 12px; }
.confirm .row-btns { display: flex; gap: 8px; justify-content: flex-end; }

@media (prefers-reduced-motion: reduce) {
  .kicker .eq i { animation: none; transform: scaleY(.6); }
  .kicker .eq, .tbtn, .tip { transition: none; }
  .tbtn.main svg[data-shown=false] { transform: none; }
  .tip { transform: translateX(-50%); }
}
@media (max-width: 900px) {
  .transport { justify-content: center; }
  .title-slot { --title-size: 28px; }
}
@media (max-width: 520px) {
  .tbtn.main { width: 60px; height: 60px; }
  .transport { gap: 4px; }
}
```

- [ ] **Step 4 : lancer** `npm test`, `npx tsc --noEmit`, puis `npx next build`. Attendu : tout vert.

### Task 7 : horloge en lecture seule et états de nuit

**Files:**
- Create: `services/web/src/hooks/useStageClock.ts`, `services/web/src/components/Stage/Clock.tsx`, `services/web/src/components/Stage/NightState.tsx`, `services/web/src/components/Stage/clock.css`, `services/web/src/components/Stage/night.css`
- Create: `services/web/public/gothique/jester-cap-256.webp`, `services/web/public/gothique/jester-cap-512.webp` : le bonnet à grelots de Greg, copié depuis `P\assets\3d\jester_cap@256.webp` et `@512.webp`, CC0
- Modify: `services/web/public/licenses/LICENSES.md` (une ligne), `services/web/tests/assets.test.mjs` (un test)

**Interfaces:**
- Consumes :
  - tâche 3 : `dialGeometry`, `clockPane`, `hitArcPath`, `paneAtPoint`, `paneTime`, `fmtSpoken` et `DialGeometry` ;
  - tâche 4 : `NightKind` ;
  - étape 1 : `useStore`, `livePosition`, `fmt`, `api.getLoginUrl`, `t` et `quip`.
- Produces :

```ts
// src/hooks/useStageClock.ts
export function useStageClock(rootRef: RefObject<HTMLElement>, n: number): number;   // panneau courant (−1 : aucun) ; écrit [data-clock]
// src/components/Stage/Clock.tsx
export default function Clock(p: { dial: DialGeometry; active: boolean; labelledBy: string }): JSX.Element;  // svg.dial (progressbar) + .spring + .dial-tip
export function TimesRow(): JSX.Element;   // .times-row : les mêmes temps, en ligne sous le portail
// src/components/Stage/NightState.tsx
export default function NightState(p: { kind: NightKind }): JSX.Element;   // .night[data-kind] dans l'oculus
```

L'oculus :
- **rien en lecture** : la couronne du Roi (`crown-320.webp`) qui l'attend ;
- **chargement** : la couronne qui tourne (`crown-turn-128.avif`), remplacée par `crown-still-128.avif` sous mouvement réduit grâce à `<picture>` ;
- **déconnecté** : le portrait de Greg (`greg-face-192.webp`, `alt` = `brand.portraitAlt`), coiffé du bonnet à grelots. Jamais de couronne sur Greg.

- [ ] **Step 1 : écrire le test qui échoue.** Dans `tests/assets.test.mjs`, ajouter `readFileSync` à l'import de `node:fs`, puis ce test en fin de fichier :

```js
test('bonnet à grelots de Greg (portrait de la nuit « déconnecté »), avec sa licence', () => {
  for (const p of ['gothique/jester-cap-256.webp', 'gothique/jester-cap-512.webp']) {
    assert.ok(existsSync(pub(p)) && statSync(pub(p)).size > 0, p);
  }
  assert.match(readFileSync(pub('licenses/LICENSES.md'), 'utf8'), /jester-cap-256\.webp/);
});
```

L'import devient `import { existsSync, readFileSync, statSync } from 'node:fs';`.

- [ ] **Step 2 : lancer** `npm test`. Attendu : FAIL sur `gothique/jester-cap-256.webp`.
- [ ] **Step 3 : copier les assets et déclarer leur licence.**

```powershell
$S = "C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad"
Copy-Item "$S\design\assets\3d\jester_cap@256.webp" services\web\public\gothique\jester-cap-256.webp
Copy-Item "$S\design\assets\3d\jester_cap@512.webp" services\web\public\gothique\jester-cap-512.webp
```

  - Tailles attendues : 13 630 et 31 114 octets.
  - Dans `public/licenses/LICENSES.md`, insérer cette ligne juste après celle de `greg-face-96.webp`, `greg-face-192.webp` :

```md
| `jester-cap-256.webp`, `jester-cap-512.webp` | Bonnet à grelots de Greg, le valet, posé sur son portrait quand personne n'est connecté | Œuvre originale : bonnet de fou modélisé dans Blender (cornes cousues, calotte mi-partie à passepoil doré, grelots), rendu Cycles | CC0 1.0 |
```

- [ ] **Step 4 : écrire `src/hooks/useStageClock.ts`.** Un minuteur de 250 ms, sans boucle par image (motion.md P4). Il ne fait un rendu React qu'au changement de panneau, soit environ toutes les 11 s pour 3 min 30.

```ts
'use client';

import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { livePosition } from '@/lib/playerUtils';
import { fmt } from '@/lib/format';
import { clockPane, fmtSpoken } from '@/lib/stage/dial';
import { t } from '@/theme/copy';

const TICK_MS = 250;

/**
 * Le temps de la scène, sans boucle par image (motion.md P4) : toutes les 250 ms, écrit les libellés
 * `[data-clock=cur]` / `[data-clock=tot]` et l'aria de `[data-clock=aria]` sous `rootRef` (seulement
 * ce qui change ; React ne leur donne jamais de texte), et renvoie le panneau courant de l'horloge :
 * un rendu React par panneau, pas plus.
 */
export function useStageClock(rootRef: RefObject<HTMLElement>, n: number): number {
  const [pane, setPane] = useState(-1);
  const nRef = useRef(n);
  nRef.current = n;

  useEffect(() => {
    let lastPane = -2;
    // écrit seulement ce qui diffère : un libellé monté plus tard (TimesRow) est rempli au tick suivant
    const put = (root: HTMLElement, sel: string, text: string) =>
      root.querySelectorAll(sel).forEach((el) => { if (el.textContent !== text) el.textContent = text; });
    const tick = () => {
      const root = rootRef.current;
      if (!root) return;
      const s = useStore.getState();
      const track = s.player.current;
      const dur = track ? s.tickBase.dur || s.player.duration || track.duration || 0 : 0;
      const pos = track ? livePosition(s.tickBase, s.player.paused, performance.now()) : 0;
      put(root, '[data-clock=cur]', track ? fmt(pos) : '0:00');
      put(root, '[data-clock=tot]', dur > 0 ? fmt(dur) : '--:--');
      const el = root.querySelector('[data-clock=aria]');
      const text = track && dur > 0 ? t('now.progressAria', { cur: fmtSpoken(pos), length: fmtSpoken(dur) }) : '';
      if (el && el.getAttribute('aria-valuetext') !== text) {
        el.setAttribute('aria-valuemax', String(Math.round(dur)));
        el.setAttribute('aria-valuenow', String(Math.round(Math.min(pos, dur))));
        el.setAttribute('aria-valuetext', text);
      }
      const i = track ? clockPane(pos, dur, nRef.current) : -1;
      if (i !== lastPane) { lastPane = i; setPane(i); }
    };
    tick();
    const id = setInterval(tick, TICK_MS);
    return () => clearInterval(id);
  }, [rootRef]);

  return pane;
}
```

- [ ] **Step 5 : écrire `src/components/Stage/Clock.tsx`.**
  - Lecture seule (spec §2) : ni clic, ni touches, ni `tabIndex`. Le survol montre le temps.
  - Les libellés n'ont pas d'enfants React : `useStageClock` les remplit.

```tsx
'use client';

import { useRef } from 'react';
import type { PointerEvent } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { fmt } from '@/lib/format';
import { hitArcPath, paneAtPoint, paneTime } from '@/lib/stage/dial';
import type { DialGeometry } from '@/lib/stage/dial';

/**
 * L'horloge en lecture seule : l'anneau du vitrail (allumé par la rosace) porte une zone de survol qui
 * montre le temps sous le pointeur ; ni clic ni touches (le bot n'a pas de seek, spec §2). Les temps sont
 * posés aux naissances de l'arc, comme les chiffres d'un cadran. Textes écrits par useStageClock
 * (`data-clock`). `labelledBy` : id du titre du morceau. Styles : clock.css.
 */
export default function Clock({ dial, active, labelledBy }: { dial: DialGeometry; active: boolean; labelledBy: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  const onMove = (e: PointerEvent<SVGPathElement>) => {
    const svg = svgRef.current, tip = tipRef.current;
    const stage = svg?.closest('.stage');
    const s = useStore.getState();
    const dur = s.tickBase.dur || s.player.duration || 0;
    if (!active || !svg || !tip || !stage || !(dur > 0)) return;
    const r = svg.getBoundingClientRect();
    const i = paneAtPoint(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2), dial);
    tip.textContent = fmt(paneTime(i, dial.n, dur));
    const sr = stage.getBoundingClientRect();
    tip.style.left = `${e.clientX - sr.left}px`;
    tip.style.top = `${e.clientY - sr.top}px`;
    tip.dataset.on = 'true';
  };
  const onLeave = () => { if (tipRef.current) tipRef.current.dataset.on = 'false'; };

  return (
    <>
      <svg ref={svgRef} className="dial" viewBox="-1.06 -1.06 2.12 2.12" data-clock="aria"
        role="progressbar" aria-labelledby={labelledBy} aria-valuemin={0} aria-hidden={active ? undefined : true}>
        <path className="dial-hit" d={hitArcPath(dial)} strokeWidth={0.1} onPointerMove={onMove} onPointerLeave={onLeave}/>
      </svg>
      <span className="spring l tnum" data-clock="cur" aria-hidden="true"/>
      <span className="spring r tnum" data-clock="tot" aria-hidden="true"/>
      <div className="dial-tip plaque tnum" ref={tipRef} aria-hidden="true"/>
    </>
  );
}

/** Les mêmes temps, en ligne sous le portail quand les naissances de l'arc manquent de place. */
export function TimesRow() {
  return (
    <div className="times-row tnum" aria-hidden="true">
      <span data-clock="cur"/>
      <span data-clock="tot"/>
    </div>
  );
}
```

- [ ] **Step 6 : écrire `src/components/Stage/NightState.tsx`.** La graine des répliques est tirée dans un effet, jamais pendant le rendu serveur (pas d'écart d'hydratation).

```tsx
'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { NightKind } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';

/** « Ajouter un titre » : donne le focus à la recherche de l'en-tête. */
function focusSearch(): void {
  document.querySelector<HTMLInputElement>('.top .field input')?.focus();
}

/**
 * La nuit (spec §4) : rien en lecture, chargement ou déconnecté. La rosace entière est au clair de lune ;
 * son oculus porte la couronne qui attend le Roi (rien en lecture), la couronne qui tourne (chargement) ou
 * le portrait de Greg en bonnet de valet (déconnecté). Greg ne porte jamais la couronne. Styles : night.css.
 */
export default function NightState({ kind }: { kind: NightKind }) {
  // Réplique tirée au montage côté client seulement (pas d'écart d'hydratation).
  const [seed, setSeed] = useState(0);
  useEffect(() => { setSeed(Math.floor(Math.random() * 1e6)); }, [kind]);

  if (kind === 'loading') {
    return (
      <div className="night" data-kind="loading" role="status">
        <div className="vl-inner">
          <div className="heart">
            <picture className="loader">
              <source srcSet="/gothique/crown-still-128.avif" media="(prefers-reduced-motion: reduce)"/>
              <img src="/gothique/crown-turn-128.avif" alt="" width={96} height={96} decoding="async"/>
            </picture>
          </div>
          <p className="vl-body">{t('loading.boot.text')}</p>
          <p className="quip" aria-hidden="true">{quip('loading.boot', seed)}</p>
        </div>
      </div>
    );
  }

  if (kind === 'out') {
    return (
      <div className="night" data-kind="out">
        <div className="vl-inner">
          <div className="heart valet">
            <span className="portrait"><img src="/gothique/greg-face-192.webp" alt={t('brand.portraitAlt')} width={150} height={150} decoding="async"/></span>
            <img className="cap" src="/gothique/jester-cap-256.webp" srcSet="/gothique/jester-cap-256.webp 1x, /gothique/jester-cap-512.webp 2x"
              alt="" width={128} height={128} decoding="async"/>
          </div>
          <p className="vl-kicker">{t('auth.kicker')}</p>
          <h2 className="vl-title">{t('auth.title')}</h2>
          <p className="vl-body">{t('auth.body')}</p>
          <a className="btn-solid" href={api.getLoginUrl()}>{t('auth.cta')}</a>
          <p className="vl-small">{t('auth.privacy')}</p>
          <p className="quip" aria-hidden="true">{quip('auth', seed)}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="night" data-kind="empty">
      <div className="vl-inner">
        <div className="heart"><img className="throne" src="/gothique/crown-320.webp" alt="" width={150} height={150} decoding="async"/></div>
        <h2 className="vl-title">{t('now.idle.title')}</h2>
        <p className="vl-body">{t('now.idle.body')}</p>
        <p className="quip" aria-hidden="true">{quip('now.idle', seed)}</p>
        <button type="button" className="btn-ghost" onClick={focusSearch}>{t('now.idle.cta')}</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 7 : écrire `src/components/Stage/clock.css` et `src/components/Stage/night.css`.**

```css
/* ═══════════════════════════════════════════════════════════════════════════
   NUIT GOTHIQUE : l'horloge en lecture seule (zone de survol sur l'anneau, temps aux naissances de l'arc).
   Repris de proto-gothique/work/refine/src/styles.css (lignes 235–251). Écart voulu : pas de seek
   (le bot n'a pas de commande) : ni curseur main, ni anneau de focus, la zone ne sert qu'au survol.
   Variables lues : --R --crown (posées sur .stage).
   ═══════════════════════════════════════════════════════════════════════════ */
.dial {
  position: absolute; left: 50%; top: 0; z-index: 1; overflow: visible; pointer-events: none;
  width: calc(2.12 * var(--R)); height: calc(2.12 * var(--R)); margin-left: calc(-1.06 * var(--R));
}
.dial .dial-hit { fill: none; stroke: transparent; pointer-events: stroke; }
.stage[data-scene=night] .dial .dial-hit { pointer-events: none; }
.spring { position: absolute; top: calc(var(--crown) - 9px); z-index: 2; font: 600 15px/1 var(--f-ui); color: var(--cendre); white-space: nowrap; }
.spring.l { right: calc(50% + 1.03 * var(--R) + 10px); color: rgb(var(--lumiere-rgb)); }
.spring.r { left: calc(50% + 1.03 * var(--R) + 10px); }
.stage[data-springs=row] .spring { display: none; }
.times-row { display: none; justify-content: space-between; margin-top: 10px; font: 600 13px/1 var(--f-ui); color: var(--cendre); }
.times-row span:first-child { color: rgb(var(--lumiere-rgb)); }
.stage[data-springs=row] .times-row { display: flex; }
.stage[data-scene=night] .spring, .stage[data-scene=night] .times-row { visibility: hidden; }
.dial-tip {
  position: absolute; z-index: 5; pointer-events: none; padding: 6px 8px; font: 600 13px/1 var(--f-ui); color: var(--os);
  opacity: 0; transform: translate(-50%, -100%) translateY(-10px); transition: opacity 120ms var(--ease-out);
}
.dial-tip[data-on=true] { opacity: 1; }
@media (hover: none) { .dial .dial-hit { pointer-events: none; } }
```

```css
/* ═══════════════════════════════════════════════════════════════════════════
   NUIT GOTHIQUE : la nuit (rien en lecture, chargement, déconnecté), dans l'oculus de la rose entière.
   Repris de proto-gothique/work/refine/src/styles.css (lignes 275–295). Écarts voulus :
   - casting (spec §1) : l'oculus porte la couronne du Roi qui l'attend, la couronne qui tourne, ou le
     portrait de Greg coiffé du bonnet à grelots (jester-cap), jamais une couronne sur Greg ;
   - le texte de nuit monte de 6 px en 400 ms, après la rose (+320 ms) quand on vient d'arrêter ;
   - mouvement réduit : opacité seule ; la couronne tournante devient la couronne immobile (<picture>).
   Variables lues : --crown --cR --heart --R (posées sur .stage).
   ═══════════════════════════════════════════════════════════════════════════ */
.night {
  position: absolute; left: 0; right: 0; top: calc(var(--crown) + var(--cR) - var(--heart) / 2); z-index: 3;
  display: flex; justify-content: center; text-align: center; pointer-events: none;
}
.night .vl-inner {
  display: flex; flex-direction: column; align-items: center; gap: 10px; max-width: 460px; pointer-events: auto;
  text-shadow: 0 1px 14px rgb(0 0 0 / .85);
  animation: night-in 400ms var(--ease-out) both;
}
.night[data-kind=empty] .vl-inner { animation-delay: 320ms; }
@keyframes night-in { from { opacity: 0; transform: translateY(6px); } }
.night p { margin: 0; }
.heart { position: relative; width: var(--heart); height: var(--heart); display: grid; place-items: center; margin-bottom: calc(var(--R) * .34); }
.heart::after {
  content: ""; position: absolute; inset: 0; border-radius: 50%; pointer-events: none;
  background: url(/gothique/grain-256.webp); opacity: .5; mix-blend-mode: overlay;
}
/* le trône vide : la couronne du Roi l'attend */
.throne {
  width: 100%; height: 100%; object-fit: contain;
  filter: sepia(.12) saturate(.9) brightness(.96) drop-shadow(0 -1.5px 0 rgb(180 196 226 / .55)) drop-shadow(0 16px 12px rgb(0 0 0 / .75));
}
.loader { width: calc(var(--heart) * .64); height: calc(var(--heart) * .64); }
.loader img { width: 100%; height: 100%; object-fit: contain; filter: sepia(.12) drop-shadow(0 10px 14px rgb(0 0 0 / .6)); }
/* Greg, valet : son portrait, et le bonnet à grelots posé de travers sur le haut du médaillon */
.heart.valet::after { display: none; }
.portrait {
  display: block; width: 100%; height: 100%; border-radius: 50%; overflow: hidden;
  box-shadow: 0 0 0 2px var(--plomb), 0 0 0 3px rgb(var(--pierre-rgb) / .6), 0 0 0 7px var(--nuit), 0 0 0 8px rgb(207 167 90 / .3), 0 20px 50px rgb(0 0 0 / .7);
}
.portrait img { width: 100%; height: 100%; object-fit: cover; filter: sepia(.14) saturate(.9); }
.valet .cap {
  position: absolute; left: 50%; top: 0; width: 86%; height: auto; z-index: 1;
  transform: translate(-50%, -52%) rotate(-8deg);
  filter: sepia(.12) drop-shadow(0 6px 8px rgb(0 0 0 / .6));
}
.vl-kicker { font: 700 12px/1 var(--f-ui); letter-spacing: .12em; text-transform: uppercase; color: var(--or); }
.vl-title { margin: 0; font: 600 42px/1 var(--f-display); color: var(--os); letter-spacing: .005em; }
.night[data-kind=out] .vl-title { font-size: 46px; }
.vl-body { font-size: 16px; color: var(--os-2); max-width: 380px; }
.vl-small { font-size: 13.5px; color: var(--cendre); }
.night[data-kind=loading] .vl-body { color: var(--os); }
.night[data-kind=loading] .quip { opacity: 0; animation: night-quip 300ms ease 400ms forwards; }
@keyframes night-quip { to { opacity: 1; } }

@media (prefers-reduced-motion: reduce) {
  @keyframes night-in { from { opacity: 0; } }
}
@media (max-width: 520px) {
  .vl-title, .night[data-kind=out] .vl-title { font-size: 30px; }
}
```

- [ ] **Step 8 : lancer** `npm test`, `npx tsc --noEmit`, puis `npx next build`. Attendu : tout vert.

### Task 8 : assemblage de la scène, page, nettoyage et vérification dans le navigateur

**Files:**
- Create: `services/web/src/components/Stage/Stage.tsx`, `services/web/src/components/Stage/stage.css`
- Modify: `services/web/src/app/globals.css` : imports de la scène, suppression des styles du lecteur provisoire, nouvelle grille
- Modify: `services/web/src/app/page.tsx` : `<Stage/>` remplace `<VideoPlayer/>`
- Modify: `services/web/src/components/Sidebar.tsx`, `services/web/src/components/Queue/QueuePanel.tsx`, `services/web/src/components/History/HistoryPanel.tsx` : le seuil `1100px` devient `900px`
- Modify: `services/web/src/components/Header/Header.tsx`, `services/web/src/components/Header/header.css` : déconnecté, ni bouton de connexion ni recherche dans l'en-tête (écart 7)
- Modify: `services/web/src/lib/playerUtils.ts` : le commentaire de `livePosition` ne cite plus `useProgress`
- Delete: `services/web/src/components/Stage/VideoPlayer.tsx`, `services/web/src/hooks/useProgress.ts` (plus aucun import)
- Test: `services/web/tests/stage-contract.test.mjs`
- Hors dépôt : `S\uimock\mock_api.js` (commande de scène) et `S\etape2-verif\shoot.py` (vérification)

**Interfaces:**
- Consumes : tout ce qui précède (voir « Contrats partagés »).
- Produces :

```ts
// src/components/Stage/Stage.tsx
function Stage(p: { booted: boolean }): JSX.Element;   // <section class="stage-col"><div class="stage" …>
export default memo(Stage);                            // page.tsx se rend à chaque tick : la scène, non
```

- `page.tsx` passe `data-scene={booted && !me ? 'out' : 'in'}` à `<main class="main-layout">`. Déconnecté (session vérifiée), la scène occupe toute la largeur (le panneau est masqué) ; pendant le chargement, la grille garde son panneau.
- `Stage` passe à `Portal` la pochette `art` d'un titre sans vidéo YouTube (`current.thumb`).

- [ ] **Step 1 : écrire le test qui échoue** (`tests/stage-contract.test.mjs`). Il vérifie :
  - les contrats entre tâches (variables CSS, imports) ;
  - la règle de mouvement (transitions et `@keyframes` sur `transform` et `opacity` seulement, mouvement réduit prévu) ;
  - le retrait du lecteur provisoire ;
  - le casting ;
  - ni filtre sur le portail ni mode de mélange dans la scène (écart 6) ;
  - `Stage` mémoïsée ;
  - un seul bouton de connexion, celui de la nuit, et la grille stable au chargement (écart 7).

```js
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
```

- [ ] **Step 2 : lancer** `npm test`. Attendu : FAIL (`stage.css` absent, `VideoPlayer.tsx` encore là, l'en-tête a encore son bouton de connexion).
- [ ] **Step 3 : écrire `src/components/Stage/Stage.tsx`.**

```tsx
'use client';

import { memo, useLayoutEffect, useMemo, useRef } from 'react';
import type { CSSProperties } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { useStageLayout } from '@/hooks/useStageLayout';
import { useStageClock } from '@/hooks/useStageClock';
import { useVideoOffset } from '@/hooks/useVideoOffset';
import { extractVideoId } from '@/lib/format';
import { stageCssVars } from '@/lib/stage/layout';
import { dialGeometry, paneMask } from '@/lib/stage/dial';
import { stageScene } from '@/lib/stage/scene';
import { t } from '@/theme/copy';
import Rose from './Rose';
import Clock, { TimesRow } from './Clock';
import NightState from './NightState';
import Portal from './Portal';
import SyncOffset from './SyncOffset';
import NowPlaying, { NOW_TITLE_ID } from './NowPlaying';
import Transport from './Transport';

/**
 * La scène (spec §4) : la rosace sur le portail de pierre, la vidéo au seuil, l'horloge dans l'anneau,
 * et dessous le titre et le transport. Une seule mesure, R (useStageLayout), pilote tout par variables CSS.
 * `booted` : la session a été vérifiée (page.tsx) ; avant, c'est la nuit « chargement ».
 * Mémoïsée : page.tsx lit tout le store (usePlayer) et se rend à chaque tick du bot ; la scène, elle,
 * ne se rend qu'à ses propres changements (sélecteurs ci-dessous) et une fois par panneau de l'horloge.
 */
function Stage({ booted }: { booted: boolean }) {
  const colRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const belowRef = useRef<HTMLDivElement>(null);
  const me = useStore((s) => s.me);
  const current = useStore((s) => s.player.current);
  const nextUrl = useStore((s) => s.player.queue[0]?.url);
  const paused = useStore((s) => s.player.paused);

  const scene = stageScene({ booted, loggedIn: !!me, hasCurrent: !!current });
  const day = scene === 'day';
  const layout = useStageLayout(colRef, belowRef);
  const dial = useMemo(() => dialGeometry(layout?.c ?? 0.3), [layout?.c]);
  const pane = useStageClock(stageRef, dial.n);
  const [offset, setOffset] = useVideoOffset();
  const videoId = day ? extractVideoId(current?.url) : null;
  const nextId = extractVideoId(nextUrl);
  // Titre sans vidéo YouTube (SoundCloud, que le bot joue aussi) : sa pochette tient lieu d'image.
  const art = day && !videoId ? current?.thumb || current?.thumbnail || null : null;

  // Filet de sécurité (DESIGN §12.4) : si la scène déborde malgré tout, la colonne défile.
  useLayoutEffect(() => {
    const col = colRef.current, stage = stageRef.current;
    if (col && stage) col.dataset.fit = stage.offsetHeight > col.clientHeight + 1 ? 'loose' : 'tight';
  }, [layout, scene]);

  const style = (layout ? { ...stageCssVars(layout), '--a0': String(dial.a0) } : undefined) as CSSProperties | undefined;

  return (
    <section className="stage-col" ref={colRef} aria-label={t('now.kicker')}>
      <div className="stage" ref={stageRef} style={style}
        data-scene={day ? 'day' : 'night'} data-paused={day && paused} data-springs={layout?.springs ?? 'spring'}>
        <Rose videoId={videoId} nextId={nextId} R={layout?.R ?? 0} mask={paneMask(day ? pane : -1)}/>
        <div className="lightpool" aria-hidden="true"/>
        <Clock dial={dial} active={day} labelledBy={NOW_TITLE_ID}/>
        {scene !== 'day' && <NightState kind={scene}/>}
        <Portal videoId={videoId} nextId={nextId} paused={paused} offset={offset} art={art}/>
        <div className="below" ref={belowRef}>
          <TimesRow/>
          <div className="now">
            <NowPlaying/>
            <Transport/>
          </div>
          <div className="below-foot">
            <p className="muted-note">
              <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5.5L6.5 9H3.5v6h3l4.5 3.5z"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5"/></svg>
              {t('now.embedMuted')}
            </p>
            {videoId && <SyncOffset value={offset} onChange={setOffset}/>}
          </div>
        </div>
      </div>
    </section>
  );
}

export default memo(Stage);
```

- [ ] **Step 4 : écrire `src/components/Stage/stage.css`.** Les valeurs par défaut de `.stage` correspondent à R = 340.

```css
/* ═══════════════════════════════════════════════════════════════════════════
   NUIT GOTHIQUE : la scène (colonne, empilement, lumière de la rose) et les classes qu'elle partage.
   Repris de proto-gothique/work/refine/src/styles.css (lignes 199–204, 226–231, 285–296, 300–302,
   556–572). Les variables --R --vw --f --crown --cR --heart --ring-h --clip-day --clip-night --a0 sont
   posées par Stage.tsx (useStageLayout) ; ci-dessous, leurs valeurs avant la première mesure.
   Importé par globals.css avec rose.css, portal.css, now.css, clock.css et night.css.
   ═══════════════════════════════════════════════════════════════════════════ */
@media (max-width: 1180px) { :root { --panel-w: 360px; } }

.stage-col {
  position: relative; min-width: 0; min-height: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  overflow: clip; overflow-clip-margin: 72px;
}
/* filet de sécurité : si la scène ne tient pas malgré la réduction, la colonne défile */
.stage-col[data-fit=loose] { justify-content: flex-start; overflow-x: clip; overflow-y: auto; }
.stage {
  --R: 340px; --vw: 654px; --f: 17px; --crown: 258px; --cR: 102px; --heart: 156px;
  --ring-h: 292.4px; --clip-day: 454.3px; --clip-night: 37.4px; --a0: -71.25;
  position: relative; flex: none; width: calc(var(--vw) + 2 * var(--f)); max-width: 100%; padding-top: var(--crown);
}
/* la lumière de la fenêtre, versée sur le seuil, le titre et le transport.
   Écart voulu : pas de `mix-blend-mode: plus-lighter` (prototype). Un mode de mélange isole le groupe
   qui contient aussi l'iframe YouTube : une passe de rendu de plus à chaque image de la vidéo
   (tech.md §6.2). Sur le mur presque noir, 11 % de lumière en mélange normal donne le même éclairage. */
.lightpool {
  position: absolute; left: 50%; top: calc(var(--crown) - .2 * var(--R)); z-index: 1; pointer-events: none;
  width: calc(3.4 * var(--R)); height: calc(2.6 * var(--R)); margin-left: calc(-1.7 * var(--R));
  transition: opacity 600ms ease;
  background: radial-gradient(50% 50% at 50% 30%, rgb(var(--lumiere-rgb) / .11), rgb(var(--lumiere-rgb) / .045) 55%, transparent 100%);
  -webkit-mask: linear-gradient(transparent 0, #000 22%); mask: linear-gradient(transparent 0, #000 22%);
}
.stage[data-scene=night] .lightpool { opacity: 0; }

/* sous le portail : ce qui joue et le transport, puis la note et la synchro */
.below { position: relative; z-index: 2; display: flow-root; }   /* flow-root : la marge de .now compte dans sa hauteur mesurée */
.stage[data-scene=night] .below { visibility: hidden; }
.now { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 24px; margin-top: 14px; }
.below-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 8px; min-height: 30px; }

/* classes partagées de la scène : réplique de Greg (or, italique), boutons secondaires */
.quip { font: italic 400 15.5px/1.35 var(--f-voice); color: var(--or); }
:root[data-quips=off] .stage .quip { display: none; }
.btn-ghost {
  height: 40px; padding: 0 16px; border-radius: 8px; corner-shape: bevel; box-shadow: inset 0 0 0 1px var(--hair-2);
  font-weight: 700; font-size: 15px; transition: transform var(--dur-press) var(--ease-out);
}
.btn-ghost:active { transform: scale(.97); }
@media (hover: hover) and (pointer: fine) { .btn-ghost:hover { background: var(--voute); } }
.btn-danger {
  height: 38px; padding: 0 14px; border-radius: 8px; corner-shape: bevel; background: var(--gueules); color: #1c0f08;
  font-weight: 800; font-size: 15px; transition: transform var(--dur-press) var(--ease-out);
}
.btn-danger:active { transform: scale(.97); }

@media (prefers-reduced-motion: reduce) { .btn-ghost, .btn-danger { transition: none; } }

/* une colonne : la scène d'abord, centrée, le transport sous le titre */
@media (max-width: 900px) {
  html { scrollbar-gutter: stable; }
  .stage-col { justify-content: flex-start; }
  .now { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .below-foot { flex-wrap: wrap; }
}
```

- [ ] **Step 5 : modifier `src/app/globals.css`.**
  1. Juste après `@import '../components/Header/header.css';`, ajouter :

```css
@import '../components/Stage/stage.css';
@import '../components/Stage/rose.css';
@import '../components/Stage/portal.css';
@import '../components/Stage/now.css';
@import '../components/Stage/clock.css';
@import '../components/Stage/night.css';
```

  2. Dans `@layer components`, supprimer tous les blocs qui ne servaient qu'au lecteur provisoire. Garder `.btn`, `.btn-accent`, `.q-item`, `.q-thumb`, `.tab`, `.status-*` et `.loading-spin`, utilisés par l'étape 3.
     - Du commentaire `/* Video container */` jusqu'à la fin de `.ctrl-active { … }`, c'est-à-dire tout ce qui précède `/* Buttons */` : `.video-frame`, `.artwork-hero`, `.artwork-center`, `.progress-track`, `.progress-fill`, `.ctrl`, `.ctrl-main` et `.ctrl-active`.
     - Le bloc `/* Waveform animation */`, jusqu'à `.wave-bars.paused .wave-bar { animation-play-state: paused; }` inclus.
  3. Remplacer toute la fin du fichier, de `/* ═══ Layout grids ═══ */` jusqu'à la dernière ligne, bloc `@media (max-width: 640px)` des `.ctrl` compris, par :

```css
/* ═══ Layout grids ═══ */
/* La page tient dans l'écran ; en une colonne, elle défile. La lumière de la rose ne crée jamais de défilement horizontal. */
.page-shell { position: relative; z-index: 10; display: flex; flex-direction: column; height: 100dvh; overflow-x: clip; }
/* La scène à gauche, le panneau à droite (--panel-w : tokens.css, 360 px sous 1180 px dans stage.css).
   Déconnecté : la scène seule. Une colonne sous 900 px, comme le prototype et useStageLayout. */
.main-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--panel-w);
  grid-template-rows: minmax(0, 1fr);
  gap: 28px;
  height: 100%;
  min-height: 0;
}
.main-layout[data-scene=out] { grid-template-columns: minmax(0, 1fr); }
.main-layout[data-scene=out] > :not(.stage-col) { display: none; }

@media (max-width: 900px) {
  body { overflow: auto; overflow-x: hidden; }
  .page-shell { height: auto; min-height: 100dvh; }
  .main-layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
    gap: 22px;
    height: auto;
  }
}
```

- [ ] **Step 6 : modifier `src/app/page.tsx`.**
  1. `import VideoPlayer from '@/components/Stage/VideoPlayer';` devient `import Stage from '@/components/Stage/Stage';`.
  2. `const { status, boot, refreshMe } = usePlayer();` devient `const { status, boot, refreshMe, me } = usePlayer();`.
  3. `<div className="relative z-10 flex flex-col h-[100dvh]">` devient `<div className="page-shell">`.
  4. Remplacer le bloc `<main …>` par :

```tsx
        {/* Scène seule une fois la déconnexion constatée ; pendant le chargement, la grille garde son panneau (pas de saut) */}
        <main className="flex-1 min-h-0 main-layout" data-scene={booted && !me ? 'out' : 'in'}>
          {/* Gauche : la scène (rosace, portail, horloge, transport) */}
          <Stage booted={booted}/>

          {/* Droite : file et historique (étape 3) */}
          <Sidebar/>
        </main>
```

  Le reste de `page.tsx` ne change pas : raccourcis, rafraîchissement au focus, barre de statut. La barre de statut sera remplacée par le Héraut à l'étape 3.

- [ ] **Step 7 : seuil d'une colonne à 900 px, en-tête déconnecté, commentaire périmé.**
  1. Remplacer `max-[1100px]:` par `max-[900px]:` :
     - une fois dans `src/components/Sidebar.tsx` (`max-[1100px]:h-auto`) ;
     - une fois dans `src/components/Queue/QueuePanel.tsx` et une fois dans `src/components/History/HistoryPanel.tsx` (`max-[1100px]:max-h-[40vh]`).
  2. `src/components/Header/Header.tsx` (écart 7) :
     - retirer l'import `api` et `loginRef` ;
     - `<header className="top">` devient `<header className="top" data-auth={ready && !me ? 'out' : undefined}>` ;
     - `.top-right` ne rend plus que `{me && (<><GuildPicker/><AccountMenu/></>)}` ;
     - à la déconnexion, `loginRef.current?.focus()` devient `document.querySelector<HTMLElement>('.night[data-kind="out"] .btn-solid')?.focus()` : Stage rend la nuit « déconnecté » dans le même rendu, avant l'effet.

     Résultat attendu :

```tsx
'use client';

import { useEffect, useRef } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { t } from '@/theme/copy';
import GregMedal from './GregMedal';
import Wordmark from './Wordmark';
import SearchBar from './SearchBar';
import GuildPicker from './GuildPicker';
import AccountMenu from './AccountMenu';

/**
 * En-tête « Nuit gothique » : Greg (médaillon et wordmark, sans couronne), la recherche,
 * puis le serveur et le compte du Roi (avatar couronné). Styles : header.css.
 *
 * Déconnecté, la nuit de la scène porte le seul « Se connecter avec Discord » (NightState ; prototype :
 * « the hero carries the only CTA », DESIGN §10) : l'en-tête n'a alors ni bouton de connexion ni recherche.
 * `ready` : la session a été vérifiée (boot) ; avant, rien ne disparaît ni ne clignote.
 */
export default function Header({ ready = true }: { ready?: boolean }) {
  const { me } = usePlayer();
  const wasIn = useRef(false);

  // Déconnexion : le compte disparaît avec le focus, qui retomberait sur <body>. On le passe
  // au « Se connecter » de la scène, sans le voler s'il est déjà ailleurs.
  useEffect(() => {
    if (me) { wasIn.current = true; return; }
    const lost = !document.activeElement || document.activeElement === document.body;
    if (wasIn.current && lost) document.querySelector<HTMLElement>('.night[data-kind="out"] .btn-solid')?.focus();
    wasIn.current = false;
  }, [me]);

  return (
    <header className="top" data-auth={ready && !me ? 'out' : undefined}>
      <div className="brand">
        <GregMedal/>
        <span className="sr">{t('brand.name')}</span>
        <Wordmark/>
      </div>

      <SearchBar/>

      <div className="top-right">
        {me && (
          <>
            <GuildPicker/>
            <AccountMenu/>
          </>
        )}
      </div>
    </header>
  );
}
```

  3. `src/components/Header/header.css`, juste après `.search { position: relative; min-width: 0; }` :

```css
/* déconnecté : rien à chercher, la scène porte le seul bouton de connexion (Header.tsx) */
.top[data-auth=out] .search { visibility: hidden; }
```

  4. `src/lib/playerUtils.ts` (en CRLF) : le commentaire de `livePosition`, `/** Position courante (s) déduite de tickBase — même calcul que useProgress, bornée à la durée. */`, devient `/** Position courante (s) déduite de tickBase, bornée à la durée (horloge de la scène, useStageClock, et synchro vidéo). */`.
- [ ] **Step 8 : retirer le lecteur provisoire, puis tout vérifier.**

```bash
cd services/web
rm src/components/Stage/VideoPlayer.tsx src/hooks/useProgress.ts
grep -rn "Stage/VideoPlayer'\|hooks/useProgress'" src || echo "plus aucun import"   # attendu : « plus aucun import »
npm test                                   # attendu : 140 tests, 0 échec
GREG_TEST_TRANSPILE=1 npm test             # attendu : 140 tests, 0 échec
npx tsc --noEmit                           # attendu : aucune sortie
npx next build                             # attendu : « ✓ Compiled successfully », route / ≈ 146 kB First Load
grep -l transferToImageBitmap .next/static/chunks/*.js   # attendu : un chunk numéroté, le worker de la rosace
```

- [ ] **Step 9 : ajouter une commande de scène à la fausse API** (`S\uimock\mock_api.js`, hors dépôt).
  - Elle ajoute `GET /__mock?me=0|1&scene=playing|paused|empty|soundcloud&latency=ms`, appelé directement sur le port 3999. `soundcloud` joue un titre sans vidéo YouTube (pochette seule).
  - Déconnecté, `/users/me` et `/guilds` répondent 401 `NOT_AUTHENTICATED`, comme la vraie API.
  - Remplacer le fichier par :

```js
// Fausse API Greg (dev UI uniquement) : répond aux routes /api/v1 utilisées par le front.
const http = require('http');
const { URL } = require('url');

const PORT = Number(process.env.PORT || 3999);
const users = {
  '101': { id: '101', display_name: 'Paul', avatar_url: null },
  '102': { id: '102', display_name: 'Gueux Numéro 2', avatar_url: null },
};
const T = (id, title, artist, duration, by) => ({
  title, artist, duration, url: `https://www.youtube.com/watch?v=${id}`,
  thumb: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`, provider: 'youtube', added_by: by,
});
let queue = [
  T('fJ9rUzIMcZQ', 'Bohemian Rhapsody', 'Queen Official', 355, '101'),
  T('hTWKbfoikeg', 'Smells Like Teen Spirit', 'Nirvana', 301, '102'),
  T('1w7OgIMMRc4', "Sweet Child O' Mine", "Guns N' Roses", 356, '101'),
  T('btPJPFnesV4', 'Eye of the Tiger', 'Survivor', 245, '102'),
  T('lDK9QqIzhwk', 'Livin\' On A Prayer', 'Bon Jovi', 251, '101'),
  T('Zi_XLOBDo_Y', 'Billie Jean', 'Michael Jackson', 294, '102'),
];
let current = T('dQw4w9WgXcQ', 'Never Gonna Give You Up', 'Rick Astley', 213, '101');
let startedAt = Date.now() - 42000;
let paused = false;
let pausedAt = 0;
let repeat = false;
// Contrôle de la scène pour les captures (scratch, pas le dépôt) : GET /__mock?me=0|1&scene=playing|empty|paused|soundcloud&latency=ms
let loggedIn = true;
let latency = Number(process.env.LATENCY || 250);
const saved = { current, queue: queue.slice() };

function position() {
  const ref = paused ? pausedAt : Date.now();
  return Math.min(current ? current.duration : 0, Math.floor((ref - startedAt) / 1000));
}
function state() {
  return {
    guild_id: 1, queue, current, paused, is_paused: paused, position: position(),
    duration: current ? current.duration : null,
    progress: { elapsed: position(), duration: current ? current.duration : null },
    thumbnail: current ? current.thumb : null, repeat_all: repeat,
    requested_by_user: current ? users[current.added_by] : null, queue_users: users,
  };
}
function next() {
  current = queue.shift() || null;
  startedAt = Date.now(); paused = false;
}

const history = [
  { title: 'Bohemian Rhapsody', artist: 'Queen', url: 'https://www.youtube.com/watch?v=fJ9rUzIMcZQ', thumb: 'https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg', play_count: 14, duration: 355 },
  { title: 'Never Gonna Give You Up', artist: 'Rick Astley', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', thumb: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg', play_count: 9, duration: 213 },
  { title: 'Billie Jean', artist: 'Michael Jackson', url: 'https://www.youtube.com/watch?v=Zi_XLOBDo_Y', thumb: 'https://i.ytimg.com/vi/Zi_XLOBDo_Y/hqdefault.jpg', play_count: 6, duration: 294 },
];

function send(res, code, body) {
  res.writeHead(code, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}
function readBody(req) {
  return new Promise((r) => { let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => { try { r(JSON.parse(b || '{}')); } catch { r({}); } }); });
}
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname.replace(/^\/api\/v1/, '');
  if (u.pathname === '/__mock') {
    const q = u.searchParams;
    if (q.has('me')) loggedIn = q.get('me') !== '0';
    if (q.has('latency')) latency = Number(q.get('latency')) || 0;
    const sc = q.get('scene');
    if (sc === 'empty') { current = null; queue = []; paused = false; }
    if (sc === 'playing' || sc === 'paused') {
      current = saved.current; queue = saved.queue.slice(); startedAt = Date.now() - 42000;
      paused = sc === 'paused'; pausedAt = Date.now();
    }
    if (sc === 'soundcloud') {   // un titre sans vidéo YouTube (le bot joue aussi SoundCloud)
      current = { ...T('fJ9rUzIMcZQ', 'Ghost Town', 'Artiste SoundCloud', 240, '102'), url: 'https://soundcloud.com/artiste/ghost-town', provider: 'soundcloud' };
      queue = saved.queue.slice(); startedAt = Date.now() - 42000; paused = false;
    }
    return send(res, 200, { ok: true, loggedIn, latency, scene: current ? (paused ? 'paused' : 'playing') : 'empty' });
  }
  await delay(latency);
  if (!loggedIn && req.method === 'GET' && (p === '/users/me' || p === '/auth/me' || p === '/guilds')) return send(res, 401, { ok: false, error: 'NOT_AUTHENTICATED' });
  if (req.method === 'GET' && (p === '/users/me' || p === '/auth/me')) return send(res, 200, { ok: true, user: { id: '101', username: 'paul', global_name: 'Paul', avatar: null } });
  if (req.method === 'GET' && p === '/guilds') return send(res, 200, { ok: true, guilds: [{ id: '1', name: 'La Taverne', icon: null, bot_present: true }, { id: '2', name: 'Autre serveur', icon: null, bot_present: false }] });
  if (req.method === 'GET' && (p === '/playlist' || p === '/player/state')) return send(res, 200, { ok: true, state: state() });
  if (req.method === 'GET' && p.startsWith('/history')) return send(res, 200, { ok: true, items: history, mode: u.searchParams.get('mode') || 'top' });
  if (req.method === 'GET' && p.startsWith('/search/autocomplete')) {
    const q = u.searchParams.get('q') || '';
    return send(res, 200, { ok: true, results: [1, 2, 3].map((i) => ({ title: `${q} — résultat ${i}`, url: `https://www.youtube.com/watch?v=dQw4w9WgXcQ`, artist: 'Chaîne', duration: 200 + i * 10, thumb: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg' })) });
  }
  if (req.method === 'POST') {
    const body = await readBody(req);
    if (p === '/queue/add' || p === '/player/enqueue') {
      const isList = /list=/.test(body.query || '');
      const n = isList ? 5 : 1;
      for (let i = 0; i < n; i++) queue.push(T('dQw4w9WgXcQ', isList ? `Titre de playlist ${i + 1}` : (body.title || body.query), 'Artiste', 200, '101'));
      return send(res, 200, { ok: true, added: n, requested: n, truncated: null, playlist: isList, title: isList ? null : (body.title || body.query) });
    }
    if (p === '/queue/skip' || p === '/player/skip') { next(); return send(res, 200, { ok: true }); }
    if (p === '/queue/stop' || p === '/player/stop') { queue = []; current = null; return send(res, 200, { ok: true }); }
    if (p === '/playlist/toggle_pause' || p === '/player/pause') {
      if (paused) { startedAt += Date.now() - pausedAt; paused = false; } else { paused = true; pausedAt = Date.now(); }
      return send(res, 200, { ok: true });
    }
    if (p === '/playlist/repeat' || p === '/player/repeat') { repeat = !repeat; return send(res, 200, { ok: true, repeat_all: repeat }); }
    if (p === '/playlist/restart') { startedAt = Date.now(); return send(res, 200, { ok: true }); }
    if (p === '/queue/remove') { queue.splice(Number(body.index) || 0, 1); return send(res, 200, { ok: true }); }
    if (p === '/player/move') { const [it] = queue.splice(body.src, 1); queue.splice(body.dst, 0, it); return send(res, 200, { ok: true }); }
    if (p === '/playlist/play_at') { const [it] = queue.splice(Number(body.index) || 0, 1); if (current) queue.unshift(); current = it; startedAt = Date.now(); return send(res, 200, { ok: true }); }
    if (p === '/voice/join') return send(res, 200, { ok: true });
    if (p === '/auth/logout') return send(res, 200, { ok: true });
  }
  send(res, 404, { ok: false, error: 'not_found' });
}).listen(PORT, () => console.log(`mock API on ${PORT}`));
```

- [ ] **Step 10 : vérifier dans le vrai navigateur.** Écrire `S\etape2-verif\shoot.py` :

```python
"""Captures et contrôles de la scène (étape 2). python shoot.py <base_url> <outdir>"""
import json, sys, urllib.request, pathlib
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:3100'
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else 'shots'); OUT.mkdir(exist_ok=True)
MOCK = 'http://localhost:3999/__mock'
def mock(q): return json.loads(urllib.request.urlopen(f'{MOCK}?{q}').read())
import re
# Bruit attendu, hors de l'application : la fausse API n'a pas de Socket.IO ; l'iframe YouTube journalise ses propres
# erreurs (publicité, CORS) ; maxresdefault manque pour certaines vidéos (le poster retombe sur hqdefault, tech.md §5.3).
IGNORE_TEXT = ('socket.io', 'WebSocket')
IGNORE_URL = re.compile(r'^https://(www\.youtube\.com/|googleads\.g\.doubleclick\.net/|i\.ytimg\.com/vi/[^/]+/maxresdefault\.jpg)')
# Déconnecté : /users/me répond 401 NOT_AUTHENTICATED (contrat de l'API, déjà le cas avant l'étape 2).
LOGGED_OUT = re.compile(r'/api/v1/users/me$')
def noise(m):
    url = m.location.get('url', '') or ''
    return any(k in m.text for k in IGNORE_TEXT) or bool(IGNORE_URL.match(url)) or ('401' in m.text and bool(LOGGED_OUT.search(url)))
results, errors = [], []
def check(name, ok, detail=''):
    results.append({'check': name, 'ok': bool(ok), 'detail': detail}); print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail else ''))

PROBE = """() => {
  const q = (s) => document.querySelector(s), r = (s) => q(s)?.getBoundingClientRect();
  const st = q('.stage'), cs = st && getComputedStyle(st);
  const play = r('.tbtn.main');
  return {
    scene: st?.dataset.scene, paused: st?.dataset.paused, springs: st?.dataset.springs,
    R: cs?.getPropertyValue('--R'), vw: cs?.getPropertyValue('--vw'), crown: cs?.getPropertyValue('--crown'),
    playBottom: play ? Math.round(play.bottom) : null, innerH: innerHeight, innerW: innerWidth,
    scrollW: document.documentElement.scrollWidth, fit: q('.stage-col')?.dataset.fit,
    win: document.querySelectorAll('.rosace canvas.win').length, ring: document.querySelectorAll('.rosace canvas.ring').length,
    moon: document.querySelectorAll('.rosace .slot[data-kind=moon]').length,
    lumiere: getComputedStyle(document.documentElement).getPropertyValue('--lumiere-rgb').trim(),
    p0: getComputedStyle(q('.rosace') || document.body).getPropertyValue('--p0'),
    cur: q('.spring.l')?.textContent, tot: q('.spring.r')?.textContent,
    aria: q('.dial')?.getAttribute('aria-valuetext'), title: q('#now-title')?.textContent,
    covered: q('.posters')?.dataset.covered, iframe: !!q('.video .yt iframe'),
    night: q('.night')?.dataset.kind || null, doc: document.title,
    layout: q('.main-layout')?.dataset.scene, logins: document.querySelectorAll('a[href$="/auth/login"]').length,
    search: q('.top .search') ? getComputedStyle(q('.top .search')).visibility : null,
    art: q('.posters .poster.art')?.getAttribute('src') || null, sync: !!q('.sync-btn'),
  };
}"""

with sync_playwright() as p:
    b = p.chromium.launch(channel='chrome', args=['--autoplay-policy=no-user-gesture-required'])
    def page(w, h, reduced=False):
        ctx = b.new_context(viewport={'width': w, 'height': h}, reduced_motion='reduce' if reduced else 'no-preference')
        pg = ctx.new_page()
        pg.on('console', lambda m: errors.append(f"{w}x{h} [{m.type}] {m.text} @ {m.location.get('url', '')}") if m.type == 'error' and not noise(m) else None)
        pg.on('pageerror', lambda e: errors.append(f'{w}x{h} [pageerror] {e}'))
        return pg
    def shoot(pg, name): pg.screenshot(path=str(OUT / f'{name}.png'))

    mock('me=1&scene=playing&latency=250')
    for (w, h) in [(1440, 900), (1280, 720), (390, 844)]:
        pg = page(w, h); pg.goto(BASE); pg.wait_for_timeout(6000)
        d = pg.evaluate(PROBE); print(json.dumps(d))
        shoot(pg, f'playing-{w}x{h}')
        check(f'{w}x{h} jour, rosace peinte', d['scene'] == 'day' and d['win'] >= 1 and d['ring'] >= 1, json.dumps({k: d[k] for k in ('win', 'ring', 'moon')}))
        check(f'{w}x{h} --lumiere tirée de la miniature', d['lumiere'] not in ('', '180 196 226'), d['lumiere'])
        check(f'{w}x{h} horloge : temps et aria', d['aria'] and d['aria'].startswith('Progression'), f"{d['cur']} / {d['tot']} / {d['aria']}")
        if w > 900:
            check(f'{w}x{h} transport au-dessus du pli', d['playBottom'] is not None and d['playBottom'] <= d['innerH'], f"{d['playBottom']} <= {d['innerH']}, fit={d['fit']}")
        else:
            check(f'{w}x{h} pas de défilement horizontal', d['scrollW'] <= d['innerW'], f"{d['scrollW']} <= {d['innerW']}")
        check(f'{w}x{h} lecteur YouTube persistant sous le poster', d['iframe'] and d['covered'] in ('false', 'true'), d['covered'])
        pg.context.close()

    # survol de l'anneau : info-bulle de temps ; clic : rien (lecture seule)
    pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(4000)
    box = pg.evaluate("() => { const r = document.querySelector('.dial').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height * .0637 }; }")
    pg.mouse.move(box['x'], box['y']); pg.wait_for_timeout(300)
    tip = pg.evaluate("() => ({ on: document.querySelector('.dial-tip').dataset.on, text: document.querySelector('.dial-tip').textContent })")
    check('survol de l’anneau : temps affiché', tip['on'] == 'true' and ':' in (tip['text'] or ''), json.dumps(tip))
    shoot(pg, 'hover-1440x900'); pg.context.close()

    # changement de titre : la rosace se rallume aux couleurs du suivant, l'horloge repart
    pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(5000)
    before = pg.evaluate(PROBE)
    pg.click('.transport .tbtn[aria-label="Passer au titre suivant"]'); pg.wait_for_timeout(4500)
    after = pg.evaluate(PROBE); shoot(pg, 'skip-1440x900')
    check('suivant : nouveau titre, nouvelle lumière, horloge remise à zéro',
          after['title'] != before['title'] and after['lumiere'] != before['lumiere'] and after['cur'] in ('0:00', '0:01', '0:02', '0:03', '0:04', '0:05'),
          f"{before['title']} → {after['title']} ; {before['lumiere']} → {after['lumiere']} ; {after['cur']}")
    # synchro vidéo : le réglage s'ouvre, bouge, et reste en mémoire
    pg.click('.sync-btn'); pg.wait_for_timeout(300)
    pg.focus('.sync-pop input[type=range]'); pg.keyboard.press('ArrowRight'); pg.keyboard.press('ArrowRight'); pg.wait_for_timeout(200)
    shoot(pg, 'sync-1440x900')
    stored = pg.evaluate("() => localStorage.getItem('greg.webplayer.video_offset')")
    check('synchro vidéo : décalage réglé et gardé', stored == '1', str(stored))
    pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
    check('synchro vidéo : Échap ferme et rend le focus', pg.evaluate("() => document.activeElement?.classList.contains('sync-btn')"))
    pg.evaluate("() => localStorage.removeItem('greg.webplayer.video_offset')")
    # reprendre au début : le son recule sur la même vidéo, rechargée sous le poster (tech.md §5.4)
    pg.wait_for_timeout(2500)
    pg.click('.transport .tbtn[aria-label="Recommencer le titre"]'); pg.wait_for_timeout(1200)
    d = pg.evaluate(PROBE)
    check('reprendre au début : vidéo rechargée sous le poster', d['covered'] == 'true' and d['cur'] in ('0:00', '0:01', '0:02'), f"{d['covered']} {d['cur']}")
    pg.context.close()
    mock('scene=playing')

    # titre sans vidéo YouTube (SoundCloud) : sa pochette tient lieu d'image, pas de synchro vidéo
    mock('scene=soundcloud'); pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(4000)
    d = pg.evaluate(PROBE); shoot(pg, 'soundcloud-1440x900')
    check('SoundCloud : pochette dans le portail, sans synchro vidéo', d['scene'] == 'day' and bool(d['art']) and d['covered'] == 'true' and not d['sync'], json.dumps({k: d[k] for k in ('scene', 'art', 'covered', 'sync')}))
    pg.context.close()
    mock('scene=playing')

    # pause : voile, badge, rosace atténuée, poster
    mock('scene=paused'); pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(5000)
    d = pg.evaluate(PROBE); shoot(pg, 'paused-1440x900')
    check('pause : data-paused et poster', d['paused'] == 'true' and d['covered'] == 'true', json.dumps({k: d[k] for k in ('paused', 'covered', 'doc')}))
    pg.context.close()

    # nuit : rien en lecture
    mock('scene=empty'); pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(5000)
    d = pg.evaluate(PROBE); shoot(pg, 'empty-1440x900')
    check('rien en lecture : nuit, lune, couronne', d['scene'] == 'night' and d['night'] == 'empty' and d['moon'] >= 1 and d['lumiere'] == '180 196 226', json.dumps(d))
    # arrêt depuis le jour : confirmation (focus sur le choix sûr) puis nuit
    mock('scene=playing'); pg.reload(); pg.wait_for_timeout(5000)
    pg.click('.stop-wrap .tbtn'); pg.wait_for_timeout(400); shoot(pg, 'stop-confirm-1440x900')
    focus = pg.evaluate("() => document.activeElement?.textContent")
    check('arrêt : le choix sûr a le focus', focus == 'Garder la musique', focus)
    pg.click('.confirm .btn-danger'); pg.wait_for_timeout(2500); d = pg.evaluate(PROBE); shoot(pg, 'stopped-1440x900')
    check('arrêt : la nuit tombe', d['scene'] == 'night' and d['night'] == 'empty', d['night'])
    pg.context.close()

    # déconnexion depuis le menu du Roi : le focus passe au seul « Se connecter », celui de la nuit
    mock('scene=playing'); pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(4000)
    pg.click('.top-right .chip[aria-haspopup=dialog]'); pg.wait_for_timeout(250)
    pg.click('.top-right .pop[role=dialog] button.pop-item:has-text("Se déconnecter")'); pg.wait_for_timeout(1200)
    d = pg.evaluate(PROBE)
    cta = pg.evaluate("() => !!document.activeElement?.matches('.night[data-kind=out] a.btn-solid')")
    check('déconnexion : le focus passe au bouton de la nuit', d['night'] == 'out' and cta, json.dumps({k: d[k] for k in ('night', 'logins')}))
    pg.context.close()

    # déconnecté : portrait de Greg en bonnet, sans couronne ; la nuit porte le seul bouton de connexion
    mock('me=0'); pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(4000)
    d = pg.evaluate(PROBE); shoot(pg, 'out-1440x900')
    cap = pg.evaluate("() => !!document.querySelector('.night .valet .cap') && !document.querySelector('.night .valet [src*=crown]')")
    check('déconnecté : portrait de Greg en bonnet, sans couronne, un seul « Se connecter », pas de recherche',
          d['night'] == 'out' and cap and d['logins'] == 1 and d['search'] == 'hidden', json.dumps({k: d[k] for k in ('night', 'logins', 'search')}))
    pg.context.close()
    pg = page(390, 844); pg.goto(BASE); pg.wait_for_timeout(4000); shoot(pg, 'out-390x844'); pg.context.close()

    # chargement : couronne qui tourne (latence 4 s)
    mock('me=1&scene=playing&latency=4000'); pg = page(1440, 900); pg.goto(BASE); pg.wait_for_timeout(1500)
    d = pg.evaluate(PROBE); shoot(pg, 'loading-1440x900')
    check('chargement : couronne qui tourne, la grille garde son panneau', d['night'] == 'loading' and d['layout'] == 'in', f"{d['night']} {d['layout']}")
    pg.context.close()
    mock('latency=250')

    # mouvement réduit : aucune animation infinie (la couronne est immobile)
    mock('scene=empty'); pg = page(1440, 900, reduced=True); pg.goto(BASE); pg.wait_for_timeout(3000)
    inf = pg.evaluate("() => document.getAnimations().filter(a => a.playState === 'running' && a.effect?.getComputedTiming().iterations === Infinity && a.effect?.target?.closest?.('.stage-col')).map(a => a.animationName || String(a.id))")
    check('mouvement réduit : aucune animation infinie', len(inf) == 0, json.dumps(inf))
    pg.context.close()
    mock('scene=playing')
    b.close()

check('console sans erreur', len(errors) == 0, ' | '.join(errors[:6]))
(OUT / 'qa.json').write_text(json.dumps({'checks': results, 'errors': errors}, indent=1, ensure_ascii=False), encoding='utf8')
```

Lancer les serveurs, la vérification, puis les arrêter (PowerShell, depuis la racine du dépôt) :

```powershell
$S = "C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad"
$W = (Resolve-Path services\web).Path
Start-Process node -ArgumentList "$S\uimock\mock_api.js" -WindowStyle Hidden
Push-Location $W; npx next build; Pop-Location
Start-Process node -ArgumentList "node_modules/next/dist/bin/next","start","-p","3100" -WorkingDirectory $W -WindowStyle Hidden
for ($i = 0; $i -lt 25; $i++) { try { if ((Invoke-WebRequest -UseBasicParsing http://localhost:3100/ -TimeoutSec 3).StatusCode -eq 200) { break } } catch { Start-Sleep -Milliseconds 700 } }
$env:PYTHONIOENCODING = 'utf-8'; & "$S\venv\Scripts\python.exe" "$S\etape2-verif\shoot.py" http://localhost:3100 "$S\etape2-verif\shots"
foreach ($port in 3100, 3999) { $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; if ($c) { Stop-Process -Id $c.OwningProcess -Force -Confirm:$false } }
```

  Attendu : 30 lignes `PASS`, aucune `FAIL`. Le détail est dans `S\etape2-verif\shots\qa.json`.

  Relire ensuite les captures de `S\etape2-verif\shots` :
  - `playing-1440x900.png`, `playing-1280x720.png`, `playing-390x844.png` :
    - la couronne de la rose est vitrée aux couleurs de la miniature, et les panneaux joués de l'anneau sont allumés ;
    - le temps est aux naissances de l'arc, ou en ligne sous le portail sur téléphone ;
    - le portail est en pierre ;
    - le titre est en Grenze, avec le sceau du Roi et « Demandé par vous » ;
    - la rondelle de lecture est en `--lumiere` ;
    - le portail a son ombre portée (une `box-shadow`, écart 6).
  - `paused-1440x900.png` : rose atténuée, voile, badge « En pause », poster.
  - `skip-1440x900.png` : la rose se rallume en grisaille pour Bohemian Rhapsody, et l'horloge repart.
  - `empty-1440x900.png` : rose entière au clair de lune, la couronne du Roi dans l'oculus, « Rien en lecture », réplique en or.
  - `out-1440x900.png` et `out-390x844.png` : le portrait de Greg avec le bonnet à grelots, **sans couronne ni sceau** ; l'en-tête n'a ni bouton de connexion ni recherche, le seul « Se connecter avec Discord » est dans la nuit.
  - `loading-1440x900.png` : la couronne qui tourne ; le panneau de droite est déjà en place.
  - `soundcloud-1440x900.png` : la pochette dans le portail, sans « Synchro vidéo ».
  - `stop-confirm-1440x900.png`, `sync-1440x900.png` : plaques plombées ; le popover s'ouvre au-dessus de son bouton.
  - Casting : couronne sur l'avatar du Roi dans l'en-tête ; aucune couronne, aucun sceau ni aucun « Rex » attribué à Greg.

- [ ] **Step 11 (orchestrateur) : un commit et un push pour l'étape.**
  - Ne pas ajouter `services/web/tsconfig.json` ni `services/web/next-env.d.ts`. Les suppressions sont prises par `git add -A` sur les chemins listés.

```bash
git add -A services/web/src services/web/tests services/web/public/gothique/jester-cap-256.webp services/web/public/gothique/jester-cap-512.webp services/web/public/licenses/LICENSES.md docs/superpowers/plans/2026-09-26-web-nuit-gothique-etape-2.md
git status --short          # vérifier : ni tsconfig.json ni next-env.d.ts dans l'index
git commit -m "feat(web): scène Nuit gothique (rosace en worker, portail, horloge, nuit, transport)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

## Couverture de la spec (§4, §6.2)

| Exigence | Tâche |
|---|---|
| R pilote la mise en page ; vidéo = R / 0,52 ; couronne de 70 % à 36 % de R ; `useStageLayout` (ResizeObserver) ; 8 tailles d'écran testées | 3 (`layout.ts`, `stageLayout.test.mjs`, `useStageLayout.ts`), 8 (variables sur `.stage`) |
| Worker de rosace : OffscreenCanvas, ImageBitmap, `bitmaprenderer`, fenêtre du prochain titre préparée pendant les temps morts | 1 (géométrie), 2 (`paint.ts`, `rose.worker.ts`, `client.ts` : `prepare`, `premount`) |
| Palette : miniature `i.ytimg.com`, histogramme pondéré par la saturation, grisaille sans teinte, `--lumiere` | 1 (`paletteFromPixels`, contraste ≥ 6:1 testé), 2 (`extractPalette` dans le worker, `setLumiere`) |
| Horloge de 48 panneaux, lecture seule, masque changé une fois par panneau, temps au survol | 3 (`dial.ts`), 7 (`useStageClock`, `Clock`), 2 (masques de `rose.css`) |
| Nuit : rose au clair de lune ; oculus avec couronne qui attend le Roi, couronne qui tourne, portrait de Greg en bonnet | 4 (`stageScene`), 7 (`NightState`, `night.css`, bonnet), 2 (fenêtre de lune), 8 (un seul bouton de connexion, grille stable au chargement) |
| YouTube : poster au-dessus du lecteur persistant jusqu'à PLAYING + 3,5 s et pendant la pause (tech.md §5.3) | 4 (`cover.ts`), 5 (`useYouTubePlayer`, `Portal`) |
| Titre en Grenze et demandeur ; transport en rondelle de verre | 4 (`titles.ts`, `scene.ts`), 6 (`NowPlaying`, `Transport`, `now.css`) |
| Portail de pierre en 9 tranches (Blender) | 5 (`portal.css`, `stone-frame-640.webp`) |
| Synchro vidéo (décalage) toujours fonctionnelle | 5 (`useVideoOffset`, `SyncOffset`, saut immédiat dans `Portal`) ; 4 et 5 (`rewound` : vidéo rechargée quand le son recule) |
| Remplacer le `VideoPlayer` provisoire | 8 ; 5 (pochette des titres SoundCloud, comme l'ancien lecteur) |
| Fluidité (spec §2) : pas de rendu React par tick, rien de filtré ni de mélangé autour de la vidéo | 8 (`memo(Stage)`, `stage.css`), 5 (`portal.css`), vérifiés par `stage-contract.test.mjs` |
| Repli sans OffscreenCanvas : rosace statique ; pierre et rosace chargées après le premier affichage (§7) | 2 (`roseSupported`, repli dans `Rose.tsx`, worker démarré dans un effet) |
| Vérifications : `npm test`, `tsc`, `next build`, captures 1440×900, 1280×720 et 390×844, console sans erreur | 8 (étapes 8 à 10 : 140 tests, 30 contrôles dans Chrome) |
