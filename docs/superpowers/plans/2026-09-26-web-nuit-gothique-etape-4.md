# Nuit gothique, étape 4 : chorégraphies et finitions, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** livrer les chorégraphies et les finitions de la spec §5 et §6.4 (DESIGN §5, §7, §12.6, §12.7) :
- le Couronnement, le Sceau, la Révérence, et l'arrêt vers la nuit ;
- le clavier complet et son interrupteur (WCAG 2.1.4), l'accessibilité ;
- le mouvement réduit suivi en direct, une colonne ≤ 900 px, la pierre et les sceaux chargés en différé ;
- les trois changements validés par Paul ;
- aucune tâche longue > 50 ms à 1× CPU pendant un Couronnement.

**Architecture:** Next.js 14, React 18, aucune nouvelle dépendance.
- **Calculs purs** (`node:test`, `tests/_loadTs.mjs`) : `lib/stage/coronation.ts` (courbe, vol, modes, plans, ordres du Roi), `lib/queue/seal.ts` (ajout attendu), `lib/keys.ts` (raccourcis, listes), `watchReducedMotion`, `reverseStagger`.
- **Le chef de cérémonie** (`components/Stage/coronation.ts`), abonné au store hors de React : au changement de `player.current.key`, il reprend l'ordre du Roi, choisit le mode et mesure la source **avant** le rendu, publie la cérémonie (`useCeremony`), puis vole à l'image suivante (DESIGN §8). `NowPlaying`, `Portal` et `Rose` suivent son plan.
- **Ordres et sceaux.** Un clic ou une touche note son intention (`kingOrders.mark`) avant l'action optimiste ; un ajout note son sceau attendu (`sealBook.expect`), repris à l'entrée de la ligne (`useFlip` → `onEnter`).
- **Clavier.** Un gestionnaire de page (`shortcutFor`) ; `useRoving` pour les listes ; `speak()` pour les régions live du Héraut.

**Tech Stack:** Next.js 14.2, React 18, TypeScript 5, zustand 4, `node:test`, WAAPI, API IFrame YouTube, Playwright (Chrome), CDP.

**Spec:** `docs/superpowers/specs/2026-09-26-web-nuit-gothique-design.md` (§5, §6.4, §7, §8). Plans de référence : `docs/superpowers/plans/2026-09-26-web-nuit-gothique-etape-1.md` à `-etape-3.md`.

## Global Constraints

- **Ressources.**
  - `S` = `C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad`, `P` = `S\design`.
  - Valeurs qui font foi : `P\proto-gothique\DESIGN.md` (§5, §7, §8, §12.6, §12.7) et `work\refine\src\{styles.css,body.html,app.js}`. Dans `app.js` : Couronnement lignes 543–621, reflet 502–514, Sceau 769–772 et 1154–1206, arrêt 1325–1348, clavier 1389–1405.
  - Mouvement : `P\research\motion.md` §6.5, §6.10, §6.11, §8. YouTube : `P\research\tech.md` §5.3. Mesure : `P\research\motion-lab\pacing.py`.
  - Textes : `services/web/src/theme/copy.v2.json` (`t`, `quip`) et `theme/copy.extra.ts` (`tx`). Guide : `P\research\persona-v2.md`.
- **Casting** (spec §1, fait foi). Le Roi, c'est l'utilisateur connecté ; Greg est son valet : ni couronne, ni sceau royal, ni « Rex » pour lui.
  - Le Sceau est `kingSealSrc(kingName(me))`, sur un ajout du Roi seulement (`requesterOf(...).kind === 'mine'`) ; le fantôme du vol porte l'image du titre.
  - Aucun « crown » dans `components/{Queue,History,Herald}` : `tests/{queue-panel,queue-contract}` le refusent (d'où `kingOrders`, « ordres du Roi »).
- **Mouvement.** `transform` et `opacity` seulement : ni `filter` (pas de flou, écart 1), ni `clip-path`, ni `transition: all`. Survols sous `@media (hover:hover) and (pointer:fine)`. Mouvement réduit suivi en direct : fondus seuls.
- **Textes.** Français ; Greg vouvoie le Roi ; rien d'humoristique dans un `aria-label` ou une annonce. Le deck ne s'édite pas, sauf `auth.kicker` (demande de Paul).
  - Les manques vont dans `copy.extra.ts` : U+00A0 avant « : », U+202F avant ; ! ?, apostrophe courbe ; aucune clé du deck doublée.
- **Compatibilité.** Les 258 tests restent verts (`cd services/web && npm test`, et `GREG_TEST_TRANSPILE=1 npm test` pour le Node 20 de l'image Docker) ; **284** après la vague A, **300** à la fin. `npx tsc --noEmit` et `npx next build` passent.
  - Aucune dépendance npm nouvelle (`node_modules` est une jonction, jamais d'`npm install`) ; rien dans `services/bot`, `services/api` ni `packages/shared`.
- **Modules purs.** Aucun import runtime (`import type` seulement) ; TypeScript effaçable (ni `enum`, ni `namespace`).
- **Fichiers.** Garder les fins de ligne de chaque fichier (`types.ts` et `playerUtils.ts` sont en CRLF et ne changent pas).
- **Commandes.** Git Bash, depuis la racine du dépôt. `S=/c/Users/Paul/AppData/Local/Temp/claude/C--Users-Paul-Documents-Codage-GregLeConsanguin/0d3cb735-ae70-4238-a3f4-f9ff22e57d5f/scratchpad`.
- **Parallélisme.** Une vague ne partage aucun fichier ; `npm test` peut tourner en parallèle. `tsc` et `next build` : l'orchestrateur, après chaque vague ; jamais deux `next build` à la fois dans `services/web` (sinon une copie dans `S` avec une jonction `node_modules`).
- **Git.** Les agents ne font ni commit, ni push, ni stash, ni reset, ni checkout ; l'orchestrateur committe (tâche 7). Jamais `services/web/tsconfig.json` ni `next-env.d.ts`.
- **Serveurs.** Fausse API `node S\uimock\mock_api.js` (port 3999, erreurs WebSocket attendues ; `/__mock?scene=playing|empty`, `?me=0|1`). Web : `npx next build && npx next start -p 3100`, jamais `next dev`. Playwright du venv `S\venv`, `channel="chrome"` ; fichiers temporaires sous `S\etape4`. Toujours arrêter les serveurs lancés.

## Décisions et écarts assumés

1. **Pas de flou** (légendes, icône) : translation et fondu seuls.
2. **La nuit n'anime pas la coupe** : la lune est une fenêtre à part (étape 2), elle entre en 240 ms ; le texte de nuit monte à +320 ms (déjà dans `night.css`).
3. **Mode rapide** : 2e changement en 1,5 s, ordre au clavier, ou changement sans ordre du Roi (fin de titre, autre membre, refus). Le vol est pour la souris. Le premier titre après la nuit passe par le repli.
4. **Le Héraut attend l'atterrissage** pour « Lecture immédiate » (500 ms). Les autres changements sont annoncés par `speak`.
5. **N, P et R disparaissent** (une lettre tapée ne saute jamais un titre). Les bulles du transport et la liste des raccourcis passent aux compléments.
6. **L'interrupteur coupe** Espace, Maj+→, Maj+←, /, ? et la saisie directe. Restent : les touches des listes (sous le focus), Échap et Ctrl+Z.
7. **YouTube** : on n'efface jamais la marque. On lève le poster après le repli de l'habillage (les 3,5 s de la spec §4 deviennent la valeur mesurée, 5 s au plus), et on coupe les sous-titres de l'iframe muette.
8. **Pas de « drain » de 240 ms** (DESIGN §5) : l'horloge est un masque conique posé une fois par panneau ; elle repart de zéro sous le fondu du nouveau verre.
9. **Boutons des lignes hors de la tabulation** (`tabIndex={-1}`, comme le prototype) : Entrée, Suppr et Alt+Début les remplacent.

## Carte des fichiers et vagues

Chemins relatifs à `services/web/`. Un seul propriétaire par fichier.

| Tâche | Crée | Modifie | Dépend de |
|---|---|---|---|
| 1. Textes, voix | `tests/a11y-contract.test.mjs` | `src/theme/{copy.v2.json,copy.ts,copy.extra.ts}`, `src/components/Herald/{store.ts,Herald.tsx}`, `tests/{copy,copy-extra}.test.mjs` | — |
| 2. Logique pure | `src/lib/stage/coronation.ts`, `src/lib/queue/seal.ts`, `src/lib/keys.ts`, `tests/{coronation,seal,keys}.test.mjs` | `src/lib/{motion,flip}.ts`, `tests/motion.test.mjs` | — |
| 6. YouTube | — (sonde `S\etape4\{yt-probe.html,yt_probe.py}` déjà écrite) | `src/lib/stage/cover.ts`, `src/hooks/useYouTubePlayer.ts`, `tests/cover.test.mjs` | — |
| 3. La scène | `src/components/Stage/{coronation.ts,Swap.tsx,glint.ts}`, `tests/choreo-stage.test.mjs` | `src/components/Stage/{Stage,NowPlaying,Portal,Rose,Transport}.tsx`, `src/components/Stage/{stage,now,portal,rose}.css`, `src/lib/rose/client.ts`, `src/hooks/usePlayer.ts`, `tests/rose-client.test.mjs` | 1, 2 |
| 4. La file | `src/components/Queue/seal.ts`, `src/hooks/useRoving.ts`, `tests/choreo-queue.test.mjs` | `src/hooks/useFlip.ts`, `src/components/Queue/{QueuePanel,QueueRow}.tsx`, `queue.css`, `src/components/History/{HistoryPanel,HistoryRow,Suggestions}.tsx`, `useRequeue.ts` | 1, 2 |
| 5. Clavier global | `tests/keyboard-contract.test.mjs` | `src/app/{page.tsx,globals.css}`, `src/components/Header/{AccountMenu,SearchBar}.tsx`, `header.css` | 1, 2 |
| 7. Navigateur, mesure, commit | — (`S\etape4\{verif.py,pacing_app.py}` déjà écrits) | corrections éventuelles | 1 à 6 |

Vagues :
- **A** : tâches 1, 2 et 6 (284 tests) ;
- **B** : tâches 3, 4 et 5 (300) ;
- **C** : tâche 7.

## Contrats partagés

- **Ordres du Roi** (`kingOrders.mark(target, via, now)`, avant l'action) :
  - Suivant du transport (tâche 3) : `NEXT`, `e.detail === 0 ? 'key' : 'pointer'` ;
  - Maj+→ (tâche 5) : `NEXT`, `'key'` ;
  - file (tâche 4) : double-clic et ▶, `key`, `'pointer'` ; Entrée, `key`, `'key'`.
- **Sceau attendu** : la recherche (tâche 5) et l'historique (tâche 4) appellent `sealBook.expect(...)` avant `enqueue`, et `sealBook.clear()` sur échec ou si `enqueue` rend `false`. `QueuePanel` (tâche 4) appelle `sealBook.take(...)`.
- **Voix** : `speak(text, { assertive? })` depuis `@/components/Herald/store` (tâche 1).
- **DOM partagé** : `#pane-queue[aria-hidden]` ; lignes `.qcontent > .qlist > .row[data-key]`, pochette `.thumb > .im > img`, sceau `.thumb .seal img` ; `.stage .video .poster` ; `#tab-queue .count` ; `.top .field input` ; `.pop[data-open="true"]`, `body.is-dragging` ; `<html data-keys>` et `<html data-motion>` (tâche 5) ;
  - `.ghost` et `decodedPosters` (Portal.tsx, tâche 3), `.seal-ghost` et `li.row[data-sealed]` (tâche 4).
- **Clavier** : un composant qui traite une touche l'annule (`preventDefault`) ; le gestionnaire de page ignore alors l'événement.
- **Réutilisé tel quel** : étapes 1 à 3 (`useStore`, `playerActions`, `say`, `useFlip`, `lib/motion`, `lib/flip`, `lib/stage/scene`, `RoseClient`).

---

### Task 1 : textes de l'étape 4 et voix des lecteurs d'écran

**Files:**
- Modify: `services/web/src/theme/copy.v2.json` (`auth.kicker`, l. 221), `src/theme/copy.ts` (en-tête), `src/theme/copy.extra.ts`, `src/components/Herald/store.ts`, `src/components/Herald/Herald.tsx`
- Test: `services/web/tests/copy.test.mjs`, `tests/copy-extra.test.mjs`, Create `tests/a11y-contract.test.mjs`

**Interfaces:**
- Produces :
  - `tx` : `keys.{toggle,toggleHelp,on,off}`, `transport.{skipTip,restartTip,repeatTip}`, `a11y.{skipToQueue,nowPlaying,paused,resumed}` ;
  - `export const KEYS: readonly (readonly [string, string])[]` ;
  - `export function speak(text: string, o?: { assertive?: boolean }): void` et `setSpeaker(fn)` (`Herald/store.ts`).

- [ ] **Step 1 : tests qui échouent.**

`tests/copy.test.mjs`, après le test « casting : aucun texte ne fait de Greg un roi » :

```js
test('connexion : Greg se présente en valet, plus de formule royale au-dessus de lui', () => {
  assert.equal(t('auth.kicker'), t('brand.tagline'));
  assert.equal(t('auth.kicker'), 'Valet de musique de Sa Majesté');
  assert.doesNotMatch(t('auth.kicker'), /grâce|\bRe[xy]\b|\broi\b/i);
});
```

`tests/copy-extra.test.mjs` : import `const { EXTRA, KEYS, tx } = await loadTs('../src/theme/copy.extra.ts');`, puis à la fin :

```js
test('raccourcis de l’étape 4 : Espace, Maj+→, Maj+← ; ni N, ni P, ni R ; libellés au format du deck', () => {
  const keys = KEYS.map(([k]) => k);
  assert.deepEqual(keys.slice(0, 3), ['Espace', 'Maj+→', 'Maj+←']);
  for (const k of ['/', '?', 'Ctrl+Z', '↑ ↓', 'Entrée', 'Alt+↑ ↓', 'Alt+Début', 'Suppr', 'Échap']) assert.ok(keys.includes(k), k);
  for (const bad of ['N', 'P', 'R']) assert.ok(!keys.includes(bad), bad);
  for (const [, label] of KEYS) assert.ok(label && !/ [:;!?]/.test(label) && !label.includes("'"), label);
});

test('textes de l’étape 4 : interrupteur, bulles, lien d’évitement, annonces', () => {
  assert.equal(tx('keys.toggle'), 'Raccourcis clavier');
  assert.equal(tx('transport.skipTip'), 'Suivant (Maj+→)');
  assert.equal(tx('transport.restartTip'), 'Depuis le début (Maj+←)');
  assert.equal(tx('a11y.skipToQueue'), 'Aller à la file');
  assert.equal(tx('a11y.nowPlaying', { title: 'Africa' }), 'En lecture\u00a0: Africa');
  for (const k of ['keys.toggleHelp', 'keys.on', 'keys.off', 'transport.repeatTip', 'a11y.paused', 'a11y.resumed']) assert.notEqual(tx(k), k, k);
});
```

`tests/a11y-contract.test.mjs` :

```js
// Régions live (étape 4) : speak() écrit dans les deux régions persistantes du Héraut.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';

test('speak() passe par les régions aria-live du Héraut (polie ou assertive)', () => {
  assert.match(read('src/components/Herald/store.ts'), /export function speak\(text: string, o: \{ assertive\?: boolean \} = \{\}\): void/);
  const herald = read('src/components/Herald/Herald.tsx');
  assert.match(herald, /setSpeaker\(\(text, assertive\) => write\(assertive \? alertRef\.current : politeRef\.current, text\)\)/);
  assert.match(herald, /return \(\) => \{ setAnnouncer\(null\); setSpeaker\(null\); \};/);
});
```

- [ ] **Step 2 :** `cd services/web && npm test` → 4 FAIL.

- [ ] **Step 3 : implémenter.**
  - `copy.v2.json` : `"kicker": "Par la grâce de Discord",` → `"kicker": "Valet de musique de Sa Majesté",`. C'est la formule A de `persona-v2.md`, égale à `brand.tagline`.
  - `copy.ts`, en-tête : ajouter ` * Seule exception, validée par Paul (étape 4) : auth.kicker, formule de valet au lieu d'une formule royale.`
  - `copy.extra.ts` : dans `EXTRA` après `herald`, puis l'export `KEYS` :

```ts
  keys: {
    toggle: 'Raccourcis clavier',
    toggleHelp: 'Désactivés\u00a0: seules les touches des listes, Échap et Ctrl+Z restent actives.',
    on: 'Raccourcis clavier activés.',
    off: 'Raccourcis clavier désactivés.',
  },
  transport: { skipTip: 'Suivant (Maj+→)', restartTip: 'Depuis le début (Maj+←)', repeatTip: 'Boucle' },
  a11y: { skipToQueue: 'Aller à la file', nowPlaying: 'En lecture\u00a0: {title}', paused: 'En pause.', resumed: 'Lecture reprise.' },
```

```ts
/** Raccourcis du menu du compte (DESIGN §12.7, body.html l. 54–63) : remplacent `shortcuts.items` du deck (N, P, R retirés). */
export const KEYS: readonly (readonly [string, string])[] = [
  ['Espace', 'Lecture / pause'], ['Maj+→', 'Titre suivant'], ['Maj+←', 'Recommencer le titre'], ['/', 'Rechercher'],
  ['A…Z', 'Chercher en tapant'], ['?', 'Afficher cette aide'], ['Ctrl+Z', 'Annuler la dernière action'],
  ['↑ ↓', 'Parcourir une liste'], ['Entrée', 'Jouer le titre maintenant'], ['Alt+↑ ↓', 'Déplacer le titre choisi'],
  ['Alt+Début', 'Mettre en suivant'], ['Suppr', 'Retirer le titre'], ['Échap', 'Fermer'],
];
```

  - `Herald/store.ts`, après `setAnnouncer` :

```ts
let speaker: ((text: string, assertive: boolean) => void) | null = null;
export function setSpeaker(fn: ((text: string, assertive: boolean) => void) | null): void { speaker = fn; }
/** Annonce sans notification visible (clavier, changement de titre), dans les régions persistantes (DESIGN §7). */
export function speak(text: string, o: { assertive?: boolean } = {}): void { if (text) speaker?.(text, !!o.assertive); }
```

  - `Herald.tsx` : importer `setSpeaker`, puis remplacer l'effet de `setAnnouncer` :

```tsx
  useEffect(() => {
    const write = (el: HTMLDivElement | null, text: string) => {   // vidée puis remplie : un texte répété est relu
      if (!el) return;
      el.textContent = '';
      setTimeout(() => { el.textContent = text; }, 40);
    };
    setAnnouncer((x) => write(x.kind === 'err' ? alertRef.current : politeRef.current,
      spokenText(x, (label) => tx('herald.undoHint', { label }))));
    setSpeaker((text, assertive) => write(assertive ? alertRef.current : politeRef.current, text));
    return () => { setAnnouncer(null); setSpeaker(null); };
  }, []);
```

- [ ] **Step 4 :** `npm test` → PASS, 262 (258 + 4).
- [ ] **Step 5 :** rendre la main (pas de commit).

---

### Task 2 : logique pure des chorégraphies et du clavier

**Files:**
- Create: `services/web/src/lib/stage/coronation.ts`, `src/lib/queue/seal.ts`, `src/lib/keys.ts`
- Modify: `src/lib/motion.ts`, `src/lib/flip.ts` (ajouts en fin de fichier)
- Test: Create `tests/coronation.test.mjs`, `tests/seal.test.mjs`, `tests/keys.test.mjs` ; Modify `tests/motion.test.mjs`

**Interfaces:**
- Produces (le code du Step 3 fait foi) : `coronation.ts` : `Box`, `Via`, `CrownMode`, `CrownPlan`, `Order`, `FLIGHT_MS`, `AFTER_CEREMONY_MS`, `QUICK_WINDOW_MS`, `ORDER_TTL_MS`, `BUSY_MS`, `NIGHT_ROSE_FADE_MS`, `NEXT`, `bezier`, `easeDrawer`, `flightFrames`, `visibleIn`, `boxOf`, `crownMode`, `crownPlan`, `createOrders`, `kingOrders` ; `seal.ts` : `SealExpect`, `SEAL_TTL_MS`, `SEAL_STAMP_DELAY_MS`, `SEAL_FLIGHT_MS`, `sameTrack`, `createSealBook`, `sealBook` ; `keys.ts` : `KeyEv`, `KeyCtx`, `Shortcut`, `ListAct`, `SHORTCUTS_STORAGE_KEY`, `HELP_EVENT`, `shortcutsOn`, `shortcutFor`, `listKey`, `moveBefore` ; `watchReducedMotion(fn): () => void` (`motion.ts`) ; `reverseStagger(i, n, step = 20, cap = 8)` (`flip.ts`).

- [ ] **Step 1 : tests qui échouent.**

`tests/coronation.test.mjs` :

```js
// Le Couronnement (étape 4) : jetons, courbe, vol, source visible, modes, plans, ordres du Roi.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const C = await loadTs('../src/lib/stage/coronation.ts');
const M = await loadTs('../src/lib/motion.ts');

test('jetons : vol 420 ms (= --dur-flight), Héraut 80 ms après, rafale 1,5 s, lune 240 ms', () => {
  assert.equal(C.FLIGHT_MS, M.DUR.flight);
  assert.equal(C.AFTER_CEREMONY_MS, M.DUR.flight + 80);
  assert.deepEqual([C.QUICK_WINDOW_MS, C.NIGHT_ROSE_FADE_MS, C.BUSY_MS], [1500, 240, 1300]);
});

test('bezier : bornes, monotone ; --ease-drawer à 95 % du trajet à mi-temps', () => {
  const f = C.easeDrawer;
  assert.deepEqual([f(0), f(1)], [0, 1]);
  let prev = 0;
  for (let i = 1; i <= 100; i++) { const v = f(i / 100); assert.ok(v >= prev - 1e-9, `${i}`); prev = v; }
  assert.ok(Math.abs(f(0.25) - 0.7791) < 1e-3 && Math.abs(f(0.5) - 0.9548) < 1e-3);
  assert.ok(Math.abs(C.bezier(0, 0, 1, 1)(0.3) - 0.3) < 1e-6);
});

test('vol : 13 images clés en transform seul, de la pochette à la scène, sans recul', () => {
  const kf = C.flightFrames({ left: 1000, top: 300, width: 72, height: 40.5 }, { left: 100, top: 200, width: 648, height: 364.5 });
  assert.equal(kf.length, 13);
  assert.deepEqual(Object.keys(kf[0]).sort(), ['offset', 'transform']);
  assert.deepEqual([kf[0].offset, kf[12].offset], [0, 1]);
  assert.equal(kf[0].transform, 'translate(1000px, 300px) scale(0.1111)');
  assert.equal(kf[12].transform, 'translate(100px, 200px) scale(1)');
  const xs = kf.map((k) => Number(/translate\(([-\d.]+)px/.exec(k.transform)[1]));
  for (let i = 1; i < xs.length; i++) assert.ok(xs[i] <= xs[i - 1], `${i}`);
});

test('source visible à moitié au moins ; une ligne repliée ne l’est pas', () => {
  const c = { left: 0, top: 100, width: 400, height: 500 }, r = (top, h = 40) => ({ left: 10, top, width: h ? 72 : 0, height: h });
  assert.deepEqual([120, 80, 70, 580, 590].map((y) => C.visibleIn(r(y), c)), [true, true, false, true, false]);
  assert.equal(C.visibleIn(r(120, 0), c), false);
});

test('mode : vol à la souris ; rapide au clavier, en rafale ou sans ordre ; repli si la nuit se lève', () => {
  const b = { via: 'pointer', sinceLast: 5000, reduced: false, canFly: true, fromNight: false };
  const m = (o) => C.crownMode({ ...b, ...o });
  assert.deepEqual([m({}), m({ canFly: false }), m({ via: 'key' }), m({ via: null }), m({ sinceLast: 900 }), m({ fromNight: true })],
    ['flight', 'fallback', 'quick', 'quick', 'quick', 'fallback']);
  assert.equal(m({ reduced: true, fromNight: true }), 'reduced');
});

test('plans de chaque mode (DESIGN §5, motion.md §6.10 et §8)', () => {
  const [f, b, q, r] = ['flight', 'fallback', 'quick', 'reduced'].map(C.crownPlan);
  assert.deepEqual([f.titleDelay, f.metaDelay, f.exitMs, f.enterMs, f.shift, f.roseAt, f.roseFade, f.glintAt], [160, 200, 180, 280, 8, 420, 900, 420]);
  assert.deepEqual([b.posterMs, b.roseAt, b.roseFade, b.glintAt], [420, 0, 900, 380]);
  assert.deepEqual([q.titleDelay, q.metaDelay, q.posterMs, q.roseFade, q.glintAt], [0, 40, 210, 450, null]);
  assert.deepEqual([r.shift, r.exitMs, r.enterMs, r.posterMs, r.roseFade, r.glintAt], [0, 150, 150, 200, 300, null]);
});

test('ordres du Roi : clé précise ou « le suivant », 4 s, pris une fois', () => {
  const I = C.createOrders();
  I.mark('k3', 'pointer', 1000);
  assert.equal(I.take('k9', 'k1', 1100), null, 'un autre titre : l’ordre attend');
  assert.deepEqual(I.take('k3', 'k1', 1200), { target: 'k3', via: 'pointer', at: 1000 });
  assert.equal(I.take('k3', 'k1', 1300), null);
  I.mark(C.NEXT, 'key', 2000);
  assert.equal(I.take('k5', 'k4', 2100), null, 'k5 n’était pas le suivant');
  assert.equal(I.take('k4', 'k4', 2200)?.via, 'key');
  I.mark('k7', 'pointer', 3000);
  assert.equal(I.take('k7', null, 3000 + C.ORDER_TTL_MS + 1), null, 'périmé');
});

test('boxOf lit un rectangle du DOM', () => {
  assert.deepEqual(C.boxOf({ getBoundingClientRect: () => ({ left: 1, top: 2, width: 3, height: 4, right: 4, bottom: 6 }) }),
    { left: 1, top: 2, width: 3, height: 4 });
});
```

`tests/seal.test.mjs` :

```js
// Le Sceau (étape 4) : l'ajout du Roi attendu, reconnu à l'entrée de sa ligne.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const S = await loadTs('../src/lib/queue/seal.ts');

test('la prochaine ligne du Roi, du même titre, dans les 10 s, une seule fois', () => {
  const b = S.createSealBook(), e = { url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', from: null, thumb: null, at: 1000 };
  b.expect(e);
  assert.equal(b.take({ url: 'https://youtu.be/dQw4w9WgXcQ', mine: false }, 1100), null, 'ligne d’un autre');
  assert.equal(b.take({ url: 'https://youtu.be/djV11Xbc914', mine: true }, 1100), null, 'autre vidéo');
  assert.equal(b.take({ url: 'https://youtu.be/dQw4w9WgXcQ?si=abc', mine: true }, 1200), e);
  assert.equal(b.take({ url: 'https://youtu.be/dQw4w9WgXcQ', mine: true }, 1300), null);
});

test('recherche tapée (url null) : la première ligne du Roi ; périmé après 10 s ; clear', () => {
  const b = S.createSealBook(), any = { url: null, from: null, thumb: null, at: 0 }, row = { url: 'https://soundcloud.com/a/b', mine: true };
  b.expect(any); assert.equal(b.take(row, S.SEAL_TTL_MS + 1), null);
  b.expect(any); assert.ok(b.take(row, 500));
  b.expect(any); b.clear(); assert.equal(b.take(row, 1), null);
});

test('même titre : ids YouTube comparés, sinon liens identiques ; délais', () => {
  assert.ok(S.sameTrack('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1', 'https://youtu.be/dQw4w9WgXcQ'));
  assert.ok(S.sameTrack('https://music.youtube.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ'));
  assert.ok(!S.sameTrack('https://youtu.be/dQw4w9WgXcQ', 'https://youtu.be/djV11Xbc914'));
  assert.ok(S.sameTrack('https://soundcloud.com/a/b', 'https://soundcloud.com/a/b') && !S.sameTrack('https://soundcloud.com/a/b', undefined));
  assert.deepEqual([S.SEAL_STAMP_DELAY_MS, S.SEAL_FLIGHT_MS], [380, 460]);
});
```

`tests/keys.test.mjs` :

```js
// Clavier (étape 4) : raccourcis de la page, interrupteur (WCAG 2.1.4), touches des listes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const K = await loadTs('../src/lib/keys.ts');
const ctx = { enabled: true, loggedIn: true, inField: false, inPopover: false, onRow: false, onControl: false, dragging: false };
const SPACE = { key: ' ', code: 'Space' }, NEXT = { key: 'ArrowRight', shiftKey: true };
const f = (ev, o = {}) => K.shortcutFor(ev, { ...ctx, ...o });

test('Espace, Maj+→, Maj+←, /, ? ; une lettre part dans la recherche (N ne saute plus)', () => {
  assert.deepEqual([f(SPACE), f(NEXT), f({ key: 'ArrowLeft', shiftKey: true }), f({ key: '/' }), f({ key: '?', shiftKey: true })],
    ['togglePause', 'skip', 'restart', 'search', 'help']);
  for (const key of ['n', 'p', 'r', 'N', 'é', '7']) assert.equal(f({ key }), 'type', key);
  for (const key of ['ArrowRight', 'Enter', 'Tab', 'Escape', 'F5']) assert.equal(f({ key }), null, key);
});

test('rien dans un champ, une fenêtre, un glisser, déconnecté, ou interrupteur coupé', () => {
  for (const off of [{ inField: true }, { inPopover: true }, { dragging: true }, { loggedIn: false }, { enabled: false }]) {
    for (const ev of [SPACE, NEXT, { key: '/' }, { key: '?' }, { key: 'a' }]) assert.equal(f(ev, off), null, `${JSON.stringify(off)} ${ev.key}`);
  }
});

test('Ctrl, Cmd, Alt et Espace maintenue restent au navigateur', () => {
  assert.deepEqual([f({ key: 'z', ctrlKey: true }), f({ key: 'r', metaKey: true }), f({ ...NEXT, altKey: true }), f({ ...SPACE, repeat: true })],
    [null, null, null, null]);
});

test('sur une ligne, les touches sont à la liste ; sur un bouton, Espace l’active', () => {
  assert.deepEqual([f(SPACE, { onRow: true }), f({ key: 'a' }, { onRow: true }), f({ key: '/' }, { onRow: true })], [null, null, 'search']);
  assert.deepEqual([f(SPACE, { onControl: true }), f(NEXT, { onControl: true }), f({ key: 'a' }, { onControl: true })], [null, 'skip', 'type']);
});

test('liste : flèches, Début, Fin, Entrée, Suppr, Alt+↑↓, Alt+Début', () => {
  const L = (key, i, o = {}) => K.listKey({ key, ...o }, i, 5);
  assert.deepEqual([L('ArrowDown', 2), L('ArrowDown', 4), L('ArrowUp', 0), L('Home', 3), L('End', 1)].map((a) => a.index), [3, 4, 0, 0, 4]);
  assert.deepEqual([L('Enter', 1), L('Delete', 1)], [{ kind: 'activate' }, { kind: 'remove' }]);
  const alt = { altKey: true };
  assert.deepEqual([L('ArrowUp', 1, alt), L('ArrowDown', 3, alt), L('Home', 3, alt)], [{ kind: 'move', dir: -1 }, { kind: 'move', dir: 1 }, { kind: 'next' }]);
  assert.deepEqual([L('ArrowUp', 0, alt), L('ArrowDown', 4, alt), L('Home', 0, alt), L('ArrowDown', 1, { ctrlKey: true }), L('a', 1)],
    [null, null, null, null, null]);
  assert.equal(K.listKey({ key: 'ArrowDown' }, 0, 0), null);
});

test('déplacer d’un rang : la clé devant laquelle déposer (null : fin de file)', () => {
  const k = ['a', 'b', 'c', 'd'];
  assert.deepEqual([K.moveBefore(k, 'c', -1), K.moveBefore(k, 'b', 1), K.moveBefore(k, 'c', 1)], ['b', 'd', null]);
  assert.deepEqual([K.moveBefore(k, 'a', -1), K.moveBefore(k, 'd', 1), K.moveBefore(k, 'x', 1)], [undefined, undefined, undefined]);
});

test('interrupteur allumé par défaut, seul « off » le coupe ; événement d’aide', () => {
  assert.deepEqual([K.SHORTCUTS_STORAGE_KEY, K.HELP_EVENT], ['greg.webplayer.keys', 'greg:help']);
  assert.deepEqual([null, undefined, 'on', 'off'].map((v) => K.shortcutsOn(v)), [true, true, true, false]);
});
```

`tests/motion.test.mjs`, à la fin (`M` = `motion.ts`, `F` = `flip.ts`, déjà chargés) :

```js
test('mouvement réduit suivi en direct, jusqu’au désabonnement', () => {
  const ls = new Set(), mq = { matches: false, addEventListener: (_, fn) => ls.add(fn), removeEventListener: (_, fn) => ls.delete(fn) };
  const saved = globalThis.matchMedia;
  globalThis.matchMedia = () => mq;
  try {
    const seen = [], stop = M.watchReducedMotion((r) => seen.push(r));
    mq.matches = true; for (const fn of [...ls]) fn();
    stop();
    mq.matches = false; for (const fn of [...ls]) fn();
    assert.deepEqual(seen, [false, true]);
    assert.equal(ls.size, 0);
  } finally { globalThis.matchMedia = saved; }
});

test('sortie en cascade inversée : la dernière ligne d’abord, 20 ms, plafond 8', () => {
  assert.deepEqual([0, 1, 2].map((i) => F.reverseStagger(i, 3)), [40, 20, 0]);
  assert.deepEqual([F.reverseStagger(0, 12), F.reverseStagger(11, 12)], [140, 0]);
});
```

- [ ] **Step 2 :** `npm test` → FAIL (modules absents).

- [ ] **Step 3 : implémenter.** `src/lib/stage/coronation.ts` :

```ts
/**
 * Le Couronnement (spec §5, DESIGN §5 et §12.6, motion.md §6.10) : calculs purs (tests/coronation.test.mjs).
 * La miniature vole de sa ligne à la scène (--ease-drawer échantillonnée en 13 images clés de transform).
 */
export type Box = { left: number; top: number; width: number; height: number };
export type Via = 'pointer' | 'key';
export type CrownMode = 'flight' | 'fallback' | 'quick' | 'reduced';
/** Délais et durées (ms) ; shift : translation des légendes (px, 0 = fondu) ; roseAt : rallumage de la rosace. */
export type CrownPlan = { titleDelay: number; metaDelay: number; exitMs: number; enterMs: number; shift: number;
  posterMs: number; roseAt: number; roseFade: number; glintAt: number | null };
export type Order = { target: string; via: Via; at: number };

export const FLIGHT_MS = 420;                    // --dur-flight
export const AFTER_CEREMONY_MS = FLIGHT_MS + 80; // le Héraut parle une fois la couronne posée
export const QUICK_WINDOW_MS = 1500;
export const ORDER_TTL_MS = 4000;
export const BUSY_MS = 1300;                     // la rosace ne peint rien d'avance pendant la cérémonie
export const NIGHT_ROSE_FADE_MS = 240;           // arrêt : la lune entre en 240 ms (DESIGN §12.6)
export const NEXT = '@next';                     // « le suivant » : sa clé n'est connue qu'au changement

/** Courbe de Bézier CSS → fonction du temps, par dichotomie. */
export function bezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const at = (t: number, a: number, b: number): number => 3 * (1 - t) * (1 - t) * t * a + 3 * (1 - t) * t * t * b + t * t * t;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0, hi = 1;
    for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; if (at(m, x1, x2) < x) lo = m; else hi = m; }
    return at((lo + hi) / 2, y1, y2);
  };
}
export const easeDrawer = bezier(0.32, 0.72, 0, 1);
const round = (v: number, d: number): number => Math.round(v * 10 ** d) / 10 ** d;

/** Fantôme de la taille de la scène (`to`, origine 0 0), réduit sur la pochette au départ : net à l'arrivée. Joué en `linear`. */
export function flightFrames(from: Box, to: Box, steps = 12): { transform: string; offset: number }[] {
  const s0 = from.width / to.width, out: { transform: string; offset: number }[] = [];
  for (let i = 0; i <= steps; i++) {
    const p = easeDrawer(i / steps);
    const x = from.left + (to.left - from.left) * p, y = from.top + (to.top - from.top) * p, s = s0 + (1 - s0) * p;
    out.push({ transform: `translate(${round(x, 2)}px, ${round(y, 2)}px) scale(${round(s, 4)})`, offset: round(i / steps, 4) });
  }
  return out;
}

/** Au moins la moitié de `r` dans `c` (motion.md §6.10). */
export function visibleIn(r: Box, c: Box): boolean {
  return r.width > 0 && r.height > 0 && r.top >= c.top - r.height / 2 && r.top + r.height <= c.top + c.height + r.height / 2;
}
export const boxOf = (el: { getBoundingClientRect(): { left: number; top: number; width: number; height: number } }): Box => {
  const b = el.getBoundingClientRect();
  return { left: b.left, top: b.top, width: b.width, height: b.height };
};

export function crownMode(o: { via: Via | null; sinceLast: number; reduced: boolean; canFly: boolean; fromNight: boolean }): CrownMode {
  if (o.reduced) return 'reduced';
  if (o.fromNight) return 'fallback';
  if (o.sinceLast < QUICK_WINDOW_MS || o.via !== 'pointer') return 'quick';
  return o.canFly ? 'flight' : 'fallback';
}

const PLANS: Record<CrownMode, CrownPlan> = {
  flight: { titleDelay: 160, metaDelay: 200, exitMs: 180, enterMs: 280, shift: 8, posterMs: 0, roseAt: FLIGHT_MS, roseFade: 900, glintAt: FLIGHT_MS },
  fallback: { titleDelay: 160, metaDelay: 200, exitMs: 180, enterMs: 280, shift: 8, posterMs: 420, roseAt: 0, roseFade: 900, glintAt: 380 },
  quick: { titleDelay: 0, metaDelay: 40, exitMs: 180, enterMs: 280, shift: 8, posterMs: 210, roseAt: 0, roseFade: 450, glintAt: null },
  reduced: { titleDelay: 0, metaDelay: 0, exitMs: 150, enterMs: 150, shift: 0, posterMs: 200, roseAt: 0, roseFade: 300, glintAt: null },
};
export const crownPlan = (m: CrownMode): CrownPlan => PLANS[m];

/** Le dernier ordre du Roi (un titre, ou NEXT), repris une fois par le changement qu'il annonçait. */
export function createOrders(ttl = ORDER_TTL_MS) {
  let last: Order | null = null;
  return {
    mark(target: string, via: Via, now: number): void { last = { target, via, at: now }; },
    take(key: string, prevNext: string | null, now: number): Order | null {
      const i = last;
      if (!i || now - i.at > ttl) { last = null; return null; }
      if (i.target !== key && !(i.target === NEXT && prevNext === key)) return null;
      last = null;
      return i;
    },
  };
}
export const kingOrders = createOrders();
```

`src/lib/queue/seal.ts` :

```ts
/** Le Sceau (DESIGN §5, motion.md §6.5) : l'ajout du Roi attendu, reconnu à l'entrée de sa ligne. Pur (tests/seal.test.mjs). */
import type { Box } from '../stage/coronation';

export type SealExpect = { url: string | null; from: Box | null; thumb: string | null; at: number };
export const SEAL_TTL_MS = 10_000, SEAL_STAMP_DELAY_MS = 380, SEAL_FLIGHT_MS = 460;
const YT_ID = /(?:[?&]v=|youtu\.be\/|\/shorts\/|\/embed\/)([\w-]{11})/;

export function sameTrack(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const ia = YT_ID.exec(a)?.[1], ib = YT_ID.exec(b)?.[1];
  return ia || ib ? ia === ib : a === b;
}

/** Un ajout attendu à la fois (le dernier l'emporte) ; url null (recherche tapée) : la prochaine ligne du Roi. */
export function createSealBook(ttl = SEAL_TTL_MS) {
  let wait: SealExpect | null = null;
  return {
    expect(e: SealExpect): void { wait = e; },
    take(row: { url?: string | null; mine: boolean }, now: number): SealExpect | null {
      const w = wait;
      if (!w || now - w.at > ttl) { wait = null; return null; }
      if (!row.mine || (w.url && !sameTrack(w.url, row.url))) return null;
      wait = null;
      return w;
    },
    clear(): void { wait = null; },
  };
}
export const sealBook = createSealBook();
```

`src/lib/keys.ts` :

```ts
/**
 * Clavier (spec §5, DESIGN §7 et §12.7), pur (tests/keys.test.mjs). L'interrupteur « Raccourcis clavier »
 * (WCAG 2.1.4) coupe tout ce qui tient en une touche, saisie directe comprise.
 */
export type KeyEv = { key: string; code?: string; shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; repeat?: boolean };
/** onRow : ligne d'une liste (ses touches sont à elle) ; onControl : bouton, lien, onglet (Espace l'active). */
export type KeyCtx = { enabled: boolean; loggedIn: boolean; inField: boolean; inPopover: boolean; onRow: boolean; onControl: boolean; dragging: boolean };
export type Shortcut = 'togglePause' | 'skip' | 'restart' | 'search' | 'help' | 'type';
export type ListAct = { kind: 'focus'; index: number } | { kind: 'activate' } | { kind: 'remove' } | { kind: 'move'; dir: -1 | 1 } | { kind: 'next' };
export const SHORTCUTS_STORAGE_KEY = 'greg.webplayer.keys';
export const HELP_EVENT = 'greg:help';
export const shortcutsOn = (stored: string | null | undefined): boolean => stored !== 'off';

export function shortcutFor(ev: KeyEv, c: KeyCtx): Shortcut | null {
  if (!c.enabled || !c.loggedIn || c.inField || c.inPopover || c.dragging) return null;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return null;
  if (ev.key === '/') return 'search';
  if (ev.key === '?') return 'help';
  if (c.onRow) return null;
  if (ev.code === 'Space' || ev.key === ' ') return c.onControl || ev.repeat ? null : 'togglePause';
  if (ev.shiftKey && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) return ev.repeat ? null : ev.key === 'ArrowRight' ? 'skip' : 'restart';
  return ev.key.length === 1 && /\S/.test(ev.key) ? 'type' : null;
}

export function listKey(ev: KeyEv, index: number, count: number): ListAct | null {
  if (ev.ctrlKey || ev.metaKey || count <= 0) return null;
  const last = count - 1;
  if (ev.altKey) {
    if (ev.key === 'ArrowUp') return index > 0 ? { kind: 'move', dir: -1 } : null;
    if (ev.key === 'ArrowDown') return index < last ? { kind: 'move', dir: 1 } : null;
    return ev.key === 'Home' && index > 0 ? { kind: 'next' } : null;
  }
  switch (ev.key) {
    case 'ArrowDown': return { kind: 'focus', index: Math.min(last, index + 1) };
    case 'ArrowUp': return { kind: 'focus', index: Math.max(0, index - 1) };
    case 'Home': return { kind: 'focus', index: 0 };
    case 'End': return { kind: 'focus', index: last };
    case 'Enter': return { kind: 'activate' };
    case 'Delete': return { kind: 'remove' };
    default: return null;
  }
}

/** Clé devant laquelle déposer `key` décalé d'un rang (moveTrack) ; null : fin de file ; undefined : impossible. */
export function moveBefore(keys: readonly string[], key: string, dir: -1 | 1): string | null | undefined {
  const i = keys.indexOf(key), j = i + dir;
  if (i < 0 || j < 0 || j >= keys.length) return undefined;
  return dir < 0 ? keys[j] : keys[i + 2] ?? null;
}
```

`src/lib/motion.ts` et `src/lib/flip.ts`, en fin de fichier :

```ts
/** Suit prefers-reduced-motion en direct (DESIGN §12.6) : `fn` tout de suite, puis à chaque changement. */
export function watchReducedMotion(fn: (reduced: boolean) => void): () => void {
  if (typeof matchMedia !== 'function') { fn(false); return () => {}; }
  const mq = matchMedia('(prefers-reduced-motion: reduce)');
  const on = (): void => fn(mq.matches);
  on();
  mq.addEventListener('change', on);
  return () => mq.removeEventListener('change', on);
}
```

```ts
/** Sortie en cascade inversée (arrêt, DESIGN §5) : de la dernière ligne à la première, `step` ms, plafond `cap`. */
export function reverseStagger(i: number, n: number, step = 20, cap = 8): number {
  return Math.min(Math.max(0, n - 1 - i), cap - 1) * step;
}
```

- [ ] **Step 4 :** `npm test && GREG_TEST_TRANSPILE=1 npm test` → PASS : 258 + 20, puis 284 avec les tâches 1 et 6.
- [ ] **Step 5 :** rendre la main.

---

### Task 3 : la scène (Couronnement, Révérence, nuit séquencée, pierre différée)

**Files:**
- Create: `services/web/src/components/Stage/coronation.ts`, `Swap.tsx`, `glint.ts`, `tests/choreo-stage.test.mjs`
- Modify: `src/components/Stage/{Stage,NowPlaying,Portal,Rose,Transport}.tsx`, `{stage,now,portal,rose}.css`, `src/lib/rose/client.ts`, `src/hooks/usePlayer.ts` (`playNow`), `tests/rose-client.test.mjs`

**Interfaces:**
- Consumes :
  - tâche 2 : `lib/stage/coronation.ts` (ordres, modes, plans, vol, délais) et `watchReducedMotion` ;
  - tâche 1 : `speak`, `tx('a11y.nowPlaying')`, `tx('transport.*')`.
- Produces :

```ts
export type Ceremony = { seq: number; key: string; mode: CrownMode; plan: CrownPlan; at: number; landed: boolean };
export function startCoronation(): () => void;   // Stage.tsx, une fois
export function useCeremony(): Ceremony | null;  // null la nuit
export function runGlint(slot: HTMLElement): void;
export const decodedPosters: Map<string, string>; // Portal.tsx : id → poster du prochain titre, décodé
RoseClient.hold(ms: number): void;               // start() peut aussi être différé
```

- [ ] **Step 1 : tests qui échouent.**

`tests/rose-client.test.mjs` :
- l'aide devient `function makeRose({ paintMs = 1, autoStart = true } = {})` ;
- `c.start();` y devient `if (autoStart) c.start();` ;
- ajouter à la fin :

```js
test('hold : pendant une cérémonie, le prochain titre attend pour être peint', async () => {
  const { c, posts, layers } = makeRose();
  c.resize(100);
  await until(() => layers.glass.children.length > 0);
  c.hold(150);
  c.prepare('N');
  await wait(60);
  assert.ok(!posts.some((k) => k.startsWith('t:N@')), 'peinte pendant la cérémonie');
  await until(() => posts.some((k) => k.startsWith('t:N@')), 1500);
  c.destroy();
});

test('démarrage différé : taille, titre et prochain titre demandés avant start() partent au démarrage', async () => {
  const { c, posts, layers, front } = makeRose({ autoStart: false });
  c.resize(100);
  await c.show('A');
  c.prepare('B');
  await wait(20);
  assert.deepEqual(posts, [], 'rien avant start()');
  c.start();
  await until(() => posts.includes('t:A@100x1') && posts.includes('moon@100x1') && posts.some((k) => k.startsWith('t:B@')));
  await until(() => layers.glass.children.some((s) => slotKey(s) === 't:A@100x1'));
  await finishFades();
  assert.equal(front().key, 't:A@100x1');
  c.destroy();
});
```

`tests/choreo-stage.test.mjs` :

```js
// La scène de l'étape 4 : Couronnement, légendes, reflet, Révérence, posters, pierre différée.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
const code = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

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
```

- [ ] **Step 2 :** `npm test` → 7 FAIL.

- [ ] **Step 3 : `RoseClient`.**
  - `request()` commence par `if (this.dead || !this.worker) return Promise.resolve(null);`. Sinon une attente posée avant `start()` ne se résout jamais.
  - À la fin de `start()` :

```ts
    // démarrage différé (Rose.tsx, après le premier affichage) : ce qui a été demandé entre-temps part maintenant
    if (this.R) { void this.request(null).then((d) => { if (d) this.build(d); }); void this.show(this.want); this.prepare(this.next); }
```

  - Après `prepare` :

```ts
  /** Cérémonie en cours : rien n'est peint d'avance avant ms. */
  hold(ms: number): void { this.busyUntil = Math.max(this.busyUntil, performance.now() + ms); }
```

- [ ] **Step 4 : le chef de cérémonie, `components/Stage/coronation.ts`.**

```ts
'use client';

import { useSyncExternalStore } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { extractVideoId } from '@/lib/format';
import { reducedMotion, watchReducedMotion } from '@/lib/motion';
import { FLIGHT_MS, NEXT, boxOf, crownMode, crownPlan, flightFrames, kingOrders, visibleIn } from '@/lib/stage/coronation';
import type { Box, CrownMode, CrownPlan } from '@/lib/stage/coronation';
import { parseTitle } from '@/lib/titles';
import { speak } from '@/components/Herald/store';
import { tx } from '@/theme/copy.extra';
import { decodedPosters } from './Portal';

/** Le chef de cérémonie (DESIGN §5, §8, §12.6), hors de React : ordre, mode et source mesurés avant le rendu, vol à l'image suivante. */
export type Ceremony = { seq: number; key: string; mode: CrownMode; plan: CrownPlan; at: number; landed: boolean };
type Source = { im: HTMLElement; img: HTMLImageElement; from: Box; to: Box };

let current: Ceremony | null = null, seq = 0, lastAt = -Infinity;
let ghost: HTMLDivElement | null = null, flight: Animation | null = null, hiddenIm: HTMLElement | null = null;
const listeners = new Set<() => void>();
const set = (c: Ceremony | null): void => { current = c; for (const l of listeners) l(); };

function ghostEl(): HTMLDivElement {
  if (ghost?.isConnected) return ghost;
  ghost = document.createElement('div');
  ghost.className = 'ghost';
  ghost.setAttribute('aria-hidden', 'true');
  document.body.appendChild(ghost);
  return ghost;
}

/** Vol fini ou interrompu : le fantôme s'efface, la pochette cachée revient (un refus peut ramener la ligne). */
function ground(): void {
  flight?.cancel(); flight = null;
  if (ghost) ghost.style.opacity = '0';
  hiddenIm?.style.removeProperty('visibility'); hiddenIm = null;
}

/** Pochette de la ligne `key`, visible à moitié dans la file et dans la fenêtre, la scène visible aussi (une colonne). */
function source(key: string): Source | null {
  const pane = document.getElementById('pane-queue');
  if (!pane || pane.getAttribute('aria-hidden') === 'true' || document.hidden) return null;
  const im = pane.querySelector<HTMLElement>(`.qcontent > .qlist > .row[data-key="${CSS.escape(key)}"] .thumb > .im`);
  const img = im?.querySelector('img'), scroller = pane.querySelector<HTMLElement>('.scroller');
  const video = document.querySelector<HTMLElement>('.stage .video');
  if (!im || !img || !scroller || !video) return null;
  const from = boxOf(im), to = boxOf(video), vp = { left: 0, top: 0, width: innerWidth, height: innerHeight };
  return visibleIn(from, boxOf(scroller)) && visibleIn(from, vp) && visibleIn(to, vp) ? { im, img, from, to } : null;
}

function land(c: Ceremony): void {
  if (current?.seq !== c.seq) return;
  set({ ...c, landed: true });
  // le fantôme se lève quand le vrai poster est décodé dessous (600 ms au plus)
  const poster = document.querySelector<HTMLImageElement>('.stage .video .poster:not([data-leaving])');
  const lift = (): void => { requestAnimationFrame(() => { if (current?.seq === c.seq) ground(); }); };
  Promise.race([poster?.decode?.() ?? Promise.resolve(), new Promise((r) => setTimeout(r, 600))]).then(lift, lift);
}

/** poster : déjà décodé (le prochain titre, Portal.tsx) : net à l'arrivée, sans mise au point (DESIGN §12.6). */
function fly(c: Ceremony, src: Source, poster: string | null): void {
  const g = ghostEl();
  g.style.backgroundImage = `url("${poster || src.img.currentSrc || src.img.src}")`;
  g.style.width = `${src.to.width}px`;
  g.style.height = `${src.to.height}px`;
  src.im.style.visibility = 'hidden';
  hiddenIm = src.im;
  requestAnimationFrame(() => {
    if (current?.seq !== c.seq) return;
    g.style.opacity = '1';
    flight = g.animate(flightFrames(src.from, src.to), { duration: FLIGHT_MS, easing: 'linear', fill: 'forwards' });
    flight.finished.then(() => land(c), () => {});
  });
}

function begin(key: string, prevNext: string | null, fromNight: boolean, title: string, id: string | null): void {
  ground();
  const now = performance.now(), order = kingOrders.take(key, prevNext, now), reduced = reducedMotion();
  const src = !reduced && !fromNight && order?.via === 'pointer' ? source(key) : null;
  const mode = crownMode({ via: order?.via ?? null, sinceLast: now - lastAt, reduced, canFly: !!src, fromNight });
  lastAt = now;
  const c: Ceremony = { seq: ++seq, key, mode, plan: crownPlan(mode), at: now, landed: mode !== 'flight' };
  set(c);
  if (mode === 'flight' && src) fly(c, src, id ? decodedPosters.get(id) ?? null : null);
  if (!order || order.target === NEXT) speak(tx('a11y.nowPlaying', { title }));   // « jouer maintenant » a son toast
}

export function startCoronation(): () => void {
  const unsub = useStore.subscribe((s, prev) => {
    const t = s.player.current, k = t?.key || null, pk = prev.player.current?.key || null;
    if (k === pk) return;
    if (!t || !k) { ground(); set(null); return; }
    begin(k, prev.player.queue[0]?.key ?? null, !pk, parseTitle(t.title, t.artist).song || t.title, extractVideoId(t.url));
  });
  const unwatch = watchReducedMotion((r) => { if (r) ground(); });
  // premier vol aussi fluide que le dixième : le fantôme est créé et composé pendant un temps mort
  const warm = (): void => { ghostEl().animate([{ transform: 'translate(-200vw, 0) scale(.2)' }, { transform: 'translate(-200vw, 0) scale(.3)' }], { duration: 32 }); };
  const ric = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
  if (ric) ric(warm, { timeout: 2000 }); else setTimeout(warm, 500);
  return () => { unsub(); unwatch(); ground(); };
}

const subscribe = (fn: () => void): (() => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
export function useCeremony(): Ceremony | null { return useSyncExternalStore(subscribe, () => current, () => null); }
```

- [ ] **Step 5 : `glint.ts` et `Swap.tsx`.**

`glint.ts` porte `glint()` de `app.js` (lignes 502–514) :
- `export function runGlint(slot: HTMLElement): void` ;
- ligne visée : `slot.querySelector(':scope > .line:not([aria-hidden])')` ; rien en mouvement réduit ;
- `W = min(slot.clientWidth, line.scrollWidth)`, `B = max(140, W * .3)` ;
- `div.glint[aria-hidden]` > `.glint-band` (largeur B) > `.glint-text` (texte de la ligne, largeur du slot) ;
- deux `animate` en `translateX` (`-B → W` et `B → -W`), `DUR.glint`, `EASE.inOut`, `fill: 'both'` ; `.glint` retiré à la fin (`finished.then(done, done)`) ;
- trois `createElement('div')` : d'où un fichier à part (`coronation.ts` n'en a qu'un).

`Swap.tsx` :

```tsx
'use client';

import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { dropLeft, mergePresence } from '@/lib/flip';
import type { Presence } from '@/lib/flip';
import { EASE } from '@/lib/motion';
import type { CrownPlan } from '@/lib/stage/coronation';

type Line = { k: string; node: ReactNode };
const keyOf = (l: Line): string => l.k;

/** Légendes croisées (.line, now.css) : l'ancienne sort vers le haut (aria-hidden), la nouvelle entre après `delay` ; sans plan, entrée immobile. */
export default function Swap({ k, plan, delay, children }: { k: string; plan: CrownPlan | null; delay: number; children: ReactNode }) {
  const [shownK, setShownK] = useState(k);
  const [lines, setLines] = useState<Presence<Line>[]>(() => (k ? [{ key: k, item: { k, node: children }, leaving: false }] : []));
  if (shownK !== k) { setShownK(k); setLines(mergePresence(lines, k ? [{ k, node: children }] : [], keyOf)); }
  const els = useRef(new Map<string, HTMLSpanElement>());
  const first = useRef(true), planRef = useRef(plan), delayRef = useRef(delay);
  planRef.current = plan; delayRef.current = delay;

  useLayoutEffect(() => {
    const p = planRef.current;
    for (const l of lines) {
      const el = els.current.get(l.key);
      if (!el) continue;
      if (l.leaving) {
        if (el.dataset.exiting) continue;
        el.dataset.exiting = '1';
        const drop = (): void => setLines((ls) => dropLeft(ls, l.key));
        el.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: `translateY(${-(p?.shift ?? 0)}px)` }],
          { duration: p?.exitMs ?? 180, easing: EASE.out, fill: 'forwards' }).finished.then(drop, drop);
      } else if (el.dataset.exiting) {   // revenue pendant sa sortie
        delete el.dataset.exiting;
        for (const a of el.getAnimations()) a.cancel();
      } else if (!el.dataset.entered) {
        el.dataset.entered = '1';
        if (first.current || !p) continue;
        el.animate([{ opacity: 0, transform: `translateY(${p.shift}px)` }, { opacity: 1, transform: 'none' }],
          { duration: p.enterMs, delay: delayRef.current, easing: EASE.out, fill: 'backwards' });
      }
    }
    first.current = false;
  }, [lines]);

  return <>{lines.map((l) => (
    <span key={l.key} className="line" aria-hidden={l.leaving || undefined}
      ref={(el) => { if (el) els.current.set(l.key, el); else els.current.delete(l.key); }}>
      {l.leaving ? l.item.node : children}
    </span>
  ))}</>;
}
```

- [ ] **Step 6 : `NowPlaying.tsx`.**
  - Les emplacements sont toujours rendus : plus de `return` anticipé. Le titre de l'onglet ne change pas.

```tsx
  const req = current ? requesterOf(current.addedBy, me?.id) : null;
  const keys = req ? requesterKeys(req) : null;
  const vars = req?.kind === 'other' ? { name: req.name } : undefined;
  const q = current && keys?.quips ? quip(keys.quips, seedOf(current.url || current.title), vars) : null;
  const cer = useCeremony();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const key = current?.key || '';
  const plan = cer && cer.key === key ? cer.plan : null;

  // reflet d'or, une fois par cérémonie ; en vol, à l'atterrissage (landed relance l'effet)
  useEffect(() => {
    if (!cer || cer.key !== key || cer.plan.glintAt == null || (cer.mode === 'flight' && !cer.landed)) return;
    const tm = setTimeout(() => { if (titleRef.current) runGlint(titleRef.current); }, cer.mode === 'flight' ? 0 : cer.plan.glintAt);
    return () => clearTimeout(tm);
  }, [cer, key]);

  return (
    <div className="now-text" aria-hidden={current ? undefined : true}>
      <div className="kicker">{current && <>
        <span className="eq" aria-hidden="true"><i/><i/><i/></span>
        <span className="kk">{t(kickerKey({ paused, repeat }))}</span>
        {q && <span className="kq quip" aria-hidden="true">— {q}</span>}
      </>}</div>
      <h2 className="title-slot" id={NOW_TITLE_ID} title={current?.title} ref={titleRef}>
        <Swap k={key} plan={plan} delay={plan?.titleDelay ?? 0}>{song}</Swap>
      </h2>
      <p className="meta-slot">
        <Swap k={key} plan={plan} delay={plan?.metaDelay ?? 0}>
          {parsed?.artist && <><span className="artist">{parsed.artist}</span><span className="dot-sep" aria-hidden="true"/></>}
          {req && keys && <span className="by">
            {req.kind === 'mine' && <img className="seal" src={kingSealSrc(kingName(me))} alt="" width={20} height={20} decoding="async"/>}
            {t(keys.plain, vars)}
          </span>}
        </Swap>
      </p>
    </div>
  );
```

- [ ] **Step 7 : `Portal.tsx`, `Rose.tsx`, `Stage.tsx`, `Transport.tsx`, `usePlayer.ts`.**

`Portal.tsx` :
- ses commentaires « 3,5 s » deviennent « REVEAL_AFTER_PLAYING_MS » (valeur mesurée par la tâche 6) ;
- nouvelle prop `crown: Ceremony | null` ; `crownRef.current = crown` à chaque rendu ;
- une entrée de poster devient `{ id, leaving, mode: CrownMode | null, ms: number | null }` ;
- effet `[videoId]` : `const cr = crownRef.current` lu avant `setPosters` (dont la fonction tourne au rendu suivant) ; nouvelle entrée `mode: cr?.mode ?? null`, `ms: cr?.plan.posterMs || null` ;
- `export const decodedPosters = new Map<string, string>();` près de `noMaxres` : le préchargement du prochain poster y écrit `decodedPosters.set(nextId, im.src)` sur une vraie image décodée ;
- `Poster({ id, leaving, held, cut, ms })` ajoute ces attributs à son `<img>` :

```tsx
      data-held={held || undefined} data-cut={cut || undefined}
      style={ms ? ({ '--poster-ms': `${ms}ms` } as CSSProperties) : undefined}
```

- rendu : `const flying = crown?.mode === 'flight' && !crown.landed;` puis `<Poster … held={!p.leaving && p.mode === 'flight' && flying} cut={p.mode === 'flight'} ms={p.ms}/>`.

`Rose.tsx` (nouvelle prop `crown`) :
- au montage, `c.start()` attend le premier temps mort (spec §7) :

```tsx
    const start = () => { if (client.current === c) c.start(); };
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void };
    const idle = w.requestIdleCallback ? w.requestIdleCallback(start, { timeout: 1500 }) : window.setTimeout(start, 200);
    return () => { if (w.cancelIdleCallback) w.cancelIdleCallback(idle); else clearTimeout(idle); c.destroy(); client.current = null; };
```

- l'effet `[videoId]` devient :

```tsx
  const crownRef = useRef(crown); crownRef.current = crown;
  const shownId = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const c = client.current, was = shownId.current;
    shownId.current = videoId;
    if (!c) return;
    const plan = videoId ? crownRef.current?.plan ?? null : null;
    if (plan) c.hold(BUSY_MS);
    const fade = !videoId ? (was ? NIGHT_ROSE_FADE_MS : undefined) : plan?.roseFade;   // arrêt : la lune en 240 ms
    if (!plan?.roseAt) { void c.show(videoId, fade); return; }
    const tm = setTimeout(() => { void c.show(videoId, fade); }, plan.roseAt);             // en vol : à l'atterrissage
    return () => clearTimeout(tm);
  }, [videoId]);
```

`Stage.tsx` (sélecteur primitif, admis par le test des sélecteurs ; imports `useEffect`, `DUR`, `EASE`, `reducedMotion`, `startCoronation`, `useCeremony`) :

```tsx
  const currentKey = useStore((s) => s.player.current?.key ?? null);
  const ceremony = useCeremony();
  const crown = ceremony && ceremony.key === currentKey ? ceremony : null;
  useEffect(() => startCoronation(), []);
  // écart 10 de l'étape 2 : R qui change avec la scène passe en FLIP (420 ms), pas un redimensionnement de fenêtre
  const sceneAt = useRef(0), lastR = useRef(0), lastDay = useRef(day);
  useLayoutEffect(() => {
    if (lastDay.current !== day) { lastDay.current = day; sceneAt.current = performance.now(); }
    const R = layout?.R ?? 0, prev = lastR.current;
    lastR.current = R;
    const rose = stageRef.current?.querySelector<HTMLElement>('.rosace');
    if (!rose || !prev || !R || Math.abs(prev - R) < 1 || performance.now() - sceneAt.current > 400 || reducedMotion()) return;
    rose.animate([{ transform: `scale(${prev / R})` }, { transform: 'none' }], { duration: DUR.reveal, easing: EASE.out });
  }, [layout?.R, day]);
```

- Passer `crown={crown}` à `Rose` et `Portal`.
- Supprimer « l'étape 4 l'animera » du commentaire de `useNightFit`.

`Transport.tsx` :
- Suivant : `onClick={(e) => { kingOrders.mark(NEXT, e.detail === 0 ? 'key' : 'pointer', performance.now()); skip().catch(() => {}); }}` ;
- bulles : `tx('transport.skipTip' | 'restartTip' | 'repeatTip')`, qui remplacent `t('controls.*.tip')` (ces bulles citaient N, P, R).

`usePlayer.ts`, `playNow` (imports `reducedMotion` et `AFTER_CEREMONY_MS`) :

```ts
  const t0 = performance.now();
  const ok = await engine.dispatch({ kind: 'playAt', key, fromKey: v.current?.key ?? null });
  if (ok) {
    const wait = reducedMotion() ? 0 : Math.max(0, AFTER_CEREMONY_MS - (performance.now() - t0));   // après l'atterrissage
    setTimeout(() => say('toast.playNow', { vars: { title: songOf(x) } }), wait);
    await bestEffortVoiceJoin('play_at');
  }
```

- [ ] **Step 8 : feuilles de style.** Mettre à jour les en-têtes (sources, écarts ; « le flou vient avec la révérence » → pas de flou).
  - `stage.css` : `.ghost` = `styles.css` l. 273 à l'identique (`position: fixed; left: 0; top: 0; z-index: 80; pointer-events: none; overflow: hidden; opacity: 0; border-radius: 3px; background: #050404 center / cover no-repeat; transform-origin: 0 0; will-change: transform;`).
  - `now.css` :
    - `.title-slot` devient `display: grid; position: relative;` et garde sa police, sa marge, `min-height` et `padding`, sans `white-space`, `overflow` ni `text-overflow` ;
    - `.meta-slot` devient `display: grid` (marge, `min-height`, taille et couleur gardées) ;
    - le reflet = `styles.css` l. 322–326, police de `.glint-text` = `600 var(--title-size)/1.08 var(--f-title)`.

```css
.title-slot > .line, .meta-slot > .line { grid-area: 1 / 1; min-width: 0; }
.title-slot > .line { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta-slot > .line { display: flex; align-items: center; gap: 7px; white-space: nowrap; overflow: hidden; }
```

  - `portal.css` : Révérence d'après `styles.css` l. 258–260 ; mouvement réduit d'après l. 538–539. `.portal` garde ses déclarations, seule sa transition change. Pas de `var(--poster-ms, var(…))` dans une `transition` : le lecteur de `stage-contract` (`animated()`) coupe à la virgule du repli et y lirait « var(--dur-reveal)) » ; le repli est posé à part (`--poster-ms`), le style en ligne de `Poster` l'emporte.

```css
.portal { transition: opacity 500ms ease, transform 520ms var(--ease-out); }
.stage[data-scene=night] .portal { opacity: 0; transform: scale(.97); pointer-events: none; }
.video { position: relative; width: var(--vw); aspect-ratio: 16 / 9; overflow: hidden; background: #050404;
  transition: transform var(--spring-settle-dur) var(--spring-settle); }
.stage[data-paused=true] .video { transform: scale(.97); }
.video .poster { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; transform: scale(.96);
  --poster-ms: var(--dur-reveal); transition: opacity var(--poster-ms) var(--ease-out), transform var(--poster-ms) var(--ease-out); }
.video .poster[data-ready=true] { opacity: 1; transform: none; }
.video .poster[data-cut] { transition: none; }
.video .poster[data-held] { opacity: 0; }
.video .poster[data-leaving] { opacity: 0; transform: scale(1.03); transition: opacity 200ms ease, transform 260ms var(--ease-out); }
.video .poster.art { object-fit: contain; transform: none; }
@media (prefers-reduced-motion: reduce) {
  .portal { transition: opacity 500ms ease; }
  .stage[data-scene=night] .portal, .stage[data-paused=true] .video { transform: none; }
  .video { transition: none; }
  .video .poster, .video .poster[data-leaving] { transform: none; transition: opacity 200ms ease; }
  /* .posters, .paused-badge, .sync-btn et .sync-reset : lignes existantes, inchangées */
}
```

  - `rose.css` : `transform-origin: 50% 0;` sur `.rosace` (le FLIP part du haut, fixe).

- [ ] **Step 9 :** `npm test` → PASS, +7 ; `stage-contract` reste vert.
- [ ] **Step 10 :** rendre la main.

---

### Task 4 : la file (Le Sceau, sortie en cascade, clavier des listes, sceaux différés)

**Files:**
- Create: `services/web/src/components/Queue/seal.ts`, `src/hooks/useRoving.ts`, `tests/choreo-queue.test.mjs`
- Modify: `src/hooks/useFlip.ts`, `src/components/Queue/{QueuePanel,QueueRow}.tsx`, `queue.css`, `src/components/History/{HistoryPanel,HistoryRow,Suggestions}.tsx`, `useRequeue.ts`

**Interfaces:**
- Consumes :
  - tâche 2 : `sealBook`, `SEAL_STAMP_DELAY_MS`, `SEAL_FLIGHT_MS`, `boxOf`, `kingOrders`, `Via`, `listKey`, `moveBefore`, `reverseStagger` ;
  - tâche 1 : `speak`.
- Produces :

```ts
useFlip(listRef, items, keyOf, opts?: { exitDir?; exitStagger?: boolean; onEnter?: (key: string, el: HTMLElement) => boolean });
useRoving(listRef, keys, attr: 'key' | 'url', onAct: (act, key, index) => string | null | undefined)
  => { tabIndexOf(k): 0 | -1; onKeyDown; onFocus };
stampRow(li: HTMLElement, w: SealExpect): void;
requeue(item: HistoryItem, from?: HTMLElement | null): void;
useRequeueList(items, listRef) => { picked, onClick, onDoubleClick, onKeyDown, onFocus, tabIndexOf };
```

- [ ] **Step 1 : tests qui échouent** (`tests/choreo-queue.test.mjs`).

```js
// La file de l'étape 4 : Le Sceau, sortie en cascade, clavier des listes, sceaux différés.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { animated, assertKeys, read } from './_contract.mjs';

test('Le Sceau : sur un ajout du Roi seulement ; ressort --spring-seal ; sceau posé de 1.35 et −14°', () => {
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /sealBook\.take\(\{ url: item\.url, mine \}, performance\.now\(\)\)/);
  assert.match(panel, /requesterOf\(item\.addedBy, meRef\.current\?\.id\)\.kind === 'mine'/);
  const seal = read('src/components/Queue/seal.ts');
  for (const re of [/SPRING\.seal/, /scale\(1\.35\) rotate\(-14deg\)/, /li\.dataset\.sealed = ''/]) assert.match(seal, re);
  assert.ok(!/crown|couronne|greg-face/i.test(seal), 'le sceau est au Roi, rien de Greg');
});

test('arrêt : sortie de la dernière ligne à la première ; ordres notés avant « jouer maintenant »', () => {
  const flip = read('src/hooks/useFlip.ts');
  assert.match(flip, /reverseStagger\(/);
  assert.match(flip, /onEnter\?\.\(key, el\)/);
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /exitStagger: shown\.length === 0/);
  assert.match(panel, /kingOrders\.mark\(key, via, performance\.now\(\)\)/);
});

test('tabindex itinérant : un arrêt de Tab par liste, touches décrites, Alt+↑↓ annoncé', () => {
  assert.match(read('src/hooks/useRoving.ts'), /listKey\(e, i, keys\.length\)/);
  const panel = read('src/components/Queue/QueuePanel.tsx');
  for (const re of [/aria-describedby=\{keysId\}/, /tx\('queue\.keys'\)/, /moveBefore\(qKeys, key, act\.dir\)/, /speak\(t\('queue\.dnd\.liveMoved'/]) {
    assert.match(panel, re);
  }
  for (const f of ['Queue/QueueRow', 'History/HistoryRow']) {
    const row = read(`src/components/${f}.tsx`), n = (re) => (row.match(re) || []).length;
    assert.match(row, /tabIndex=\{tabIndex\}/, f);
    assert.ok(n(/<button /g) > 0 && n(/<button /g) === n(/<button type="button" tabIndex=\{-1\}/g), `${f} : bouton dans la tabulation`);
  }
  assert.match(read('src/components/History/useRequeue.ts'), /useRoving\(listRef, keys, 'url'/);
  for (const f of ['HistoryPanel', 'Suggestions']) assert.match(read(`src/components/History/${f}.tsx`), /tx\('history\.keys'\)/, f);
});

test('sceaux différés (loading="lazy") ; queue.css en transform et opacity ; fantôme fixe', () => {
  assert.match(read('src/components/Queue/QueueRow.tsx'), /<img src=\{sealSrc\} alt="" width=\{23\} height=\{23\} loading="lazy"/);
  const css = read('src/components/Queue/queue.css');
  for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), prop);
  assert.match(css, /\.seal-ghost\s*\{[^}]*position:\s*fixed/);
});

test('textes cités par la file et l’historique : chaque clé existe', () => {
  assert.ok(assertKeys(['Queue/QueuePanel.tsx', 'Queue/QueueRow.tsx', 'History/HistoryPanel.tsx', 'History/Suggestions.tsx']
    .map((f) => `src/components/${f}`)) >= 14);
});
```

- [ ] **Step 2 :** `npm test` → 4 FAIL (le 5e, garde-fou, passe déjà).

- [ ] **Step 3 : `useFlip.ts`.**
  - `const optsRef = useRef(opts); optsRef.current = opts;` remplace la référence `exitDir`.
  - Une ligne qui se met à sortir est posée hors du flux dans la boucle, comme aujourd'hui. Son animation est remise après la boucle, pour connaître son rang :

```ts
    const exits: { el: HTMLElement; key: string }[] = [];   // dans la boucle : exits.push({ el, key }) au lieu de el.animate
    const stagger = !!optsRef.current.exitStagger && !reduce && exits.length > 1;
    exits.forEach(({ el, key }, i) => {
      const dir = optsRef.current.exitDir?.(key) ?? 1;
      const kf = reduce ? [{ opacity: 1 }, { opacity: 0 }] : [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: `translateX(${12 * dir}px) scale(.98)` }];
      el.animate(kf, { duration: reduce ? 120 : DUR.exit, delay: stagger ? reverseStagger(i, exits.length) : 0, easing: EASE.out, fill: 'forwards' })
        .finished.then(() => onExited(key), () => onExited(key));
    });
```

  - Entrées : avant l'entrée par défaut, `if (optsRef.current.onEnter?.(key, el)) { entering++; continue; }`.
  - Documenter `exitStagger` et `onEnter` dans l'en-tête.

- [ ] **Step 4 : `components/Queue/seal.ts`.**

```ts
'use client';

import { EASE, SPRING, reducedMotion } from '@/lib/motion';
import { SEAL_FLIGHT_MS, SEAL_STAMP_DELAY_MS } from '@/lib/queue/seal';
import type { SealExpect } from '@/lib/queue/seal';
import { boxOf } from '@/lib/stage/coronation';

/**
 * Le Sceau (DESIGN §5, motion.md §6.5) : la ligne entre avec le seul rebond de l'app, le sceau du Roi se pose,
 * la pochette source vole jusqu'à elle. Mouvement réduit : fondu de 150 ms. data-sealed : pour la vérification.
 */
export function stampRow(li: HTMLElement, w: SealExpect): void {
  li.dataset.sealed = '';
  if (reducedMotion()) { li.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 150, easing: 'ease', fill: 'backwards' }); return; }
  const spring: KeyframeAnimationOptions = { duration: SPRING.seal.dur, easing: SPRING.seal.easing, fill: 'backwards' };
  li.animate([{ opacity: 0, transform: 'scale(.9)' }, { opacity: 1, transform: 'none' }], spring);
  li.querySelector<HTMLElement>('.thumb .seal')?.animate(
    [{ opacity: 0, transform: 'scale(1.35) rotate(-14deg)' }, { opacity: 1, transform: 'none' }], { ...spring, delay: SEAL_STAMP_DELAY_MS });
  const sc = li.closest<HTMLElement>('.scroller');
  const r = li.getBoundingClientRect(), c = sc?.getBoundingClientRect();
  if (sc && c && (r.bottom > c.bottom - 20 || r.top < c.top)) sc.scrollTo({ top: li.offsetTop - 40, behavior: 'smooth' });
  if (w.from && w.thumb) fly(w.from, w.thumb, li);
}
```

`fly(from, thumb, li)` porte `fly()` de `app.js` (lignes 1154–1166), en rAF :
- cible : `li.querySelector('.thumb > .im')` ; si `#pane-queue` est `aria-hidden="true"`, `#tab-queue .count` (`toCount`) ;
- `div.seal-ghost[aria-hidden]` de la taille de `from`, `backgroundImage` = `thumb`, ajouté à `body` ;
- cible cachée (`style.visibility = 'hidden'`) sauf `toCount` ;
- `animate` de `translate(from)` à `translate(to) scale(sx, sy)` (`0.4` et opacité 0 vers le compteur), `SEAL_FLIGHT_MS`, `EASE.drawer`, `fill: 'forwards'` ;
- à la fin (`finished.then(done, done)`), le fantôme est retiré et la cible revient (`removeProperty('visibility')`).

`queue.css` :
- `.seal-ghost { position: fixed; left: 0; top: 0; z-index: 80; pointer-events: none; border-radius: 3px; background: #050404 center / cover no-repeat; transform-origin: 0 0; }` ;
- dans le bloc de mouvement réduit : `.seal-ghost { display: none; }`.

- [ ] **Step 5 : `hooks/useRoving.ts`.**

```ts
'use client';

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import type { FocusEvent, KeyboardEvent, RefObject } from 'react';
import { listKey } from '@/lib/keys';
import type { ListAct } from '@/lib/keys';

/**
 * Tabindex itinérant (DESIGN §12.7) : un arrêt de Tab par liste ; ↑ ↓ Début Fin sans animation ; le reste va à `onAct`, qui rend
 * la ligne à focaliser (null : aucune ; undefined : la même), refocalisée après le rendu qui l'a déplacée. attr : data-key ou data-url.
 */
export function useRoving(listRef: RefObject<HTMLElement>, keys: readonly string[], attr: 'key' | 'url',
  onAct: (act: Exclude<ListAct, { kind: 'focus' }>, key: string, index: number) => string | null | undefined) {
  const [active, setActive] = useState<string | null>(null);
  const refocus = useRef<string | null>(null);
  const current = active != null && keys.includes(active) ? active : keys[0] ?? null;
  const rowOf = useCallback((k: string) =>
    listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-${attr}="${CSS.escape(k)}"]`) ?? null, [listRef, attr]);

  useLayoutEffect(() => {
    const k = refocus.current, el = k ? rowOf(k) : null;
    if (!el || el.dataset.leaving != null) return;   // pas encore là : au prochain rendu
    refocus.current = null;
    if (document.activeElement !== el) el.focus();
  });

  const onKeyDown = (e: KeyboardEvent<HTMLElement>): void => {
    const row = e.target as HTMLElement;
    if (!row.classList.contains('row') || row.parentElement !== listRef.current) return;   // pas depuis un bouton
    const k = row.dataset[attr] || '', i = keys.indexOf(k);
    const act = i < 0 ? null : listKey(e, i, keys.length);
    if (!act) return;
    e.preventDefault();
    if (act.kind === 'focus') { const to = keys[act.index]; setActive(to); rowOf(to)?.focus(); return; }
    const next = onAct(act, k, i), target = next === undefined ? k : next;
    if (target) { setActive(target); refocus.current = target; }
  };
  const onFocus = (e: FocusEvent<HTMLElement>): void => {
    const row = (e.target as HTMLElement).closest<HTMLElement>('.row');
    if (row && row.parentElement === listRef.current && row.dataset[attr]) setActive(row.dataset[attr] || null);
  };
  return { tabIndexOf: (k: string): 0 | -1 => (k === current ? 0 : -1), onKeyDown, onFocus };
}
```

- [ ] **Step 6 : `QueuePanel.tsx` et `QueueRow.tsx`.**

```tsx
  const keysId = useId();
  const qKeys = useMemo(() => queue.map(keyOf), [queue]);
  const shownKeys = useMemo(() => shown.map(keyOf), [shown]);
  const byKey = useRef(new Map<string, Track>()); byKey.current = new Map(queue.map((x) => [x.key, x]));
  const meRef = useRef(me); meRef.current = me;
  const onEnter = useCallback((key: string, el: HTMLElement) => {   // Le Sceau : l'ajout du Roi attendu
    const item = byKey.current.get(key);
    if (!item) return false;
    const mine = requesterOf(item.addedBy, meRef.current?.id).kind === 'mine';
    const w = sealBook.take({ url: item.url, mine }, performance.now());
    if (w) stampRow(el, w);
    return !!w;
  }, []);
  const { rendered, freeze } = useFlip(listRef, shown, keyOf, { exitDir, exitStagger: shown.length === 0, onEnter });
  const playNow = (key: string, via: Via) => {
    if (dedupeRef.current(key, performance.now())) return;
    kingOrders.mark(key, via, performance.now());
    settle();
    void playerActions.playNow(key);
  };
  const songOf = (x: Track) => parseTitle(x.title, x.artist).song || x.title;
  const roving = useRoving(listRef, shownKeys, 'key', (act, key, i) => {
    const near = shownKeys[i + 1] ?? shownKeys[i - 1] ?? null;
    if (act.kind === 'activate') { playNow(key, 'key'); return near; }
    if (act.kind === 'remove') { settle(); void playerActions.removeTrack(key); return near; }
    if (act.kind === 'next') { void playerActions.playNext(key); return undefined; }
    const before = moveBefore(qKeys, key, act.dir), item = queue[i];
    if (before === undefined || !item) return undefined;
    void playerActions.moveTrack(key, before).then((ok) => {
      if (ok) speak(t('queue.dnd.liveMoved', { title: songOf(item), pos: i + 1 + act.dir, total: queue.length }));
    });
    return undefined;
  });
```

- ▶ et double-clic appellent `playNow(key, 'pointer')`.
- Sceau du Roi décodé au premier temps mort : `useEffect` sur `[seal]` ; `requestIdleCallback` (repli `setTimeout` 1000), puis `new Image()`, `src = seal`, `decode().catch(() => {})`.
- `<ol>` : `aria-describedby={keysId}`, `onKeyDown={roving.onKeyDown}`, `onFocus={roving.onFocus}`. Après `</ol>` : `<p id={keysId} className="sr">{tx('queue.keys')}</p>`.
- Lignes : `tabIndex={leaving ? -1 : roving.tabIndexOf(key)}`.
- `QueueRow` : prop `tabIndex: 0 | -1` sur le `<li>` ; ses trois boutons commencent par `<button type="button" tabIndex={-1}` (écart 9). Le sceau devient `<img src={sealSrc} alt="" width={23} height={23} loading="lazy" decoding="async" draggable={false}/>`.

- [ ] **Step 7 : l'historique.**

`useRequeue.ts` :

```ts
export function requeue(item: HistoryItem, from?: HTMLElement | null): void {
  if (!item.url && !item.title) return;
  sealBook.expect({ url: item.url || null, from: from && !reducedMotion() ? boxOf(from) : null,
    thumb: from?.querySelector('img')?.currentSrc || item.thumb || null, at: performance.now() });
  playerActions.enqueue({ query: item.url || item.title, url: item.url, title: item.title, artist: item.artist,
    thumb: item.thumb, duration: item.duration, provider: item.provider || 'youtube' })
    .then((ok) => { if (!ok) sealBook.clear(); }, () => { sealBook.clear(); });   // erreur déjà annoncée par le Héraut
}
```

`useRequeueList(items, listRef: RefObject<HTMLOListElement>)`. `tests/queue-contract` exige exactement deux `add(it)` (« + » et double-clic) et aucun `requeue(it)` : `add` garde un seul argument et cherche lui-même la pochette source ; Entrée passe par `add(hit)`.

```ts
  const sourceOf = (url?: string): HTMLElement | null =>
    (url ? listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-url="${CSS.escape(url)}"] .thumb`) ?? null : null);
  const add = (item: HistoryItem) => { if (!once.current('add', performance.now())) requeue(item, sourceOf(item.url)); };
  // itemOf, onClick et onDoubleClick : inchangés (ce commentaire ne va pas dans le fichier)
  const keys = useMemo(() => items.map((x) => x.url || ''), [items]);
  const roving = useRoving(listRef, keys, 'url', (act, url) => {   // Entrée : remettre dans la file, depuis sa pochette
    const hit = act.kind === 'activate' ? items.find((x) => x.url === url) : undefined;
    if (hit) add(hit);
    return undefined;
  });
  return { picked, onClick, onDoubleClick, onKeyDown: roving.onKeyDown, onFocus: roving.onFocus, tabIndexOf: roving.tabIndexOf };
```

`HistoryRow` : prop `tabIndex: 0 | -1` sur le `<li>` ; « + » commence par `<button type="button" tabIndex={-1}`.

`HistoryPanel` et `Suggestions` :
- `listRef = useRef<HTMLOListElement>(null)`, `keysId = useId()`, `useRequeueList(items, listRef)` ;
- sur l'`<ol>` : `ref={listRef}`, `aria-describedby={keysId}`, `onKeyDown`, `onFocus` ;
- lignes : `tabIndex={list.tabIndexOf(it.url || '')}` ;
- après la liste : `<p id={keysId} className="sr">{tx('history.keys')}</p>`.

- [ ] **Step 8 :** `npm test` → PASS, +5 (`queue-panel` et `queue-contract` restent verts).
- [ ] **Step 9 :** rendre la main.

---

### Task 5 : clavier global, interrupteur des raccourcis, lien d'évitement, recherche

**Files:**
- Modify: `services/web/src/app/page.tsx`, `src/app/globals.css`, `src/components/Header/{AccountMenu,SearchBar}.tsx`, `header.css`
- Test: Create `tests/keyboard-contract.test.mjs`

**Interfaces:**
- Consumes :
  - tâche 2 : `shortcutFor`, `HELP_EVENT`, `SHORTCUTS_STORAGE_KEY`, `shortcutsOn`, `kingOrders`, `NEXT`, `watchReducedMotion`, `sealBook`, `boxOf` ;
  - tâche 1 : `KEYS`, `tx`, `speak`.
- Produces : `<html data-keys>`, `<html data-motion>`, l'événement `greg:help`, `a.skip-link`.

- [ ] **Step 1 : tests qui échouent** (`tests/keyboard-contract.test.mjs`).

```js
// Clavier de la page (étape 4) : un gestionnaire, interrupteur (WCAG 2.1.4), lien d'évitement, recherche.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';
const css = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '');

test('page : un gestionnaire (shortcutFor) ; plus de N / P / R ; « / » et « ? » ne s’écoutent plus ailleurs', () => {
  const page = read('src/app/page.tsx');
  for (const re of [/if \(ev\.defaultPrevented\) return;/, /shortcutFor\(ev, \{/, /kingOrders\.mark\(NEXT, 'key', performance\.now\(\)\)/,
    /watchReducedMotion\(/, /getAttribute\('aria-hidden'\) !== 'true'/]) assert.match(page, re);
  assert.ok(page.includes('playerActions.togglePause()'));
  assert.ok(!/ev\.key === '[npr]'/.test(page));
  assert.ok(!read('src/components/Header/SearchBar.tsx').includes("e.key !== '/'"));
  assert.ok(!read('src/components/Header/AccountMenu.tsx').includes("e.key !== '?'"));
});

test('interrupteur : role=switch, mémorisé, reflété sur <html data-keys>, annoncé ; liste KEYS', () => {
  const menu = read('src/components/Header/AccountMenu.tsx');
  for (const re of [/SHORTCUTS_STORAGE_KEY/, /document\.documentElement\.dataset\.keys = keys \? 'on' : 'off'/, /tx\('keys\.toggle'\)/,
    /speak\(tx\(next \? 'keys\.on' : 'keys\.off'\)\)/, /addEventListener\(HELP_EVENT/, /KEYS\.map\(/]) assert.match(menu, re);
  assert.match(read('src/app/page.tsx'), /dataset\.keys !== 'off'/);
  assert.match(css('src/components/Header/header.css'), /:root\[data-keys=off\] \.kbd\s*\{\s*display:\s*none;?\s*\}/);
});

test('« Aller à la file » avant l’en-tête, visible au focus, en transform', () => {
  const page = read('src/app/page.tsx'), at = page.indexOf('className="skip-link"');
  assert.ok(at > 0 && at < page.indexOf('<Header'));
  assert.match(page, /tx\('a11y\.skipToQueue'\)/);
  const g = css('src/app/globals.css');
  assert.match(g, /\.skip-link:focus-visible\s*\{\s*transform:/);
  assert.match(g, /\.skip-link\s*\{[^}]*transition:\s*transform/);
});

test('recherche : sceau attendu noté avant l’ajout, oublié sur échec, pochette source transmise', () => {
  const sb = read('src/components/Header/SearchBar.tsx');
  for (const re of [/sealBook\.expect\(/, /sealBook\.clear\(\)/, /pick\(s, e\.currentTarget\.querySelector\('\.th'\)\)/]) assert.match(sb, re);
});
```

- [ ] **Step 2 :** `npm test` → 4 FAIL.

- [ ] **Step 3 : `page.tsx`.** Remplacer l'effet clavier (l'import `isShortcutIgnored` part) et ajouter :

```tsx
const SEARCH = '.top .field input';
const FIELD = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
const CONTROL = 'button, a[href], [role="button"], [role="switch"], [role="tab"], [role="slider"], [role="option"]';
/** « Aller à la file » : la ligne active de la file, sinon l'onglet File (volet Historique affiché : la ligne, cachée, refuserait le focus). */
function focusQueue(): void {
  const shown = document.getElementById('pane-queue')?.getAttribute('aria-hidden') !== 'true';
  (shown && document.querySelector<HTMLElement>('.qcontent > .qlist > .row[tabindex="0"]') || document.getElementById('tab-queue'))?.focus();
}
  // dans Home :
  useEffect(() => watchReducedMotion((r) => { document.documentElement.dataset.motion = r ? 'reduced' : 'full'; }), []);
  useEffect(() => {
    const handler = (ev: KeyboardEvent) => {
      if (ev.defaultPrevented) return;   // déjà traitée : onglets (Maj+→ y changerait aussi de titre), listes, popovers
      const el = ev.target instanceof Element ? ev.target : null, s = useStore.getState();
      const act = shortcutFor(ev, {
        enabled: document.documentElement.dataset.keys !== 'off', loggedIn: !!s.me && !!s.guildId,
        inField: !!el?.closest(FIELD), inPopover: !!el?.closest('.pop[data-open="true"]'), onRow: !!el?.closest('.qlist > .row'),
        onControl: !!el?.closest(CONTROL), dragging: document.body.classList.contains('is-dragging'),
      });
      if (!act) return;
      const search = document.querySelector<HTMLInputElement>(SEARCH);
      if (act === 'type') { search?.focus(); return; }   // focus pendant keydown : la lettre tombe dans le champ
      ev.preventDefault();
      if (act === 'search') search?.focus();
      else if (act === 'help') document.dispatchEvent(new Event(HELP_EVENT));
      else if (act === 'togglePause') {
        if (!s.player.current) return;
        void playerActions.togglePause();
        speak(tx(s.player.paused ? 'a11y.resumed' : 'a11y.paused'));
      } else if (act === 'skip') { kingOrders.mark(NEXT, 'key', performance.now()); void playerActions.skip(); }
      else void playerActions.restartTrack();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);
```

Avant `<Header ready={booted}/>` :

```tsx
      {booted && me && <a className="skip-link" href="#pane-queue" onClick={(e) => { e.preventDefault(); focusQueue(); }}>{tx('a11y.skipToQueue')}</a>}
```

`globals.css`, dans `@layer components` près de `.sr`. C'est la règle `.skip` de `styles.css` (l. 83–84), renommée :

```css
  .skip-link { position: fixed; left: 12px; top: -60px; z-index: 200; padding: 10px 14px; border-radius: 6px;
    background: var(--os); color: var(--nuit); font-weight: 700; transition: transform var(--dur-micro) var(--ease-out); }
  .skip-link:focus-visible { transform: translateY(72px); }
  @media (prefers-reduced-motion: reduce) { .skip-link { transition: none; } }
```

- [ ] **Step 4 : `AccountMenu.tsx`.**
  - Retirer : l'effet « ? », `isShortcutIgnored`, `SHORTCUTS` et `deck` s'il n'est plus lu.
  - Ajouter :

```tsx
function readKeys(): boolean { try { return shortcutsOn(localStorage.getItem(SHORTCUTS_STORAGE_KEY)); } catch { return true; } }
  const keysId = useId();
  const [keys, setKeys] = useState(true);
  useEffect(() => { setKeys(readKeys()); }, []);
  useEffect(() => { document.documentElement.dataset.keys = keys ? 'on' : 'off'; }, [keys]);
  const toggleKeys = () => {
    const next = !keys;
    setKeys(next);
    try { localStorage.setItem(SHORTCUTS_STORAGE_KEY, next ? 'on' : 'off'); } catch {}
    speak(tx(next ? 'keys.on' : 'keys.off'));
  };
  useEffect(() => {   // « ? » (page.tsx) ouvre ce menu, qui porte la liste des raccourcis
    const open = () => setOpen(true);
    document.addEventListener(HELP_EVENT, open);
    return () => document.removeEventListener(HELP_EVENT, open);
  }, [setOpen]);
```

  - Après l'interrupteur des répliques, un second interrupteur au même balisage :

```tsx
        <button type="button" role="switch" aria-checked={keys} className="pop-item" onClick={toggleKeys}
          aria-labelledby={`${keysId}-l`} aria-describedby={`${keysId}-d`}>
          <span className="two"><b id={`${keysId}-l`}>{tx('keys.toggle')}</b><small id={`${keysId}-d`}>{tx('keys.toggleHelp')}</small></span>
          <span className="switch" aria-hidden="true"/>
        </button>
```

  - La liste devient `{KEYS.map(([key, label]) => (<Fragment key={key}><dt><kbd>{key}</kbd></dt><dd>{label}</dd></Fragment>))}`.

- [ ] **Step 5 : `SearchBar.tsx` et `header.css`.**
  - Retirer l'effet « / » et `isShortcutIgnored`. Importer `sealBook`, `boxOf` et `reducedMotion`.

```tsx
  const expectSeal = (url: string | null, from: Element | null | undefined, thumb: string | null) =>
    sealBook.expect({ url, from: from && !reducedMotion() ? boxOf(from) : null, thumb, at: performance.now() });
```

  - `submit` : `sealBook.clear();` en tête du `catch`, et aussi quand `enqueue` rend `false` (rien n'est parti).
  - `pick(sug, from?: Element | null)` appelle d'abord `expectSeal(url || null, from, sug.thumb || sug.thumbnail || null)`.
  - `submitTyped` : `if (kind === 'none' || kind === 'video') expectSeal(kind === 'video' ? text : null, null, null);` avant `submit`. Une playlist n'a pas de Sceau.
  - Suggestions : `onClick={(e) => pick(s, e.currentTarget.querySelector('.th'))}`. À Entrée : `pick(sugs[idx], document.getElementById(optId(idx))?.querySelector('.th'))`.
  - `header.css` : `:root[data-keys=off] .kbd { display: none; }`.

- [ ] **Step 6 :** `npm test` → PASS, +4 (`player-contract` reste vert).
- [ ] **Step 7 :** rendre la main.

---

### Task 6 : YouTube, habillage au lever du poster et sous-titres de l'iframe muette

**Files:**
- Utilise (hors dépôt, déjà écrits) : `S\etape4\yt-probe.html`, `S\etape4\yt_probe.py`
- Modify: `services/web/src/lib/stage/cover.ts`, `src/hooks/useYouTubePlayer.ts`
- Test: `tests/cover.test.mjs`

**Interfaces:**
- Produces :
  - `CaptionsApi` et `muteCaptions(p)` (`cover.ts`) ;
  - `REVEAL_AFTER_PLAYING_MS` mesuré, dans [3500, 5000], multiple de 250 ;
  - `YTPlayer` étend `CaptionsApi`.

- [ ] **Step 1 : la sonde.** Les deux fichiers sont déjà écrits par ce plan ; les relire avant de lancer.
  - `S\etape4\yt-probe.html` : les `playerVars` de `useYouTubePlayer.ts` ; `?cc=mute` applique `muteCaptions` (Step 5) à `onApiChange` et à PLAYING ; `?lang=fr` ajoute `cc_lang_pref` et `hl`.
  - `S\etape4\yt_probe.py` : pour les variantes `base`, `lang` et `mute`, environ 26 captures du lecteur en 6,5 s après PLAYING, puis après un `seekTo(+0,5 s)`, dans `S\etape4\yt-<variante>\{play,seek}-<ms>.png`. Il imprime aussi les derniers événements, `getOptions()` et `getOption('captions', 'track')`.
  - **Le compléter avant de lancer** (fichier hors dépôt) :
    - une phase `resume`, car l'app réarme le poster à chaque reprise : `pauseVideo()`, 1,5 s, `playVideo()`, puis `frames(page, out, "resume", t0)`, où `t0` est l'instant du premier état 1 de `__log` postérieur à l'appel ;
    - une planche par phase avec PIL (présent dans `S\venv`) : les 26 captures réduites à 320 px, chacune étiquetée de son instant, dans `yt-<variante>\<phase>.png`. On lit ces 9 planches, pas les 234 captures.

```bash
cd "$S/etape4" && ("$S/venv/Scripts/python.exe" -m http.server 3210 >/dev/null 2>&1 & echo $! > server.pid)
PYTHONIOENCODING=utf-8 "$S/venv/Scripts/python.exe" yt_probe.py; kill "$(cat server.pid)"
```

- [ ] **Step 2 : décider en lisant les planches** (outil Read ; une capture seule en cas de doute).
  - **Habillage.** `t_play` est l'instant de la dernière image `play` où le bandeau du titre YouTube ou son logo se voit encore, même à demi, sur les trois variantes ; `t_seek` et `t_resume`, de même.
    - `REVEAL_AFTER_PLAYING_MS = min(5000, max(3500, ceil((max(t_play, t_seek, t_resume) + 250) / 250) * 250))`. Au-delà de 5000, garder 5000 et le signaler.
    - Aucun paramètre documenté ne masque ce bandeau (`showinfo` et `modestbranding` sont retirés, `controls: 0` déjà en place). On décale seulement le lever, sans toucher à la marque.
  - **Sous-titres.** À l'étape 2, `base` et `lang` montraient une piste automatique.
    - Si `mute` n'en montre aucune entre 1 et 6,5 s et que `track` vaut `{}`, garder `muteCaptions`.
    - Sinon, le garder quand même (sans effet de bord) et le signaler : rien d'autre n'atteint une iframe d'une autre origine.
  - Noter la date, `t_play`, `t_seek`, `t_resume` et le résultat de `mute` dans le compte rendu et dans le commentaire de la constante.

- [ ] **Step 3 : tests qui échouent** (`tests/cover.test.mjs`).
  - Importer `muteCaptions` ; ajouter `const R = REVEAL_AFTER_PLAYING_MS;`.
  - Retirer `assert.equal(REVEAL_AFTER_PLAYING_MS, 3500);` (l. 13), puis : l. 16 `revealIn(armed, 2000), 2500` → `R - 1000` ; l. 19 et 32 `now: 4500` → `1000 + R` ; l. 26 `now: 4600` → `1000 + R + 100` ; l. 28 `PLAYING, 5000` → `1000 + R + 500` ; l. 55 `now: 23500` → `20000 + R` ; l. 56 `PLAYING, 24000` → `20000 + R + 500`.
  - Les instants « trop tôt » (3000) restent valables ; le titre du premier test dit « +REVEAL_AFTER_PLAYING_MS » au lieu de « +3,5 s ».

```js
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
```

- [ ] **Step 4 :** `npm test` → FAIL (`muteCaptions` absent).

- [ ] **Step 5 : implémenter.**
  - `cover.ts` :
    - `REVEAL_AFTER_PLAYING_MS` prend la valeur mesurée, avec le commentaire `// habillage YouTube replié vers t_play (départ), t_seek (saut), t_resume (reprise) ms ; sonde du JJ/MM/2026 (yt_probe.py)` ;
    - dans l'en-tête, « 3,5 s » devient « REVEAL_AFTER_PLAYING_MS » ;
    - ajouter :

```ts
/**
 * Iframe muette : YouTube y montre une piste automatique malgré cc_load_policy: 0 (écart 5 de l'étape 2).
 * setOption('captions', 'track', {}) vide la piste ; unloadModule (non documenté) retire le module s'il existe.
 */
export type CaptionsApi = { setOption?(module: string, option: string, value: unknown): void; unloadModule?(module: string): void };
export function muteCaptions(p: CaptionsApi): void {
  for (const m of ['captions', 'cc']) {
    try { p.setOption?.(m, 'track', {}); } catch {}
    try { p.unloadModule?.(m); } catch {}
  }
}
```

  - `useYouTubePlayer.ts` :
    - `export type YTPlayer = CaptionsApi & { … }` ;
    - remplacer le commentaire « Sous-titres (écart 5 du plan) … à trancher à l'étape 4 » par `// Sous-titres : muteCaptions à chaque module chargé et à chaque départ (cover.ts).` ;
    - dans `events` :

```ts
          onApiChange: () => { if (alive && created) muteCaptions(created); },
          onStateChange: (e: { data: number }) => {
            if (!alive) return;
            if (e.data === 1 && created) muteCaptions(created);   // le module revient avec chaque vidéo
            h.current.onState(e.data);
          },
```

- [ ] **Step 6 :** `npm test` → PASS, +2 ; 284 avec les tâches 1 et 2.
- [ ] **Step 7 :** rendre la main, avec les mesures.

---

### Task 7 : vérification dans le navigateur, mesure de performance, commit

**Files:**
- Utilise (hors dépôt, déjà écrits) : `S\etape4\verif.py`, `S\etape4\pacing_app.py`
- Modify : seulement pour corriger ce que la vérification trouve, dans le fichier de la tâche qui le possède (un test d'abord quand il se prête à un test pur ou de contrat).

- [ ] **Step 1 : contrôles de la vague B** (orchestrateur) :
  - `npm test`, puis `GREG_TEST_TRANSPILE=1 npm test` : **300** tests, 0 échec ;
  - `npx tsc --noEmit`, puis `npx next build`.

- [ ] **Step 2 : les scripts, déjà écrits par ce plan.** Les relire avant de lancer ; les compléter si une correction ajoute un comportement.
  - **`S\etape4\verif.py <dossier>`** attend `:3100`, pilote Chrome à 1440 × 900, affiche `OK` ou `ÉCHEC` par contrôle puis « Tout est vert. » (code 0) : pierre et sceaux différés ; vol, Héraut après l'atterrissage, légendes, Maj+→ sans vol ; Révérence ; saisie directe, « / », « ? », interrupteur ; listes (un `tabindex="0"`, ↓, Alt+↓ annoncé) ; Sceau ; mouvement réduit en direct ; arrêt → nuit ; 1280 × 720 et 390 × 844 ; déconnecté ; console. Captures : `1440x900`, `couronnement`, `reverence`, `nuit`, `1280x720`, `390x844`, `deconnecte`.
  - **À y ajouter** : Tab depuis la ligne active sort de la file (aucun bouton de ligne) ; le premier Tab atteint « Aller à la file », dont Entrée focalise la ligne active.
  - **`S\etape4\pacing_app.py [essais]`** reprend `P\research\motion-lab\pacing.py` (métriques CDP), à 1× puis 4× CPU, en alternant vol (double-clic, 2e ligne), Suivant cliqué et Maj+→. Pendant 1,5 s : tâches longues, LoAF (avec leurs scripts), temps du fil principal. Il écrit `S\etape4\perf.json` ; code 0 si aucun essai à 1× n'a de tâche longue.

- [ ] **Step 3 : lancer**, puis arrêter les serveurs quel que soit le résultat.

```bash
node "$S/uimock/mock_api.js" > "$S/etape4/mock.log" 2>&1 & echo $! > "$S/etape4/mock.pid"
(cd services/web && npx next build && (npx next start -p 3100 > "$S/etape4/next.log" 2>&1 & echo $! > "$S/etape4/next.pid"))
PYTHONIOENCODING=utf-8 "$S/venv/Scripts/python.exe" "$S/etape4/verif.py" "$S/etape4/shots"
PYTHONIOENCODING=utf-8 "$S/venv/Scripts/python.exe" "$S/etape4/pacing_app.py" 6
kill "$(cat "$S/etape4/next.pid")" "$(cat "$S/etape4/mock.pid")"   # sinon : taskkill //F //T //PID <pid> ; ports 3100 et 3999 libres
```

Résultats attendus :
- `verif.py` : toutes les lignes `OK`, puis « Tout est vert. » ;
- `pacing_app.py` : « OK : aucune tâche longue à 1× », et `perf.json`. Les chiffres à 4× sont à comparer à DESIGN §12.8 et à donner dans le compte rendu.

- [ ] **Step 4 : si la mesure échoue**, lire les `loaf[].s` fautifs et corriger dans cet ordre (DESIGN §8), en remesurant à chaque fois :
  1. `QueueRow` et `HistoryRow` mémoïsées sans prop recréée ; `Stage` rendue aux seules cérémonies ;
  2. `--lumiere` et `--lumiere-rgb` posées sur `.page-shell` (2e argument de `setLumiere`, dans `swap`), défaut gardé sur `:root` ;
  3. « jouer maintenant » : décoder `posterUrl(id)` pendant le vol et l'inscrire dans `decodedPosters`.

- [ ] **Step 5 : relire les captures** (`S\etape4\shots`) : `couronnement` sans double exposition ; `reverence` inclinée, badge lisible ; `nuit` : rose entière, couronne du Roi dans l'oculus, « Aucune corvée » ; `390x844` en une colonne, rien ne déborde, Héraut en bas au centre ; `1280x720` sans défilement ; `deconnecte` : Greg en bonnet, formule de valet, **aucune couronne sur Greg**.

- [ ] **Step 6 : critères d'acceptation** (spec §8), sur la même instance :
  - coller un lien de playlist ; glisser ; retirer puis annuler ; mettre en pause ; arrêter : sans à-coup ni erreur de console ;
  - casting respecté ; les tests `copy`, `copy-extra`, `stage-copy`, `queue-panel` et `choreo-queue` le gardent.

- [ ] **Step 7 : commit et push** (orchestrateur). Vérifier que `git status` ne met ni `tsconfig.json` ni `next-env.d.ts` dans l'index.

```bash
git add services/web/src services/web/tests docs/superpowers/plans/2026-09-26-web-nuit-gothique-etape-4.md
git commit -m "feat(web): chorégraphies Nuit gothique, clavier complet et finitions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Puis `git archive --format=tar HEAD | docker build -f services/web/Dockerfile -` (démon arrêté : le noter ; `GREG_TEST_TRANSPILE=1 npm test` et `next build` couvrent alors Node 20).

## Auto-relecture

- **Couverture** (tâches). Couronnement 2, 3 (FLIP : `useFlip`) ; Sceau 2, 4, 5 ; Révérence 3 ; arrêt → nuit 3, 4 ; clavier 2, 4, 5 (Ctrl+Z : Héraut) ; interrupteur 5 ; accessibilité 1, 4, 5 ; mouvement réduit 2, 3, 5 ; une colonne 7 ; pierre 3, sceaux 4 ; performance 7 ; demandes de Paul 1, 6.
- **Noms croisés.** `kingOrders.mark(target, via, now)` / `take(key, prevNext, now)` : tâches 2 à 5. `sealBook.expect / take / clear` : 2, 4, 5. `speak` : 1, 3 à 5. `HELP_EVENT` : 2, 5. `KEYS` : 1, 5. `decodedPosters` : 3. `useRoving(…, 'key' | 'url')` : 4.
- **Tests existants gardés.** `queue-panel` et `queue-contract` (aucun « crown », deux `add(it)`), `stage-contract` (`animated()`, sélecteurs primitifs), `player-contract`.
- **Comptes.** 258 + 4 + 20 + 2 = 284 ; + 7 + 5 + 4 = 300.
