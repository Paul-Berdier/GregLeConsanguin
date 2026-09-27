# Nuit gothique, étape 3 : la file, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** remplacer le panneau provisoire (file, historique, barre de statut) par la file « Nuit gothique » de la spec §5 et §6.3 :
- des lignes lisibles : poignée 6 points, pochette (poignée elle aussi), titre nettoyé (`parseTitle`, le brut en info-bulle), artiste, blason et nom du demandeur, sceau royal du Roi à son initiale sur **ses** titres, durée et heure estimée (« À suivre », « dans 9 min »), et « fin vers 22 h 47 » dans le résumé ;
- des actions rapides (jouer maintenant, jouer ensuite, retirer) sur une puce opaque ; un clic sélectionne, un double-clic joue ; une accalmie après chaque changement et un anti-doublon de 500 ms ;
- le glisser-déposer en pointer events : seuil de 4 px, élastique, défilement automatique, Échap, refus du serveur = retour en place et secousse ;
- le FLIP des listes (`useFlip`, API Web Animations) ;
- les actions optimistes dans `usePlayer`, avec retour en arrière et mise en tampon des états reçus pendant une action en vol ou un glisser ;
- le Héraut (toasts à la Sonner : pile de 3, survol, fusion ×N, « Annuler », Ctrl+Z), qui remplace la barre de statut ; l'annulation d'un retrait (re-ajout puis déplacement) et d'un ajout ;
- « Souvent demandés ici » sous la file, l'historique avec ses rangs dorés, et la fin des alias Tailwind legacy.

**Architecture:** Next.js 14 (App Router, React 18, Tailwind 3), aucune nouvelle dépendance npm (`zustand` est déjà là).
- **Moteur optimiste pur** (`lib/queue/optimistic.ts`). La vue affichée est l'état reçu, plus les ordres du Roi pas encore confirmés. Ces ordres sont exprimés **par clé de titre**, jamais par index, et sont idempotents ou conditionnels : on peut les rejouer sur un état plus récent sans double saut ni clignotement. Une seule requête part à la fois, et ses index sont calculés sur l'état que le bot verra. Les états reçus pendant une requête en vol (les 2,5 premières secondes) ou pendant un glisser sont gardés en tampon. Un tick de progression reçu pendant l'attente se calcule sur l'état gardé (`engine.latest()`, correction C1), jamais sur le précédent : rien ne se perd. Un refus retire l'ordre : la vue revient en arrière.
- **`usePlayer`** : le store zustand ne contient plus que la vue du moteur (`player`, `tickBase`). Les actions sortent au niveau du module (`playerActions`), donc le clavier de `page.tsx` les appelle hors de React.
- **Le Héraut** : un réducteur pur à minuteurs injectés (`lib/herald.ts`), un singleton de page (`components/Herald/store.ts`, `say` / `sayError` avec les textes du deck) et un composant avec deux régions `aria-live` persistantes.
- **Listes** : `useFlip` garde les lignes qui sortent le temps de leur sortie (présence, `lib/flip.ts`) et anime les déplacements en `translateY`. `useQueueDrag` fait le glisser. Les calculs purs (`lib/queue/drag.ts`, `lib/motion.ts`) sont testés.
- Une feuille de style par composant, importée par `globals.css`.

**Tech Stack:** Next.js 14.2, React 18, TypeScript 5, Tailwind 3, zustand 4, `node:test`, API Web Animations, Pointer Events, Playwright (Chrome installé) pour la vérification.

**Spec:** `docs/superpowers/specs/2026-09-26-web-nuit-gothique-design.md` (§5 « Fluidité et file », §6.3). Plans de référence : `docs/superpowers/plans/2026-09-26-web-nuit-gothique-etape-1.md` et `-etape-2.md`.

## Global Constraints

- **Ressources.**
  - `S` = `C:\Users\Paul\AppData\Local\Temp\claude\C--Users-Paul-Documents-Codage-GregLeConsanguin\0d3cb735-ae70-4238-a3f4-f9ff22e57d5f\scratchpad`, `P` = `S\design`, **`R` = `S\etape3-ref\web`** (la référence validée, voir plus bas).
  - Le prototype `P\proto-gothique` fait foi pour les valeurs : son `DESIGN.md` (§2, §5, §12.5, §12.6) et ses sources `work\refine\src\styles.css`, `body.html` et `app.js`.
  - Mouvement : `P\research\motion.md` (§4, §6.6 à §6.8, §6.14 à §6.16). Technique : `P\research\tech.md` (§6.4).
  - Textes : `services/web/src/theme/copy.v2.json`, par `theme/copy.ts` (`t`, `quip`, `has`). Guide : `P\research\persona-v2.md`.
- **Casting** (spec §1, qui fait foi). Le Roi, c'est l'utilisateur connecté ; Greg est son valet.
  - Aucune couronne, aucun sceau royal, aucun « Rex » attribué à Greg.
  - Le sceau `king-seal-<L>.webp` (initiale du Roi, `kingSealSrc(kingName(me))`) ne va que sur les lignes dont le demandeur est le Roi (`requesterOf(...).kind === 'mine'`).
  - Greg parle dans le Héraut avec son portrait de valet (`/gothique/greg-face-96.webp`), jamais couronné.
- **Mouvement.**
  - Animer uniquement `transform` et `opacity`, jamais `transition: all` ; les couleurs de survol changent sans transition.
  - Survols derrière `@media (hover:hover) and (pointer:fine)`.
  - `prefers-reduced-motion` respecté : fondus seuls. La ligne saisie suit toujours le pointeur, et un anneau rouge remplace la secousse.
- **Textes.** En français, depuis le deck v2 (Greg vouvoie le Roi).
  - Le deck est généré : on ne l'édite pas. Les libellés qui lui manquent (heures estimées, « fin vers », « Souvent demandés ici », libellés `aria`…) vont dans `theme/copy.extra.ts` (`tx`). Ce module suit la typographie du deck, ne double aucune clé et ne contient aucun humour.
  - Les répliques sont en `aria-hidden`, en or, et coupées par `<html data-quips="off">`.
- **Compatibilité.**
  - Les 182 tests web existants restent verts : `cd services/web && npm test`. `GREG_TEST_TRANSPILE=1 npm test` passe aussi (chemin Node 20 de l'image Docker).
  - À la fin de l'étape, on compte **243 tests** (les 241 de `R`, plus 2 des corrections de la relecture).
  - `npx tsc --noEmit` et `npx next build` passent.
  - Aucune nouvelle dépendance npm. `services/web/node_modules` est une jonction : ne jamais lancer `npm install`.
  - Aucun changement dans `services/bot`, `services/api` ni `packages/shared`. L'API a déjà `POST /player/move {src, dst}` (le bot fait `insert(dst, pop(src))` ; refus `403 PRIORITY_FORBIDDEN`, file changée `409`).
- **Modules purs** (chargés par `tests/_loadTs.mjs`) :
  - aucun import runtime (seulement `import type`) ;
  - syntaxe TypeScript effaçable : pas d'`enum`, pas de `namespace`, pas de paramètres de constructeur `private x`.
- **Fins de ligne.** Le dépôt a `core.autocrlf=true` : l'index garde LF quoi qu'il arrive, git normalise au commit.
  - Les fichiers de `R` gardent les fins de ligne de l'arbre de travail d'où ils viennent. `src/lib/types.ts` est en CRLF. `src/lib/playerUtils.ts` est en CRLF sauf ses lignes 431–455 (LF), et `tests/api.test.mjs` sauf ses lignes 104–121 (LF). Tous les autres sont en LF.
  - On les recopie tels quels, sans rien convertir : la comparaison finale (tâche 7, étape 5) se fait octet par octet.
  - Les remplacements des corrections C1 à C4 portent sur des fichiers en LF.
- **Commandes.** Elles sont écrites pour Git Bash, lancées depuis la racine du dépôt sauf `cd services/web` explicite.
  - En Git Bash : `S=/c/Users/Paul/AppData/Local/Temp/claude/C--Users-Paul-Documents-Codage-GregLeConsanguin/0d3cb735-ae70-4238-a3f4-f9ff22e57d5f/scratchpad`.
  - Sous PowerShell : `$env:GREG_TEST_TRANSPILE=1; npm test; Remove-Item Env:GREG_TEST_TRANSPILE`.
- **Parallélisme.** Les tâches d'une même vague partagent `services/web`.
  - `npm test` peut tourner en même temps.
  - `tsc` et `next build`, non : l'orchestrateur les lance une fois la vague finie.
- **Git.**
  - Les agents ne font ni commit, ni push, ni stash, ni reset, ni checkout. L'orchestrateur committe et pousse (tâche 7, étape 9).
  - Ne jamais committer `services/web/tsconfig.json` ni `services/web/next-env.d.ts`.
- **Serveurs de vérification.**
  - Fausse API : `node S\uimock\mock_api.js`, port 3999. `services/web/.env.local` pointe déjà `API_URL` dessus. Elle n'a pas de Socket.IO : les erreurs WebSocket sont attendues.
  - La fausse API est **déjà étendue pour l'étape 3** (copie d'avant : `mock_api.before-etape3.js`) :
    - `ts` sur chaque titre ;
    - un ajout garde l'`url` demandée ;
    - un historique de 6 titres avec `last_played` et `last_played_by` ;
    - `/__mock?refuse=move|remove|play_at` fait refuser la commande suivante de ce type (`403 PRIORITY_FORBIDDEN`) ;
    - `/__mock?scene=playing` remet la file à ses 6 titres ; `POST /api/v1/queue/add` ajoute un titre (le Roi, id `101`).
  - Web : `npx next build && npx next start -p 3100` dans `services/web`, jamais `next dev`. Toujours arrêter les serveurs lancés. Fichiers temporaires sous `S`.
  - Scripts Playwright (venv `S\venv`, Chrome installé) : `S\etape3-ref\verif.py` (22 contrôles) puis `S\etape3-ref\verif-corrections.py` (3 contrôles, corrections C2 à C4 ; il remplit la file de 62 titres, puis la remet à 6).

## Référence validée, corrections de la relecture et écarts assumés

Tout le code de ce plan est dans **`R`** : même arborescence que `services/web`, uniquement les 43 fichiers créés ou modifiés par l'étape. On l'a monté sur une copie de `services/web` au commit `31e6213`, et mesuré :
- 241 tests verts, dans les deux modes de chargement ;
- `tsc` et `next build` passent ;
- les états intermédiaires après les vagues C et D (tâches 1 à 5, puis 1 à 6) passent aussi `tsc`, les tests (232, puis 236) et le build ;
- `S\etape3-ref\verif.py` : 22 contrôles sur 22 dans Chrome, sur la fausse API.

### Corrections de la relecture (écarts à `R`)

La relecture critique du 2026-09-27 a rejoué ce plan vague par vague sur une copie propre de `services/web` au commit `31e6213`. Elle a trouvé dans `R` quatre défauts qu'aucun contrôle ne couvrait. Ce plan les corrige, et chaque correction a un test qui échoue d'abord.

**C1. Tampon : un tick écrase l'état gardé** (tâches 2 et 5).
- Défaut. Le bot publie un tick chaque seconde pendant la lecture. `usePlayer.receive` le calcule sur `engine.server()`. Pendant un glisser ou une requête en vol, il **remplace donc l'état complet gardé en tampon** :
  - un titre ajouté par un courtisan pendant le glisser disparaît jusqu'au prochain état complet (la resynchronisation REST le ramène en 5 s au plus pendant la lecture) ;
  - un retrait du Roi accusé peut réapparaître après 4 s (`ACK_GRACE_MS`), puis disparaître de nouveau à la resynchronisation : un clignotement.
- C'est contraire à la spec §5 (« les poussées serveur reçues pendant une action en vol sont mises en mémoire tampon »).
- Correction : `QueueEngine.latest()` rend `held ?? server`. `usePlayer` calcule chaque état reçu, et le gel `BOT_OFFLINE`, sur `engine.latest()`.
- Tests : `optimistic.test.mjs` (un 15e test) et `player-contract.test.mjs` (test 1 renforcé).

**C2. Plus de 60 titres : page blanche** (tâche 6).
- Défaut. `QueuePanel` passe à `useFlip` une tranche neuve à chaque rendu (`queue.slice(0, MAX_ROWS)`). Or `useFlip` compare `items` par référence et fait un `setState` pendant le rendu. Résultat : une boucle de rendus, **React #301, page blanche**. Mesuré dans Chrome avec 69 titres.
- Correction : `shown` est mémoïsé (`useMemo`, dépendance `queue`).
- Tests : `queue-panel.test.mjs` (test 3) et `verif-corrections.py`.

**C3. File repliée : le dépôt part en fin de file** (tâche 6).
- Défaut. Sous la dernière ligne visible, `dropAnchor` rend `null`, c'est-à-dire « en fin de file ». Le titre part donc au bout de la file entière, hors de la vue.
- Correction : `beforeKey ?? queue[MAX_ROWS]?.key ?? null`, c'est-à-dire devant le premier titre caché.
- Tests : `queue-panel.test.mjs` (test 3) et `verif-corrections.py`.

**C4. « + » double-cliqué : deux ajouts** (tâche 7).
- Défaut. Dans l'historique et « Souvent demandés ici », un « + » double-cliqué ajoute le titre deux fois (mesuré : file de 6 à 8). Et la suggestion suivante, qui remonte sous le pointeur, peut être ajoutée par erreur. La file a une garde, pas l'historique.
- Correction : `useRequeueList` n'accepte qu'un ajout par 500 ms (`createDedupe`, une clé commune).
- Tests : `queue-contract.test.mjs` (un 6e test) et `verif-corrections.py`.

**Mesures du plan corrigé.** Il a été rejoué tel qu'écrit : script `S\etape3-corrige\waves2.sh`, copie complète dans `S\etape3-corrige\web`.
- Après chaque vague : 221, 229, 233, 237, puis **243** tests, dans les deux modes de chargement. `tsc` et `next build` passent à chaque vague.
- Chaque test ajouté ou renforcé échoue avant sa correction.
- `verif.py` : 22 sur 22. `verif-corrections.py` : 3 sur 3 (0 sur 3 avec `R` d'origine).

**Règle d'exécution.**
- Chaque tâche recopie ses fichiers depuis `R` tels quels, sauf mention contraire. Deux cas, tous donnés en clair dans la tâche :
  - les états intermédiaires de `usePlayer.ts`, `page.tsx` et `globals.css` ;
  - les corrections C1 à C4 : des remplacements exacts, appliqués juste après la copie.
- Pour les 8 fichiers touchés par C1 à C4, `S\etape3-corrige\web` contient le résultat attendu, octet pour octet. Seule exception : à la fin de la tâche 5, `usePlayer.ts` porte en plus la compat.
  - On peut recopier ces fichiers au lieu de faire les remplacements à la main.
  - L'ordre des étapes ne change pas : d'abord le fichier de `R`, pour voir le test de la correction échouer, puis le fichier corrigé.
- Pour un fichier **modifié**, vérifier d'abord `git diff --quiet 31e6213 -- <fichier>` : s'il a bougé depuis, reporter les changements de `R` à la main.
- Le relecteur compare le résultat à `R` (tâche 7, étape 5) :
  - seuls les 8 fichiers des corrections diffèrent, et seulement par les lignes données ici ;
  - le résultat est identique, octet pour octet, à `S\etape3-corrige\web`.
- Ce plan donne les interfaces, les tests (en entier quand ils sont courts, sinon leur contenu et des extraits réels) et la logique clé. Le fichier de `R`, corrigé par C1 à C4, fait foi pour le reste.

**Écarts assumés :**
1. **Le Héraut est en bas à droite, au-dessus du pied du panneau** (DESIGN §5, écart n° 1), et non en haut au centre comme dans motion.md §6.16. Il passe au centre en bas quand le panneau manque : déconnecté, ou une colonne. La file garde sous ses dernières lignes la hauteur de la pile repliée (`--herald-h`).
2. **Annulations livrées** : le retrait, l'ajout et « Jouer ensuite » (un simple déplacement retour).
   - Annuler un saut, un « jouer maintenant » ou un arrêt demanderait une position de départ côté API (spec §2, non-objectifs).
   - Le bot n'a pas de « remettre » : un titre remis après un retrait est **rajouté par le Roi** (il devient son titre, avec sa préséance), puis replacé.
3. **Clés stables.** Le bot ne donne pas d'id par titre. La clé est `f:url|added_by|ts|repeat_tag#n`, `n` étant le rang parmi les vrais doublons (`assignKeys`). Un titre garde sa clé quand d'autres s'insèrent devant lui.
4. **Tampon et rapprochement.**
   - Un état reçu pendant les 2,5 premières secondes d'une requête en vol (`HOLD_MAX_MS`) attend sa fin ; passé ce délai, les états reçus s'appliquent tout de suite (un bot lent ne fige pas la page). Pendant un glisser, ils attendent le dépôt.
   - Seul le dernier état gardé compte. Un tick reçu pendant l'attente se calcule sur lui (`engine.latest()`, C1).
   - Un ordre accusé reste rejoué jusqu'à ce qu'un état reçu le montre, ou pendant 4 s (`ACK_GRACE_MS`).
   - Un ordre devenu sans effet (titre parti entre-temps) n'envoie rien.
5. **Pas de toast pour pause, reprise, boucle, reprise au début ni saut** (DESIGN §12.6 : le surtitre parlera à l'étape 4). Leurs erreurs passent par le Héraut.
6. **Historique.** Le bot ne donne que l'id du dernier demandeur. Son nom et son blason n'apparaissent que s'il est connu : le Roi (« vous »), ou un courtisan présent dans la file.
7. **Onglet court « File » + compte.** « File d'attente (8) » du deck ne tient pas à côté du titre en Grenze sur 360 px. Le résumé du deck (« File d'attente · 8 titres · 47 min · fin vers 22 h 47 ») passe sous le titre et les onglets, sur toute la largeur du panneau.
8. **Textes d'erreur du deck** (`errorCopy`, au vouvoiement), à la place des messages tutoyés de `describeError`. `staleStateText`, `enqueueSuccessText` et `recoveredStatusText` ne servent plus ; ils restent, avec leurs tests, pour un nettoyage ultérieur.
9. **Hors étape 3** (spec §6.4, étape 4) :
   - le Couronnement, le Sceau qui se pose, la Révérence ;
   - la ligne « en cours d'ajout » au collage d'un lien, le crochet de lot, les toasts des actions des autres (`remote.*`) ;
   - le tabindex itinérant, Alt+↑↓, Entrée et Suppr sur une ligne. D'ici là, les boutons de la puce restent dans l'ordre de tabulation.
   - « Retirer les miens » et le quota ne sont pas prévus.
   - `Transport` lit encore tout le store par `usePlayer()` (écart 4 de l'étape 2). Ses actions sont désormais optimistes sans qu'il change ; l'abonnement sera resserré avec la Révérence.
   - **Ctrl+Z est livré** : c'est l'annulation du Héraut.
10. **Découpage des fichiers (spec §3).** La spec liste `components/Queue/` : QueuePanel, QueueRow, DragLayer, RowActions et Suggestions. Ici :
    - pas de `DragLayer` : la ligne saisie se déplace elle-même, et le glisser est un hook, `Queue/useQueueDrag.ts` ;
    - pas de `RowActions` : la puce fait partie de `QueueRow` ;
    - `Suggestions` est dans `components/History/`, car elle partage `HistoryRow` et `useRequeue` avec l'historique. `QueuePanel` la reçoit par sa prop `after`.
11. **Garde de l'historique** (C4). Un seul ajout par 500 ms, tous titres confondus. Le prototype, dont les ajouts sont locaux et instantanés, n'en a pas.

## Carte des fichiers et vagues

Chaque fichier a un seul propriétaire par vague. Tous les chemins sont relatifs à `services/web/`.

| Tâche | Crée | Modifie | Dépend de |
|---|---|---|---|
| 1. État reçu, clés, textes, vue de la file (pur) | `src/theme/copy.extra.ts`, `src/lib/queue/view.ts`, `src/lib/queue/arms.ts`, `src/lib/queue/undo.ts`, `tests/queueState.test.mjs`, `tests/copy-extra.test.mjs`, `tests/queue-view.test.mjs` | `src/lib/types.ts`, `src/lib/playerUtils.ts` | aucune |
| 2. Moteur optimiste (pur), avec C1 | `src/lib/queue/optimistic.ts`, `tests/optimistic.test.mjs` | | aucune (types de 1, en `import type` : `tsc` ne passe qu'une fois la vague A finie) |
| 3. Le Héraut | `src/lib/herald.ts`, `src/components/Herald/store.ts`, `src/components/Herald/Herald.tsx`, `src/components/Herald/herald.css`, `tests/herald.test.mjs` | | 1 |
| 4. Mouvement de liste | `src/lib/motion.ts`, `src/lib/flip.ts`, `src/lib/queue/drag.ts`, `src/hooks/useFlip.ts`, `tests/motion.test.mjs` | | aucune |
| 5. usePlayer optimiste, API, page (C1) | `tests/player-contract.test.mjs` | `src/hooks/usePlayer.ts`, `src/lib/api.ts`, `src/app/page.tsx`, `src/app/globals.css`, `tests/api.test.mjs` | 1, 2, 3 |
| 6. La file (C2, C3) | `src/components/Queue/QueueRow.tsx`, `Shield.tsx`, `useQueueDrag.ts`, `queue.css`, `tests/_contract.mjs`, `tests/queue-panel.test.mjs` | `src/components/Queue/QueuePanel.tsx`, `src/hooks/usePlayer.ts` (compat retirée), `src/app/globals.css` | 1, 4, 5 |
| 7. Panneau, historique, nettoyage, navigateur (C4) | `src/components/panel.css`, `src/components/History/HistoryRow.tsx`, `Suggestions.tsx`, `useRequeue.ts`, `history.css`, `tests/queue-contract.test.mjs` | `src/components/Sidebar.tsx`, `src/components/History/HistoryPanel.tsx`, `tailwind.config.js`, `src/app/globals.css`, `src/app/page.tsx` | 1, 3, 4, 5, 6 |

Vagues :
- **A** : tâches 1, 2 et 4 (221 tests) ;
- **B** : tâche 3 (229) ;
- **C** : tâche 5 (233) ;
- **D** : tâche 6 (237) ;
- **E** : tâche 7 (243).

Après chaque vague, l'orchestrateur lance `npx tsc --noEmit` et `npx next build`.

## Contrats partagés

- **Types** (`src/lib/types.ts`, tâche 1) :
  - `Track.key: string`, toujours rempli par `assignKeys` (`''` avant) ;
  - `interface TickBase { pos: number; at: number; dur: number }` ;
  - `interface Snapshot { player: PlayerState; tickBase: TickBase }`.
- **Store** (`hooks/usePlayer.ts`, tâche 5) :
  - `useStore` garde `me, guilds, guildId, socketReady, player, tickBase, historyItems` et les setters `setMe`, `setGuilds`, `setGuildId`, `setSocketReady`, `setHistoryItems`.
  - `status`, `setStatus`, `setPlayer`, `setTickBase` et `applyPlaylistPayload` disparaissent.
  - `player` / `tickBase` sont la vue du moteur ; `historyItems` est la liste « Plus joués ».
- **Actions** : `export const playerActions` (tâche 5) ; `usePlayer()` renvoie `{ ...store, ...playerActions }`.

```ts
boot(): Promise<void>; setGuild(id: string): Promise<void>; logout(): Promise<void>;
refreshMe(): Promise<UserInfo | null>; refreshGuilds(): Promise<GuildInfo[]>; refreshHistory(): Promise<void>;
enqueue(payload: Record<string, any>): Promise<boolean>;           // lève l'erreur API (déjà annoncée)
skip(): Promise<boolean>; togglePause(): Promise<boolean>;          // optimistes
removeTrack(key: string, o?: { silent?: boolean }): Promise<boolean>;
moveTrack(key: string, beforeKey: string | null): Promise<boolean>; // false = refusé (retour en arrière fait)
playNext(key: string): Promise<boolean>; playNow(key: string): Promise<boolean>;
setDragging(on: boolean): void;                                     // tampon pendant un glisser
stop(): Promise<void>; toggleRepeat(): Promise<void>; restartTrack(): Promise<void>;
bestEffortVoiceJoin(reason: string): Promise<void>;
```

- **Héraut** (tâche 3) :
  - `say(key, { vars?, text?, action?: { label, run } | null, kind? }): number`, où `key` est une entrée du deck `{ text, kind?, quips? }` ;
  - `sayError(e, { name?, q?, action?: string }): number`, où `action` vaut `'move'` ou `'state'` quand il sert (`errorCopy`) ;
  - `herald.dismiss(id)` ;
  - `<Herald dock="panel" | "center"/>`, monté par `page.tsx`.
- **Classes et attributs partagés** :
  - lignes : `li.row[data-key][data-leaving][data-picked]` > `.card` (`queue.css`, tâche 6), reprises par `.hrow` et `.srow` (`history.css`) ;
  - `.qlist.settling` (accalmie) ; `.scroller` ; `.qcontent`, le bloc que `Sidebar` mesure pour les ménestrels ;
  - `[data-pane="queue|hist"]` sur les éléments d'un volet, que `Sidebar` fait se relayer ;
  - variable `--herald-h` sur `:root` (`Herald.tsx`), lue par `.scroller`.
- **Code des étapes 1 et 2 réutilisé tel quel** :
  - `parseTitle` (`lib/titles.ts`) ; `fmt`, `extractVideoId` (`lib/format.ts`) ; `livePosition` (`lib/playerUtils.ts`) ;
  - `requesterOf`, `kingSealSrc`, `seedOf` (`lib/stage/scene.ts`) ; `kingName` (`components/Header/KingAvatar.tsx`) ;
  - `.quip`, `.dot-sep` (`Stage/stage.css`, `now.css`) ; `.plaque`, `.ico`, `.tnum`, `.sr` (étape 1).

---

### Task 1 : état reçu, clés stables, textes et vue de la file (pur)

**Files:**
- Modify: `services/web/src/lib/types.ts` (ajouts seulement) ; `services/web/src/lib/playerUtils.ts` (`normalizeItem` pose `key: ''`, plus les ajouts listés ci-dessous)
- Create: `services/web/src/theme/copy.extra.ts`, `services/web/src/lib/queue/view.ts`, `services/web/src/lib/queue/arms.ts`, `services/web/src/lib/queue/undo.ts`
- Test: `services/web/tests/queueState.test.mjs`, `services/web/tests/copy-extra.test.mjs`, `services/web/tests/queue-view.test.mjs`

**Interfaces:**
- Consumes : rien.
- Produces :

```ts
// src/lib/playerUtils.ts (ajouts)
export function assignKeys(items: Track[]): Track[];                 // f:url|added_by|ts|repeat_tag#n (q:<qid> si le bot en donne un)
export function sameTrack(a: Track | null, b: Track | null): boolean;
export function shareTracks(prev: Track[], next: Track[]): Track[];  // partage structurel : file inchangée = même tableau
export function snapshotFromPayload(payload: any, prev: Snapshot, now: number): Snapshot | null; // null : état périmé (C3)
export function emptySnapshot(now?: number): Snapshot;
export type ErrorCopy = { key: string; path: string; vars?: Record<string, string> } | { key: string; text: string };
export function errorCopy(e: any, ctx?: { name?: string; q?: string; action?: string }): ErrorCopy;
export function addedCopy(res: any, fallbackTitle: string): { key: string; path: string; suffix: string | null;
  vars: Record<string, string | number>; action: string };
// src/theme/copy.extra.ts (espaces insécables U+00A0 et U+202F écrits en clair, ici comme dans R)
export const EXTRA = {
  panel: { label: 'File d’attente et historique', tabs: 'Vues', queueTab: 'File' },
  queue: {
    list: 'Titres de la file', endsAt: 'fin vers {time}', etaNext: 'À suivre', eta: 'dans {n} min',
    more: { one: '…et 1 autre titre', other: '…et {n} autres titres' },
    rowAria: '{title}, {artist}, demandé par {name}', rowAriaMine: '{title}, {artist}, votre titre', rowAriaUnknown: '{title}, {artist}',
    keys: 'Flèches haut et bas : parcourir. Entrée : jouer maintenant. Suppr : retirer. Alt+flèches : déplacer. Alt+Début : jouer ensuite.',
  },
  often: { title: 'Souvent demandés ici' },
  history: {
    list: 'Titres joués sur ce serveur', keys: 'Flèches haut et bas : parcourir. Entrée : remettre le titre dans la file.',
    plays: { one: '1 écoute', other: '{n} écoutes' },
    ago: { now: 'à l’instant', min: 'il y a {n} min', h: 'il y a {n} h', yesterday: 'hier', d: 'il y a {n} j' },
  },
  herald: { region: 'Notifications', undoHint: '{label} avec Ctrl+Z.', dismiss: 'Fermer la notification' },
} satisfies Record<string, Node>;
export function tx(path: string, vars?: Record<string, string | number>): string;   // pluriel { one, other } par n ; chemin absent → le chemin
// src/lib/queue/view.ts
export type Eta = { key: string; next: boolean; mins: number | null };
export function queueEtas(queue: readonly Pick<Track, 'key' | 'duration'>[], remaining: number): Eta[];
export const queueSeconds: (queue: readonly Pick<Track, 'duration'>[]) => number;
export function fmtLong(sec: number): string;          // « 47 min », « 1 h 05 » (U+00A0)
export function clockText(d: Date): string;            // « 22 h 47 »
export const endsAt: (nowMs: number, remaining: number, queue: readonly Pick<Track, 'duration'>[]) => Date;
export type HistoryItem = { url?: string; title?: string; artist?: string; thumb?: string | null; duration?: number | null;
  provider?: string; play_count?: number; last_played?: number; last_played_by?: string };   // history_manager.py du bot
export function oftenAsked(top: readonly HistoryItem[], queue: readonly Pick<Track, 'url'>[], currentUrl: string | null | undefined, n?: number): HistoryItem[];
export type Ago = { unit: 'now' | 'min' | 'h' | 'yesterday' | 'd'; n: number };
export function agoOf(lastPlayedSec: number | undefined, nowMs: number): Ago | null;
export const dropEmptyTail: (s: string) => string;
// src/lib/queue/arms.ts
export type Division = 'pale' | 'chevron' | 'bend' | 'fess' | 'quarterly' | 'bordure';
export type Arms = { d: Division; a: string; b: string };
export const DIVISIONS: readonly Division[]; export const FIELDS: readonly string[]; export const LIGHT: readonly string[]; export const DARK: string;
export function armsOf(id: string | null | undefined): Arms;
export const SHIELD_PATH: string;                       // contour de l'écu, viewBox 0 0 13 15
// src/lib/queue/undo.ts
export function addedKeys(beforeKeys: readonly string[], after: readonly Pick<Track, 'key' | 'addedBy'>[], meId: string): string[];
export function restorePlan(beforeKeys: readonly string[], after: readonly Pick<Track, 'key' | 'url'>[], url: string, index: number):
  { key: string; beforeKey: string | null } | null;
```

- [ ] **Step 1 : les tests qui échouent.** Recopier depuis `R` : `tests/queueState.test.mjs` (7 tests), `tests/copy-extra.test.mjs` (3) et `tests/queue-view.test.mjs` (7).
  - `queueState` :
    - `assignKeys` : stable quand un titre s'insère devant, unique pour les doublons ;
    - `shareTracks` / `sameTrack` ;
    - `snapshotFromPayload` : état complet, demandeur résolu par `queue_users`, horloge ancrée à la réception, état périmé → `null` ; même état reçu deux fois → mêmes objets ; un tick ne touche ni au titre, ni à la file, ni à la boucle ;
    - `errorCopy` : 14 cas, chacun mène à un texte du deck ;
    - `addedCopy`.
  - `copy-extra` :
    - `tx` : jetons et pluriel ;
    - typographie du deck : U+00A0 avant « : », U+202F avant ; ! ?, apostrophe courbe ;
    - aucune clé en double avec le deck, pas de couronne pour Greg.
  - `queue-view` : heures estimées, durée longue et heure à la française, « Souvent demandés ici », moment relatif, blasons (stables, jamais de rouge, les 6 partitions servent), `addedKeys`, `restorePlan`.

Extraits réels (`tests/queue-view.test.mjs`) :

```js
const NB = '\u00a0';
test('heure estimée : reste du titre en cours puis durées cumulées, « À suivre » pour le premier', () => {
  const etas = V.queueEtas([T('a', 300), T('b', 120), T('c')], 90);
  assert.deepEqual(etas.map((e) => [e.key, e.next, e.mins]), [['a', true, 2], ['b', false, 7], ['c', false, 9]]);
  assert.equal(V.queueEtas([T('a')], 0)[0].mins, 1, 'jamais « dans 0 min »');
  assert.deepEqual(V.queueEtas([T('a', null), T('b')], 60).map((e) => e.mins), [1, null], 'après un titre sans durée : inconnu');
});
test('annuler un retrait : la ligne revenue et le titre devant lequel la replacer', () => {
  const url = 'https://youtu.be/b';
  const after = [T('a'), T('c'), T('d'), { key: 'b2', url }];
  assert.deepEqual(U.restorePlan(['a', 'c', 'd'], after, url, 1), { key: 'b2', beforeKey: 'c' });
  assert.deepEqual(U.restorePlan(['a', 'c', 'd'], after, url, 3), { key: 'b2', beforeKey: null }, 'ancienne place en fin de file');
  assert.equal(U.restorePlan(['a', 'c', 'd'], [T('a'), T('c'), T('d')], url, 1), null, 'refusé (quota) : rien à déplacer');
});
```

Extrait réel (`tests/queueState.test.mjs`) :

```js
test('snapshotFromPayload : un tick ne touche ni au titre, ni à la file, ni à la boucle', () => {
  const s1 = snapshotFromPayload(state([raw('a')], raw('cur'), { repeat_all: true }), emptySnapshot(), 1000);
  const tick = { only_elapsed: true, paused: true, is_paused: true, position: 40, duration: 200, progress: { elapsed: 40, duration: 200 } };
  const s2 = snapshotFromPayload(tick, s1, 3000);
  assert.equal(s2.player.current, s1.player.current);
  assert.equal(s2.player.queue, s1.player.queue);
  assert.equal(s2.player.repeat, true);
  assert.deepEqual(s2.tickBase, { pos: 40, at: 3000, dur: 200 });
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/queueState.test.mjs tests/copy-extra.test.mjs tests/queue-view.test.mjs`
  - Attendu : FAIL. Les modules sont introuvables (`ERR_MODULE_NOT_FOUND` pour `copy.extra.ts`, `queue/view.ts`…) ; `assignKeys` n'est pas une fonction.
- [ ] **Step 3 : implémenter.** Recopier depuis `R` : `src/lib/types.ts`, `src/lib/playerUtils.ts`, `src/theme/copy.extra.ts`, `src/lib/queue/view.ts`, `src/lib/queue/arms.ts` et `src/lib/queue/undo.ts`. Logique clé :

```ts
// playerUtils.ts : clés stables (le bot n'a pas d'id par titre ; `ts` est posé à l'ajout et suit le titre)
function fingerprint(t: Track): string {
  const r = t.raw && typeof t.raw === 'object' ? t.raw : {};
  if (r.qid) return `q:${r.qid}`;
  return `f:${[t.url || r.url || '', r.added_by ?? r.requested_by ?? '', r.ts ?? '', r.repeat_tag ?? ''].join('|')}`;
}
export function assignKeys(items: Track[]): Track[] {
  const seen = new Map<string, number>();
  return items.map((t) => {
    const fp = fingerprint(t);
    const n = seen.get(fp) ?? 0;
    seen.set(fp, n + 1);
    const key = `${fp}#${n}`;
    return t.key === key ? t : { ...t, key };
  });
}
// snapshotFromPayload : parse repris de l'ancien applyPlaylistPayload (usePlayer.ts, lignes 102–157), avec clés,
// partage structurel (shareTracks) et `repeat` gardé sur un tick.
// view.ts : le reste du titre en cours, puis les durées cumulées
export function queueEtas(queue, remaining) {
  let acc: number | null = Math.max(0, remaining || 0);
  return queue.map((t, i) => {
    const out = { key: t.key, next: i === 0, mins: acc == null ? null : Math.max(1, Math.round(acc / 60)) };
    acc = acc == null || t.duration == null || !Number.isFinite(t.duration) ? null : acc + Math.max(0, t.duration);
    return out;
  });
}
// arms.ts : émaux de PEOPLE (app.js, lignes 56–65) ; sur le champ d'or (#c99a2e), une pièce sombre
export function armsOf(id) {
  const h = hash(String(id || '?'));   // FNV-1a recopié (un module pur n'importe rien)
  const a = FIELDS[h % FIELDS.length];
  const d = DIVISIONS[(h >>> 8) % DIVISIONS.length];
  const b = a === '#c99a2e' ? DARK : LIGHT[(h >>> 16) % LIGHT.length];
  return { d, a, b };
}
```

- [ ] **Step 4 : lancer, constater le succès.**
  - Même commande qu'à l'étape 2, puis `npm test` : 199 tests, ou plus si les tâches 2 et 4 de la vague sont déjà là.
  - Puis `GREG_TEST_TRANSPILE=1 npm test`.
- [ ] **Step 5 : pas de commit** (orchestrateur).

---

### Task 2 : le moteur des actions optimistes (pur), avec la correction C1

**Files:**
- Create: `services/web/src/lib/queue/optimistic.ts` (`R`, plus C1)
- Test: `services/web/tests/optimistic.test.mjs` (`R`, plus le test de C1)

**Interfaces:**
- Consumes : `import type { Snapshot, Track } from '../types'` (tâche 1 ; un import de type ne bloque pas le test).
- Produces :

```ts
export type MutationBody =
  | { kind: 'remove'; key: string }
  | { kind: 'move'; key: string; beforeKey: string | null }   // null : en fin de file
  | { kind: 'playAt'; key: string; fromKey: string | null }   // conditionnel : la scène est encore celle du clic
  | { kind: 'skip'; fromKey: string | null }                   // jamais de double saut
  | { kind: 'setPaused'; paused: boolean };
export type Mutation = MutationBody & { id: number; at: number; status: 'queued' | 'sent' | 'acked'; ackedAt?: number };
export const ACK_GRACE_MS = 4000;
export const HOLD_MAX_MS = 2500;
export function moveIndices(q: Track[], key: string, beforeKey: string | null): { src: number; dst: number } | null;
export function applyMutation(s: Snapshot, m: Mutation): Snapshot;
export const viewOf: (server: Snapshot, pending: readonly Mutation[]) => Snapshot;
export function isSatisfied(m: Mutation, s: Snapshot): boolean;
export function reconcile(pending: readonly Mutation[], server: Snapshot, now: number): Mutation[];
export function enqueueMutation(pending: readonly Mutation[], m: Mutation): Mutation[];
export interface QueueEngineOptions {
  initial: Snapshot; now: () => number;
  send: (m: Mutation, before: Snapshot) => Promise<unknown> | null;   // null : devenue sans effet
  onView: (view: Snapshot) => void;
  onRefused?: (m: Mutation, error: unknown, before: Snapshot) => void;
  holdMaxMs?: number;
}
export interface QueueEngine {
  view(): Snapshot; server(): Snapshot; pending(): readonly Mutation[];
  latest(): Snapshot;                     // C1 : l'état gardé en tampon s'il y en a un, sinon server()
  receive(next: Snapshot): void; dispatch(body: MutationBody): Promise<boolean>;
  hold(): void; release(): void; reset(next: Snapshot): void;
}
export function createQueueEngine(o: QueueEngineOptions): QueueEngine;
```

- [ ] **Step 1 : les tests qui échouent.** Recopier `R\tests\optimistic.test.mjs` (14 tests), puis y ajouter le test de C1 : le 15e.
  - Contenu de `R` :
    - `moveIndices` reproduit le bot (`insert(dst, pop(src))`) ;
    - déplacer : ancre disparue, titre disparu, même place ;
    - retirer, jouer maintenant et passer sont conditionnels, jamais de double saut ;
    - pause : l'horloge s'arrête à l'instant du clic ;
    - rapprochement ; regroupement des déplacements et des pauses non envoyés ;
    - moteur : vue immédiate ; refus = retour en arrière ; une requête à la fois ; état reçu gardé pendant l'action ; `HOLD_MAX_MS` ; glisser ; ordre sans effet ; `reset`.
  - Test de C1, à insérer juste après le test `'moteur : glisser = états gardés jusqu’au dépôt'` (une ligne vide avant et après) :

```js
test('moteur : latest() rend l’état gardé en tampon, base du tick suivant (rien ne se perd)', () => {
  const q = ['a', 'b'].map((k) => T(k));
  const { engine } = rig(snap(q));
  assert.equal(engine.latest(), engine.server(), 'rien en tampon : le dernier état appliqué');
  engine.hold();
  const withX = snap([...q, T('x')]);
  engine.receive(withX);                        // un courtisan ajoute x pendant le glisser : gardé
  assert.equal(engine.latest(), withX, 'un tick calculé sur server() remplacerait cet état et effacerait x');
  assert.equal(order(engine.server()), 'a,b');
  engine.receive({ ...withX, tickBase: { pos: 5, at: 1000, dur: 200 } });   // le tick, calculé sur latest()
  engine.release();
  assert.equal(order(engine.view()), 'a,b,x');
  assert.equal(engine.view().tickBase.pos, 5);
  assert.equal(engine.latest(), engine.server());
});
```

Extraits réels de `R` :

```js
test('moteur : une requête à la fois ; la suivante voit l’effet de la précédente', async () => {
  const q = ['a', 'b', 'c', 'd'].map((k) => T(k));
  const { engine, sent } = rig(snap(q));
  engine.dispatch({ kind: 'remove', key: 'b' });
  engine.dispatch({ kind: 'remove', key: 'd' });
  assert.equal(order(engine.view()), 'a,c');
  assert.equal(sent.length, 1, 'la deuxième attend');
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(sent.length, 2);
  assert.equal(order(sent[1].before), 'a,c,d', 'index de d calculé après le retrait de b');
});
test('moteur : un état reçu pendant l’action en vol attend sa fin (pas de clignotement)', async () => {
  const q = ['a', 'b', 'c'].map((k) => T(k));
  const { engine, sent, views } = rig(snap(q));
  engine.dispatch({ kind: 'move', key: 'c', beforeKey: 'a' });
  const n = views.length;
  engine.receive(snap([...q, T('x')]));        // quelqu'un ajoute x ; le bot n'a pas encore déplacé c
  assert.equal(views.length, n, 'rien ne bouge pendant l’action');
  sent[0].resolve({ ok: true });
  await flush();
  assert.equal(order(engine.view()), 'c,a,b,x', 'l’état gardé est appliqué, le déplacement rejoué dessus');
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/optimistic.test.mjs`
  - Attendu : FAIL, `ERR_MODULE_NOT_FOUND` (`src/lib/queue/optimistic.ts`).
- [ ] **Step 3 : implémenter.** Recopier `R\src\lib\queue\optimistic.ts`.
  - Relancer la commande : 14 tests verts, 1 FAIL, `TypeError: engine.latest is not a function` (le test de C1 échoue bien d'abord).
  - Puis appliquer C1, deux insertions exactes :
    - dans `interface QueueEngine`, remplacer la ligne `  pending(): readonly Mutation[];` par :

```ts
  pending(): readonly Mutation[];
  /** Dernier état reçu, celui gardé en tampon compris : un tick (snapshotFromPayload) se calcule dessus, sinon il l'écraserait. */
  latest(): Snapshot;
```

    - dans l'objet rendu par `createQueueEngine`, remplacer la ligne `    pending: () => pending,` par :

```ts
    pending: () => pending,
    latest: () => held ?? server,
```

  - Le cœur du moteur (`R`, inchangé par C1) :

```ts
function pump(): void {
  if (sending) return;
  const i = pending.findIndex((m) => m.status === 'queued');
  if (i < 0) return;
  const m = pending[i];
  const before = viewOf(server, pending.slice(0, i));          // ce que le bot verra
  let call: Promise<unknown> | null;
  try { call = o.send(m, before); } catch (e) { call = Promise.reject(e); }
  if (!call) { pending = pending.filter((p) => p.id !== m.id); refresh(); resolve(m.id, true); pump(); return; }
  const ep = epoch;
  sending = { id: m.id, since: o.now() };
  pending = pending.map((p) => (p.id === m.id ? { ...p, status: 'sent' } : p));
  const done = (ok: boolean) => { sending = null; flush(); refresh(); resolve(m.id, ok); pump(); };
  call.then(() => {
    if (ep !== epoch) return;
    const now = o.now();
    pending = reconcile(pending.map((p) => (p.id === m.id ? { ...p, status: 'acked', ackedAt: now } : p)), server, now);
    done(true);
  }, (e: unknown) => {
    if (ep !== epoch) return;
    pending = pending.filter((p) => p.id !== m.id);             // retour en arrière
    o.onRefused?.(m, e, before);
    done(false);
  });
}
// receive : holding() = glisser en cours, ou requête en vol depuis moins de holdMaxMs → l'état attend (le dernier seulement)
// latest (C1) : held ?? server — usePlayer (tâche 5) calcule chaque état reçu dessus, un tick ne remplace plus l'état gardé
```

- [ ] **Step 4 : lancer, constater le succès.** Même commande : 15 tests verts. Puis `npm test` (182 + 15, plus les tâches 1 et 4 si elles sont là : 221 à la fin de la vague A).
- [ ] **Step 5 : pas de commit.**

---

### Task 3 : le Héraut (pile, fusion ×N, survol, « Annuler », Ctrl+Z)

**Files:**
- Create: `services/web/src/lib/herald.ts` (pur), `services/web/src/components/Herald/store.ts`, `services/web/src/components/Herald/Herald.tsx`, `services/web/src/components/Herald/herald.css`
- Test: `services/web/tests/herald.test.mjs`

**Interfaces:**
- Consumes (tâche 1) : `errorCopy` (`lib/playerUtils.ts`) et `tx` (`theme/copy.extra.ts`). Consumes aussi `t`, `has`, `quip` (`theme/copy.ts`) et `seedOf` (`lib/stage/scene.ts`).
- Produces :

```ts
// src/lib/herald.ts
export type ToastKind = 'ok' | 'info' | 'warn' | 'err';
export type ToastAction = { label: string; run: () => void };
export type ToastInput = { kind?: ToastKind; fact: string; quip?: string | null; action?: ToastAction | null; ms?: number };
export type Toast = { id: number; kind: ToastKind; fact: string; quip: string | null; action: ToastAction | null; n: number; leaving: boolean };
export const LIFE = { ok: 3500, info: 4000, warn: 6000, err: 8000 }; export const ACTION_LIFE = 6500, RELEASE_MS = 2400,
  LEAVE_MS = 260, UNDO_MS = 15000, QUIP_EVERY_MS = 30000, VISIBLE = 3, STEP_Y = 14, STEP_SCALE = 0.05, GAP = 8;
export function stackLayout(heights: readonly number[], expanded: boolean): { y: number; s: number; o: number; z: number }[];
export function stackHeight(heights: readonly number[]): number;
export interface Herald { subscribe(fn: () => void): () => void; getSnapshot(): readonly Toast[]; notify(i: ToastInput): number;
  dismiss(id: number): void; act(id: number): void; undo(): boolean; hold(): void; release(): void }
export function createHerald(o: { now: () => number; setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (h: unknown) => void; announce?: (t: Toast) => void }): Herald;
// src/components/Herald/store.ts
export const herald: Herald;
export function useToasts(): readonly Toast[];                  // useSyncExternalStore
export function say(key: string, o?: { vars?: CopyVars; text?: string; action?: ToastAction | null; kind?: ToastKind }): number;
export function sayError(e: unknown, ctx?: { name?: string; q?: string; action?: string }): number;
export function setAnnouncer(fn: ((t: Toast) => void) | null): void;
// src/components/Herald/Herald.tsx
export default function Herald(props: { dock: 'panel' | 'center' }): JSX.Element;
```

- [ ] **Step 1 : le test qui échoue.** Recopier `R\tests\herald.test.mjs`, qui contient 8 tests avec une horloge et des minuteurs factices :
  - durées de vie ; fusion ×2 ; une action ne fusionne jamais ;
  - Ctrl+Z pendant 15 s ; bouton d'action ;
  - survol : les minuteurs s'arrêtent, puis repartent pour 2,4 s ;
  - une réplique toutes les 30 s au plus ; abonnés ;
  - pile repliée ou dépliée.

Extrait réel :

```js
test('pile : repliée (14 px, −5 %, 3 visibles) ou dépliée (hauteurs réelles + 8 px)', () => {
  const hs = [60, 80, 70, 50];
  assert.deepEqual(stackLayout(hs, false).map((p) => [p.y, +p.s.toFixed(2), p.o]), [[0, 1, 1], [14, 0.95, 1], [28, 0.9, 1], [42, 0.85, 0]]);
  assert.deepEqual(stackLayout(hs, true).map((p) => p.y), [0, 68, 156, 234]);
  assert.equal(stackHeight(hs), 60 + 2 * 14);
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/herald.test.mjs`
  - Attendu : FAIL, `ERR_MODULE_NOT_FOUND` (`src/lib/herald.ts`).
- [ ] **Step 3 : implémenter.** Recopier depuis `R` : `src/lib/herald.ts`, `src/components/Herald/store.ts`, `Herald.tsx` et `herald.css`.
  - `herald.css` est le portage de `styles.css`, lignes 502–523, avec ces changements :
    - la pile se place d'après `--panel-w` et `--page-x` ;
    - la couleur du bouton « Annuler » change sans transition ;
    - `@starting-style` pour l'entrée ;
    - le mouvement réduit passe en opacité seule.
  - `Herald.tsx` :
    - il écrit `--y --s --o` sur chaque plaque, et `--herald-h` (hauteur de la pile repliée + 16 px) sur `:root` ;
    - survol, focus et onglet caché mettent les minuteurs en pause ;
    - Ctrl+Z (hors champ de saisie) appelle `herald.undo()` ;
    - les annonces passent par deux régions `aria-live` persistantes (polie, ou assertive pour `err`), avec 40 ms d'écart pour NVDA et JAWS.
  - Point à ne pas perdre, mesuré dans Chrome : une plaque retirée sous le pointeur, ou qui avait le focus (clic sur « Annuler »), ne déclenche ni `mouseleave` ni `blur`. Sans cette revérification, les minuteurs restaient arrêtés pour toujours :

```tsx
useEffect(() => {
  const sec = sectionRef.current;
  if (!sec) return;
  if (focus && !sec.contains(document.activeElement)) setFocus(false);
  if (hover && !sec.matches(':hover')) setHover(false);
}, [toasts, focus, hover]);
```

  - `say` prend le fait dans `${key}.text` (ou `o.text`), la sorte dans `${key}.kind` et la réplique dans `${key}.quips` (`quip(key, seedOf(fait))`).
  - `sayError` passe par `errorCopy` : `PRIORITY_FORBIDDEN` nomme le demandeur (`ctx.name`), un refus de déplacement sans code devient `MOVE_CONFLICT`, et un état périmé devient `toast.stale`.
- [ ] **Step 4 : lancer, constater le succès.** Même commande : 8 tests verts. Puis `npm test`. Le composant n'est monté qu'à la tâche 5.
- [ ] **Step 5 : pas de commit.**

---

### Task 4 : mouvement de liste (jetons JS, présence et FLIP, glisser pur) et `useFlip`

**Files:**
- Create: `services/web/src/lib/motion.ts`, `services/web/src/lib/flip.ts`, `services/web/src/lib/queue/drag.ts` (purs), `services/web/src/hooks/useFlip.ts`
- Test: `services/web/tests/motion.test.mjs`

**Interfaces:**
- Consumes : `src/theme/tokens.css`, lu par le test.
- Produces :

```ts
// src/lib/motion.ts : mêmes valeurs que tokens.css (le test compare les 29 jetons)
export const DUR: { press: 120; hover: 150; micro: 160; popIn: 200; popOut: 120; shift: 200; exit: 180; enter: 260;
  text: 280; toast: 400; reveal: 420; flight: 420; glint: 900; ambient: 900; stagger: 30 };
export const EASE: Record<'out' | 'inOut' | 'drawer' | 'shift' | 'drop' | 'flash', string>;          // cubic-bezier de tokens.css
export const SPRING: Record<'snap' | 'move' | 'settle' | 'seal', { dur: number; easing: string }>;   // --spring-*-dur, linear(…)
export const FLASH_MS = 700, SHAKE_MS = 320; export const SHAKE_X = [0, -4, 4, -3, 2, 0] as const; export const STAGGER_CAP = 8;
export function reducedMotion(): boolean;                                // relu à chaque appel (réglage en direct)
// src/lib/flip.ts
export type Presence<T> = { key: string; item: T; leaving: boolean };
export function mergePresence<T>(prev: readonly Presence<T>[], next: readonly T[], keyOf: (t: T) => string): Presence<T>[];
export function dropLeft<T>(list: readonly Presence<T>[], key: string): Presence<T>[];
export function translateYOf(transform: string): number;
export function staggerDelay(i: number, step: number, cap?: number): number;
// src/lib/queue/drag.ts
export const DRAG_THRESHOLD = 4, EDGE = 50, MAX_SCROLL = 25, SETTLE_MS = 400, SETTLE_PX = 3, DEDUPE_MS = 500;
export function rubber(over: number, dim?: number, c?: number): number;
export function clampOffset(raw: number, tops: readonly number[], from: number): number;
export function targetIndex(tops: readonly number[], from: number, y: number, step: number): number;
export function shiftFor(i: number, from: number, to: number, step: number): number;
export function autoScrollSpeed(py: number, top: number, bottom: number, edge?: number, max?: number): number;
export function dropDuration(dist: number, cancel: boolean): number;   // 330 → 550 ms, ×0,6 à l'annulation
export function dropAnchor(keys: readonly string[], key: string, to: number): string | null;
export function createSettle(): { start(now: number): void; move(x: number, y: number, now: number): boolean; active(now: number): boolean };
export function createDedupe(ms?: number): (key: string, now: number) => boolean;
// src/hooks/useFlip.ts
export function useFlip<T>(listRef: RefObject<HTMLElement>, items: readonly T[], keyOf: (t: T) => string,
  opts?: { exitDir?: (key: string) => 1 | -1 }): { rendered: Presence<T>[]; freeze: () => void };
```

- [ ] **Step 1 : le test qui échoue.** Recopier `R\tests\motion.test.mjs`, qui contient 7 tests :
  - `lib/motion.ts` reprend à la lettre les jetons de `tokens.css` ;
  - présence : un titre parti reste le temps de sa sortie, après son ancien voisin, et redevient présent s'il revient ;
  - `translateYOf` et `staggerDelay` ;
  - glisser : rang visé, écart des voisins, élastique ;
  - défilement automatique et durée de dépôt ;
  - ancre du dépôt ;
  - accalmie et anti-doublon.

Extrait réel :

```js
test('accalmie : 400 ms, ou 3 px de mouvement ; anti-doublon 500 ms par titre', () => {
  const s = D.createSettle();
  s.start(1000);
  assert.ok(s.active(1399));
  assert.ok(!s.active(1400));
  s.start(2000);
  assert.equal(s.move(10, 10, 2010), false, 'premier mouvement : origine');
  assert.equal(s.move(12, 11, 2020), false);
  assert.equal(s.move(14, 10, 2030), true);
  const seen = D.createDedupe();
  assert.equal(seen('k1', 0), false);
  assert.equal(seen('k1', 499), true);
  assert.equal(seen('k2', 499), false);
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/motion.test.mjs`
  - Attendu : FAIL, `ERR_MODULE_NOT_FOUND` (`src/lib/motion.ts`).
- [ ] **Step 3 : implémenter.** Recopier depuis `R` : `src/lib/motion.ts`, `src/lib/flip.ts`, `src/lib/queue/drag.ts` et `src/hooks/useFlip.ts`.
  - Les calculs du glisser viennent de `app.js`, lignes 881–957 (`rubber`, `moveDrag`, `autoScroll`, `endDrag`), et de l'accalmie des lignes 793–803.
  - `useFlip`, après chaque rendu :
    - une ligne `[data-key]` enfant directe de la liste repart de son ancienne place (`translateY`, `SPRING.move`). Une animation en cours repart de là où elle en est (`translateYOf`) ;
    - une ligne nouvelle entre (fondu, 8 px, cascade de 30 ms plafonnée à 8), sauf au premier rendu ;
    - une ligne `data-leaving` sort en `position: absolute`, vers `exitDir(key)` (−1 : vers la scène), puis `dropLeft`.
  - `freeze()` : le rendu suivant remesure sans animer (dépôt d'un glisser).
  - Mouvement réduit : fondus seuls. Onglet caché : rien n'est animé.
  - **Contrat de l'appelant** : `items` est comparé par référence, et un nouveau tableau déclenche un `setState` pendant le rendu. L'appelant passe donc un tableau stable (mémoïsé), sinon les rendus bouclent (React #301). `QueuePanel` le fait avec C2 (tâche 6).
- [ ] **Step 4 : lancer, constater le succès.** Même commande : 7 tests verts. Puis `npm test`.
- [ ] **Step 5 : pas de commit.**

---

### Task 5 : `usePlayer` optimiste, `api.move`, le Héraut à la place de la barre de statut (avec C1)

**Files:**
- Modify: `services/web/src/hooks/usePlayer.ts` (réécrit : `R`, plus C1, plus la compat ci-dessous), `services/web/src/lib/api.ts` (ajout de `move`), `services/web/src/app/page.tsx`, `services/web/src/app/globals.css` (une ligne), `services/web/tests/api.test.mjs` (un test ajouté)
- Test: `services/web/tests/player-contract.test.mjs` (nouveau : `R`, test 1 renforcé pour C1)

**Interfaces:**
- Consumes :
  - tâche 1 : `snapshotFromPayload`, `emptySnapshot`, `addedCopy`, `addedKeys`, `restorePlan` ;
  - tâche 2 : `createQueueEngine`, `moveIndices`, et `QueueEngine.latest()` (C1) ;
  - tâche 3 : `herald`, `say`, `sayError`, `Herald`.
- Produces : le store et `playerActions` de « Contrats partagés », plus `api.move(guildId: string, userId: string, src: number, dst: number): Promise<any>`, qui envoie `POST /player/move`.
  - Compat provisoire, retirée à la tâche 6 : `playerActions.removeFromQueue(i: number)` et `playerActions.playAt(i: number)`.

- [ ] **Step 1 : les tests qui échouent.**
  - Recopier `R\tests\api.test.mjs`, qui ajoute ce test à la fin :

```js
test('api.move : POST /player/move {src, dst} (le bot fait insert(dst, pop(src)))', async () => {
  const realFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url: String(url), method: opts.method, body: JSON.parse(opts.body) });
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await api.move('42', '7', 3, 0);
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/v1\/player\/move$/);
    assert.equal(calls[0].method, 'POST');
    assert.deepEqual(calls[0].body, { src: 3, dst: 0, guild_id: '42', user_id: '7' });
  } finally {
    globalThis.fetch = realFetch;
  }
});
```

  - Créer `tests/player-contract.test.mjs`. C'est la copie de `R`, avec deux assertions de C1 en plus dans le test 1 :

```js
// Contrats de usePlayer (étape 3) : un seul chemin pour les états reçus, plus de barre de statut, le Héraut monté.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = (p) => readFileSync(fileURLToPath(new URL(`../${p}`, import.meta.url)), 'utf8');

test('usePlayer : les états reçus passent par le moteur optimiste, jamais directement dans le store', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.ok(src.includes('createQueueEngine('), 'moteur optimiste');
  assert.ok(src.includes("socket.on('playlist_update', onPlaylistUpdate)"));
  assert.ok(src.includes('const onPlaylistUpdate = (payload: any) => { receive(payload); };'), 'socket → receive → moteur');
  assert.ok(src.includes('snapshotFromPayload(payload, engine.latest(), performance.now())'), 'un tick se calcule sur l’état gardé en tampon');
  assert.ok(!src.includes('engine.server()'), 'jamais sur le seul dernier état appliqué');
  assert.ok(!/\b(?:applyPlaylistPayload|setPlayer|setTickBase)\b/.test(src), 'plus d’écriture directe de player / tickBase');
});

test('barre de statut retirée : ni status ni setStatus, le Héraut parle à sa place', () => {
  for (const f of ['src/hooks/usePlayer.ts', 'src/app/page.tsx']) {
    assert.ok(!/\bsetStatus\b|status\.(?:text|kind)|status-ok|status-err/.test(read(f)), f);
  }
  const page = read('src/app/page.tsx');
  assert.ok(!page.includes('<footer'), 'plus de barre de statut');
  assert.ok(page.includes('<Herald dock='), 'le Héraut est monté');
  assert.ok(read('src/app/globals.css').includes("@import '../components/Herald/herald.css';"));
});

test('le clavier de la page passe par les actions optimistes, pas par l’API', () => {
  const page = read('src/app/page.tsx');
  assert.ok(!page.includes("from '@/lib/api'"), 'page.tsx n’appelle plus l’API');
  assert.ok(page.includes('playerActions.togglePause()'));
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/api.test.mjs tests/player-contract.test.mjs`
  - Attendu : 4 FAIL sur 13, les 9 tests existants de `api.test.mjs` restent verts :
    - `api.move is not a function` ;
    - test 1 : `moteur optimiste` ;
    - test 2 : `src/hooks/usePlayer.ts` (il a encore `setStatus`) ;
    - test 3 : `page.tsx n’appelle plus l’API`.
- [ ] **Step 3 : `api.move`.** Recopier `R\src\lib\api.ts` : ajout de `move` avant `// Playlist controls`, commentaire d'en-tête inchangé.
- [ ] **Step 4 : `usePlayer.ts`.** Recopier `R\src\hooks\usePlayer.ts`, puis faire deux choses.
  - Relancer la commande de l'étape 2 : le test 1 échoue sur `un tick se calcule sur l’état gardé en tampon`. Le test de C1 est bien rouge avant C1. Les tests 2 et 3 attendent `page.tsx` (étape 5).
  - Appliquer C1, deux remplacements exacts (ce sont les deux seules lectures de `engine.server()` du fichier) :
    - `  const snap = snapshotFromPayload(payload, engine.server(), performance.now());` (dans `receive`) devient :

```ts
  const snap = snapshotFromPayload(payload, engine.latest(), performance.now());   // l'état gardé compris : un tick ne l'efface pas
```

    - `      const srv = engine.server();` (gel `BOT_OFFLINE` de `refreshPlaylist`) devient `      const srv = engine.latest();`.
  - Ajouter la compat de l'ancien panneau, que la tâche 6 retirera. Dans `playerActions`, juste après la ligne `  restartTrack: () => command((g, u) => api.restart(g, u)),` :

```ts
  // Compat de l'ancien panneau (index de la file affichée) : retirée à la tâche 6.
  removeFromQueue: (i: number) => removeTrack(engine.view().player.queue[i]?.key ?? ''),
  playAt: (i: number) => playNow(engine.view().player.queue[i]?.key ?? ''),
```

Logique clé (`R`, avec C1) :

```ts
// Indices calculés sur `before`, l'état que le bot verra (une requête à la fois) ; null : devenu sans effet.
function sendMutation(m: Mutation, before: Snapshot): Promise<unknown> | null {
  const s = useStore.getState();
  if (!s.me || !s.guildId) return null;
  const gid = s.guildId, uid = s.me.id;
  const q = before.player.queue;
  const at = (key: string) => q.findIndex((x) => x.key === key);
  switch (m.kind) {
    case 'remove': { const i = at(m.key); return i < 0 ? null : api.queueRemove(gid, uid, i); }
    case 'move': { const mv = moveIndices(q, m.key, m.beforeKey); return mv ? api.move(gid, uid, mv.src, mv.dst) : null; }
    case 'playAt': {
      const i = at(m.key);
      return i < 0 || (before.player.current?.key ?? null) !== m.fromKey ? null : api.playAt(gid, uid, i);
    }
    case 'skip': return before.player.current && before.player.current.key === m.fromKey ? api.queueSkip(gid, uid) : null;
    case 'setPaused': return before.player.current && before.player.paused !== m.paused ? api.togglePause(gid, uid) : null;
  }
}
const engine = createQueueEngine({
  initial: EMPTY, now: () => performance.now(), send: sendMutation,
  onView: (v) => useStore.setState({ player: v.player, tickBase: v.tickBase }),
  onRefused: (m, e, before) => { sayError(e, { name: requesterName(m, before), action: m.kind === 'move' ? 'move' : undefined }); },
});
/** État reçu (REST ou socket) : clés, partage structurel, tampon pendant une action ou un glisser. */
function receive(payload: any): boolean {
  const snap = snapshotFromPayload(payload, engine.latest(), performance.now());   // l'état gardé compris : un tick ne l'efface pas
  if (!snap) return false;
  engine.receive(snap);
  return true;
}
/** « Annuler » d'un retrait : le titre est rajouté (le bot n'a pas de « remettre »), puis replacé. */
async function restoreTrack(x: Track, index: number) {
  const s = useStore.getState();
  if (!s.me || !s.guildId) return;
  const before = engine.view().player.queue.map((q) => q.key);
  try { await api.queueAdd(s.guildId, s.me.id, trackPayload(x)); } catch (e) { sayError(e); return; }
  await refreshPlaylist({ quiet: true }).catch(() => {});
  const plan = restorePlan(before, engine.view().player.queue, x.url, index);
  if (plan) await engine.dispatch({ kind: 'move', key: plan.key, beforeKey: plan.beforeKey });
}
async function removeTrack(key: string, o: { silent?: boolean } = {}): Promise<boolean> {
  const q = engine.view().player.queue;
  const i = q.findIndex((x) => x.key === key);
  if (i < 0) return false;
  const x = q[i];
  const id = o.silent ? 0 : say('toast.removed', {                   // le toast part tout de suite, avec la ligne
    vars: { title: songOf(x) },
    action: { label: t('toast.removed.action'), run: () => { void restoreTrack(x, i); } },
  });
  const ok = await engine.dispatch({ kind: 'remove', key });
  if (!ok && id) herald.dismiss(id);                                 // refusé : le toast s'efface, l'erreur parle
  return ok;
}
```

Autres points de `R` :
- **`enqueue`.** Il capture les clés avant l'ajout, relit l'état (`refreshPlaylist({ quiet: true })`), puis dit `addedCopy(res)` : « Ajouté : … » ou « Playlist ajoutée : 12 titres sur 20 ». Le toast propose d'annuler l'ajout si `addedKeys` trouve les nouvelles lignes du Roi ; l'annulation les retire en silence.
- **`playNext(key)`.**
  - Déjà prochain : `toast.alreadyNext`.
  - Sinon, déplacement devant `queue[0]`, avec le toast `toast.playNext` et « Annuler », qui remet le titre devant son ancien voisin.
- **`playNow`** : `playAt`, conditionné au titre en cours ; `toast.playNow` sans « Annuler » (écart 2). **`skip`** et **`togglePause`** : optimistes, sans toast.
- **`stop`, `toggleRepeat`, `restartTrack`** passent par `command()` : non optimistes, erreurs au Héraut.
- **Anciens messages de statut** :
  - socket coupé ou rétabli : `toast.socketDown` / `toast.socketUp`, un par changement ;
  - état périmé : `sayError(e, { action: 'state' })` ; retour : `toast.recovered` ;
  - déconnexion : `toast.loggedOut` ; session perdue : `sayError` (401) ;
  - `boot` ne dit plus rien.
- **Gel de la progression, bot hors ligne** : `srv = engine.latest()` (C1), puis `engine.receive({ player: { ...srv.player, paused: true, position: pos }, tickBase: { pos, at: now, dur } })`.
- **Changer de serveur, se déconnecter** : `engine.reset(emptySnapshot(performance.now()))`.

- [ ] **Step 5 : `page.tsx` et `globals.css`.**
  - Recopier `R\src\app\page.tsx`, puis y remettre `<Sidebar/>` sans props : l'ancien `Sidebar` n'en a pas, et la tâche 7 remettra `booted={booted}`. Le fichier obtenu :
    - n'importe plus `api` : le clavier appelle `playerActions.togglePause()` (Espace), `.skip()` (n), `.restartTrack()` (p) et `.toggleRepeat()` (r) ;
    - retire la barre de statut (`<footer>` et `status`) ;
    - monte `<Herald dock={booted && me ? 'panel' : 'center'}/>` après le bloc principal.
  - Dans `globals.css`, après `@import '../components/Stage/night.css';`, ajouter :

```css
@import '../components/Herald/herald.css';
```

- [ ] **Step 6 : lancer, constater le succès.**
  - Même commande qu'à l'étape 2 : 13 tests verts (10 + 3).
  - `npm test` : 233 tests. `GREG_TEST_TRANSPILE=1 npm test` : 233.
  - `npx tsc --noEmit` et `npx next build`, si la tâche tourne seule dans sa vague (c'est le cas ici).
- [ ] **Step 7 : contrôle rapide dans le navigateur** (fausse API + `next start -p 3100`). Avec l'ancien panneau :
  - retirer un titre : la ligne part tout de suite, et « Retiré : … » s'affiche avec « Annuler » ;
  - « Annuler » : le titre revient à sa place (`GET http://localhost:3999/api/v1/playlist?guild_id=1`) ;
  - avec `/__mock?refuse=remove` : la ligne revient et « Action impossible : … » s'affiche ;
  - Espace : le bouton lecture/pause bascule sans attendre.
  - Arrêter les serveurs.
- [ ] **Step 8 : pas de commit.**

---

### Task 6 : la file (lignes, actions rapides, accalmie, glisser-déposer), avec C2 et C3

**Files:**
- Create: `services/web/src/components/Queue/QueueRow.tsx`, `Shield.tsx`, `useQueueDrag.ts`, `queue.css`
- Modify:
  - `services/web/src/components/Queue/QueuePanel.tsx` : réécrit (`R`, plus C2 et C3) ;
  - `services/web/src/hooks/usePlayer.ts` : retirer les 3 lignes de compat de la tâche 5. **Ne pas le recopier depuis `R`**, ce qui perdrait C1. Le fichier devient `R` plus C1 ;
  - `services/web/src/app/globals.css` : une ligne.
- Test: `services/web/tests/_contract.mjs` (aides, pas un test), `services/web/tests/queue-panel.test.mjs` (`R`, test 3 renforcé pour C2 et C3)

**Interfaces:**
- Consumes :
  - tâche 1 : `queueEtas`, `armsOf`, `SHIELD_PATH`, `tx` ;
  - tâche 4 : `useFlip`, `createSettle`, `createDedupe`, calculs du glisser et `motion.ts` ;
  - tâche 5 : `useStore`, `playerActions`.
- Produces :

```ts
// QueuePanel.tsx
export const MAX_ROWS = 60;
export default function QueuePanel(props: { after?: ReactNode }): JSX.Element;   // after : « Souvent demandés ici » (tâche 7)
// QueueRow.tsx
export function thumbOf(x: { thumb?: string | null; thumbnail?: string | null; url?: string }): string | null;
export type QueueRowProps = { item: Track; eta: string; next: boolean; sealSrc: string | null; picked: boolean; leaving: boolean };
export default memo(QueueRow);
// Shield.tsx
export default function Shield(props: { id: string | null | undefined }): JSX.Element;   // clipPath par useId
// useQueueDrag.ts
export type QueueDragOptions = { listRef: RefObject<HTMLElement>; scrollRef: RefObject<HTMLElement>; order: string;
  onLift: () => void; onEnd: () => void; onDrop: (key: string, beforeKey: string | null) => Promise<boolean>;
  freeze: () => void; settle: () => void };
export function useQueueDrag(o: QueueDragOptions): { onPointerDown: (e: React.PointerEvent) => void; swallowClick: () => boolean };
export function flashRow(li: HTMLElement | null | undefined): void;
export function refuseRow(li: HTMLElement | null | undefined): void;
// tests/_contract.mjs
export const path: (p: string) => string; export const read: (p: string) => string;
export function animated(css: string): string[];     // propriétés des transition: et @keyframes
export function assertKeys(files: string[]): number; // chaque t('…') / quip('…') / tx('…') cité existe
```

- DOM produit, que `Sidebar` (tâche 7) et `verif.py` lisent :

```
div.qpane > div.scroller > div.qcontent > ol.qlist > li.row[data-key] > div.card > (span.grip, div.thumb > (div.im > img, span.seal),
  div.meta > (div.t[title=brut], div.a > (span.nm, span.dot-sep, svg.shield, span.by)), div.side > (span.dur, span.eta),
  div.acts > button.act[data-act=play|next|del], span.flash)
div.qpane > div.panel-foot > span.hint[data-shown]
```

- [ ] **Step 1 : le test qui échoue.**
  - Recopier `R\tests\_contract.mjs`. Il exporte `path`, `read`, `animated(css)` (même extraction que `stage-contract.test.mjs`) et `assertKeys(files)`.
  - Créer `tests/queue-panel.test.mjs`. C'est la copie de `R`, avec le test 3 renforcé pour C2 et C3 :

```js
// La file (étape 3, tâche 6) : mouvement de queue.css, casting du sceau, repli à 60 lignes, textes cités.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { animated, assertKeys, path, read } from './_contract.mjs';

const QUEUE = readdirSync(path('src/components/Queue')).filter((f) => /\.tsx?$/.test(f)).map((f) => `src/components/Queue/${f}`);

test('queue.css : transform et opacity seulement, mouvement réduit prévu, importée', () => {
  const css = read('src/components/Queue/queue.css');
  for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), `anime « ${prop} »`);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.ok(read('src/app/globals.css').includes("@import '../components/Queue/queue.css';"));
});

test('casting : le sceau royal ne va que sur les titres du Roi ; aucune couronne dans la file', () => {
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /requesterOf\(item\.addedBy, me\?\.id\)\.kind === 'mine'/);
  assert.match(panel, /sealSrc=\{mine \? seal : null\}/);
  assert.match(panel, /kingSealSrc\(kingName\(me\)\)/);
  for (const f of QUEUE) assert.ok(!/crown|couronne|\bRex\b/i.test(read(f)), `${f} : couronne`);
});

test('file longue repliée à 60 lignes (tech.md §6.4) ; compat de l’ancien panneau retirée', () => {
  const panel = read('src/components/Queue/QueuePanel.tsx');
  assert.match(panel, /export const MAX_ROWS = 60;/);
  // une tranche neuve à chaque rendu fait boucler useFlip (React #301 dès 61 titres)
  assert.ok(panel.includes('useMemo(() => (queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue), [queue])'), 'tranche mémoïsée');
  assert.ok(panel.includes('beforeKey ?? queue[MAX_ROWS]?.key ?? null'), 'dépôt sous la dernière ligne visible : devant le premier titre caché');
  assert.ok(!/removeFromQueue|playAt: \(i/.test(read('src/hooks/usePlayer.ts')), 'compat retirée');
});

test('textes de la file : chaque clé citée existe', () => {
  assert.ok(assertKeys(QUEUE) >= 12);
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/queue-panel.test.mjs`
  - Attendu : 4 FAIL : `queue.css` absent (ENOENT), pas de `requesterOf`, pas de `MAX_ROWS`, moins de 12 clés.
- [ ] **Step 3 : implémenter.**
  - Recopier depuis `R` : `src/components/Queue/QueuePanel.tsx`, `QueueRow.tsx`, `Shield.tsx`, `useQueueDrag.ts` et `queue.css`. **Pas `usePlayer.ts`.**
  - Dans `globals.css`, juste avant `@import '../components/Herald/herald.css';`, ajouter :

```css
@import '../components/Queue/queue.css';
```

  - Relancer la commande : 3 verts, 1 FAIL (test 3, `tranche mémoïsée`). Les tests de C2 et C3 échouent bien d'abord.
  - Appliquer C2 et C3 à `QueuePanel.tsx`, trois remplacements exacts :
    - C2, import. `import { useCallback, useEffect, useRef, useState } from 'react';` devient `import { useCallback, useEffect, useMemo, useRef, useState } from 'react';`.
    - C2, tranche. `  const shown = queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue;` devient :

```tsx
  // même tableau tant que la file ne change pas : useFlip compare `items` par référence (une tranche neuve à chaque rendu boucle)
  const shown = useMemo(() => (queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue), [queue]);
```

    - C3. `    onDrop: (key, beforeKey) => playerActions.moveTrack(key, beforeKey),` devient :

```tsx
    // file repliée : déposé sous la dernière ligne visible = devant le premier titre caché (pas en fin de file)
    onDrop: (key, beforeKey) => playerActions.moveTrack(key, beforeKey ?? queue[MAX_ROWS]?.key ?? null),
```

  - Relancer : 1 FAIL, `compat retirée`.
  - Dans `usePlayer.ts`, supprimer les 3 lignes de compat ajoutées à la tâche 5 : le commentaire `// Compat de l'ancien panneau…`, `removeFromQueue: …` et `playAt: …`. Rien d'autre ne change : C1 reste.
  - Sources des portages :
    - `QueueRow` : `app.js`, lignes 638–670 (`rowFor`, `fillRow`) et icônes 168–177 ; libellés `queue.actions.*`, `queue.mine.*` et `tx('queue.rowAria…')`.
    - `Shield` : lignes 155–166 (`shieldSvg`).
    - `queue.css` : `styles.css`, lignes 321, 394–398, 400–427, 432–456, 460, 462–464, 471–474, 539–540 et 555–589. Écarts : couleurs de survol sans transition, `@media (prefers-reduced-motion: reduce)`, pas de ligne en attente ni de crochet de lot, `padding-bottom: max(12px, var(--herald-h, 0px))` sur `.scroller`, `.qpane { height: 100% }`.
  - Logique clé de `QueuePanel` (`R`, avec C2 et C3) :

```tsx
const shown = useMemo(() => (queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue), [queue]);   // C2 : référence stable
const exitDir = useCallback((key: string) => (key === currentKey ? -1 : 1) as 1 | -1, [currentKey]); // joué : vers la scène
const { rendered, freeze } = useFlip(listRef, shown, keyOf, { exitDir });
const settle = useCallback(() => {                  // après retrait, jouer, en suivant, dépôt : clics ignorés 400 ms / 3 px
  const list = listRef.current;
  const s = settleRef.current;
  s.start(performance.now());
  list?.classList.add('settling');
  const done = () => { if (!s.active(performance.now())) list?.classList.remove('settling'); };
  const onMove = (e: PointerEvent) => { if (s.move(e.clientX, e.clientY, performance.now())) { done(); window.removeEventListener('pointermove', onMove); } };
  window.addEventListener('pointermove', onMove);
  setTimeout(() => { done(); window.removeEventListener('pointermove', onMove); }, 420);
}, []);
const drag = useQueueDrag({ listRef, scrollRef, freeze, settle, order: rendered.map((p) => p.key).join('\n'),
  onLift: () => playerActions.setDragging(true), onEnd: () => playerActions.setDragging(false),
  onDrop: (key, beforeKey) => playerActions.moveTrack(key, beforeKey ?? queue[MAX_ROWS]?.key ?? null) });   // C3
const playNow = (key: string) => { if (dedupeRef.current(key, performance.now())) return; settle(); void playerActions.playNow(key); };
const onClick = (e: MouseEvent) => {                // un clic sélectionne ; la puce agit
  if (drag.swallowClick()) return;
  const key = rowOf(e);                             // null si ligne qui sort, ou accalmie
  if (!key) return;
  const act = (e.target as HTMLElement).closest<HTMLElement>('[data-act]')?.dataset.act;
  if (act === 'del') { settle(); void playerActions.removeTrack(key); return; }
  if (act === 'next') { settle(); void playerActions.playNext(key); return; }
  if (act === 'play') { playNow(key); return; }
  setPicked(key);
};
// onDoubleClick : hors puce et poignée → playNow(key)
```

  - Logique clé de `useQueueDrag` : le dépôt efface les décalages **dans le même rendu** que le nouvel ordre, sans saut visible :

```ts
useLayoutEffect(() => { pendingClear.current?.(); pendingClear.current = null; }, [o.order]);
// fin de l'animation de dépôt (dropDuration, EASE.drop ; 0 en mouvement réduit) :
const finish = () => {
  const o2 = opts.current;
  if (cancel || to === d.from) { clear(); o2.onEnd(); return; }
  const keys = d.rows.map((r) => r.dataset.key || '');
  const key = d.li.dataset.key || '';
  pendingClear.current = clear;
  o2.freeze();
  o2.settle();
  o2.onDrop(key, dropAnchor(keys, key, to)).then((ok) => { if (!ok) refuseRow(d.li); });   // refus : secousse à 40 % du ressort
  o2.onEnd();
  requestAnimationFrame(() => { pendingClear.current?.(); pendingClear.current = null; }); // filet
  flashRow(d.li);
};
```

  - Le glisser part de `.grip` ou de `.thumb`, après 4 px (`DRAG_THRESHOLD`), jamais du corps de la ligne ni de `.act`.
    - La ligne suit le pointeur avec `clampOffset(py − grab − haut de la liste − tops[from])` ; les autres lignes s'écartent de `shiftFor` avec `transition: transform 200ms --ease-shift`.
    - `autoScrollSpeed` s'applique à chaque image ; Échap et `pointercancel` annulent.
    - `setPointerCapture` ; classes `.dragging` sur la ligne et `.is-dragging` sur `body`.
    - Les états reçus attendent le dépôt : `playerActions.setDragging`.
- [ ] **Step 4 : lancer, constater le succès.**
  - `node --test tests/queue-panel.test.mjs` : 4 tests verts. `npm test` : 237. `GREG_TEST_TRANSPILE=1 npm test` : 237.
  - `npx tsc --noEmit` et `npx next build`.
- [ ] **Step 5 : contrôle rapide dans le navigateur.** L'ancien `Sidebar` monte la nouvelle file ; le panneau définitif arrive à la tâche 7. Vérifier :
  - glisser la ligne 4 en tête par la poignée ; l'ordre du serveur suit ;
  - Échap pendant un glisser ;
  - `/__mock?refuse=move`, puis un glisser par la pochette : la ligne revient et secoue ;
  - double-clic puis un troisième clic : un seul titre joué ;
  - C2 et C3, avec une file de 68 titres (commande ci-dessous), puis un rechargement :
    - 60 lignes et « …et 8 autres titres », sans erreur React #301 dans la console ;
    - déposer la ligne 58 sous la ligne 60 : le serveur la met au rang 59 (base 0), pas en fin de file.

```bash
for i in $(seq -w 0 61); do curl -s -o /dev/null -X POST http://localhost:3999/api/v1/queue/add -H 'content-type: application/json' \
  -d "{\"guild_id\":\"1\",\"user_id\":\"101\",\"url\":\"https://youtu.be/long00000$i\",\"query\":\"https://youtu.be/long00000$i\",\"title\":\"Long $i\"}"; done
curl -s 'http://localhost:3999/__mock?scene=playing'   # après le contrôle : la file revient à 6 titres
```

  - Arrêter les serveurs.
- [ ] **Step 6 : pas de commit.**

---

### Task 7 : panneau, historique, « Souvent demandés ici », nettoyage legacy et vérification dans le navigateur (avec C4)

**Files:**
- Create: `services/web/src/components/panel.css`, `services/web/src/components/History/HistoryRow.tsx`, `Suggestions.tsx`, `useRequeue.ts` (`R`, plus C4), `history.css`
- Modify: `services/web/src/components/Sidebar.tsx` et `services/web/src/components/History/HistoryPanel.tsx` (réécrits) ; `services/web/tailwind.config.js` (alias legacy retirés) ; `services/web/src/app/globals.css` (état final) ; `services/web/src/app/page.tsx` (`<Sidebar booted={booted}/>`)
- Test: `services/web/tests/queue-contract.test.mjs` (`R`, plus le test de C4)

**Interfaces:**
- Consumes :
  - tâche 1 : `oftenAsked`, `agoOf`, `clockText`, `endsAt`, `fmtLong`, `queueSeconds`, `HistoryItem`, `tx` ;
  - tâche 3 : `Herald` (le contrat vérifie son portrait) ;
  - tâche 4 : `EASE`, `reducedMotion` (`lib/motion.ts` : volets de `Sidebar`, bouton « Actualiser ») ; `createDedupe` (`lib/queue/drag.ts`, C4) ;
  - tâche 5 : `useStore`, `playerActions` ;
  - tâche 6 : `QueuePanel` (`after`), `QueueRow.thumbOf`, `Shield`, `.qcontent`, les classes `.row` / `.card` / `.thumb` / `.meta`.
- Produces :

```ts
// Sidebar.tsx
export default function Sidebar(props: { booted?: boolean }): JSX.Element;   // aside.panel, onglets #tab-queue / #tab-hist
// History/HistoryRow.tsx
export type HistoryRowProps = { item: HistoryItem; rank: number; meta: string; byName: string; variant: 'hrow' | 'srow'; picked: boolean };
export default memo(HistoryRow);
// History/useRequeue.ts
export function requeue(item: HistoryItem): void;                           // playerActions.enqueue(…) : toast « Ajouté », annulable
export function useRequeueList(items: readonly HistoryItem[]): { picked: string | null; onClick: (e: MouseEvent) => void; onDoubleClick: (e: MouseEvent) => void };
// ↑ C4 : « + » et double-clic passent par add(), un seul ajout par 500 ms (createDedupe, clé commune 'add')
// History/Suggestions.tsx, History/HistoryPanel.tsx
export default function Suggestions(): JSX.Element | null;
export default function HistoryPanel(): JSX.Element;
```

- [ ] **Step 1 : le test qui échoue.** Créer `tests/queue-contract.test.mjs`. C'est la copie de `R`, avec un 6e test, celui de C4 :

```js
// Le panneau, l'historique et le Héraut (étape 3, tâche 7) : mouvement, textes, casting, nettoyage legacy.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { animated, assertKeys, path, read } from './_contract.mjs';

const SHEETS = ['src/components/panel.css', 'src/components/History/history.css', 'src/components/Herald/herald.css'];
const FILES = [
  ...['src/components/History', 'src/components/Herald'].flatMap((d) => readdirSync(path(d)).filter((f) => /\.tsx?$/.test(f)).map((f) => `${d}/${f}`)),
  'src/components/Sidebar.tsx',
];

test('mouvement : transform et opacity seulement, mouvement réduit prévu', () => {
  for (const f of SHEETS) {
    const css = read(f);
    for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), `${f} : anime « ${prop} »`);
    if (animated(css).includes('transform')) assert.match(css, /prefers-reduced-motion:\s*reduce/, f);
  }
});

test('globals.css importe les feuilles du panneau ; les classes legacy ont disparu', () => {
  const css = read('src/app/globals.css');
  for (const f of SHEETS) assert.ok(css.includes(`@import '../${f.replace('src/', '')}';`), f);
  for (const cls of ['.glass', '.glass-subtle', '.btn-accent', '.q-item', '.q-thumb', '.tab-active', '.status-ok', '.status-err', '.loading-spin']) {
    assert.ok(!new RegExp(`\\${cls}\\b`).test(css), `${cls} encore dans globals.css`);
  }
});

test('alias Tailwind legacy supprimés, et plus aucune classe qui s’en sert', () => {
  const cfg = read('tailwind.config.js');
  for (const alias of ['surface', 'accent', 'teal', 'rose', 'txt', 'border']) assert.ok(!new RegExp(`\\b${alias}\\s*:`).test(cfg), `alias ${alias}`);
  const walk = (dir) => readdirSync(path(dir), { withFileTypes: true }).flatMap((e) => (e.isDirectory()
    ? walk(`${dir}/${e.name}`) : /\.tsx?$/.test(e.name) ? [`${dir}/${e.name}`] : []));
  // classes des attributs className (chaînes et gabarits), variantes retirées (hover:, max-[900px]:…)
  const LEGACY = /^(?:(?:bg|text|border|ring)-(?:surface|accent|teal|rose|txt|border)(?:-\S+)?|glass|glass-subtle|q-item|q-thumb|tab-active|btn|btn-accent|status-ok|status-err|loading-spin)$/;
  const classes = (src) => [...src.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)]
    .flatMap((m) => (m[1] ?? m[2]).replace(/\$\{[^}]*\}/g, ' ').split(/\s+/)).filter(Boolean).map((c) => c.split(':').pop());
  for (const f of walk('src')) for (const c of classes(read(f))) assert.ok(!LEGACY.test(c), `${f} : classe legacy « ${c} »`);
});

test('textes du panneau, de l’historique et du Héraut : chaque clé citée existe', () => {
  assert.ok(assertKeys(FILES) >= 15);
});

test('casting : Greg parle avec son portrait de valet ; ni couronne ni « Rex » dans le panneau et le Héraut', () => {
  assert.ok(read('src/components/Herald/Herald.tsx').includes('/gothique/greg-face-96.webp'));
  for (const f of FILES) assert.ok(!/crown|couronne|\bRex\b/i.test(read(f)), `${f} : couronne`);
});

test('historique : « + » ou double-clic, un seul ajout par 500 ms (createDedupe)', () => {
  const src = read('src/components/History/useRequeue.ts');
  assert.match(src, /createDedupe\(\)/);
  assert.equal(src.match(/\badd\(it\)/g)?.length, 2, '« + » et double-clic passent par la garde');
  assert.ok(!/requeue\(it\)/.test(src), 'aucun ajout sans la garde');
});
```

- [ ] **Step 2 : lancer, constater l'échec.**
  - Commande : `cd services/web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/queue-contract.test.mjs`
  - Attendu : 5 FAIL sur 6.
    - `panel.css` est absent (ENOENT) ;
    - `globals.css` n'importe pas `panel.css` (et `.glass` y est encore) ;
    - l'alias `surface` est encore là (puis les classes `bg-surface-3`, `text-txt-muted`…) ;
    - moins de 15 clés ;
    - `useRequeue.ts` est absent (ENOENT).
  - Le test `casting` passe déjà : c'est une garde, car le Héraut et son portrait existent depuis la tâche 3, et l'ancien `HistoryPanel` n'a pas de couronne.
- [ ] **Step 3 : panneau, historique, suggestions.** Recopier depuis `R` : `src/components/Sidebar.tsx`, `panel.css`, `src/components/History/HistoryPanel.tsx`, `HistoryRow.tsx`, `Suggestions.tsx`, `useRequeue.ts` et `history.css`.
  - Puis appliquer C4 à `useRequeue.ts`. Le fichier complet, après correction :

```ts
'use client';

import { useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { playerActions } from '@/hooks/usePlayer';
import { createDedupe } from '@/lib/queue/drag';
import type { HistoryItem } from '@/lib/queue/view';

/** Remettre un titre de l'historique dans la file (un ajout du Roi : toast « Ajouté », annulable). */
export function requeue(item: HistoryItem): void {
  if (!item.url && !item.title) return;
  playerActions.enqueue({
    query: item.url || item.title, url: item.url, title: item.title, artist: item.artist,
    thumb: item.thumb, duration: item.duration, provider: item.provider || 'youtube',
  }).catch(() => {});   // l'erreur est déjà annoncée par le Héraut
}

/**
 * Clics d'une liste d'historique (délégués) : un clic sélectionne, un double-clic ou « + » remet dans la file.
 * Un seul ajout par 500 ms : « + » cliqué deux fois, ou la ligne de « Souvent demandés ici » qui remonte sous le
 * pointeur quand la précédente entre dans la file, ne remettent pas un second titre.
 */
export function useRequeueList(items: readonly HistoryItem[]) {
  const [picked, setPicked] = useState<string | null>(null);
  const once = useRef(createDedupe());
  const add = (item: HistoryItem) => { if (!once.current('add', performance.now())) requeue(item); };
  const itemOf = (e: MouseEvent) => {
    const url = (e.target as HTMLElement).closest<HTMLElement>('.row')?.dataset.url;
    return url ? items.find((x) => x.url === url) ?? null : null;
  };
  const onClick = (e: MouseEvent) => {
    const it = itemOf(e);
    if (!it) return;
    if ((e.target as HTMLElement).closest('[data-act=add]')) add(it);
    else setPicked(it.url || null);
  };
  const onDoubleClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest('[data-act=add]')) return;
    const it = itemOf(e);
    if (it) add(it);
  };
  return { picked, onClick, onDoubleClick };
}
```

  - Par rapport à `R` : l'import de `useRef` et de `createDedupe`, deux lignes de commentaire, les lignes `once` et `add`, et deux `requeue(it)` devenus `add(it)`.
  - Sources des portages :
    - `Sidebar` : `body.html`, lignes 159–209 ; onglets et volets, `app.js` 1262–1285 ;
    - `HistoryRow` : `app.js` 1209–1219 ; `Suggestions` : 1227–1235 (données : `oftenAsked`) ;
    - `panel.css` : `styles.css`, lignes 371–393, 483–485 et 555–589 ; `history.css` : lignes 476–482 et 488–500.
  - Logique clé de `Sidebar` :

```tsx
const summary = !booted ? t('queue.tab.zero') : !n ? t('queue.empty.title')
  : `${t('queue.subtitle', { n })}${t('queue.durationSuffix', { dur: fmtLong(queueSeconds(queue)) })} · ${tx('queue.endsAt', { time: clockText(endsAt(Date.now(), remaining, queue)) })}`;
// l'ancien volet s'efface (60 ms), puis le nouveau entre (140 ms, 4 px) : jamais deux listes à la fois
const switchTo = (next: Tab) => {
  if (next === tab) return;
  for (const a of anims.current) a.cancel();
  if (reducedMotion()) { setTab(next); return; }
  const outs = groupOf(tab).map((el) => el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 60, easing: 'ease-out', fill: 'forwards' }));
  anims.current = outs;
  (outs[0]?.finished ?? Promise.resolve()).then(() => { incoming.current = next; setTab(next); }, () => {});
};
// useLayoutEffect([tab]) : entrée du volet `incoming` ; un autre useLayoutEffect([tab]) observe .scroller et .qcontent
// (ResizeObserver) : data-roomy={place vide > 190 px} fait paraître les ménestrels (opacité .075).
<QueuePanel after={<Suggestions/>}/>
```

  - `HistoryPanel` :
    - « Plus joués » = `historyItems` du store (`playerActions.refreshHistory`) ; « Récents » = liste locale (`api.getHistory(guildId, 'recent', 30)`) ;
    - rang : `mode === 'top' ? i + 1 : 0`, doré jusqu'à 3 ; méta : `tx('history.plays', { n })` ou `tx('history.ago.<unit>', { n })` ;
    - demandeur : `t('history.mine')` si c'est le Roi, un nom de la file sinon, ou rien ;
    - bouton « Actualiser » : un tour de 500 ms (`EASE.inOut`), sauf en mouvement réduit ;
    - états : `history.noGuild`, `history.loading.text`, `history.empty.*`.
- [ ] **Step 4 : nettoyage legacy.**
  - Recopier `R\tailwind.config.js` : les six alias marqués `// legacy: supprimé à l'étape 3` (surface, accent, teal, rose, txt, border) disparaissent ; les tokens `nuit…gueules`, les polices, `borderRadius`, `boxShadow`, `keyframes` et `animation` restent.
  - Recopier `R\src\app\globals.css`, état final :
    - les imports `panel.css`, `Queue/queue.css`, `History/history.css` et `Herald/herald.css` suivent `Stage/night.css` ;
    - tout le bloc `/* ═══ Components (legacy… */` (`.glass`, `.glass-subtle`, `.btn`, `.btn-accent`, `.q-item`, `.q-thumb`, `.tab`, `.tab-active`, `.status-*`, `.loading-spin` et son `@keyframes spin`) disparaît. `header.css` a son propre `@keyframes spin`.
  - Dans `page.tsx`, remplacer `<Sidebar/>` par `<Sidebar booted={booted}/>` : le fichier est alors identique à `R`.
- [ ] **Step 5 : lancer, constater le succès.**
  - `node --test tests/queue-contract.test.mjs` : 6 tests verts.
  - `npm test` : **243**. `GREG_TEST_TRANSPILE=1 npm test` : 243.
  - `npx tsc --noEmit`, puis `npx next build`.
  - Comparaison avec `R`, octet par octet. Les deux commandes se lancent depuis la racine du dépôt, avec `S` défini comme dans « Commandes ».
    - La première affiche **exactement ces 8 lignes**, dans un ordre quelconque : `DIFF src/components/History/useRequeue.ts`, `DIFF src/components/Queue/QueuePanel.tsx`, `DIFF src/hooks/usePlayer.ts`, `DIFF src/lib/queue/optimistic.ts`, `DIFF tests/optimistic.test.mjs`, `DIFF tests/player-contract.test.mjs`, `DIFF tests/queue-contract.test.mjs` et `DIFF tests/queue-panel.test.mjs`. Ce sont les fichiers de C1 à C4. Le relecteur lit leur `diff` avec `R` : seules les lignes données dans ce plan changent.
    - La seconde n'affiche rien : l'étape donne, octet pour octet, la copie validée `S\etape3-corrige\web`.

```bash
cd "$S/etape3-ref/web" && for f in $(find . -type f | sed 's|^\./||'); do cmp -s "$f" "$OLDPWD/services/web/$f" || echo "DIFF $f"; done; cd "$OLDPWD"
cd "$S/etape3-ref/web" && for f in $(find . -type f | sed 's|^\./||'); do cmp -s "$S/etape3-corrige/web/$f" "$OLDPWD/services/web/$f" || echo "ÉCART $f"; done; cd "$OLDPWD"
```
- [ ] **Step 6 : vérification dans le navigateur.**
  - Lancer `node S\uimock\mock_api.js` et `npx next build && npx next start -p 3100` (dans `services/web`).
  - Puis, avec le venv qui a Playwright (`S\venv`) :

```bash
PYTHONIOENCODING=utf-8 "$S/venv/Scripts/python.exe" "$S/etape3-ref/verif.py" "$S/etape3-verif"
```

  - Attendu : 22 lignes `OK` et « Tout est vert. » (code 0). Contrôles :
    - les lignes : titres nettoyés, sceau à l'initiale du Roi sur ses 3 titres seulement, heures estimées, « fin vers », blasons, « Souvent demandés ici » ;
    - glisser par la poignée ; Échap ; refus (`refuse=move`) par la pochette, avec retour en place et toast d'erreur ;
    - double-clic suivi d'un troisième clic : un seul titre joué ;
    - retirer (optimiste), puis « Annuler » : même ordre qu'avant ;
    - « ×2 » ; les toasts s'éteignent ;
    - historique : rangs dorés, « il y a… » ;
    - 390 px sans défilement horizontal ; glisser en mouvement réduit ;
    - déconnecté : pas de panneau, le Héraut au centre ;
    - aucune erreur de console hors bruit attendu : WebSocket, 404 du poster maxres, pubs YouTube, 403 du refus simulé, 401 déconnecté.
  - Ensuite, sur la même instance, les corrections C2 à C4 :

```bash
PYTHONIOENCODING=utf-8 "$S/venv/Scripts/python.exe" "$S/etape3-ref/verif-corrections.py"
```

  - Attendu : 3 lignes `OK` et « Tout est vert. » (code 0) :
    - « + » double-cliqué : un seul titre ajouté ;
    - plus de 60 titres : 60 lignes et « …et N autres titres », page rendue ;
    - dépôt sous la dernière ligne visible : rang 59, pas en fin de file.
  - Le script remet ensuite la file à 6 titres. Avec `R` d'origine, il donne 3 ÉCHEC : 6 → 8 titres, page blanche (React #301), et une file non rendue.
- [ ] **Step 7 : relire les captures** (`S\etape3-verif\1440x900.png`, `1280x720.png`, `390x844.png`, `historique.png`) :
  - le résumé tient sur une ligne sous le titre et les onglets ;
  - rien ne déborde des lignes (nom du demandeur et artiste en ellipse) ;
  - la puce ne laisse pas voir la durée ;
  - le Héraut ne couvre pas les dernières lignes (`--herald-h`) ;
  - les ménestrels ne paraissent que s'il reste plus de 190 px vides ;
  - en une colonne, le panneau suit la scène.
  - Arrêter les deux serveurs.
- [ ] **Step 8 : critères d'acceptation** (spec §8), sur la même instance :
  - coller un lien de playlist (`https://www.youtube.com/watch?v=x&list=PL1`) : 5 lignes entrent en cascade, et « Playlist ajoutée : 5 titres » s'affiche avec « Annuler l'ajout » ; l'annuler les retire ;
  - glisser, retirer puis annuler, mettre en pause : sans à-coup et sans erreur de console ;
  - aucune couronne, aucun sceau, aucun « Rex » pour Greg ;
  - l'image Docker du web se construit : voir l'étape 9, après le commit.
- [ ] **Step 9 : commit et push (orchestrateur seulement).**
  - `git status` : ni `services/web/tsconfig.json` ni `next-env.d.ts` dans l'index.
  - Puis :

```bash
git add services/web/src services/web/tests services/web/tailwind.config.js docs/superpowers/plans/2026-09-26-web-nuit-gothique-etape-3.md
git commit -m "feat(web): file Nuit gothique, actions optimistes et Héraut

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

  - Spec §8, l'image Docker du web se construit. On la construit depuis le commit, pas depuis l'arbre de travail.
    - Il n'y a pas de `.dockerignore`. `COPY services/web/ .` copierait donc la jonction `node_modules` (binaires Windows), `.next` et `.env.local` par-dessus l'`npm install` de l'image.
    - Commande : `git archive --format=tar HEAD | docker build -f services/web/Dockerfile -`. Elle fait `npm install` dans l'image, jamais dans le dépôt.
    - Si le démon Docker ne tourne pas (c'était le cas à la relecture), le noter dans le compte rendu. Le chemin Node 20 reste couvert par `GREG_TEST_TRANSPILE=1 npm test` et `next build`.
  - Puis `git push`.

## Auto-relecture (faite à l'écriture, complétée par la relecture critique)

- **Couverture de la spec.**
  - §5, actions optimistes : skip, retirer, déplacer, jouer maintenant, mettre en suivant, pause → tâches 2 et 5.
    - Tampon → tâche 2 (`receive`, `hold`, `latest`) et tâche 5 (`receive` sur `engine.latest()`, C1). Pendant un glisser → tâche 6 (`setDragging`).
    - Retour en arrière et message du Héraut → tâches 2, 3 et 5.
  - §5, glisser-déposer : 4 px, défilement automatique, Échap, ressort et secousse → tâches 4 et 6 ; file repliée → C3.
  - §5, clavier : Ctrl+Z → tâche 3 ; le reste à l'étape 4 (écart 9).
  - §2.3, ergonomie de la file :
    - lignes (poignée 6 points, pochette qui sert aussi de poignée, titre nettoyé par `parseTitle` avec le brut en info-bulle, blason et demandeur, sceau du Roi à son initiale sur **ses** titres, durée et heure estimée) → tâches 1 (`view.ts`, `arms.ts`) et 6 (`QueueRow`, `Shield`) ;
    - « fin vers 22 h 47 » → tâches 1 (`endsAt`, `clockText`) et 7 (résumé de `Sidebar`) ;
    - actions rapides sur une puce opaque, clic = sélection, double-clic = jouer, accalmie et anti-doublon → tâches 4 (`createSettle`, `createDedupe`) et 6 ; garde de l'historique → C4 ;
    - annulation du retrait (re-ajout puis déplacement) et de l'ajout → tâches 1 (`undo.ts`), 3 (Ctrl+Z) et 5 ;
    - « Souvent demandés ici » → tâches 1 (`oftenAsked`) et 7.
  - §3 : `components/Queue`, `History`, `Herald`, `hooks/useFlip.ts` (API Web Animations), `lib/motion.ts` → tâches 3, 4, 6 et 7 ; découpage assumé → écart 10.
  - §6.3 : historique aux rangs dorés → tâche 7 ; suppression des alias legacy → tâche 7 ; barre de statut remplacée par le Héraut → tâche 5.
  - §8, critères d'acceptation → tâche 7, étapes 6 à 8 ; image Docker → tâche 7, étape 9.
- **Cohérence des noms.**
  - `moveTrack(key, beforeKey)` (tâche 5) = `onDrop(key, beforeKey)` (tâche 6) = `MutationBody.move` (tâche 2).
  - `dropAnchor` (tâche 4) produit ce `beforeKey`. `QueuePanel` le complète par `queue[MAX_ROWS]?.key` quand la file est repliée (C3).
  - `QueueEngine.latest()` (tâche 2) est celle que lit `usePlayer.receive` (tâche 5).
  - `say`, `sayError`, `herald` (tâche 3) sont ceux qu'importe `usePlayer` (tâche 5).
  - `QueuePanel.after` (tâche 6) reçoit `Suggestions` (tâche 7) ; `.qcontent` (tâche 6) est mesuré par `Sidebar` (tâche 7).
  - `createDedupe` (tâche 4) sert à `QueuePanel` (tâche 6) et à `useRequeueList` (tâche 7, C4).

### Relecture critique (2026-09-27)

Le plan a été rejoué vague par vague sur une copie propre de `services/web` au commit `31e6213`, deux fois : tel qu'il était, puis corrigé. Script : `S\etape3-corrige\waves2.sh`. Constats et corrections apportées au texte :
- **Défauts de `R`** : C1 à C4, décrits et corrigés plus haut. Les 22 contrôles de `verif.py` ne couvraient ni un tick pendant l'attente, ni une file de plus de 60 titres, ni un « + » double-cliqué.
- **Tests qui échouent d'abord** : les échecs annoncés sont désormais exacts.
  - Tâche 5 : 4 FAIL et non 3 ; le test du clavier échoue aussi.
  - Tâche 7 : 5 FAIL sur 6, et le test `casting` est une garde qui passe déjà.
  - Tâches 2, 6 et 7 : un relancement intermédiaire montre chaque test de correction rouge avant sa correction.
- **Ordre des copies** : la tâche 6 ne recopie plus `usePlayer.ts` depuis `R`, ce qui aurait effacé C1. Elle retire seulement la compat.
- **Dépendances** : la tâche 7 importe aussi la tâche 1 (`view.ts`, `copy.extra.ts`) et la tâche 4 (`motion.ts`, `createDedupe`). Ces liens étaient déjà couverts par la tâche 6, mais sont désormais écrits.
- **Fins de ligne** : l'ancienne règle (« tout en LF ») était fausse pour trois fichiers de `R`. Elle est corrigée, sans conversion.
- **Nombres de tests** : 221, 229, 233, 237 et 243, mesurés à chaque vague, dans les deux modes de chargement. `tsc` et `next build` passent à chaque vague.
- **Navigateur** : `verif.py` donne 22 sur 22 et `verif-corrections.py` 3 sur 3 sur la copie corrigée ; ce dernier donne 0 sur 3 sur `R` d'origine. Les captures à 1440 × 900, 390 × 844 et de l'historique ont été relues : sceau du Roi sur ses 3 titres, résumé sur une ligne, rangs dorés, pas de débordement.
- **Spec §8** : la construction de l'image Docker est ajoutée, depuis le commit (tâche 7, étape 9).
- **Casting** : aucune couronne, aucun sceau ni « Rex » n'est attribué à Greg dans les 43 fichiers.
  - Les seules mentions de couronne sont la fonction `crown()` du moteur, qui fait monter un titre en scène, et le commentaire « en valet, sans couronne » de `herald.css`.
  - Le sceau `king-seal-<L>.webp` ne va que sur les lignes `requesterOf(...).kind === 'mine'`.
  - Le Héraut montre le portrait de valet `greg-face-96.webp`.
