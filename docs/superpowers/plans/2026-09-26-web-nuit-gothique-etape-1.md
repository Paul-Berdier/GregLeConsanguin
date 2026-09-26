# Nuit gothique, étape 1 : fondations, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** poser les fondations de la direction « Nuit gothique » dans `services/web`. Ça couvre :
- les assets et licences ;
- les tokens de couleur, polices et mouvement ;
- le module de textes « valet du Roi » ;
- le découpage de `page.tsx` à comportement identique ;
- le nouvel en-tête.

**Architecture:** Next.js 14 (App Router, React 18, Tailwind 3). Aucune nouvelle dépendance npm.
- Tokens en variables CSS sur `:root`, reprises à la lettre du prototype.
- Polices chargées avec `next/font/local`.
- Les anciennes classes Tailwind (`surface`, `txt`, `accent`…) deviennent des alias vers les nouveaux tokens, pour que le reste de l'interface change de peau sans être réécrit avant les étapes 2 et 3.
- Fonctions pures dans `src/lib/*` et `src/theme/*`, testées avec `node:test` via `tests/_loadTs.mjs`.

**Tech Stack:** Next.js 14, React 18, TypeScript 5, Tailwind 3, `node:test`, Python fontTools (sous-ensembles de polices), Chrome headless (captures).

**Spec:** `docs/superpowers/specs/2026-09-26-web-nuit-gothique-design.md`

## Global Constraints

- **Ressources.** `P` = `C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad\design`.
  - Prototype de référence : `P\proto-gothique`. Son `DESIGN.md` et ses sources (`work\refine\src\styles.css`, `body.html`, `app.js`, `wordmark.html`) font foi pour les valeurs.
  - Deck de textes : `P\research\copy-v2.json`, guide `P\research\persona-v2.md`.
- **Casting.** Le Roi, c'est l'utilisateur connecté ; Greg est son valet. Aucune couronne, aucun sceau royal, aucun « Rex » attribué à Greg. La couronne va sur l'avatar de l'utilisateur.
- **Mouvement.**
  - Animer uniquement `transform` et `opacity`, jamais `transition: all`.
  - Survols derrière `@media (hover:hover) and (pointer:fine)`.
  - `prefers-reduced-motion` respecté.
- **Textes.** En français, depuis le deck v2 (Greg vouvoie le Roi). Libellés neutres ; les répliques sont en plus et peuvent être désactivées.
- **Compatibilité.** Pas de régression : les 45 tests web existants restent verts, et `tsc --noEmit` et `next build` passent.
- **Git.** Ne pas committer `services/web/tsconfig.json` ni `services/web/next-env.d.ts`, que le serveur de dev modifie. Les commits sont faits par l'orchestrateur, pas par les agents.

---

### Task 1 : Assets et licences dans `public/`

**Files:**
- Create: `services/web/public/gothique/` (images), `services/web/public/fonts/` (woff2), `services/web/public/licenses/` (OFL et `LICENSES.md`)
- Create: `services/web/scripts/subset-fonts.py`, qui régénère les sous-ensembles avec U+202F
- Test: `services/web/tests/assets.test.mjs`

**Interfaces:**
- Produces, avec des chemins publics stables :
  - `/gothique/stone-rose-2048.webp`, `/gothique/stone-frame-640.webp`
  - `/gothique/crown-320.webp`, `/gothique/crown-turn-128.avif`, `/gothique/crown-still-128.avif`, `/gothique/crown-badge-64.webp`, `/gothique/crown-badge-128.webp`
  - `/gothique/grain-256.webp`
  - `/gothique/greg-face-96.webp`, `/gothique/greg-face-192.webp`
  - `/gothique/seals/king-seal-{A..Z}.webp` (256 px)
  - `/gothique/minstrels-manesse-line.webp`
  - `/fonts/GrenzeGotisch-VF.woff2`, `/fonts/Grenze-VF.woff2`, `/fonts/AlegreyaSans-{Regular,Medium,Bold,ExtraBold}.woff2`, `/fonts/Alegreya-Italic-VF.woff2`

- [ ] **Step 1: Write the failing test** (`tests/assets.test.mjs`)

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const pub = (p) => fileURLToPath(new URL(`../public/${p}`, import.meta.url));
const REQUIRED = [
  'gothique/stone-rose-2048.webp', 'gothique/stone-frame-640.webp', 'gothique/crown-320.webp',
  'gothique/crown-turn-128.avif', 'gothique/crown-still-128.avif', 'gothique/crown-badge-64.webp',
  'gothique/crown-badge-128.webp', 'gothique/grain-256.webp', 'gothique/greg-face-96.webp',
  'gothique/greg-face-192.webp', 'gothique/minstrels-manesse-line.webp',
  'fonts/GrenzeGotisch-VF.woff2', 'fonts/Grenze-VF.woff2', 'fonts/AlegreyaSans-Regular.woff2',
  'fonts/AlegreyaSans-Medium.woff2', 'fonts/AlegreyaSans-Bold.woff2', 'fonts/AlegreyaSans-ExtraBold.woff2',
  'fonts/Alegreya-Italic-VF.woff2', 'licenses/LICENSES.md',
];
test('assets Nuit gothique présents et non vides', () => {
  for (const p of REQUIRED) {
    assert.ok(existsSync(pub(p)), `manquant : ${p}`);
    assert.ok(statSync(pub(p)).size > 0, `vide : ${p}`);
  }
});
test('un sceau royal par initiale A–Z', () => {
  for (const c of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') assert.ok(existsSync(pub(`gothique/seals/king-seal-${c}.webp`)), c);
});
test('poids total raisonnable (< 1,6 Mo hors sceaux)', () => {
  const total = REQUIRED.reduce((s, p) => s + statSync(pub(p)).size, 0);
  assert.ok(total < 1_600_000, `${total} octets`);
});
```

- [ ] **Step 2: Run** `cd services/web && npm test`. Expected : FAIL (fichiers manquants).
- [ ] **Step 3: Copier les assets.**
  - Images depuis `P\proto-gothique\assets\img` et `P\assets\3d\royal` : `crown_badge@64/128.webp` devient `crown-badge-64/128.webp`, `king_seal_X.webp` devient `seals/king-seal-X.webp`.
  - Licences : `P\assets\LICENSES.md` (sections utilisées uniquement) et les OFL de `P\proto-gothique\assets\licenses` vont dans `public/licenses/`.
- [ ] **Step 4: Régénérer les polices avec U+202F** : `scripts/subset-fonts.py`, `pyftsubset` depuis les fontes complètes de `P\assets\fonts`, qu'on retélécharge depuis Google Fonts si elles manquent.
  - Unicodes à garder : `U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2190-2193,U+2212,U+2215,U+202F,U+00A0`.
  - Features à garder : `--layout-features='*'`.
  - Vérifier ensuite avec fontTools que `0x202F` est dans la cmap de chaque woff2.
- [ ] **Step 5: Run** `npm test`. Expected : PASS.

### Task 2 : Tokens (couleur, mouvement), polices, alias Tailwind

**Files:**
- Create: `services/web/src/theme/tokens.css`, qui reprend les tokens `:root` de `styles.css` lignes 14–59
- Create: `services/web/src/theme/fonts.ts` (`next/font/local`)
- Create: `services/web/src/lib/color.ts`, test `services/web/tests/color.test.mjs`
- Modify: `services/web/src/app/globals.css` : importe `tokens.css`, fond `--nuit`, base `body`, focus doré, `.plaque`
- Modify: `services/web/src/app/layout.tsx` : classes des polices sur `<html>`
- Modify: `services/web/tailwind.config.js` : couleurs vers les tokens, alias legacy

**Interfaces:**
- Produces, en CSS :
  - `--nuit --nef --voute --voute-2 --os --os-2 --cendre --cendre-2 --or --gueules --plomb --pierre-rgb --hair --hair-2 --lumiere --lumiere-rgb` ;
  - `--f-display --f-title --f-ui --f-voice` ;
  - `--dur-*`, `--ease-*`, `--spring-*` et `--spring-*-dur`, avec les valeurs exactes du prototype ;
  - la classe `.plaque`.
- Produces, en TS :
  - `fonts.ts` exporte `fontVariables: string`, les classes à poser sur `<html>` ;
  - `color.ts` exporte `hexToRgb(hex): [number, number, number]`, `relLuminance(rgb): number` et `contrast(a: string, b: string): number` (WCAG 2.x).

- [ ] **Step 1: Write the failing test** (`tests/color.test.mjs`)

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { contrast, hexToRgb } = await loadTs('../src/lib/color.ts');
test('hexToRgb', () => { assert.deepEqual(hexToRgb('#0b0908'), [11, 9, 8]); });
test('contrastes des tokens de texte (DESIGN §2)', () => {
  const nef = '#14110e';
  assert.ok(contrast('#efe7d8', nef) >= 15.0, 'os/nef');
  assert.ok(contrast('#9b9183', nef) >= 6.0, 'cendre/nef');
  assert.ok(contrast('#cfa75a', nef) >= 8.0, 'or/nef');
  assert.ok(contrast('#e0583e', nef) >= 5.0, 'gueules/nef');
  assert.ok(contrast('#9b9183', '#27221c') >= 4.5, 'cendre/voute-2');
});
```

- [ ] **Step 2: Run** `npm test`. Expected : FAIL (module absent).
- [ ] **Step 3: Implement `src/lib/color.ts`**

```ts
export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  const v = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16)) as [number, number, number];
}
export function relLuminance([r, g, b]: [number, number, number]): number {
  const f = (c: number) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
export function contrast(a: string, b: string): number {
  const [la, lb] = [relLuminance(hexToRgb(a)), relLuminance(hexToRgb(b))].sort((x, y) => y - x);
  return (la + 0.05) / (lb + 0.05);
}
```

- [ ] **Step 4: Tokens et polices.**
  - `tokens.css` : copier à la lettre le bloc `:root{…}` de `P\proto-gothique\work\refine\src\styles.css` (lignes 14–59, jusqu'à `--panel-w`), sans les variables de scène `--R --vw --f --crown --heart`, qui arrivent à l'étape 2. Ajouter :

```css
@media (prefers-reduced-motion: reduce){:root{--dur-flight:0ms;--dur-glint:0ms;--stagger:0ms}}
```

  - `fonts.ts` : un `localFont` par famille, pointant sur les fichiers `public/fonts/*`. Pour `next/font/local`, les chemins sont relatifs au fichier : utiliser `../../public/fonts/…`. Chaque famille reçoit sa `variable` :
    - `--font-grenze-gotisch`
    - `--font-grenze`
    - `--font-alegreya-sans`, avec les poids 400/500/700/800
    - `--font-alegreya-italic`
  - Dans `tokens.css`, `--f-display: var(--font-grenze-gotisch), "Grenze", serif;` et de même pour les trois autres rôles.
- [ ] **Step 5: `globals.css`.**
  - Garder les directives `@tailwind`.
  - Remplacer l'import Google Fonts Sora/DM Sans par `@import '../theme/tokens.css';`.
  - `body` : fond `var(--nuit)`, couleur `var(--os)`, `font: 400 15.5px/1.42 var(--f-ui)`, `font-synthesis:none`, `-webkit-font-smoothing:antialiased`.
  - `:focus-visible` : `outline: 2px solid var(--or); outline-offset: 3px`.
  - Ajouter `.plaque` (styles.css ligne 88) et `.sr` / `.tnum` (styles.css lignes 70–71).
  - Retirer le calque de bruit et les dégradés violet et turquoise de `body::before` / `::after`, remplacés par `.nightfall` (styles.css ligne 84) posé dans `layout.tsx`.
  - Dans `.glass`, `.glass-subtle`, `.btn`, `.ctrl`, `.q-item`, `.tab` : remplacer `transition-all` par des propriétés explicites (`background-color`, `border-color`, `transform`) et `backdrop-filter: blur(24px)` par un fond plein `var(--nef)`.
- [ ] **Step 6: `tailwind.config.js`.**
  - Nouvelles couleurs `nuit nef voute os cendre or gueules`, en `var(--x)`.
  - Alias legacy vers les tokens, marqués `// legacy: supprimé à l'étape 3` :
    - `surface.0` = `var(--nuit)`, `surface.1` = `var(--nef)`, `surface.2` = `var(--voute)`, `surface.3` = `var(--voute-2)` ;
    - `txt.DEFAULT` = `var(--os)`, `txt.muted` = `var(--cendre)`, `txt.dim` = `var(--cendre-2)` ;
    - `accent.DEFAULT` = `rgb(var(--lumiere-rgb))`, `accent.light` = `var(--or)`, `accent.dim` = `rgb(var(--lumiere-rgb) / .15)` ;
    - `teal` = `var(--or)`, `rose` = `var(--gueules)`, `border.DEFAULT` = `var(--hair)`, `border.hover` = `var(--hair-2)`.
  - Polices : `display: ['var(--f-display)']`, `body: ['var(--f-ui)']`, `mono: ['var(--f-ui)']`.
- [ ] **Step 7: Run** `npm test`, `npx tsc --noEmit`, `npx next build`. Expected : tout vert.

### Task 3 : Module de textes « valet du Roi »

**Files:**
- Create: `services/web/src/theme/copy.ts`, `services/web/src/theme/copy.v2.json` (copie du deck, pris tel quel)
- Test: `services/web/tests/copy.test.mjs`

**Interfaces:**
- Produces :

```ts
export type CopyVars = { sire?: string; kingName?: string; theKing?: string; name?: string; q?: string; count?: number | string; [k: string]: unknown };
export const deck: Record<string, any>;                // contenu de copy.v2.json
export function t(path: string, vars?: CopyVars): string;   // 'search.placeholder' → texte rempli
export function fill(template: string, vars?: CopyVars): string;  // remplace {clé}, laisse intact un jeton inconnu
export function quip(path: string, seed: number, vars?: CopyVars): string | null; // choisit une réplique déterministe dans path.quips, null si absente
export const SIRE_DEFAULT = 'Sire';
```

- [ ] **Step 1: Write the failing test** (`tests/copy.test.mjs`)

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { t, fill, quip, deck } = await loadTs('../src/theme/copy.ts');
test('fill remplace les jetons connus et garde les inconnus', () => {
  assert.equal(fill('Salut {sire}, {x}', { sire: 'Sire' }), 'Salut Sire, {x}');
});
test('t lit un chemin du deck', () => {
  assert.equal(t('search.submit.playlist'), 'Ajouter la playlist');
  assert.match(t('search.placeholder'), /YouTube/);
});
test('quip est déterministe et remplit {sire}', () => {
  const a = quip('header.welcome', 3, { sire: 'Sire' });
  assert.equal(a, quip('header.welcome', 3, { sire: 'Sire' }));
  assert.ok(a && !a.includes('{sire}'));
});
test('casting : aucun texte ne fait de Greg un roi', () => {
  const all = JSON.stringify(deck);
  for (const bad of ['Yo el Rey', 'GREGORIVS · REX', 'Greg, roi', 'le roi Greg']) assert.ok(!all.includes(bad), bad);
});
```

- [ ] **Step 2: Run.** Expected : FAIL.
- [ ] **Step 3: Implement.**
  - `import deckJson from './copy.v2.json'` avec `resolveJsonModule`, déjà actif dans le tsconfig Next ; sinon charger via `readFileSync` dans le test et exporter le JSON typé.
  - `t` suit le chemin en pointillés.
  - `fill` utilise l'expression `/\{(\w+)\}/g`.
  - `quip` prend `list[seed % list.length]`.
- [ ] **Step 4: Run.** Expected : PASS.

### Task 4 : Découper `page.tsx` à comportement identique

**Files:**
- Create: `services/web/src/lib/format.ts` (`fmt`, `extractVideoId`, `discordAvatar` déplacés tels quels depuis `page.tsx` lignes 13–33), test `services/web/tests/format.test.mjs`
- Create: `services/web/src/components/icons.tsx` (`I`, `Ic` depuis les lignes 36–50)
- Create: `services/web/src/components/Header/SearchBar.tsx` (lignes 55–180)
- Create: `services/web/src/components/Stage/VideoPlayer.tsx` (`VideoPlayer` à partir de la ligne 181, provisoire, remplacé à l'étape 2)
- Create: `services/web/src/components/Queue/QueuePanel.tsx`, `services/web/src/components/History/HistoryPanel.tsx`, `services/web/src/components/Sidebar.tsx`
- Modify: `services/web/src/app/page.tsx`, qui ne garde que `Home` : assemblage, raccourcis, rafraîchissement au focus

**Interfaces:**
- Produces : `fmt(sec?: number|null): string` ; `extractVideoId(url?: string|null): string|null` ; `discordAvatar(me: any, size?: number): string|null` ; composants par défaut sans props : `SearchBar`, `VideoPlayer`, `QueuePanel`, `HistoryPanel`, `Sidebar`.

- [ ] **Step 1: Write the failing test** (`tests/format.test.mjs`)

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { fmt, extractVideoId, discordAvatar } = await loadTs('../src/lib/format.ts');
test('fmt', () => { assert.equal(fmt(213), '3:33'); assert.equal(fmt(null), '--:--'); assert.equal(fmt(-1), '--:--'); });
test('extractVideoId', () => {
  assert.equal(extractVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1'), 'dQw4w9WgXcQ');
  assert.equal(extractVideoId('https://youtu.be/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.equal(extractVideoId('nope'), null);
});
test('discordAvatar', () => {
  assert.equal(discordAvatar({ id: '1', avatar: 'abc' }, 96), 'https://cdn.discordapp.com/avatars/1/abc.png?size=96');
  assert.match(discordAvatar({ id: '175928847299117063' }), /embed\/avatars\/\d\.png$/);
  assert.equal(discordAvatar(null), null);
});
```

- [ ] **Step 2: Run.** Expected : FAIL.
- [ ] **Step 3: Déplacer le code sans le modifier.** Seuls les imports et les exports changent.
- [ ] **Step 4: Run** `npm test`, `npx tsc --noEmit`, `npx next build`. Expected : PASS, et les 45 anciens tests restent verts.
- [ ] **Step 5: Vérification de parité dans le navigateur.**
  - Lancer la fausse API (`.claude/launch.json` : `mock-api`, `web-ui`).
  - Capturer en 1440×900 : même contenu, même comportement (recherche, file, historique). Seule la palette peut changer, à cause des tokens de la tâche 2.

### Task 5 : Nouvel en-tête (wordmark, recherche, serveur, avatar couronné)

**Files:**
- Create: `services/web/src/components/Header/Header.tsx`, `Wordmark.tsx`, `GregMedal.tsx`, `GuildPicker.tsx`, `KingAvatar.tsx`, `AccountMenu.tsx`, `header.css` (importé dans `globals.css`)
- Create: `services/web/src/lib/links.ts`, test `services/web/tests/links.test.mjs`
- Modify: `services/web/src/components/Header/SearchBar.tsx` : habillage `.field` et `.btn-add`, pastille de type de lien, raccourci `/`
- Modify: `services/web/src/app/page.tsx` : `<Header/>` remplace l'ancien `<header>`

**Interfaces:**
- Consumes : `t`, `quip`, `fill` (tâche 3), les tokens (tâche 2), les assets (tâche 1), `discordAvatar` (tâche 4), `usePlayer()` et ses champs `me, guilds, guildId, setGuild, logout, socketReady`.
- Produces :

```ts
export type LinkKind = 'none' | 'video' | 'playlist' | 'mix' | 'channel' | 'spotify' | 'unsupported';
export function classifyLink(input: string): LinkKind;
export function submitLabelKey(kind: LinkKind): 'search.submit.default' | 'search.submit.playlist' | 'search.submit.mix';
```

- [ ] **Step 1: Write the failing test** (`tests/links.test.mjs`)

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { classifyLink, submitLabelKey } = await loadTs('../src/lib/links.ts');
const cases = [
  ['never gonna give you up', 'none'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'video'],
  ['youtu.be/dQw4w9WgXcQ', 'video'],
  ['https://www.youtube.com/shorts/dQw4w9WgXcQ', 'video'],
  ['https://m.youtube.com/playlist?list=PLabc', 'playlist'],
  ['https://music.youtube.com/playlist?list=OLAK5uy_x', 'playlist'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc', 'playlist'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ', 'mix'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&start_radio=1', 'mix'],
  ['https://www.youtube.com/@artiste', 'channel'],
  ['https://open.spotify.com/playlist/37i9', 'spotify'],
  ['https://soundcloud.com/x/y', 'unsupported'],
];
test('classifyLink', () => { for (const [i, k] of cases) assert.equal(classifyLink(i), k, i); });
test('submitLabelKey', () => {
  assert.equal(submitLabelKey('playlist'), 'search.submit.playlist');
  assert.equal(submitLabelKey('mix'), 'search.submit.mix');
  assert.equal(submitLabelKey('video'), 'search.submit.default');
});
```

- [ ] **Step 2: Run.** Expected : FAIL.
- [ ] **Step 3: Implement `links.ts`.**
  - Normalisation : lien sans schéma → `https://`.
  - Reconnaissance des hôtes youtube.com, m., music., youtu.be, open.spotify.com, spotify.link.
  - `list=RD…` ou `start_radio=1` : `mix`.
  - `list=` ou chemin `/playlist` : `playlist`.
  - `v=`, `/shorts/` ou youtu.be : `video`.
  - `/@x`, `/channel/`, `/c/`, `/user/` : `channel`.
  - Tout autre lien : `unsupported`.
  - Pas un lien : `none`.
  - SoundCloud reste `unsupported` : on n'utilise que YouTube.
- [ ] **Step 4: En-tête.** Porter le HTML de `P\proto-gothique\work\refine\src\body.html` (bloc `.top`) et le CSS de `styles.css` lignes 91–186 (en-tête, recherche, suggestions, chip, avatar, popovers, interrupteur) dans `header.css`, en JSX :
  - `Wordmark` : SVG de `wordmark.html`, dont on **supprime les chemins `class="wm-crown"`**, parce que Greg ne porte pas de couronne. Version courte « Greg » sous 900 px.
  - `GregMedal` : `/gothique/greg-face-96.webp` dans le médaillon (`.medal`). Info-bulle `t('brand.medalTip')` si la clé existe, sinon « Greg, votre valet ».
  - `SearchBar` : habillage `.field`, touche `/` qui donne le focus, `data-link={classifyLink(q)}` et pastille `t('search.linkKind.<kind>')`. Libellé du bouton : `t(submitLabelKey(kind))`, avec `min-width` pour qu'il ne saute pas. Placeholder `t('search.placeholder')`, et `placeholderShort` sous 520 px. **Garder toute la logique existante** (suggestions, `enterPicksSuggestion`, `looksLikeUrl`, envoi).
  - `GuildPicker` : popover `.pop` à la place du `<select>`. Chaque ligne sur deux lignes : présence de Greg d'après `bot_present`, « Greg présent » ou « Greg absent ». Navigation au clavier (flèches, Entrée, Échap), focus rendu au déclencheur.
  - `KingAvatar` : avatar Discord, plus `/gothique/crown-badge-64.webp` posé en haut à droite. `title` = `t('header.account.crownTip', { theKing: 'Votre Majesté' })`, surtitre `t('header.account.kicker')` (« Sa Majesté »).
  - `AccountMenu` : se déconnecter (`logout`), interrupteur « Répliques de Greg » (`localStorage`, dans un try/catch), liste des raccourcis.
  - Voyant de connexion : `socketReady`, puis `t('header.live.on'|'off')`.
- [ ] **Step 5: Run** `npm test`, `npx tsc --noEmit`, `npx next build`. Expected : PASS.
- [ ] **Step 6: Vérifier dans le navigateur**, avec la fausse API, en 1440×900, 1280×720 et 390×844 :
  - l'en-tête correspond au prototype, sans couronne sur Greg ;
  - la couronne est sur l'avatar du Roi ;
  - la pastille « Playlist YouTube » s'affiche quand on colle `…&list=PL…` ;
  - le popover des serveurs fonctionne au clavier ;
  - aucune erreur console.
