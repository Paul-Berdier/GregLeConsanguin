# Appli Overwolf de Greg (overlay v3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** remplacer l'ancienne appli GregLC par une appli Overwolf OW-native (dépôt `greg-overlay-ow`, branche `feat/overlay-v3`) : un bandeau et un panneau par-dessus League of Legends, une fenêtre bureau avec liaison par code et réglages, et des raccourcis, le tout branché sur l'API publique par jeton porteur.

**Architecture:**
- La page de fond (`fond.html`) est le seul cerveau. `createBrain(env)` assemble des modules dont les dépendances sont injectées : connexion par code, socket, jeu et fenêtres, raccourcis, actions. Il expose `window.greg`, et les fenêtres `bandeau`, `panneau` et `bureau` s'y abonnent par `overwolf.windows.getMainWindow().greg`, comme dans l'essai.
- Les fenêtres ne font que peindre des vues calculées par des fonctions pures (`lib/vue-*.js`).
- Toute la logique sans DOM vit dans `lib/*.js` (modules ES testés par `node --test`), dont des portages fidèles des modules purs du site.
- Un banc fait tourner le cerveau entier avec un faux `overwolf`, un faux `fetch`, un faux socket et une fausse horloge.

**Tech Stack:**
- Overwolf OW-native (`manifest_version` 1, CEF), testé sur Overwolf 0.317.0.3.
- JavaScript en modules ES, sans bundler. `socket.io.min.js` 4.7.5 copié dans `vendor/`.
- Node ≥ 22 (`node --test`, globs dans `--test`), aucun paquet npm.
- Aperçus des fenêtres : Playwright (MCP) ou le navigateur intégré, sur un petit serveur local qui injecte un faux `overwolf`.

**Spec:** `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-design.md` (ce plan couvre §6, avec §1, §2 et §7 ; §3 à §5 sont le plan A, côté serveur, qui ne nous lie que par le contrat ci-dessous).

## Global Constraints

- **Dépôt.** `C:\Users\Paul\Documents\Codage\greg-overlay-ow`, branche `feat/overlay-v3` créée depuis `master`.
  - La session qui exécute a pour dossier de travail `GregLeConsanguin`, et le shell revient à ce dossier entre deux appels. Chaque commande de ce plan commence donc par `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && ` (Git Bash), y compris `git`, `npm` et `node`. Les commandes de plusieurs lignes sont enchaînées par `&&`, pour qu'un échec arrête la suite. Sans ce `cd`, un `git commit` partirait sur `feat/overlay-overwolf` de GregLeConsanguin.
  - Les fichiers sont créés et modifiés par leur chemin absolu sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\`, comme les listent les sections **Files**. Les chemins relatifs des blocs de test (`// tests/x.test.js`) et des tableaux partent de cette racine.
- **Scratchpad.** Les fichiers temporaires (paquet npm, journal des tests, corps de la PR) vont dans le scratchpad de la session qui exécute, que son prompt système donne. On n'utilise jamais celui d'une autre session.
  - Les commandes le lisent dans `$SCRATCHPAD`. L'état du shell ne survit pas d'un appel à l'autre, donc chaque bloc qui s'en sert le pose juste après le `cd`, en chemin Git Bash : `SCRATCHPAD='/c/Users/Paul/AppData/Local/Temp/claude/<projet>/<session>/scratchpad' && …`.
    - Le chemin exact est recopié du prompt système de la session qui exécute (deux niveaux sous `claude/`).
    - Dans les blocs de ce plan, `SCRATCHPAD='<scratchpad>'` est à remplacer par ce chemin.
  - `test -d "$SCRATCHPAD"` arrête la commande s'il manque.
- **Dossiers intouchables.** `essai-eclair/` et `essai-overwolf/` (exclus par `.git/info/exclude`) ne sont jamais modifiés, déplacés ni commités. Interdits : `git add -A`, `git add .`, `git clean`, `git stash`, `git reset --hard`, `git push --force`.
- **Git.** Messages en français. Aucune mention d'IA : ni `Co-Authored-By`, ni « Generated with », ni nom d'outil, dans les commits comme dans la PR. Une seule PR, vers `master`, fusionnée seulement avec l'accord de Paul.
- **Ancienne appli.** Les fichiers de l'ancienne appli à la racine sont retirés de l'arbre (ils restent dans l'historique). `assets/icon.png` est gardé.
- **Outillage.**
  - Pas de bundler : modules ES chargés par `<script type="module">`.
  - `vendor/socket.io.min.js` en version **4.7.5**, chargé en script classique avant le module de `fond.html`.
  - Node ≥ 22, aucune dépendance npm. `npm test` lance `node --test "tests/**/*.test.js"`.
- **Logique pure.** `lib/*.js` n'utilise ni DOM, ni `overwolf`, ni horloge globale (elle est injectée). `fond/*.js` reçoit `overwolf`, `io`, `fetch`, le stockage et les minuteurs en paramètres, jamais par les globales.
- **Manifeste.**
  - `name: "GregLC"`, `author: "Paul Berdier"` (même UID, donc l'origine `overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk`), `version: "3.0.0"`.
  - Permissions `Hotkeys`, `GameInfo` seulement.
  - `game_targeting` `dedicated [5426]` ; `launch_events` `GameLaunch 5426`.
- **Raccourcis.** `pause` Ctrl+F7, `suivant` Ctrl+F8, `panneau` Ctrl+F10, `bandeau` Ctrl+F11, en `custom` et `passthrough: false`.
- **Fenêtres.**
  - `fond` : page de fond, cerveau unique.
  - `bureau` : `desktop_only`, `native_window`.
  - `bandeau` : en jeu, `transparent`, `clickthrough`, `ignore_keyboard_events`, jamais de focus.
  - `panneau` : en jeu, `grab_keyboard_focus`, plus `requestOverlayFocus` à l'ouverture, avec `bringToFront(id, true)` en secours.
- **CSP**, posée par `<meta http-equiv>` dans chaque page, à l'identique (constante `CSP` de `lib/config.js`) :
  `default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' https://i.ytimg.com https://cdn.discordapp.com; connect-src https://greg-api.up.railway.app wss://greg-api.up.railway.app`.
  Pas d'attribut `style=` dans le HTML ; les styles dynamiques passent par `element.style.setProperty`.
- **Contrat partagé avec le plan A** (noms exacts ; base `https://greg-api.up.railway.app/api/v1`) :
  - liaison : `POST /overlay/device {client_name}` puis `POST /overlay/token {device_code}` (400 `authorization_pending` | `slow_down` (+5 s) | `access_denied` | `expired_token`) ;
  - identité : `GET /overlay/me`, `GET /overlay/guilds`, `POST /overlay/logout` ;
  - lecteur : `GET /playlist?guild_id=`, `POST /queue/add`, `/queue/skip`, `/queue/stop`, `/playlist/toggle_pause`, `/playlist/restart`, `/playlist/repeat`, `/voice/join`, `/queue/remove {index, expected}`, `/player/move {src, dst, expected}`, `/playlist/play_at {index, expected}`, `GET /search/autocomplete?q=&limit=` ;
  - `expected = {url, added_by, ts}` ; un écart donne 409 `{error:"STALE"}`.
  - Toujours `Authorization: Bearer <jeton>` et `guild_id` dans le corps. Jamais de cookie (`credentials: 'omit'`), jamais de `user_id`.
  - Socket : `io("https://greg-api.up.railway.app", {path:"/socket.io", auth:{token}, transports:["websocket"]})`.
    - Émissions : `join_guild`, `leave_guild`, `request_state`, `time_sync`. Jamais d'événement `overlay_*`.
    - Écoutes : `playlist_update` (complet ou tick `only_elapsed` avec `guild_id`), `player_event {guild_id, action, actor:{id, display_name}, title, at_ms}`, `guild_join_error`.
    - Un jeton invalide donne `connect_error` de message `NOT_AUTHENTICATED`.
- **Jeton.** Rangé dans le `localStorage` de l'extension sous `greg.ow.token`, jamais dans une URL. Il est effacé sur 401 ou sur `connect_error` `NOT_AUTHENTICATED`.
- **Délais** (constante `DELAIS` de `lib/config.js`) :
  - fusion des raccourcis 350 ms, répétition 600 ms ;
  - sondage REST 5 s quand le socket est coupé ; contrôle du jeu toutes les 3 s ;
  - garde clic/blur du panneau 250 ms ; retour du bandeau à la 1re touche ou après 3 s ;
  - refus affiché 6 s, ligne d'ami 5 s, une réplique au plus toutes les 30 s ;
  - suggestions après 280 ms et 2 caractères.
- **Bandeau.**
  - Par défaut en bas à gauche : `left = 16`, `top = max(16, hauteur logique − hauteur du bandeau − MARGE_BAS)`.
  - `MARGE_BAS` vaut 24 px au départ. La tâche 18 (étape 8) l'ajuste sur une capture réelle de LoL, chat ouvert, pour que le bandeau ne le couvre pas (spec §6.4 et §8).
  - Autres emplacements : « Bord gauche, au tiers » (`top = 29 %` de la hauteur) et « En haut à gauche ».
  - Tailles « Compacte » et « Normale ».
  - Fond réglable de 0 à 100 %, 70 % par défaut, appliqué au fond seulement, avec une ombre de texte.
  - Il ne bouge jamais quand la hauteur du jeu est sous 200 px (Plein écran hors focus = 1×1).
- **Textes.**
  - Le deck du site (`copy.v2.json`, recopié dans `lib/deck.js`) d'abord, puis `lib/copy.overlay.js` sous la clé `ow`.
  - Greg est le valet et vouvoie (« Sire ») ; jamais de couronne pour Greg.
  - Typographie : U+00A0 avant « : », entre un nombre et son unité et dans « », U+202F avant ; ! ?, apostrophe ’.
- **Jeu.** Rien ne touche au processus du jeu hors des API d'Overwolf, et aucune donnée de partie n'est affichée.
- **Jeu en cours.** Avant de lancer quoi que ce soit de visible (navigateur de Playwright, Overwolf, URL `overwolf://`, fenêtre de l'appli), la session vérifie qu'aucune partie de LoL n'est ouverte : une fenêtre de bureau qui prend le focus réduit le jeu en Plein écran.
  - Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && (tasklist //FO CSV //NH | grep -ci '"League of Legends.exe"' || true)`
  - Expected : `0`. Sinon, attendre la fin de la partie.
- **DA.**
  - Les maquettes validées font foi. Elles sont dans `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\` :
    - `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.tpl.html` pour le bandeau et le panneau ;
    - `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\2-hors-jeu.tpl.html` pour la connexion, le bureau, les réglages et les états du bandeau ;
    - `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\shared.css`.
  - Les pages autonomes (`1-en-jeu.html`, `2-hors-jeu.html`) se construisent par `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/docs/superpowers/specs/2026-11-25-overlay-overwolf-maquettes && python build.py`. Elles ne sont pas commitées.
  - On garde leur lumière violette (`--lumiere: hsl(265 78% 74%)`, `--lumiere-rgb: 180 137 240`) et le médaillon de Greg de l'essai.
  - `3-dans-lol` est remplacée par le bas à gauche.
- **Ressources du site.** Recopiées par `scripts/sync-web.mjs` depuis `../GregLeConsanguin/services/web` et commitées. Elles ne s'éditent jamais à la main.

## Review Focus

1. **Appli relancée pendant une partie** (bouton Launch d'Overwolf, icône du dock, `onAppLaunchTriggered`, lancement automatique) : la fenêtre bureau ne s'ouvre jamais par-dessus LoL, où elle volerait le focus et réduirait le jeu Plein écran. Elle ne s'ouvre que hors partie. Test : tâche 11.
2. **Les propres actions de Paul** (Ctrl+F8, ajout depuis le panneau) reviennent en `player_event` avec `actor.id` égal au sien : aucune « ligne d'ami » à son nom. Seuls les autres sont annoncés. Tests : tâches 5 et 14.
3. **« Nouveau code » cliqué deux fois, ou bureau rouvert pendant un code :** un seul sondage actif, sur le dernier `device_code`. Pas de cascade de `slow_down`, et l'ancien code n'est plus sondé. Test : tâche 9.
4. **Appareil délié depuis le site en pleine partie** (jeton révoqué, socket fermé par le serveur) :
   - le sondage REST prend le relais, reçoit 401, efface le jeton une seule fois et s'arrête ;
   - pas de boucle de 401 toutes les 5 s, ni de reconnexion avec le vieux jeton ;
   - le bandeau dit « Liez l’appli depuis la fenêtre Greg ».
   Tests : tâches 10 et 14.
5. **Raccourci « non attribué » par Overwolf** (conflit avec Porofessor, TFTactics ou Ctrl+Tab) :
   - au début de la partie, une ligne du bandeau nomme les raccourcis manquants ;
   - le pied du panneau et les réglages affichent « non attribué » au lieu d'une touche qui ne marche pas.
   Tests : tâches 12, 14 et 16.

---

## Structure des fichiers

Chemins relatifs à la racine `C:\Users\Paul\Documents\Codage\greg-overlay-ow\`.

| Fichier | Rôle |
|---|---|
| `manifest.json` | Manifeste Overwolf (identité, permissions, raccourcis, quatre fenêtres). |
| `package.json`, `.gitignore`, `.gitattributes` | Scripts `test`, `sync-web` et `apercu` ; fins de ligne LF ; binaires. |
| `README.md` | Charger l'appli, régler Railway, délier, désactiver. |
| `fond.html`, `bandeau.html`, `panneau.html`, `bureau.html` | Les quatre pages, à la racine comme dans l'essai, pour que `img/…` et `css/…` se résolvent pareil partout. |
| `assets/icon.png` | Icône (gardée). |
| `fonts/`, `licences/`, `img/` (`greg-face-*`, `crown-badge-*`, `seals/`), `css/tokens.css`, `lib/deck.js` | Recopiés du site par `scripts/sync-web.mjs`, commités, jamais édités. |
| `img/icones.svg` | Sprite des icônes au trait, reprises des maquettes. |
| `vendor/socket.io.min.js`, `vendor/socket.io-client.LICENSE` | socket.io-client 4.7.5. |
| `lib/config.js` | Constantes : adresses, délais, clés de stockage, CSP. |
| `lib/format.js`, `lib/titles.js`, `lib/scene.js`, `lib/links.js`, `lib/timesync.js`, `lib/refclock.js` | Portages fidèles des modules purs du site. |
| `lib/player.js` | Portage de `playerUtils` : normalisation de l'état, erreurs, plus `expected`, déplacements et choix du serveur. |
| `lib/copy.js`, `lib/copy.overlay.js`, `lib/annonces.js` | `t` / `fill` / `quip` sur le deck et les textes de l'appli ; choix des annonces (ami, préconditions). |
| `lib/herald.js` | Le Héraut réduit : pile, ×N, une réplique toutes les 30 s, durées de l'appli. |
| `lib/settings.js`, `lib/placement.js` | Réglages (`localStorage`), tailles et positions du bandeau et du panneau. |
| `lib/api.js` | Client REST à jeton porteur. |
| `lib/hotkeys.js` | Fusion et répétition, libellés, capture, conflits, lecture des liaisons Overwolf. |
| `lib/vue-bandeau.js`, `lib/vue-lecteur.js`, `lib/vue-bureau.js` | Vues pures que les fenêtres peignent. |
| `fond/connexion.js` | Jeton, validation, liaison par code, délier. |
| `fond/temps-reel.js` | Socket, abonnement au serveur, `time_sync`, sondage de repli. |
| `fond/fenetres.js` | Détection de LoL, fenêtres, placement, focus du panneau, fermetures, bureau. |
| `fond/raccourcis.js` | Raccourcis Overwolf, touches captées par le panneau, réattribution. |
| `fond/actions.js` | Actions du lecteur par REST, annonces de succès et de refus, `STALE`. |
| `fond/cerveau.js`, `fond/demarrage.js` | Assemblage, état diffusé, `window.greg`. |
| `ui/pont.js`, `ui/dom.js`, `ui/bandeau-rendu.js`, `ui/bandeau.js`, `ui/lecteur.js`, `ui/panneau.js`, `ui/bureau.js`, `ui/reglages.js` | Code DOM des fenêtres. |
| `css/base.css`, `css/bandeau.css`, `css/lecteur.css`, `css/bureau.css` | Styles (polices, atomes des maquettes, fenêtres). |
| `scripts/sync-web.mjs` | Recopie depuis le site, avec un mode `--check`. |
| `apercu/serveur.mjs`, `apercu/faux-overwolf.js`, `apercu/scenarios.js`, `apercu/index.html` | Aperçu des fenêtres dans un navigateur, avec un faux `overwolf`. |
| `tests/*.test.js`, `tests/fakes/{horloge,stockage,fetch,socket,overwolf}.js` | Tests et faux. |

---

## Tâche 1 : branche, ménage et socle (manifeste, configuration)

**Files:**
- Delete (`git rm`, chemins sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\`) : `.idea/.gitignore`, `.idea/vcs.xml`, `README.md`, `assets/css/overlay.css`, `assets/icon.jpg`, `manifest.json` (l'ancien), `overwolf-manifest-schema.json`, `src/overlay-boot.js`, `src/overlay-core.js`, `src/ow-bridge.js`, `windows/` (tout le dossier).
- Create :
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\package.json`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\.gitignore`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\.gitattributes`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\config.js`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\manifest.json`
- Create puis supprime, jamais commités (étape 7, fumée dans Overwolf) :
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond.html`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\bureau.html`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fumee\fond.js`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fumee\bureau.js`
- Test :
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\config.test.js`
  - `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\manifest.test.js`

**Interfaces:**
- Produces (`lib/config.js`) :
  - `API_ORIGIN`, `API_BASE`, `SOCKET_PATH`, `LOL` ;
  - `CLIENT_NAME = 'GregLC · Overwolf'` ;
  - `STORAGE = {token, profil, reglages}` ;
  - `DELAIS`, `SUGGESTIONS`, `FILE_MAX`, `HAUTEUR_MIN`, `CSP`.

- [ ] **Step 1 : créer la branche et retirer l'ancienne appli**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git switch master && git pull --ff-only && git switch -c feat/overlay-v3 \
  && git rm -r -q .idea README.md assets/css assets/icon.jpg manifest.json overwolf-manifest-schema.json src windows \
  && git status --short && git ls-files assets && git branch --show-current
```
Attendu :
- seulement des lignes `D` dans `git status --short` ; ni `essai-eclair/` ni `essai-overwolf/` ;
- `git ls-files assets` affiche `assets/icon.png` seul ;
- la dernière ligne vaut `feat/overlay-v3`.

- [ ] **Step 2 : écrire les tests qui échouent**

```js
// tests/config.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as C from '../lib/config.js';

test('adresses de l’API publique', () => {
  assert.equal(C.API_ORIGIN, 'https://greg-api.up.railway.app');
  assert.equal(C.API_BASE, 'https://greg-api.up.railway.app/api/v1');
  assert.equal(C.SOCKET_PATH, '/socket.io');
  assert.equal(C.LOL, 5426);
  assert.equal(C.CLIENT_NAME, 'GregLC · Overwolf');
  assert.ok(C.CLIENT_NAME.length <= 40);
});
test('délais et limites de la spec', () => {
  assert.deepEqual(C.DELAIS, { fusion: 350, repetition: 600, sondage: 5000, controleJeu: 3000, garde: 250, gardeTouche: 100,
    retourBandeau: 3000, refus: 6000, ami: 5000, replique: 30000, suggestions: 280, reessaiServeur: 5000, reessaiBandeau: 15000,
    timeSyncSalve: 1000, timeSyncPeriode: 30000, timeSyncAttente: 2000, voix: 10000 });
  assert.deepEqual(C.SUGGESTIONS, { min: 2, limite: 6 });
  assert.equal(C.FILE_MAX, 60);
  assert.equal(C.HAUTEUR_MIN, 200);
});
test('stockage et CSP', () => {
  assert.deepEqual(C.STORAGE, { token: 'greg.ow.token', profil: 'greg.ow.profil', reglages: 'greg.ow.reglages' });
  assert.equal(C.CSP, "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' https://i.ytimg.com https://cdn.discordapp.com; connect-src https://greg-api.up.railway.app wss://greg-api.up.railway.app");
});
```

```js
// tests/manifest.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const m = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'));

test('identité, permissions et jeu', () => {
  assert.equal(m.manifest_version, 1);
  assert.deepEqual([m.meta.name, m.meta.author, m.meta.version], ['GregLC', 'Paul Berdier', '3.0.0']);
  assert.equal(m.meta.icon, 'assets/icon.png');
  assert.ok(m.meta.description.length <= 180);
  assert.deepEqual(m.permissions, ['Hotkeys', 'GameInfo']);
  assert.equal(m.data.start_window, 'fond');
  assert.deepEqual(m.data.game_targeting, { type: 'dedicated', game_ids: [5426] });
  assert.deepEqual(m.data.launch_events, [{ event: 'GameLaunch', event_data: { game_ids: [5426] } }]);
});
test('raccourcis', () => {
  const h = m.data.hotkeys;
  assert.deepEqual(Object.fromEntries(Object.entries(h).map(([k, v]) => [k, v.default])),
    { pause: 'Ctrl+F7', suivant: 'Ctrl+F8', panneau: 'Ctrl+F10', bandeau: 'Ctrl+F11' });
  for (const v of Object.values(h)) { assert.equal(v['action-type'], 'custom'); assert.equal(v.passthrough, false); }
});
test('fenêtres', () => {
  const w = m.data.windows;
  assert.deepEqual(Object.keys(w).sort(), ['bandeau', 'bureau', 'fond', 'panneau']);
  assert.equal(w.fond.is_background_page, true);
  assert.equal(w.bureau.desktop_only, true);
  assert.equal(w.bureau.native_window, true);
  for (const k of ['in_game_only', 'transparent', 'clickthrough', 'ignore_keyboard_events']) assert.equal(w.bandeau[k], true, k);
  assert.equal(w.bandeau.grab_keyboard_focus, false);
  assert.deepEqual(w.bandeau.size, { width: 340, height: 132 });
  assert.equal(w.panneau.in_game_only, true);
  assert.equal(w.panneau.grab_keyboard_focus, true);
  assert.equal(w.panneau.clickthrough, false);
  assert.deepEqual(w.panneau.size, { width: 440, height: 680 });
});
```

- [ ] **Step 3 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/config.test.js tests/manifest.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND` pour `lib/config.js`, `ENOENT` pour `manifest.json`).

- [ ] **Step 4 : écrire `package.json`, `.gitignore`, `.gitattributes`, `lib/config.js` et `manifest.json`**

- `package.json` :
  - `{"name":"greg-overlay-ow","version":"3.0.0","private":true,"type":"module","engines":{"node":">=22"}}` ;
  - scripts : `"test": "node --test \"tests/**/*.test.js\""`, `"sync-web": "node scripts/sync-web.mjs"`, `"apercu": "node apercu/serveur.mjs"`.
- `.gitignore` : `node_modules/`, `*.tgz`.
- `.gitattributes` :
  - `* text=auto eol=lf` (le dépôt a `core.autocrlf=true` ; LF partout rend `sync-web --check` stable) ;
  - `*.woff2 binary`, `*.webp binary`, `*.png binary`.
- `lib/config.js` : les valeurs exactes des tests.
- `manifest.json` (valeurs à reprendre telles quelles) :

```json
{
  "manifest_version": 1,
  "type": "WebApp",
  "meta": {
    "name": "GregLC", "author": "Paul Berdier", "version": "3.0.0",
    "minimum-overwolf-version": "0.209.0",
    "description": "Greg, valet de musique du Roi : bandeau et panneau par-dessus League of Legends.",
    "icon": "assets/icon.png", "icon_gray": "assets/icon.png"
  },
  "permissions": ["Hotkeys", "GameInfo"],
  "data": {
    "start_window": "fond",
    "game_targeting": { "type": "dedicated", "game_ids": [5426] },
    "launch_events": [{ "event": "GameLaunch", "event_data": { "game_ids": [5426] } }],
    "hotkeys": {
      "pause": { "title": "Greg : pause ou reprise", "action-type": "custom", "default": "Ctrl+F7", "passthrough": false },
      "suivant": { "title": "Greg : titre suivant", "action-type": "custom", "default": "Ctrl+F8", "passthrough": false },
      "panneau": { "title": "Greg : ouvrir ou fermer le panneau", "action-type": "custom", "default": "Ctrl+F10", "passthrough": false },
      "bandeau": { "title": "Greg : afficher ou cacher le bandeau", "action-type": "custom", "default": "Ctrl+F11", "passthrough": false }
    },
    "windows": {
      "fond": { "file": "fond.html", "is_background_page": true, "show_in_taskbar": false },
      "bureau": { "file": "bureau.html", "desktop_only": true, "native_window": true, "transparent": true, "resizable": false,
        "show_in_taskbar": true, "size": { "width": 480, "height": 780 }, "start_position": { "top": 80, "left": 80 } },
      "bandeau": { "file": "bandeau.html", "in_game_only": true, "transparent": true, "clickthrough": true,
        "ignore_keyboard_events": true, "grab_keyboard_focus": false, "resizable": false, "show_in_taskbar": false,
        "keep_window_location": true, "disable_restore_animation": true, "size": { "width": 340, "height": 132 },
        "min_size": { "width": 0, "height": 0 }, "start_position": { "top": 300, "left": 16 } },
      "panneau": { "file": "panneau.html", "in_game_only": true, "transparent": true, "clickthrough": false,
        "grab_keyboard_focus": true, "resizable": false, "show_in_taskbar": false, "keep_window_location": true,
        "disable_restore_animation": true, "size": { "width": 440, "height": 680 }, "start_position": { "top": 124, "left": 24 } }
    },
    "developer": { "enable_auto_refresh": false }
  }
}
```

`minimum-overwolf-version` reste celle de l'essai, qui s'est chargé ; `requestOverlayFocus` (0.250+) est détecté à l'exécution.

- [ ] **Step 5 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0` (2 fichiers, 6 tests).

- [ ] **Step 6 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add package.json .gitignore .gitattributes lib/config.js manifest.json tests/config.test.js tests/manifest.test.js \
  && git commit -m "chore: retire l'ancienne appli et pose le socle v3 (manifeste, configuration)"
```

- [ ] **Step 7 : fumée dans Overwolf, avec Paul (modules, origine, pont du bureau natif)**

L'essai chargeait des scripts classiques. Ce plan charge des modules ES (`<script type="module">`) depuis `overwolf-extension://`, sous la CSP. La fenêtre `bureau` est `native_window` et lit `getMainWindow().greg`. On vérifie ces trois choix dans Overwolf maintenant, plutôt qu'à la tâche 18. L'étape confirme aussi l'UID dont le plan A a besoin avant qu'on touche aux réglages Railway (`OVERLAY_ORIGINS`).

1. **Aucune partie ouverte** (contrainte « Jeu en cours »). Avant tout geste qui affiche une fenêtre (Load unpacked, relance d'Overwolf, URL `overwolf://`), la session vérifie que LoL ne tourne pas : la fenêtre bureau volerait le focus et réduirait le jeu en Plein écran.

   Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && (tasklist //FO CSV //NH | grep -ci '"League of Legends.exe"' || true)`
   Expected : `0`. Sinon, attendre la fin de la partie et refaire la vérification.

2. **Écrire les quatre fichiers jetables** (jamais commités).

   `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond.html` :
   ```html
   <!doctype html>
   <html lang="fr"><head><meta charset="utf-8">
   <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' https://i.ytimg.com https://cdn.discordapp.com; connect-src https://greg-api.up.railway.app wss://greg-api.up.railway.app">
   </head><body><script type="module" src="fumee/fond.js"></script></body></html>
   ```
   `C:\Users\Paul\Documents\Codage\greg-overlay-ow\bureau.html` : le même texte, avec `src="fumee/bureau.js"`.

   `bandeau.html` et `panneau.html` : `<!doctype html><html lang="fr"><head><meta charset="utf-8"></head><body></body></html>`. Ces pages vides existent seulement parce que le manifeste déclare ces fenêtres ; sans elles, Load unpacked pourrait refuser l'appli. Elles sont jetables, comme les autres, et supprimées au nettoyage de l'étape, avec les deux pages de fumée et le dossier `fumee/`.

   `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fumee\fond.js` :
   ```js
   // Fumée jetable (tâche 1, étape 7), supprimée après la vérification.
   console.info('GregLC origine', location.origin, 'module', import.meta.url);   // import.meta n'existe que dans un module
   window.greg = { ping: () => 'pong' };
   overwolf.windows.obtainDeclaredWindow('bureau', (r) => {
     console.info('GregLC bureau obtenu', r.success);
     if (r.success) overwolf.windows.restore(r.window.id, (x) => console.info('GregLC bureau affiché', x.success));
   });
   ```
   `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fumee\bureau.js` :
   ```js
   // Fumée jetable (tâche 1, étape 7), supprimée après la vérification.
   let pont = 'absent';
   try { pont = overwolf.windows.getMainWindow().greg?.ping?.() ?? 'absent'; } catch (e) { pont = `erreur ${e}`; }
   console.info('GregLC pont', pont, 'module', import.meta.url);
   ```

3. **Paul charge l'appli** (geste manuel dans Overwolf ; la session le lui demande, attend sa réponse et ne clique pas dans Overwolf) :
   - dans `overwolf://packages`, retirer la carte de l'ancienne GregLC s'il y en a une (même nom et même auteur, donc même UID), et désactiver « Greg essai » ;
   - Load unpacked → `C:\Users\Paul\Documents\Codage\greg-overlay-ow`. La page `fond` démarre et ouvre la fenêtre bureau, vide.

4. **Lire les journaux.** Overwolf ajoute chaque session à la suite des précédentes : on ne lit que les lignes qui suivent le dernier `new session` de chaque fichier.

   Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && grep -h 'GregLC\|Content Security Policy\|Uncaught' /c/Users/Paul/AppData/Local/Overwolf/Log/Apps/GregLC/fond.html.log /c/Users/Paul/AppData/Local/Overwolf/Log/Apps/GregLC/bureau.html.log`
   Expected, des lignes qui contiennent :
   - `GregLC origine overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk module overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk/fumee/fond.js` ;
   - `GregLC bureau obtenu true`, puis `GregLC bureau affiché true` ;
   - `GregLC pont pong module overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk/fumee/bureau.js` ;
   - aucune ligne `Content Security Policy` ni `Uncaught`.

5. **Écarts.**
   - Origine différente : s'arrêter et prévenir Paul. Le plan A et `OVERLAY_ORIGINS` dépendent de cette valeur.
   - Pas de ligne `GregLC origine`, ou une erreur CSP : les modules ne se chargent pas. S'arrêter et prévenir Paul, car tout le plan repose dessus.
   - `GregLC pont absent` ou `GregLC pont erreur …` alors que le fond a démarré : le bureau natif n'atteint pas la page de fond. Le noter pour Paul et lui proposer le repli `native_window: false` pour `bureau`. Avec son accord seulement :
     - `manifest.json` : `"native_window": false` dans `bureau` ;
     - `tests/manifest.test.js` : `assert.equal(w.bureau.native_window, false);` ;
     - refaire les points 1, 3 et 4 (Paul retire puis recharge la carte), lancer `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test` (`# fail 0`), puis :
       ```bash
       cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add manifest.json tests/manifest.test.js \
         && git commit -m "fix: fenêtre bureau non native, le pont n'atteignait pas la page de fond"
       ```
     - La contrainte « Fenêtres » de ce plan se lit alors avec `native_window: false`, et la tâche 18 le dit dans le README.

6. **Ménage.**

   Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && rm fond.html bureau.html bandeau.html panneau.html fumee/fond.js fumee/bureau.js && rmdir fumee && git status --short`
   Expected : sortie vide.
   La carte GregLC peut rester chargée : jusqu'à la tâche 14, elle n'a plus de page de fond et ne fait rien en partie. Paul peut aussi la désactiver jusqu'à la tâche 18.

---

## Tâche 2 : ressources du site (`scripts/sync-web.mjs`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\scripts\sync-web.mjs`, puis les sorties qu'il génère sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\` :
  - `fonts\*.woff2` (7) ;
  - `licences\LICENSES.md`, `licences\*-OFL.txt` (4) ;
  - `img\greg-face-96.webp`, `img\greg-face-192.webp`, `img\crown-badge-64.webp`, `img\crown-badge-128.webp`, `img\seals\king-seal-*.webp` (27) ;
  - `css\tokens.css`, `lib\deck.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\sync-web.test.js`.

**Interfaces:**
- Produces (`scripts/sync-web.mjs`) :
  - `WEB_PAR_DEFAUT` : chemin absolu de `new URL('../../GregLeConsanguin/services/web/', import.meta.url)` ;
  - `CHEMINS_DECK = ['address','auth','now','controls','queue','toast','remote','error','confirm','guild','search','header.settings']` ;
  - `transformerTokens(css: string): string` ;
  - `extraireDeck(deck: object, chemins: string[]): object` ;
  - `construireSorties(webDir: string): Map<string, Buffer|string>`, dont les clés sont des chemins POSIX relatifs au dépôt ;
  - `main(argv: string[]): number`, lancé seulement si le script est appelé directement (`import.meta.url === pathToFileURL(process.argv[1]).href`), avec `--web <dossier>` et `--check`.
- Produces (fichiers) :
  - `lib/deck.js` : `export default {…}` (sous-ensemble du deck) ;
  - `css/tokens.css` : bloc `:root` du site, plus le bloc `prefers-reduced-motion`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/sync-web.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { transformerTokens, extraireDeck, CHEMINS_DECK, WEB_PAR_DEFAUT } from '../scripts/sync-web.mjs';
import deck from '../lib/deck.js';
const webPresent = existsSync(WEB_PAR_DEFAUT);

test('transformerTokens remplace les polices de next/font et garde les couleurs', () => {
  const out = transformerTokens(':root{\n  --or:#cfa75a;\n  --f-display:var(--font-grenze-gotisch),"Grenze",serif;\n  --f-title:var(--font-grenze),"Alegreya Sans",serif;\n  --f-ui:var(--font-alegreya-sans),"Segoe UI",system-ui,sans-serif;\n  --f-voice:var(--font-alegreya-italic),Georgia,serif;\n}');
  assert.match(out, /^\/\* Généré par scripts\/sync-web\.mjs/);
  for (const s of ['--f-display:"Grenze Gotisch","Grenze",serif;', '--f-title:"Grenze","Alegreya Sans",serif;',
    '--f-ui:"Alegreya Sans","Segoe UI",system-ui,sans-serif;', '--f-voice:"Alegreya",Georgia,serif;', '--or:#cfa75a;']) assert.ok(out.includes(s), s);
  assert.ok(!out.includes('var(--font-'));
});
test('extraireDeck garde l’imbrication et nomme un chemin absent', () => {
  const d = { a: { b: 1 }, header: { settings: { quips: 'x' }, other: 1 }, z: 3 };
  assert.deepEqual(extraireDeck(d, ['a', 'header.settings']), { a: { b: 1 }, header: { settings: { quips: 'x' } } });
  assert.throws(() => extraireDeck(d, ['nope.x']), /nope\.x/);
});
test('chaque renvoi { ref } du sous-ensemble se résout dans le sous-ensemble', () => {
  const at = (p) => p.split('.').reduce((o, k) => (o == null ? undefined : o[k]), deck);
  const walk = (n) => { if (!n || typeof n !== 'object') return;
    const ks = Object.keys(n); if (ks.length === 1 && typeof n.ref === 'string') assert.notEqual(at(n.ref), undefined, n.ref);
    Object.values(n).forEach(walk); };
  walk(deck);
});
test('ressources recopiées et deck lisible', () => {
  assert.equal(readdirSync('fonts').filter((f) => f.endsWith('.woff2')).length, 7);
  assert.equal(readdirSync('img/seals').length, 27);
  assert.equal(readdirSync('licences').length, 5);
  for (const f of ['greg-face-96.webp', 'greg-face-192.webp', 'crown-badge-64.webp', 'crown-badge-128.webp']) assert.ok(existsSync(`img/${f}`), f);
  assert.equal(deck.now.idle.title, 'Rien en lecture');
  assert.deepEqual(Object.keys(deck).sort(), ['address', 'auth', 'confirm', 'controls', 'error', 'guild', 'header', 'now', 'queue', 'remote', 'search', 'toast']);
  assert.ok(readFileSync('css/tokens.css', 'utf8').includes('--gueules:#e0583e'));
});
test('sorties à jour (--check)', { skip: !webPresent }, () => {
  const r = spawnSync(process.execPath, ['scripts/sync-web.mjs', '--check'], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/sync-web.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND` pour `scripts/sync-web.mjs`).

- [ ] **Step 3 : écrire `scripts/sync-web.mjs`**

Sorties de `construireSorties(webDir)` :
- `fonts/<f>` ← `public/fonts/*.woff2` ;
- `licences/<f>` ← `public/licenses/LICENSES.md` et `public/licenses/*-OFL.txt` ;
- `img/<f>` ← `public/gothique/{greg-face-96,greg-face-192,crown-badge-64,crown-badge-128}.webp` ;
- `img/seals/<f>` ← `public/gothique/seals/*.webp` ;
- `css/tokens.css` ← `transformerTokens(src/theme/tokens.css)` ;
- `lib/deck.js` ← `// Généré par scripts/sync-web.mjs depuis services/web/src/theme/copy.v2.json : ne pas éditer.\nexport default ${JSON.stringify(extraireDeck(deck, CHEMINS_DECK), null, 2)};\n`.

`transformerTokens` :
- ajoute en tête `/* Généré par scripts/sync-web.mjs depuis services/web/src/theme/tokens.css : ne pas éditer. */` ;
- remplace `var(--font-grenze-gotisch)` par `"Grenze Gotisch"`, `var(--font-grenze)` par `"Grenze"`, `var(--font-alegreya-sans)` par `"Alegreya Sans"` et `var(--font-alegreya-italic)` par `"Alegreya"`. Traiter `grenze-gotisch` avant `grenze`.

`main` :
- sans `--check`, écrit toutes les sorties (dossiers créés) et affiche le nombre de fichiers ;
- avec `--check`, compare chaque sortie au disque (texte comparé après `\r\n` → `\n`), liste les écarts et renvoie 1 s'il y en a, 0 sinon.

- [ ] **Step 4 : générer les ressources**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node scripts/sync-web.mjs`
Expected : `45 fichiers écrits` (7 polices, 5 licences, 4 images, 27 sceaux, `css/tokens.css`, `lib/deck.js`), aucun hors de `fonts/`, `licences/`, `img/`, `css/` et `lib/`.

- [ ] **Step 5 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 6 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add scripts/sync-web.mjs tests/sync-web.test.js fonts licences img/greg-face-96.webp img/greg-face-192.webp img/crown-badge-64.webp img/crown-badge-128.webp img/seals css/tokens.css lib/deck.js \
  && git commit -m "feat: recopie des polices, images, jetons et textes du site (sync-web)"
```

---

## Tâche 3 : modules purs repris du site

**Files:**
- Create (sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\`) : `format.js`, `titles.js`, `scene.js`, `links.js`, `timesync.js`, `refclock.js`.
- Test (sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\`) : `format.test.js`, `titles.test.js`, `scene.test.js`, `links.test.js`, `timesync.test.js`, `refclock.test.js`.

Règle de portage :
- les sources, sous `C:\Users\Paul\Documents\Codage\GregLeConsanguin\services\web\src\lib\` :

  | Module de l'appli | Source | En-tête exact du fichier porté |
  |---|---|---|
  | `lib/format.js` | `format.ts` | `// Porté de services/web/src/lib/format.ts (GregLeConsanguin c6063f0).` |
  | `lib/titles.js` | `titles.ts` | `// Porté de services/web/src/lib/titles.ts (GregLeConsanguin c6063f0).` |
  | `lib/scene.js` | `stage\scene.ts` | `// Porté de services/web/src/lib/stage/scene.ts (GregLeConsanguin c6063f0).` |
  | `lib/links.js` | `links.ts` | `// Porté de services/web/src/lib/links.ts (GregLeConsanguin c6063f0).` |
  | `lib/timesync.js` | `sync\timesync.ts` | `// Porté de services/web/src/lib/sync/timesync.ts (GregLeConsanguin c6063f0).` |
  | `lib/refclock.js` | `sync\refclock.ts` | `// Porté de services/web/src/lib/sync/refclock.ts (GregLeConsanguin c6063f0).` |

- les types sont retirés ; la logique, les noms exportés et les commentaires sont gardés ;
- chaque fichier commence par l'en-tête exact de la table.

**Interfaces:**
- Produces :
  - `lib/format.js` : `fmt(sec)`, `extractVideoId(url)`, `discordAvatar(me, size = 96)`, et le nouveau `thumbOf(track): string|null` ;
  - `lib/titles.js` : `normTitle`, `cleanTitle`, `cleanArtist`, `parseTitle(title, artist) → {song, artist}` ;
  - `lib/scene.js` : `kickerKey({paused, repeat})`, `requesterOf(addedBy, meId)`, `requesterKeys(r)`, `sealInitial(name)`, `kingSealSrc(name)`, `seedOf(s)` (sans `stageScene`) ;
  - `lib/links.js` : `classifyLink(input)`, `submitLabelKey(kind)`, `isBadLink(kind)` ;
  - `lib/timesync.js` : `TS_KEEP`, `TS_MAX_RTT_MS`, `sampleOf(t0, ts, t1)`, `createTimeSync()` → `{add, best, serverNow, reset}` ;
  - `lib/refclock.js` : `REANCHOR_MS`, `clockSampleOf(payload, recvNow)`, `predict(a, t)`, `createRefClock()` → `{ingest, positionAt, anchor, reset}` (sans `clockViewOf` ni `NO_CLOCK`).

- [ ] **Step 1 : porter les tests du site, puis ajouter les cas propres à l'appli**

Porter tous les cas de `services/web/tests/{format,titles,scene,links,timesync,refclock}.test.mjs` : `loadTs(...)` devient `import * as X from '../lib/x.js'`. On saute les cas de `stageScene` et de `clockViewOf`, et le chemin attendu des sceaux devient `img/seals/…`. Puis on ajoute :

```js
// tests/format.test.js (ajouts)
test('thumbOf : vignette YouTube tirée du lien, sinon i.ytimg seulement (CSP)', () => {
  assert.equal(thumbOf({ url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', thumb: 'https://i9.ytimg.com/x.jpg' }), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
  assert.equal(thumbOf({ url: '', thumb: 'https://i.ytimg.com/vi/abc/mqdefault.jpg' }), 'https://i.ytimg.com/vi/abc/mqdefault.jpg');
  assert.equal(thumbOf({ url: 'https://soundcloud.com/a/b', thumb: 'https://i1.sndcdn.com/a.jpg' }), null);
  assert.equal(thumbOf({ url: '', thumb: 'pas une url' }), null);
});
// tests/scene.test.js (ajout)
test('kingSealSrc pointe dans img/seals', () => {
  assert.equal(kingSealSrc('Paul'), 'img/seals/king-seal-P.webp');
  assert.equal(kingSealSrc('★'), 'img/seals/king-seal-fleur.webp');
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/format.test.js tests/titles.test.js tests/scene.test.js tests/links.test.js tests/timesync.test.js tests/refclock.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : porter les six modules**

`thumbOf(track)` :
- `https://i.ytimg.com/vi/<id>/hqdefault.jpg` si `extractVideoId(track.url)` donne un id ;
- sinon `track.thumb` si son hôte est exactement `i.ytimg.com` ;
- sinon `null`.

`kingSealSrc(name)` vaut `` `img/seals/king-seal-${sealInitial(name)}.webp` ``.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/format.js lib/titles.js lib/scene.js lib/links.js lib/timesync.js lib/refclock.js tests/format.test.js tests/titles.test.js tests/scene.test.js tests/links.test.js tests/timesync.test.js tests/refclock.test.js \
  && git commit -m "feat: portage des modules purs du site (format, titres, scène, liens, horloges)"
```

---

## Tâche 4 : état du lecteur (`lib/player.js`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\player.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\player.test.js`.

**Interfaces:**
- Consumes : `fmt` et `extractVideoId` (`lib/format.js`), `classifyLink` (`lib/links.js`).
- Produces, portés tels quels de `services/web/src/lib/playerUtils.ts` :
  - `toSeconds`, `normalizeItem`, `buildUsersMap`, `isStalePayload` ;
  - `stateKind(payload, guildId)` → `'other'|'tick'|'full'` ;
  - `assignKeys`, `sameTrack`, `shareTracks` ;
  - `snapshotFromPayload(payload, prev, now)` → `{player, tickBase} | null`, avec `now` en `Date.now()` ;
  - `withClock(snap, {pos, at, frozen})`, `emptySnapshot(now)`, `looksLikeUrl`, `errorCode`, `errorCopy(e, ctx)` (avec `DECK_ERRORS`) ;
  - `livePosition(tb, paused, now)`, `addedCopy(res, fallbackTitle, link)`.
- Produces, portés d'autres fichiers :
  - `moveIndices(queue, key, beforeKey)` → `{src, dst}|null` (de `services/web/src/lib/queue/optimistic.ts:41-48`) ;
  - `moveBefore(keys, key, dir)` → `string|null|undefined` (de `services/web/src/lib/keys.ts:58-62`).
- Produces, nouveaux :
  - `joinErrorAction(p, guildId)` → `{action: 'ignore'|'retry'|'show', code}` (le `guildJoinErrorAction` du site, sans texte) ;
  - `expectedOf(track)` → `{url, added_by, ts}` ;
  - `isQueueMoved(e)` → `boolean` ;
  - `pickGuild(guilds, saved, defaultId)` → `string` ;
  - `addPayloadOf(entree)` → `object`, où `entree` vaut `{texte}` ou `{suggestion}` ;
  - `normalizeSuggestions(data)` → `Suggestion[]`, où `Suggestion = {title, url, artist, duration, thumb, provider}` ;
  - `publicTrack(track)` → le titre sans `raw`.

- [ ] **Step 1 : écrire les tests qui échouent**

Porter les cas de `services/web/tests/playerUtils.test.mjs` qui visent les fonctions portées. On ne porte pas `describeError`, `staleStateText`, `enqueueSuccessText`, `guildJoinErrorAction`, `recoveredStatusText`, `createSeqGate`, `pickDefaultGuild`, `isShortcutIgnored` ni `enterPicksSuggestion`. On porte aussi `tests/keys.test.mjs:66-68` pour `moveBefore`. Puis on ajoute :

```js
test('expectedOf reprend url, added_by et ts du titre brut, null s’ils manquent', () => {
  const t = normalizeItem({ title: 'x', url: 'u', added_by: '42', ts: 1732540000.123 });
  assert.deepEqual(expectedOf(t), { url: 'u', added_by: '42', ts: 1732540000.123 });
  assert.deepEqual(expectedOf(normalizeItem({ title: 'x', url: 'u' })), { url: 'u', added_by: null, ts: null });
});
test('isQueueMoved : 409 STALE ou 409 sans code (index hors bornes), rien d’autre', () => {
  assert.equal(isQueueMoved({ status: 409, payload: { ok: false, error: 'STALE' } }), true);
  assert.equal(isQueueMoved({ status: 409, payload: { ok: false } }), true);
  assert.equal(isQueueMoved({ status: 409, payload: { ok: false, error: 'USER_NOT_IN_VOICE' } }), false);
  assert.equal(isQueueMoved({ status: 403, payload: { error: 'PRIORITY_FORBIDDEN' } }), false);
});
test('pickGuild : sauvegardé, puis défaut, puis Greg en vocal, puis le premier', () => {
  const g = [{ id: '1', greg_voice: null }, { id: '2', greg_voice: { id: '9', name: 'Taverne' } }];
  assert.equal(pickGuild(g, '1', '2'), '1');
  assert.equal(pickGuild(g, '7', '2'), '2');
  assert.equal(pickGuild(g, '', null), '2');
  assert.equal(pickGuild([{ id: '1', greg_voice: null }], '', null), '1');
  assert.equal(pickGuild([], 'x', '2'), '');
});
test('addPayloadOf : texte tapé ou suggestion choisie', () => {
  assert.deepEqual(addPayloadOf({ texte: '  daft punk ' }), { query: 'daft punk' });
  const url = 'https://youtu.be/dQw4w9WgXcQ';
  assert.deepEqual(addPayloadOf({ suggestion: { title: 'T', url, artist: 'A', duration: 212, thumb: 'th', provider: '' } }),
    { query: url, url, title: 'T', artist: 'A', duration: 212, thumb: 'th', provider: 'youtube' });
  assert.deepEqual(addPayloadOf({ texte: '   ' }), { query: '' });
});
test('normalizeSuggestions : results ou tableau, champs du site', () => {
  assert.deepEqual(normalizeSuggestions({ results: [{ title: 'T', webpage_url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', uploader: 'U', duration: '3:32', thumbnail: 't', source: 'yt' }] }),
    [{ title: 'T', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', artist: 'U', duration: 212, thumb: 't', provider: 'yt' }]);
  assert.deepEqual(normalizeSuggestions(null), []);
});
test('moveIndices : le bot fait queue.insert(dst, queue.pop(src))', () => {
  const q = ['a', 'b', 'c', 'd'].map((key) => ({ key }));
  assert.deepEqual(moveIndices(q, 'd', 'b'), { src: 3, dst: 1 });
  assert.deepEqual(moveIndices(q, 'a', null), { src: 0, dst: 3 });
  assert.equal(moveIndices(q, 'b', 'c'), null);
  assert.equal(moveIndices(q, 'x', 'a'), null);
});
test('joinErrorAction : retry, show, ignore', () => {
  assert.deepEqual(joinErrorAction({ guild_id: '1', error: 'BOT_OFFLINE', retry: true }, '1'), { action: 'retry', code: 'BOT_OFFLINE' });
  assert.deepEqual(joinErrorAction({ guild_id: '1', error: 'NOT_GUILD_MEMBER', retry: false }, '1'), { action: 'show', code: 'NOT_GUILD_MEMBER' });
  assert.deepEqual(joinErrorAction({ guild_id: '2', error: 'TIMEOUT' }, '1'), { action: 'ignore', code: '' });
});
test('publicTrack retire raw', () => {
  assert.equal('raw' in publicTrack(normalizeItem({ title: 'x', url: 'u' })), false);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/player.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/player.js`**

- `expectedOf` lit `track.raw`, sans rien convertir :
  - `url: raw.url ?? null` ;
  - `added_by: raw.added_by ?? raw.requested_by ?? null` ;
  - `ts: raw.ts ?? null`.
- `isQueueMoved(e)` : `e.status === 409 && (errorCode(e) === 'STALE' || errorCode(e) === '')`.
- `addPayloadOf({suggestion: s})` :
  - `{query: s.url || s.title, url: s.url, title, artist, duration, thumb, provider: s.provider || 'youtube'}` ;
  - les champs vides sont omis, sauf `query`.
- `normalizeSuggestions` :
  - prend `data.results` ou `data` s'il est un tableau ;
  - `url = webpage_url || url`, `artist = artist || uploader || channel`, `duration = toSeconds(duration)`, `thumb = thumb || thumbnail || null`, `provider = provider || source || 'youtube'`.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/player.js tests/player.test.js \
  && git commit -m "feat: état du lecteur porté du site, plus expected, déplacements et choix du serveur"
```

---

## Tâche 5 : textes (`lib/copy.js`, `lib/copy.overlay.js`, `lib/annonces.js`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\copy.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\copy.overlay.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\annonces.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\copy.test.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\annonces.test.js`.

**Interfaces:**
- Consumes : `lib/deck.js` (default), `parseTitle` (`lib/titles.js`).
- Produces :
  - `lib/copy.js` : `SIRE_DEFAULT`, `fill(template, vars)`, `t(path, vars)`, `has(path)`, `quip(path, seed, vars)`, `kingAddress(option)`. C'est le portage de `services/web/src/theme/copy.ts` sur la racine `{...deck, ...OVERLAY}`.
  - `lib/copy.overlay.js` : `OVERLAY` (ci-dessous).
  - `lib/annonces.js` :
    - `copieAmi(evt, meId)` → `{path, vars} | null` ;
    - `motifAction({lie, serveur})` → `'ow.hotkey.notLinked' | 'ow.hotkey.noGuild' | null` ;
    - `copieRaccourcisLibres(raccourcis)` → `{path, vars} | null`. Elle prend `raccourcis = {nom: {binding, libre}}` et donne `vars.list` = les combinaisons par défaut des raccourcis libres, jointes par « , ».

`lib/copy.overlay.js`, texte exact :

```js
export const OVERLAY = {
  ow: {
    banner: {
      kicker: { playing: 'Greg · en lecture', paused: 'Greg · en pause', idle: 'Greg · au repos', offline: 'Greg · hors ligne', notLinked: 'Greg · pas encore lié', noGuild: 'Greg · sans serveur' },
      byMe: 'par vous', byOther: 'par {name}', byUnknown: 'depuis Discord',
      idleHint: '{keys} pour ajouter un titre',
      notLinked: 'Liez l’appli depuis la fenêtre Greg',
      notLinkedHint: 'Ouvrez Greg depuis Overwolf, hors partie.',
      noGuildHint: '{keys} pour choisir un serveur',
    },
    hotkey: {
      notLinked: { text: 'Greg n’est pas encore lié\u00a0: ouvrez la fenêtre Greg hors partie.', kind: 'warn' },
      noGuild: { text: 'Aucun serveur choisi\u00a0: ouvrez le panneau pour en choisir un.', kind: 'warn' },
      unassigned: { text: 'Raccourcis non attribués par Overwolf\u00a0: {list}. Changez-les dans la fenêtre Greg.', kind: 'warn' },
    },
    toast: { stale: { text: 'La file a bougé, réessayez.', kind: 'warn' } },
    remote: {
      someone: 'Quelqu’un',
      addedNoTitle: '{name} a ajouté un titre.', skippedNoTitle: '{name} a passé le titre.',
      removed: '{name} a retiré\u00a0: {title}', removedNoTitle: '{name} a retiré un titre.',
      moved: '{name} a réordonné la file.', playNowNoTitle: '{name} a lancé un titre tout de suite.',
      restarted: '{name} a repris le titre au début.', repeat: '{name} a changé la boucle.',
    },
    device: {
      intro: 'Pour que je vous obéisse en jeu, validez ce code sur le site.',
      open: 'Ouvrir le site pour l’autoriser', validity: 'Valable encore {time}',
      waiting: 'En attente de votre accord sur le site…', preparing: 'Préparation du code…', checking: 'Vérification de la liaison…',
      expired: 'Ce code a expiré.', denied: 'Demande refusée sur le site.',
      rateLimited: 'Trop de demandes de code\u00a0: réessayez dans une minute.',
      failed: 'Le site ne répond pas\u00a0: réessayez dans un instant.',
      renew: 'Nouveau code', linked: 'À votre service, {sire}.',
      pickGuild: 'Sur quel serveur dois-je jouer\u202f?', continue: 'Continuer',
    },
    guilds: {
      gregHere: 'Greg est là', gregIn: 'Greg est dans {channel}', youIn: 'Vous êtes dans {channel}', playing: 'En lecture',
      change: 'Changer de serveur', failed: 'Impossible de lire vos serveurs pour l’instant. Réessayez.',
    },
    panel: {
      idleKicker: 'Au repos', close: 'Rendre la main au jeu',
      queueHead: { one: 'À suivre · 1 titre', other: 'À suivre · {n} titres' }, total: '{n}\u00a0min',
      footer: { pause: 'pause', suivant: 'suivant', panneau: 'panneau', bandeau: 'bandeau' },
      unassigned: 'non attribué', suggestHint: { choose: 'choisir', add: 'ajouter' },
      notLinked: 'Liez l’appli depuis la fenêtre Greg, hors partie.',
    },
    queue: { more: { one: '…et 1 autre titre', other: '…et {n} autres titres' }, mine: 'Vous' },
    settings: {
      playerTab: 'Lecteur', tab: 'Réglages', hotkeys: 'Raccourcis', change: 'Changer',
      capture: 'Appuyez sur la combinaison…', captureHelp: 'Ctrl ou Alt obligatoire. Échap annule.',
      hotkeyLabels: { pause: 'Pause ou reprise', suivant: 'Titre suivant', panneau: 'Ouvrir ou fermer le panneau', bandeau: 'Afficher ou cacher le bandeau' },
      taken: 'Déjà prise par «\u00a0{name}\u00a0».', needModifier: 'Ajoutez Ctrl ou Alt.', assignFailed: 'Overwolf a refusé ce raccourci.',
      unassigned: 'Non attribué', banner: 'Le bandeau en jeu', place: 'Emplacement',
      places: { 'bas-gauche': 'En bas à gauche', 'gauche-tiers': 'Bord gauche, au tiers', 'haut-gauche': 'En haut à gauche' },
      size: 'Taille', sizes: { compacte: 'Compacte', normale: 'Normale' },
      opacity: 'Fond du bandeau', opacityHelp: 'À 0\u00a0%, il ne reste que le texte et la barre.',
      friends: 'Annoncer ce que font les amis', friendsHelp: 'Une ligne sous le bandeau, quelques secondes.',
      account: 'Compte', linkedAs: 'Lié au compte de {name}', unlink: 'Délier cet appareil',
      unlinkHelp: 'Il faudra un nouveau code pour lier l’appli de nouveau.',
      unlinkConfirm: { title: 'Délier cet appareil\u202f?', confirm: 'Délier', cancel: 'Garder' }, preview: 'Aperçu',
    },
  },
};
```

Note sur `opacity` : la spec dit « transparence », mais « à 0 %, il ne reste que le texte et la barre ». La valeur règle donc l'opacité du fond, d'où l'intitulé « Fond du bandeau ».

Table de `copieAmi` (`name` = `actor.display_name` sans espaces autour, sinon `ow.remote.someone` ; `title` = `parseTitle(evt.title).song`) :

| `action` | avec titre | sans titre |
|---|---|---|
| `add` | `remote.added` | `ow.remote.addedNoTitle` |
| `skip` | `remote.skipped` | `ow.remote.skippedNoTitle` |
| `remove` | `ow.remote.removed` | `ow.remote.removedNoTitle` |
| `play_at` | `remote.playNow` | `ow.remote.playNowNoTitle` |
| `stop`, `pause`, `resume` | `remote.stopped`, `remote.paused`, `remote.resumed` | idem |
| `move`, `repeat`, `restart` | `ow.remote.moved`, `ow.remote.repeat`, `ow.remote.restarted` | idem |
| autre | `null` | `null` |

`copieAmi` renvoie `null` si `String(evt.actor?.id) === String(meId)`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/copy.test.js
import { OVERLAY } from '../lib/copy.overlay.js';
import deck from '../lib/deck.js';
import { t, quip, has } from '../lib/copy.js';
// + porter les cas de services/web/tests/copy.test.mjs dont les chemins sont dans CHEMINS_DECK (tâche 2)
function* strings(n, p = '') { if (typeof n === 'string') { yield [p, n]; return; } for (const [k, v] of Object.entries(n)) yield* strings(v, p ? `${p}.${k}` : k); }
test('deck d’abord, puis textes de l’appli', () => {
  assert.equal(t('now.idle.title'), 'Rien en lecture');
  assert.equal(t('ow.toast.stale.text'), 'La file a bougé, réessayez.');
  assert.equal(t('remote.added', { name: 'Kévin', title: 'Thunderstruck' }), 'Kévin a ajouté\u00a0: Thunderstruck');
  assert.equal(t('ow.queue.more', { n: 3 }), '…et 3 autres titres');
  assert.equal(t('ow.panel.queueHead', { n: 1 }), 'À suivre · 1 titre');
  assert.match(quip('error.USER_NOT_IN_VOICE', 0), /^Je veux bien jouer, Sire\./);
  assert.equal(has('ow.nope'), false);
});
test('typographie du deck (services/web/tests/copy-extra.test.mjs:24-31)', () => {
  for (const [path, s] of strings(OVERLAY)) {
    assert.ok(!/ [:;!?]/.test(s), `${path} : espace ordinaire avant la ponctuation haute`);
    assert.ok(!/[^ \s]:(?!\d)/.test(s.replace(/\{\w+\}/g, '')), `${path} : « : » sans U+00A0`);
    assert.ok(!/[;!?]/.test(s.replace(/ [;!?]/g, '')), `${path} : ; ! ? sans U+202F`);
    assert.ok(!s.includes("'"), `${path} : apostrophe droite`);
  }
});
test('aucune clé de l’appli dans le deck ; Greg jamais couronné', () => {
  assert.deepEqual(Object.keys(OVERLAY), ['ow']);
  assert.equal(deck.ow, undefined);
  for (const [path, s] of strings(OVERLAY)) assert.ok(!/Greg[^.]*\b(roi|couronne|Rex)\b/i.test(s), path);
});
```

```js
// tests/annonces.test.js
const evt = (o) => ({ guild_id: '123', actor: { id: '7', display_name: 'Kévin' }, title: 'AC/DC - Thunderstruck (Official Video)', at_ms: 1, ...o });
test('ligne d’ami : action et titre nettoyé', () => {
  assert.deepEqual(copieAmi(evt({ action: 'add' }), '42'), { path: 'remote.added', vars: { name: 'Kévin', title: 'Thunderstruck' } });
  assert.deepEqual(copieAmi(evt({ action: 'add', title: null }), '42'), { path: 'ow.remote.addedNoTitle', vars: { name: 'Kévin', title: '' } });
  assert.equal(copieAmi(evt({ action: 'move' }), '42').path, 'ow.remote.moved');
  assert.equal(copieAmi(evt({ action: 'zzz' }), '42'), null);
  assert.equal(copieAmi(evt({ action: 'add', actor: { id: '7', display_name: '  ' } }), '42').vars.name, 'Quelqu’un');
});
test('Review Focus 2 : ses propres actions ne font pas de ligne d’ami', () => {
  assert.equal(copieAmi(evt({ action: 'skip', actor: { id: '42', display_name: 'Paul' } }), '42'), null);
  assert.equal(copieAmi(evt({ action: 'skip', actor: { id: 42, display_name: 'Paul' } }), '42'), null);
});
test('motifAction : liaison puis serveur', () => {
  assert.equal(motifAction({ lie: false, serveur: '123' }), 'ow.hotkey.notLinked');
  assert.equal(motifAction({ lie: true, serveur: '' }), 'ow.hotkey.noGuild');
  assert.equal(motifAction({ lie: true, serveur: '123' }), null);
});
test('copieRaccourcisLibres nomme les combinaisons par défaut', () => {
  const r = { pause: { binding: 'Ctrl+F7', libre: false }, suivant: { binding: 'Ctrl+F8', libre: false }, panneau: { binding: '', libre: true }, bandeau: { binding: '', libre: true } };
  assert.deepEqual(copieRaccourcisLibres(r), { path: 'ow.hotkey.unassigned', vars: { list: 'Ctrl+F10, Ctrl+F11' } });
  assert.equal(copieRaccourcisLibres({ ...r, panneau: { binding: 'Ctrl+F10', libre: false }, bandeau: { binding: 'Ctrl+F11', libre: false } }), null);
});
```

`copieRaccourcisLibres` lit les combinaisons par défaut dans une table locale `{pause:'Ctrl+F7', suivant:'Ctrl+F8', panneau:'Ctrl+F10', bandeau:'Ctrl+F11'}` : `lib/hotkeys.js` vient plus tard (tâche 12), qui réexportera la même table sous le nom `DEFAUTS`, importée d'ici.

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/copy.test.js tests/annonces.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire les trois modules**

- `lib/copy.js` est le portage de `copy.ts` (`own`, `refOf`, `resolve` avec `MAX_REFS = 8`, `plural`, `render`, `withDefaults`). La racine est `ROOT = {...deck, ...OVERLAY}`.
- `lib/annonces.js` exporte aussi `DEFAUTS_RACCOURCIS` (la table ci-dessus).

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/copy.js lib/copy.overlay.js lib/annonces.js tests/copy.test.js tests/annonces.test.js \
  && git commit -m "feat: textes du deck et de l'appli, choix des annonces"
```

---

## Tâche 6 : le Héraut (`lib/herald.js`) et la fausse horloge

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\herald.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fakes\horloge.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\herald.test.js`.

**Interfaces:**
- Consumes : `t`, `has`, `quip` (`lib/copy.js`) ; `seedOf` (`lib/scene.js`) ; `DELAIS` (`lib/config.js`).
- Produces :
  - `LIFE = {ok: 3500, info: 4000, warn: 6000, err: 6000}`, `QUIP_EVERY_MS = 30000`, `LEAVE_MS = 260`, `VISIBLE = 3` ;
  - `LECTEUR_DECK = {t, has, quip, seedOf}` ;
  - `deckToast(key, o = {}, d = LECTEUR_DECK)` → `ToastInput` et `errorToast(c, d = LECTEUR_DECK)` → `ToastInput`, portés de `services/web/src/lib/herald.ts` ;
  - `createHerald({now, setTimer, clearTimer, quipsOn})` → `{subscribe(fn) → () => void, getSnapshot() → Toast[], notify(input) → id, dismiss(id)}`.
  - Types :
    - `ToastInput = {kind?, fact, quip?, ms?, bandeau?}` ;
    - `Toast = {id, kind, fact, quip, n, leaving, bandeau}`, le plus récent en tête.
- Produces (`tests/fakes/horloge.js`) : `creerHorloge(debut = 1_700_000_000_000)` → `{now, perfNow, setTimeout, clearTimeout, setInterval, clearInterval, avancer(ms): Promise, vider(): Promise}`.
  - `avancer` exécute dans l'ordre les minuteurs échus et attend `new Promise((r) => setImmediate(r))` après chacun, pour que les promesses se règlent.
  - `perfNow()` vaut `now() - debut`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/herald.test.js
const monter = (quipsOn = () => true) => { const h = creerHorloge(); return { h, her: createHerald({ now: h.now, setTimer: h.setTimeout, clearTimer: h.clearTimeout, quipsOn }) }; };
test('une erreur vit 6 s, puis part (leaving), retirée 260 ms après', async () => {
  const { h, her } = monter(); her.notify({ kind: 'err', fact: 'X' });
  await h.avancer(5999); assert.equal(her.getSnapshot()[0].leaving, false);
  await h.avancer(1); assert.equal(her.getSnapshot()[0].leaving, true);
  await h.avancer(260); assert.equal(her.getSnapshot().length, 0);
});
test('même fait et même sorte : ×2 et minuteur relancé', async () => {
  const { h, her } = monter(); her.notify({ kind: 'warn', fact: 'Y' }); await h.avancer(5000); her.notify({ kind: 'warn', fact: 'Y' });
  assert.equal(her.getSnapshot().length, 1); assert.equal(her.getSnapshot()[0].n, 2);
  await h.avancer(5999); assert.equal(her.getSnapshot()[0].leaving, false);
});
test('au plus une réplique toutes les 30 s', async () => {
  const { h, her } = monter(); const vus = [];
  her.notify({ kind: 'err', fact: 'a', quip: 'q1' }); vus.push(her.getSnapshot()[0].quip);
  await h.avancer(10000); her.notify({ kind: 'err', fact: 'b', quip: 'q2' }); vus.push(her.getSnapshot()[0].quip);
  await h.avancer(21000); her.notify({ kind: 'err', fact: 'c', quip: 'q3' }); vus.push(her.getSnapshot()[0].quip);
  assert.deepEqual(vus, ['q1', null, 'q3']);
});
test('répliques coupées : quip null, et la fenêtre de 30 s n’est pas consommée', async () => {
  let on = false; const { h, her } = monter(() => on);
  her.notify({ fact: 'a', quip: 'q1' }); on = true; her.notify({ fact: 'b', quip: 'q2' });
  assert.deepEqual(her.getSnapshot().map((x) => x.quip), ['q2', null]);
});
test('ms explicite et bandeau recopiés', async () => {
  const { h, her } = monter(); her.notify({ kind: 'info', fact: 'ami', ms: 5000, bandeau: true });
  assert.equal(her.getSnapshot()[0].bandeau, true); await h.avancer(5000); assert.equal(her.getSnapshot()[0].leaving, true);
});
test('errorToast : texte du deck, sorte err, réplique de l’entrée', () => {
  const x = errorToast({ key: 'error.USER_NOT_IN_VOICE', path: 'error.USER_NOT_IN_VOICE.text' });
  assert.equal(x.kind, 'err'); assert.equal(x.fact, 'Rejoignez d’abord un salon vocal sur ce serveur, puis réessayez.'); assert.ok(x.quip);
  assert.equal(deckToast('ow.toast.stale').kind, 'warn');
});
```
- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/herald.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/herald.js` et `tests/fakes/horloge.js`**

`createHerald` est le `createHerald` du site, réduit à `notify`, `dismiss`, `subscribe` et `getSnapshot` : ni annulation, ni survol, ni onglet.
- La durée vaut `input.ms ?? LIFE[kind]`, avec `kind = input.kind ?? 'ok'`.
- La réplique est gardée seulement si `quipsOn()` et si 30 s se sont écoulées depuis la dernière gardée.
- `bandeau: Boolean(input.bandeau)`.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/herald.js tests/fakes/horloge.js tests/herald.test.js \
  && git commit -m "feat: le Héraut de l'appli (durées, ×N, une réplique par 30 s)"
```

---

## Tâche 7 : réglages et placement (`lib/settings.js`, `lib/placement.js`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\settings.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\placement.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fakes\stockage.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\settings.test.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\placement.test.js`.

**Interfaces:**
- Produces (`lib/settings.js`) :
  - `REGLAGES_DEFAUT = {emplacement:'bas-gauche', taille:'normale', opacite:70, amis:true, repliques:true, serveur:''}` ;
  - `nettoyerReglages(brut)` → `Reglages` ;
  - `lireReglages(storage)` → `Reglages` (clé `STORAGE.reglages`) ;
  - `ecrireReglages(storage, r)` → `void` ;
  - `fondBandeau(opacite)` → `number` (de 0 à 1).
- Produces (`lib/placement.js`) :
  - `TAILLES_BANDEAU = {normale: {width: 340, height: 132}, compacte: {width: 300, height: 92}}` ;
  - `PANNEAU = {width: 440, height: 680}` ;
  - `EMPLACEMENTS = ['bas-gauche','gauche-tiers','haut-gauche']`, `MARGE_BAS = 24` ;
  - `positionBandeau({emplacement, taille, hauteurJeu, marge = MARGE_BAS})` → `{left, top} | null` ;
  - `positionPanneau(hauteurJeu)` → `{left, top} | null`.
- Produces (`tests/fakes/stockage.js`) : `creerStockage(init = {}, {casse = false} = {})` → `{getItem, setItem, removeItem, donnees: Map}`. Avec `casse`, chaque appel lève une erreur.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/settings.test.js
test('défauts', () => assert.deepEqual(REGLAGES_DEFAUT, { emplacement: 'bas-gauche', taille: 'normale', opacite: 70, amis: true, repliques: true, serveur: '' }));
test('nettoyage', () => {
  const n = (o) => nettoyerReglages({ ...REGLAGES_DEFAUT, ...o });
  assert.equal(n({ opacite: 140 }).opacite, 100); assert.equal(n({ opacite: -5 }).opacite, 0);
  assert.equal(n({ opacite: '55' }).opacite, 55); assert.equal(n({ opacite: 33.6 }).opacite, 34); assert.equal(n({ opacite: 'abc' }).opacite, 70);
  assert.equal(n({ emplacement: 'droite' }).emplacement, 'bas-gauche'); assert.equal(n({ taille: 'grande' }).taille, 'normale');
  assert.equal(n({ amis: 'oui' }).amis, true); assert.equal(n({ repliques: false }).repliques, false);
  assert.equal(n({ serveur: '123456789012345678' }).serveur, '123456789012345678'); assert.equal(n({ serveur: 'abc' }).serveur, '');
  assert.deepEqual(nettoyerReglages(null), REGLAGES_DEFAUT);
});
test('stockage absent, cassé ou illisible : défauts, sans exception', () => {
  assert.deepEqual(lireReglages(null), REGLAGES_DEFAUT);
  assert.deepEqual(lireReglages(creerStockage({}, { casse: true })), REGLAGES_DEFAUT);
  assert.deepEqual(lireReglages(creerStockage({ 'greg.ow.reglages': '{pas du json' })), REGLAGES_DEFAUT);
  assert.doesNotThrow(() => ecrireReglages(creerStockage({}, { casse: true }), REGLAGES_DEFAUT));
  const s = creerStockage(); ecrireReglages(s, { ...REGLAGES_DEFAUT, opacite: 40 }); assert.equal(lireReglages(s).opacite, 40);
});
test('fondBandeau', () => { assert.equal(fondBandeau(70), 0.7); assert.equal(fondBandeau(0), 0); assert.equal(fondBandeau(100), 1); });
```

```js
// tests/placement.test.js
test('bas à gauche par défaut : left 16, top = max(16, h − hauteur − MARGE_BAS), MARGE_BAS = 24', () => {
  assert.equal(MARGE_BAS, 24);   // valeur de départ ; la tâche 18 (étape 8) l'ajuste sur une capture de LoL, avec les valeurs ci-dessous
  assert.deepEqual(positionBandeau({ emplacement: 'bas-gauche', taille: 'normale', hauteurJeu: 1080 }), { left: 16, top: 924 });
  assert.deepEqual(positionBandeau({ emplacement: 'bas-gauche', taille: 'compacte', hauteurJeu: 1080 }), { left: 16, top: 964 });
  assert.deepEqual(positionBandeau({ emplacement: 'bas-gauche', taille: 'normale', hauteurJeu: 1440 }), { left: 16, top: 1284 });
  assert.deepEqual(positionBandeau({ emplacement: 'bas-gauche', taille: 'normale', hauteurJeu: 1080, marge: 2000 }), { left: 16, top: 16 });
});
test('bord gauche au tiers et en haut à gauche', () => {
  assert.deepEqual(positionBandeau({ emplacement: 'gauche-tiers', taille: 'normale', hauteurJeu: 1080 }), { left: 16, top: 313 });
  assert.deepEqual(positionBandeau({ emplacement: 'haut-gauche', taille: 'normale', hauteurJeu: 1080 }), { left: 16, top: 16 });
});
test('jamais de déplacement sous 200 px (Plein écran hors focus = 1×1)', () => {
  for (const h of [0, 1, 199]) assert.equal(positionBandeau({ emplacement: 'bas-gauche', taille: 'normale', hauteurJeu: h }), null);
  assert.deepEqual(positionBandeau({ emplacement: 'bas-gauche', taille: 'normale', hauteurJeu: 200 }), { left: 16, top: 44 });
  assert.equal(positionPanneau(199), null);
});
test('panneau : left 24, top = max(10, min(11,5 % de h, h − 680 − 20))', () => {
  assert.deepEqual(positionPanneau(1080), { left: 24, top: 124 });
  assert.deepEqual(positionPanneau(720), { left: 24, top: 20 });
});
test('les tailles du manifeste suivent celles du code', () => {
  const m = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'));
  assert.deepEqual(m.data.windows.bandeau.size, TAILLES_BANDEAU.normale);
  assert.deepEqual(m.data.windows.panneau.size, PANNEAU);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/settings.test.js tests/placement.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire les deux modules et `tests/fakes/stockage.js`**

`nettoyerReglages` :
- un booléen qui n'en est pas un prend la valeur par défaut ;
- `opacite` : `Math.round(Number(x))`, bornée à `[0, 100]`, et 70 si `NaN` ;
- `serveur` doit vérifier `/^\d{1,25}$/`.

`positionBandeau` :
- `null` si `hauteurJeu < HAUTEUR_MIN` ;
- `bas-gauche` : `top = Math.max(16, hauteurJeu − TAILLES_BANDEAU[taille].height − marge)`. Le plancher garde le bandeau dans le jeu si la tâche 18 relève fortement `MARGE_BAS` ;
- `gauche-tiers` : `Math.round(hauteurJeu * 0.29)` ;
- `haut-gauche` : 16.

`positionPanneau` est la formule de l'essai (`C:\Users\Paul\Documents\Codage\greg-overlay-ow\essai-overwolf\fond.js:203`) avec `PANNEAU.height`.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/settings.js lib/placement.js tests/fakes/stockage.js tests/settings.test.js tests/placement.test.js \
  && git commit -m "feat: réglages de l'appli et placement du bandeau en bas à gauche"
```

---

## Tâche 8 : client REST (`lib/api.js`) et faux `fetch`

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\api.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fakes\fetch.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\api.test.js`.

**Interfaces:**
- Consumes : `API_BASE` (`lib/config.js`).
- Produces :
  - `class ApiError extends Error`, avec `name: 'ApiError'`, `status`, `payload` et `message = payload?.error || payload?.message || 'HTTP ' + status`.
  - `createApi({fetch, base = API_BASE, getToken, onUnauthorized})` donne les méthodes suivantes. Chacune renvoie une Promise du corps JSON ; `guildId` est une chaîne.
    - liaison et identité : `deviceStart(clientName)`, `deviceToken(deviceCode)` → `{status, body}` (ne lève qu'en cas d'erreur réseau), `me()`, `guilds()`, `logout()` ;
    - lecteur : `playlist(guildId)`, `add(guildId, payload)`, `skip(guildId)`, `stop(guildId)`, `togglePause(guildId)`, `restart(guildId)`, `repeat(guildId)`, `voiceJoin(guildId)` ;
    - file : `remove(guildId, index, expected)`, `move(guildId, src, dst, expected)`, `playAt(guildId, index, expected)` ;
    - recherche : `autocomplete(q, limit)` → `Array`.
- Produces (`tests/fakes/fetch.js`) : `creerFetch(routes = {})` → `{fetch, appels, routes}`.
  - `routes` est lu à chaque appel : un test peut ajouter ou changer une route en cours de route (`f.routes['POST /queue/remove'] = …`).
  - Les réponses arrivent par promesse, jamais par minuteur, pour que `horloge.avancer` et `horloge.vider` les règlent.
  - La clé de route vaut `'MÉTHODE /chemin'`, chemin pris après `/api/v1` et sans la requête.
  - La valeur vaut `{status, body}`, ou `(appel) => ({status, body})`, ou `'reseau'` (lève `new TypeError('Failed to fetch')`).
  - Le défaut est `{status: 200, body: {ok: true}}`.
  - Un `appel` vaut `{methode, chemin, query, headers, corps, credentials}`, avec des clés d'en-tête en minuscules.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/api.test.js
const monter = (routes, jeton = 'greg_ow_abc') => { const f = creerFetch(routes); let perdu = 0;
  const api = createApi({ fetch: f.fetch, getToken: () => jeton, onUnauthorized: () => { perdu++; } }); return { f, api, perdu: () => perdu }; };
const E = { url: 'u', added_by: '42', ts: 1.5 };
test('action : URL, corps guild_id, Bearer, JSON, sans cookie', async () => {
  const { f, api } = monter(); await api.skip('123');
  const a = f.appels[0];
  assert.deepEqual([a.methode, a.chemin, a.corps, a.credentials], ['POST', '/queue/skip', { guild_id: '123' }, 'omit']);
  assert.equal(a.headers.authorization, 'Bearer greg_ow_abc'); assert.equal(a.headers['content-type'], 'application/json');
});
test('remove, move et play_at envoient expected', async () => {
  const { f, api } = monter(); await api.remove('123', 1, E); await api.move('123', 3, 1, E); await api.playAt('123', 2, E);
  assert.deepEqual(f.appels.map((a) => [a.chemin, a.corps]), [['/queue/remove', { guild_id: '123', index: 1, expected: E }],
    ['/player/move', { guild_id: '123', src: 3, dst: 1, expected: E }], ['/playlist/play_at', { guild_id: '123', index: 2, expected: E }]]);
});
test('lectures : playlist et autocomplete', async () => {
  const { f, api } = monter({ 'GET /search/autocomplete': { status: 200, body: { results: [{ title: 'T' }] } } });
  await api.playlist('123'); assert.deepEqual([f.appels[0].chemin, f.appels[0].query, f.appels[0].corps], ['/playlist', { guild_id: '123' }, null]);
  assert.deepEqual(await api.autocomplete('noir dés', 6), [{ title: 'T' }]); assert.deepEqual(f.appels[1].query, { q: 'noir dés', limit: '6' });
});
test('liaison : jamais d’Authorization ; les erreurs RFC 8628 ne lèvent pas', async () => {
  const { f, api } = monter({ 'POST /overlay/token': { status: 400, body: { ok: false, error: 'authorization_pending' } } });
  await api.deviceStart('GregLC · Overwolf'); assert.deepEqual(f.appels[0].corps, { client_name: 'GregLC · Overwolf' }); assert.equal(f.appels[0].headers.authorization, undefined);
  assert.deepEqual(await api.deviceToken('dc1'), { status: 400, body: { ok: false, error: 'authorization_pending' } });
  assert.equal(f.appels[1].headers.authorization, undefined);
});
test('401 avec jeton : onUnauthorized une fois, ApiError 401', async () => {
  const m = monter({ 'POST /queue/skip': { status: 401, body: { ok: false, error: 'NOT_AUTHENTICATED' } } });
  await assert.rejects(m.api.skip('123'), (e) => e.name === 'ApiError' && e.status === 401); assert.equal(m.perdu(), 1);
});
test('sans jeton : ni en-tête, ni onUnauthorized', async () => {
  const m = monter({ 'GET /overlay/me': { status: 401, body: { ok: false, error: 'NOT_AUTHENTICATED' } } }, null);
  await assert.rejects(m.api.me()); assert.equal(m.f.appels[0].headers.authorization, undefined); assert.equal(m.perdu(), 0);
});
test('2xx ok:false lève avec le corps ; réseau : TypeError', async () => {
  const m = monter({ 'GET /playlist': { status: 200, body: { ok: false, stale: true, backend_error: 'BOT_OFFLINE' } }, 'POST /queue/stop': 'reseau' });
  await assert.rejects(m.api.playlist('1'), (e) => e.payload.backend_error === 'BOT_OFFLINE');
  await assert.rejects(m.api.stop('1'), (e) => e.name === 'TypeError');
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/api.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/api.js` et `tests/fakes/fetch.js`**

Une fonction privée `requete(methode, chemin, {corps, query, auth = true})` :
- `credentials: 'omit'`, `Accept: application/json` ;
- `Content-Type: application/json` seulement avec un corps ;
- `Authorization` seulement si `auth` et `getToken()` ;
- corps vide toléré (`{}`) ;
- `!res.ok` : si 401 avec `Authorization` envoyé, appelle `onUnauthorized()`, puis lève `ApiError` ;
- 2xx avec `ok === false` : lève `ApiError`.

`deviceStart` et `deviceToken` passent `auth: false`. `deviceToken` renvoie `{status, body}` sans lever pour tout statut HTTP.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/api.js tests/fakes/fetch.js tests/api.test.js \
  && git commit -m "feat: client REST à jeton porteur"
```

---

## Tâche 9 : liaison par code (`fond/connexion.js`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\connexion.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\connexion.test.js`.

**Interfaces:**
- Consumes : `ApiError` et les méthodes `deviceStart`, `deviceToken`, `me` et `logout` de l'objet `api` (tâche 8) ; `STORAGE`, `CLIENT_NAME` ; `creerHorloge`, `creerStockage`.
- Produces : `createConnexion({api, storage, horloge, ouvrirUrl, surChangement})` →
  - `etat()` → `EtatConnexion` ;
  - `jeton()` → `string|null` ;
  - `demarrer()` → `Promise<void>` ;
  - `nouveauCode()` → `Promise<void>` ;
  - `ouvrirSite()` → `void` ;
  - `delier()` → `Promise<boolean>` ;
  - `oublier(raison)` → `void`, idempotent.
- `EtatConnexion = {statut, code, uri, expireA, user: {id, name, avatar}|null, serveurDefaut: string|null, erreur: 'RATE_LIMITED'|'RESEAU'|null}`.
  - `statut` vaut `'verification'`, `'non-lie'`, `'code'`, `'code-expire'`, `'refuse'` ou `'lie'`.
  - `erreur` ne vaut autre chose que `null` qu'en `non-lie`, après un échec de `deviceStart` : `RATE_LIMITED` pour un 429, `RESEAU` pour tout le reste.
  - `name = global_name || username`.
  - `uri` = `verification_uri_complete`.
- Stockage :
  - `STORAGE.token` contient le jeton seul ;
  - `STORAGE.profil` contient `JSON {user, serveurDefaut}`, pour démarrer lié même hors ligne.

Comportement :
- `demarrer()` :
  - sans jeton : `non-lie`, sans requête ;
  - avec jeton : `verification`, puis `me()` ;
  - succès : `lie`, profil rangé ;
  - `ApiError` 401 : `oublier` ;
  - erreur réseau ou 5xx : `lie` avec le profil rangé, jeton gardé.
- `nouveauCode()` :
  - incrémente une génération : la réponse d'une génération dépassée est ignorée, et le minuteur de sondage précédent est annulé ;
  - remet `erreur` à `null` avant d'appeler `deviceStart` ;
  - `deviceStart(CLIENT_NAME)` donne `code`, puis un sondage toutes les `interval` s ;
  - `authorization_pending` : on continue ; `slow_down` : `interval += 5` ;
  - `access_denied` : `refuse` ; `expired_token`, ou `expireA` atteint (600 s) : `code-expire` ; sondage arrêté dans ces deux cas ;
  - 200 : jeton et profil rangés, `lie` ;
  - échec de `deviceStart` :
    - `ApiError` 429 : `non-lie` avec `erreur: 'RATE_LIMITED'` ;
    - toute autre `ApiError` (400 `INVALID_REQUEST`, 503 `STORAGE_UNAVAILABLE` du plan A…) ou une erreur réseau (`TypeError`) : `non-lie` avec `erreur: 'RESEAU'`. La fenêtre affiche alors `ow.device.failed` et le bouton « Nouveau code » (tâche 17), et ne reste jamais sur « Préparation du code… » ;
  - 429, 5xx ou réseau sur `deviceToken` : on continue au même rythme.
- `surChangement(etat())` est appelé à chaque changement de `statut` ou d'`erreur`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/connexion.test.js
const CODE = { ok: true, device_code: 'dc1', user_code: 'BCDF-GHJK', verification_uri: 'https://site/lier', verification_uri_complete: 'https://site/lier?code=BCDF-GHJK', expires_in: 600, interval: 5 };
const USER = { id: '42', username: 'paul', global_name: 'Paul', avatar: 'av' };
const JETON = { ok: true, access_token: 'greg_ow_abc', token_type: 'Bearer', expires_in: 15552000, user: USER, default_guild_id: '123' };
const pending = { status: 400, body: { ok: false, error: 'authorization_pending' } };
function monter({ stockage = creerStockage(), api = {} } = {}) {
  const horloge = creerHorloge(); const urls = []; const statuts = []; const erreurs = [];
  const c = createConnexion({ api: { me: async () => ({ ok: true, via: 'overlay', user: USER, default_guild_id: '123' }), deviceStart: async () => CODE,
    deviceToken: async () => pending, logout: async () => ({ ok: true }), ...api }, storage: stockage, horloge, ouvrirUrl: (u) => urls.push(u),
    surChangement: (e) => { statuts.push(e.statut); erreurs.push(e.erreur); } });
  return { c, horloge, stockage, urls, statuts, erreurs };
}
test('sans jeton : non-lie, aucune requête', async () => {
  let n = 0; const { c } = monter({ api: { me: async () => { n++; } } }); await c.demarrer();
  assert.equal(c.etat().statut, 'non-lie'); assert.equal(n, 0);
});
test('jeton valide : lie, user et serveur par défaut, profil rangé', async () => {
  const { c, stockage } = monter({ stockage: creerStockage({ 'greg.ow.token': 'greg_ow_abc' }) }); await c.demarrer();
  assert.deepEqual([c.etat().statut, c.etat().user, c.etat().serveurDefaut], ['lie', { id: '42', name: 'Paul', avatar: 'av' }, '123']);
  assert.ok(stockage.getItem('greg.ow.profil'));
});
test('jeton refusé (401) : effacé, non-lie', async () => {
  const { c, stockage } = monter({ stockage: creerStockage({ 'greg.ow.token': 'x' }), api: { me: async () => { throw new ApiError(401, { ok: false, error: 'NOT_AUTHENTICATED' }); } } });
  await c.demarrer(); assert.equal(stockage.getItem('greg.ow.token'), null); assert.equal(c.etat().statut, 'non-lie');
});
test('API injoignable au démarrage : lie avec le profil rangé, jeton gardé', async () => {
  const { c } = monter({ stockage: creerStockage({ 'greg.ow.token': 'x', 'greg.ow.profil': JSON.stringify({ user: { id: '42', name: 'Paul', avatar: null }, serveurDefaut: '123' }) }),
    api: { me: async () => { throw new TypeError('Failed to fetch'); } } });
  await c.demarrer(); assert.equal(c.etat().statut, 'lie'); assert.equal(c.jeton(), 'x');
});
test('code : XXXX-XXXX, sondage toutes les 5 s, slow_down ajoute 5 s', async () => {
  const rep = ['authorization_pending', 'slow_down', 'authorization_pending']; const t = [];
  const { c, horloge } = monter({ api: { deviceToken: async (dc) => { t.push([dc, horloge.now()]); return { status: 400, body: { ok: false, error: rep.shift() } }; } } });
  await c.nouveauCode(); const t0 = horloge.now();
  assert.deepEqual([c.etat().statut, c.etat().code, c.etat().uri], ['code', 'BCDF-GHJK', 'https://site/lier?code=BCDF-GHJK']);
  await horloge.avancer(20000);
  assert.deepEqual(t.map(([dc, x]) => [dc, x - t0]), [['dc1', 5000], ['dc1', 10000], ['dc1', 20000]]);
});
test('jeton reçu : rangé, lie, plus aucun sondage', async () => {
  let n = 0; const { c, horloge, stockage } = monter({ api: { deviceToken: async () => (++n === 2 ? { status: 200, body: JETON } : pending) } });
  await c.nouveauCode(); await horloge.avancer(60000);
  assert.equal(stockage.getItem('greg.ow.token'), 'greg_ow_abc'); assert.equal(c.etat().statut, 'lie'); assert.equal(c.etat().serveurDefaut, '123'); assert.equal(n, 2);
});
test('refus, expiration annoncée et expiration à 600 s', async () => {
  const a = monter({ api: { deviceToken: async () => ({ status: 400, body: { ok: false, error: 'access_denied' } }) } }); await a.c.nouveauCode(); await a.horloge.avancer(5000); assert.equal(a.c.etat().statut, 'refuse');
  const b = monter({ api: { deviceToken: async () => ({ status: 400, body: { ok: false, error: 'expired_token' } }) } }); await b.c.nouveauCode(); await b.horloge.avancer(5000); assert.equal(b.c.etat().statut, 'code-expire');
  let n = 0; const d = monter({ api: { deviceToken: async () => { n++; return pending; } } }); await d.c.nouveauCode(); await d.horloge.avancer(600000);
  assert.equal(d.c.etat().statut, 'code-expire'); const vu = n; await d.horloge.avancer(60000); assert.equal(n, vu);
});
test('429 à la demande de code : non-lie, erreur RATE_LIMITED', async () => {
  const { c } = monter({ api: { deviceStart: async () => { throw new ApiError(429, { ok: false, error: 'RATE_LIMITED' }); } } });
  await c.nouveauCode(); assert.deepEqual([c.etat().statut, c.etat().erreur], ['non-lie', 'RATE_LIMITED']);
});
test('autre refus de la demande de code (503 STORAGE_UNAVAILABLE) : non-lie, erreur RESEAU, diffusée ; puis un nouveau code l’efface', async () => {
  let echec = true;
  const { c, erreurs } = monter({ api: { deviceStart: async () => { if (echec) throw new ApiError(503, { ok: false, error: 'STORAGE_UNAVAILABLE' }); return CODE; } } });
  await c.nouveauCode(); assert.deepEqual([c.etat().statut, c.etat().erreur], ['non-lie', 'RESEAU']); assert.equal(erreurs.at(-1), 'RESEAU');
  echec = false; await c.nouveauCode(); assert.deepEqual([c.etat().statut, c.etat().erreur], ['code', null]);
});
test('Review Focus 3 : deux « Nouveau code » rapprochés → un seul sondage, sur le dernier code', async () => {
  let k = 0; const sondes = [];
  const { c, horloge } = monter({ api: { deviceStart: async () => ({ ...CODE, device_code: `dc${++k}`, user_code: k === 1 ? 'BCDF-GHJK' : 'CDFG-HJKL' }),
    deviceToken: async (dc) => { sondes.push(dc); return pending; } } });
  await c.nouveauCode(); await horloge.avancer(2000); await c.nouveauCode(); await horloge.avancer(15000);
  assert.deepEqual(sondes, ['dc2', 'dc2', 'dc2']); assert.equal(c.etat().code, 'CDFG-HJKL');
});
test('ouvrirSite et délier', async () => {
  const { c, urls, stockage } = monter({ stockage: creerStockage({ 'greg.ow.token': 'x' }) }); await c.nouveauCode(); c.ouvrirSite();
  assert.deepEqual(urls, ['https://site/lier?code=BCDF-GHJK']);
  assert.equal(await c.delier(), true); assert.equal(stockage.getItem('greg.ow.token'), null); assert.equal(c.etat().statut, 'non-lie');
  const r = monter({ stockage: creerStockage({ 'greg.ow.token': 'x' }), api: { logout: async () => { throw new TypeError('Failed to fetch'); } } });
  await r.c.demarrer(); assert.equal(await r.c.delier(), false); assert.equal(r.c.jeton(), 'x');
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/connexion.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `fond/connexion.js`**

Suivre exactement le comportement listé plus haut. `delier()` :
- `logout()` ;
- succès ou `ApiError` 401 : `oublier('delier')` puis `true` ;
- sinon : `false`, jeton gardé.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add fond/connexion.js tests/connexion.test.js \
  && git commit -m "feat: liaison par code et cycle de vie du jeton"
```

---

## Tâche 10 : temps réel (`fond/temps-reel.js`) et socket.io-client 4.7.5

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\temps-reel.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\vendor\socket.io.min.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\vendor\socket.io-client.LICENSE`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fakes\socket.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\temps-reel.test.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\vendor.test.js`.

**Interfaces:**
- Consumes : `API_ORIGIN`, `SOCKET_PATH`, `DELAIS` ; `createTimeSync` (`lib/timesync.js`) ; `joinErrorAction` (`lib/player.js`).
- Produces : `createTempsReel({io, horloge, perfNow, sonder, surEtat, surEvenement, surRefusServeur, surStatut, surJetonRefuse, surEchecSondage})` →
  - `connecter(jeton)`, `deconnecter()` ;
  - `suivre(guildId)` ;
  - `demanderEtat()` ;
  - `heureApi()` → `number|null` ;
  - `connecte()` → `boolean`.
  - Rappels : `sonder(guildId)` → `Promise<payload>` ; `surEtat(payload)`, `surEvenement(evt)`, `surRefusServeur(p)`, `surStatut(connecte)`, `surJetonRefuse()`, `surEchecSondage(erreur)`.
- Produces (`tests/fakes/socket.js`) : `creerIo()` → `{io, sockets}`. `io(url, opts)` crée et renvoie un `FauxSocket` :
  - champs : `url`, `opts`, `connected` (faux à la création), `active` (vrai à la création, puisque `io()` se connecte seul), `emis: [{ev, data}]` ;
  - méthodes : `on`, `off`, `removeAllListeners`, `emit(ev, data, ack?)`, `timeout(ms)` → `{emit(ev, data, cb)}`, `connect()` (passe `active` à vrai), `disconnect()` (passe `connected` et `active` à faux) ;
  - aides de test :
    - `ouvrir()` : passe `connected` et `active` à vrai, puis émet `connect` ;
    - `couper(raison = 'transport close')` : passe `connected` à faux, et `active` à faux seulement pour `'io server disconnect'` (le client ne se reconnecte pas seul après une coupure du serveur), puis émet `disconnect` avec `raison` ;
    - `refuser(message, {actif = false} = {})` : passe `connected` à faux et `active` à `actif`, puis émet `connect_error` avec `new Error(message)`. `actif: false` imite un refus du serveur dans un middleware (`ConnectionRefusedError` du plan A) ; `actif: true`, un échec passager que socket.io réessaie seul ;
    - `serveur(ev, payload)`, `repondreTimeSync(ts)` (répond `{t0, ts}` à chaque `time_sync` en attente).
  - Ces valeurs de `active` suivent la doc de socket.io-client 4 (https://socket.io/docs/v4/client-socket-instance/, `connect_error` et `socket.active`) : un refus du serveur dans un middleware, ou une coupure `io server disconnect`, laisse `active` à faux, et le client ne se reconnecte plus sans `socket.connect()`.

Comportement :
- `connecter(jeton)` :
  - ferme l'ancien socket (`removeAllListeners` + `disconnect`) ;
  - crée `io(API_ORIGIN, {path: SOCKET_PATH, auth: {token: jeton}, transports: ['websocket'], reconnection: true, timeout: 8000})`.
- `deconnecter()` : ferme le socket (`removeAllListeners` + `disconnect`), arrête le sondage de repli, les mesures `time_sync` et la relance programmée.
- `connect` :
  - `surStatut(true)`, sondage arrêté ;
  - `join_guild {guild_id}` si un serveur est suivi ;
  - salve `time_sync` : 5 mesures espacées de 1 s, puis une toutes les 30 s, par `socket.timeout(2000).emit('time_sync', {t0: perfNow()}, cb)`. À une nouvelle connexion, les anciennes mesures servent jusqu'à la première nouvelle, comme `services/web/src/lib/socket.ts:111-146`.
- `disconnect(raison)` :
  - `surStatut(false)`, sondage toutes les 5 s s'il y a un serveur ;
  - si `raison === 'io server disconnect'` : relance programmée (voir plus bas).
- `connect_error` :
  - message `NOT_AUTHENTICATED` : `surJetonRefuse()` une fois, puis `deconnecter()`, donc ni sondage ni reconnexion ;
  - autre message : sondage toutes les 5 s s'il y a un serveur ;
  - autre message avec `socket.active === false` (refus du serveur, comme `STORAGE_UNAVAILABLE` quand Redis tombe, plan A tâche 6) : relance programmée. Avec `socket.active === true`, socket.io réessaie seul et on ne relance rien.
- Relance programmée :
  - un seul minuteur, `socket.connect()` après `DELAIS.reessaiServeur` (5 s) ; un nouveau report remplace l'ancien ;
  - au déclenchement, `socket.connect()` seulement si le socket n'est pas connecté ;
  - `deconnecter()` et `connecter(jeton)` l'annulent, donc rien ne repart après un jeton refusé.
- Le sondage de repli n'a qu'un minuteur : une deuxième coupure ou un deuxième `connect_error` ne le double pas.
- Événements :
  - `playlist_update` : `surEtat` ;
  - `player_event` : `surEvenement` ;
  - `guild_join_error` : `joinErrorAction(p, suivi)` ; `retry` réémet `join_guild` après 5 s si c'est toujours le même serveur et que le socket est connecté ; puis `surRefusServeur(p)`.
- Sondage : `await sonder(g)`, puis `surEtat(payload)` si `g` est toujours suivi ; une erreur va à `surEchecSondage`.
- `suivre(id)` :
  - même serveur : rien ;
  - connecté : `leave_guild {guild_id: ancien}` puis `join_guild {guild_id: id}` ;
  - socket coupé ou refusé depuis la dernière connexion (mode repli) : sondage immédiat du nouveau serveur, puis le sondage toutes les 5 s continue (ou démarre) sur lui ;
  - juste après `connecter`, avant la première connexion : rien de plus, `join_guild` part au `connect`. Les tests « Review Focus 4 », « socket coupé » et « connect_error refusé par le serveur » comptent sur ce point : `connecter` puis `suivre` ne sondent pas.
- `demanderEtat()` : connecté, `request_state {guild_id}` ; sinon `sonder` tout de suite.
- `heureApi()` = `timeSync.serverNow(perfNow())`.

- [ ] **Step 1 : copier socket.io-client 4.7.5 depuis le registre npm**

C'est un téléchargement : si l'environnement demande un accord, le demander à Paul.

Le paquet est déballé dans un dossier neuf du scratchpad de la session qui exécute (contrainte « Scratchpad ») : `SCRATCHPAD` est posé en tête de la commande, au chemin Git Bash de ce scratchpad.

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && SCRATCHPAD='<scratchpad>' && test -d "$SCRATCHPAD" && S="$SCRATCHPAD/sio475" \
  && mkdir -p "$S" && (cd "$S" && npm pack socket.io-client@4.7.5 && tar -xzf socket.io-client-4.7.5.tgz) \
  && mkdir -p vendor && cp "$S/package/dist/socket.io.min.js" vendor/socket.io.min.js && cp "$S/package/LICENSE" vendor/socket.io-client.LICENSE \
  && head -c 120 vendor/socket.io.min.js
```
Expected : l'en-tête contient `Socket.IO v4.7.5`.

- [ ] **Step 2 : écrire les tests qui échouent**

```js
// tests/vendor.test.js
test('socket.io-client 4.7.5 copié avec sa licence', () => {
  assert.ok(readFileSync('vendor/socket.io.min.js', 'utf8').slice(0, 300).includes('Socket.IO v4.7.5'));
  assert.match(readFileSync('vendor/socket.io-client.LICENSE', 'utf8'), /MIT/);
});
```

```js
// tests/temps-reel.test.js
function monter(o = {}) {
  const horloge = creerHorloge(); const { io, sockets } = creerIo(); const vus = { etats: [], statuts: [], refus: 0, sondes: [], evts: [] };
  const tr = createTempsReel({ io, horloge, perfNow: horloge.perfNow, sonder: async (g) => { vus.sondes.push([g, horloge.now()]); return { guild_id: g }; },
    surEtat: (p) => vus.etats.push(p), surEvenement: (e) => vus.evts.push(e), surRefusServeur: () => {}, surStatut: (c) => vus.statuts.push(c),
    surJetonRefuse: () => { vus.refus++; }, surEchecSondage: () => {}, ...o });
  return { tr, horloge, sockets, vus };
}
test('connecter : io(origin, path, auth.token, websocket seul)', () => {
  const { tr, sockets } = monter(); tr.connecter('greg_ow_abc');
  assert.equal(sockets[0].url, 'https://greg-api.up.railway.app');
  assert.deepEqual([sockets[0].opts.path, sockets[0].opts.auth, sockets[0].opts.transports], ['/socket.io', { token: 'greg_ow_abc' }, ['websocket']]);
});
test('abonnement : join à la connexion, puis leave/join au changement', async () => {
  const { tr, sockets } = monter(); tr.connecter('j'); tr.suivre('123'); sockets[0].ouvrir();
  tr.suivre('456');
  assert.deepEqual(sockets[0].emis.filter((x) => x.ev !== 'time_sync'), [{ ev: 'join_guild', data: { guild_id: '123' } },
    { ev: 'leave_guild', data: { guild_id: '123' } }, { ev: 'join_guild', data: { guild_id: '456' } }]);
});
test('Review Focus 4 : connect_error NOT_AUTHENTICATED → jeton refusé une fois, plus rien ensuite', async () => {
  const { tr, sockets, horloge, vus } = monter(); tr.connecter('j'); tr.suivre('123'); sockets[0].refuser('NOT_AUTHENTICATED');
  await horloge.avancer(30000);
  assert.equal(vus.refus, 1); assert.equal(vus.sondes.length, 0); assert.equal(sockets[0].connected, false); assert.equal(sockets.length, 1);
  assert.equal(sockets[0].active, false);   // aucun socket.connect() n'est reparti avec le vieux jeton
});
test('connect_error refusé par le serveur (STORAGE_UNAVAILABLE, socket inactif) : sondage toutes les 5 s et un seul connect() à 5 s', async () => {
  const { tr, sockets, horloge, vus } = monter(); tr.connecter('j'); tr.suivre('123');
  let relance = 0; sockets[0].connect = () => { relance++; };
  sockets[0].refuser('STORAGE_UNAVAILABLE');
  await horloge.avancer(4999); assert.deepEqual([relance, vus.sondes.length], [0, 0]);
  await horloge.avancer(1); assert.deepEqual([relance, vus.sondes.length], [1, 1]);
  await horloge.avancer(10000); assert.deepEqual([relance, vus.sondes.length], [1, 3]);
  assert.equal(vus.refus, 0);   // STORAGE_UNAVAILABLE n'efface jamais le jeton
});
test('relance annulée par deconnecter() ou connecter() ; échec passager (socket actif) : sondage sans connect()', async () => {
  const a = monter(); a.tr.connecter('j'); a.tr.suivre('123'); let ra = 0; a.sockets[0].connect = () => { ra++; };
  a.sockets[0].refuser('STORAGE_UNAVAILABLE'); a.tr.deconnecter(); await a.horloge.avancer(10000);
  assert.deepEqual([ra, a.vus.sondes.length], [0, 0]);
  const b = monter(); b.tr.connecter('j'); b.tr.suivre('123'); let rb = 0; b.sockets[0].connect = () => { rb++; };
  b.sockets[0].refuser('STORAGE_UNAVAILABLE'); b.tr.connecter('k'); await b.horloge.avancer(10000);
  assert.equal(rb, 0); assert.equal(b.sockets.length, 2);
  const c = monter(); c.tr.connecter('j'); c.tr.suivre('123'); let rc = 0; c.sockets[0].connect = () => { rc++; };
  c.sockets[0].refuser('websocket error', { actif: true }); await c.horloge.avancer(10000);
  assert.deepEqual([rc, c.vus.sondes.length], [0, 2]);
});
test('socket coupé : sondage toutes les 5 s, arrêté à la reconnexion', async () => {
  const { tr, sockets, horloge, vus } = monter(); tr.connecter('j'); tr.suivre('123'); sockets[0].ouvrir(); sockets[0].couper();
  await horloge.avancer(10000); assert.equal(vus.sondes.length, 2); assert.equal(vus.etats.length, 2);
  sockets[0].ouvrir(); await horloge.avancer(20000); assert.equal(vus.sondes.length, 2);
});
test('io server disconnect : sondage, puis socket.connect() après 5 s', async () => {
  const { tr, sockets, horloge } = monter(); tr.connecter('j'); tr.suivre('123'); sockets[0].ouvrir();
  let relance = 0; sockets[0].connect = () => { relance++; }; sockets[0].couper('io server disconnect');
  await horloge.avancer(4999); assert.equal(relance, 0); await horloge.avancer(1); assert.equal(relance, 1);
});
test('time_sync : 5 mesures sur 4 s puis toutes les 30 s ; heureApi = perfNow + écart', async () => {
  const { tr, sockets, horloge } = monter(); tr.connecter('j'); sockets[0].ouvrir();
  await horloge.avancer(4000); assert.equal(sockets[0].emis.filter((x) => x.ev === 'time_sync').length, 5);
  sockets[0].repondreTimeSync(horloge.perfNow() + 50_000); assert.ok(Math.abs(tr.heureApi() - (horloge.perfNow() + 50_000)) < 5);
  await horloge.avancer(30000); assert.equal(sockets[0].emis.filter((x) => x.ev === 'time_sync').length, 6);
});
test('guild_join_error retry du même serveur : join réémis après 5 s ; autre serveur ignoré', async () => {
  const { tr, sockets, horloge } = monter(); tr.connecter('j'); tr.suivre('123'); sockets[0].ouvrir();
  sockets[0].serveur('guild_join_error', { guild_id: '123', error: 'BOT_OFFLINE', retry: true });
  sockets[0].serveur('guild_join_error', { guild_id: '999', error: 'TIMEOUT', retry: true });
  await horloge.avancer(5000);
  assert.equal(sockets[0].emis.filter((x) => x.ev === 'join_guild').length, 2);
});
test('demanderEtat : request_state connecté, sondage sinon', async () => {
  const { tr, sockets, vus } = monter(); tr.connecter('j'); tr.suivre('123'); sockets[0].ouvrir(); tr.demanderEtat();
  assert.deepEqual(sockets[0].emis.at(-1), { ev: 'request_state', data: { guild_id: '123' } });
  sockets[0].couper(); const n = vus.sondes.length; tr.demanderEtat(); await Promise.resolve(); assert.equal(vus.sondes.length, n + 1);
});
test('nouveau jeton : l’ancien socket est fermé, un seul actif', () => {
  const { tr, sockets } = monter(); tr.connecter('a'); sockets[0].ouvrir(); tr.connecter('b');
  assert.equal(sockets[0].connected, false); assert.deepEqual(sockets[1].opts.auth, { token: 'b' });
});
```

- [ ] **Step 3 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/temps-reel.test.js tests/vendor.test.js`
Expected : `vendor.test.js` PASS ; `temps-reel.test.js` FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 4 : écrire `fond/temps-reel.js` et `tests/fakes/socket.js`**

Suivre exactement le comportement listé plus haut.

- [ ] **Step 5 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 6 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add fond/temps-reel.js vendor/socket.io.min.js vendor/socket.io-client.LICENSE tests/fakes/socket.js tests/temps-reel.test.js tests/vendor.test.js \
  && git commit -m "feat: socket à jeton, abonnement au serveur, time_sync et sondage de repli"
```

---

## Tâche 11 : jeu et fenêtres (`fond/fenetres.js`) et faux `overwolf`

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\fenetres.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fakes\overwolf.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fenetres.test.js`.

**Interfaces:**
- Consumes : `positionBandeau`, `positionPanneau`, `TAILLES_BANDEAU` (tâche 7) ; `LOL`, `DELAIS`.
- Produces :
  - `estLoL(gi)` → `boolean` : `isRunning && (classId === 5426 || Math.floor(Number(id) / 10) === 5426)`.
  - `createFenetres({overwolf, horloge, reglages, sourceLancement, appelerFenetre, surJeu, surPanneau})` donne :
    - `demarrer()`, `jeu()` → `{lol, hauteur, focus}` ;
    - `ouvrirPanneau()`, `fermerPanneau(raison)` → `boolean`, `basculerPanneau()`, `panneauOuvert()`, `panneauAbonne()`, `signalPanneau('focus'|'blur')` ;
    - `basculerBandeau()`, `bandeauVoulu()` ;
    - `montrerBureau()`, `replacer()`.
  - Paramètres :
    - `reglages()` → `Reglages` ;
    - `appelerFenetre(nom, cle, ...args)` → valeur, ou `undefined` si la fenêtre n'est pas abonnée ;
    - `surJeu({lol, hauteur, focus})` ;
    - `surPanneau(ouvert)`.
- Produces (`tests/fakes/overwolf.js`) :
  - `jeuLoL({focus = true, w = 1920, h = 1080} = {})` → `{isRunning: true, id: 54261, classId: 5426, isInFocus: focus, gameIsInFocus: focus, width: w, height: h, logicalWidth: w, logicalHeight: h}`.
  - `creerOverwolf({focusAccepte = true, sansRequestOverlayFocus = false} = {})` → `{overwolf, appels, urls, definirJeu(gi|null), majJeu(raisons), touche(vk, onGame), clic(x, y, onGame), lancement(source)}`.
    - Les rappels Overwolf passent par `queueMicrotask`.
    - Chaque évènement du faux vaut `{addListener, removeListener, _emit(e)}`.
    - Option `refusRestore: string[]` : le premier `restore` de ces fenêtres répond `{success: false, error: 'faux refus'}`.
    - `appels` contient des chaînes : `'obtenir <nom>'`, `'restore id-<nom>'`, `'hide id-<nom>'`, `'position id-<nom> <l>,<t>'`, `'taille id-<nom> <w>x<h>'`, `'focus id-<nom>'` (`requestOverlayFocus`), `'devant id-<nom> <bool>'` (`bringToFront`).
    - Sous-ensemble d'API : `windows.{obtainDeclaredWindow, restore, hide, changePosition, changeSize, requestOverlayFocus, bringToFront, onStateChanged, getMainWindow}`, `games.{getRunningGameInfo2, onGameInfoUpdated, inputTracking.{onKeyDown, onKeyUp, onMouseDown}}`, `extensions.{onAppLaunchTriggered}`, `utils.openUrlInDefaultBrowser`.
    - Signatures imitées, vérifiées sur https://dev.overwolf.com/ow-native/reference/windows/ow-windows :
      - `changePosition(windowId, left, top, cb?)` (0.78, applique le DPI) ;
      - `changeSize(params, cb?)` (0.149+, applique le DPI). `ChangeWindowSizeParams` est un objet **plat** : `{window_id: string, width: int, height: int, auto_dpi_resize?: boolean}`, sans objet `size` imbriqué. L'ancienne forme `changeSize(windowId, width, height, cb)` (0.78) est dépréciée et n'applique pas le DPI. `auto_dpi_resize` ne vaut que pour les fenêtres natives ;
      - `bringToFront(windowId, grabFocus, cb)` (0.124) ; `requestOverlayFocus(windowId, cb)` (0.250).
    - Le faux `changeSize` lève `TypeError('changeSize : forme attendue {window_id, width, height}')` si son premier argument n'est pas un objet, si `window_id` n'est pas une chaîne, si `width` ou `height` n'est pas un entier, ou si l'objet porte une autre clé que `window_id`, `width`, `height` et `auto_dpi_resize`. Une forme dépréciée ou imbriquée fait donc échouer le test.

Comportement (repris de `C:\Users\Paul\Documents\Codage\greg-overlay-ow\essai-overwolf\fond.js`) :
- `demarrer()` :
  - branche `onGameInfoUpdated`, `inputTracking.onKeyDown` / `onMouseDown`, `onAppLaunchTriggered`, puis un contrôle toutes les 3 s ;
  - premier `getRunningGameInfo2` ;
  - si `sourceLancement !== 'gamelaunchevent'` et pas de LoL : `montrerBureau()`.
- LoL repéré :
  - bandeau obtenu ; `overwolf.windows.changeSize({window_id: id, width, height}, cb)`, avec `{width, height} = TAILLES_BANDEAU[reglages().taille]`, seulement si la taille change. Pas d'`auto_dpi_resize` : le bandeau n'est pas une fenêtre native. Puis `changePosition(id, left, top, cb)` ;
  - `restore`, si `bandeauVoulu` et panneau fermé ;
  - panneau préchargé : obtenu, sans `restore`.
- Hauteur sous 200 : aucun `changeSize` ni `changePosition`. Hauteur changée : on replace.
- Restauration du bandeau refusée : nouvel essai au premier contrôle qui suit d'au moins 15 s (`≥`) le refus.
- Fin de partie : panneau fermé, identifiants des fenêtres oubliés, `bandeauVoulu = true`.
- `ouvrirPanneau()` :
  - sans LoL : rien ;
  - sinon : `hide` du bandeau, `changePosition` du panneau, `restore` ;
  - puis `requestOverlayFocus(id)` ; s'il est absent ou refusé : `bringToFront(id, true)` ;
  - puis `appelerFenetre('panneau', 'surOuvert')` et `surPanneau(true)`.
- `panneauAbonne()` : si le panneau est ouvert, rejoue `surOuvert`.
- Première touche ordinaire après l'ouverture : si `onGame` est vrai, au moins 100 ms après l'ouverture, et que la touche n'est pas technique (16, 17, 18, 27, 91, 92, 118 à 122, 160 à 165), alors `bringToFront(id, true)`, une seule fois.
- `fermerPanneau(raison)` :
  - `hide` du panneau ;
  - le bandeau revient à la première touche reçue au moins 100 ms après, sinon après 3 s.
- `onMouseDown` `onGame` plus de 250 ms après l'ouverture : `fermerPanneau('clic')`.
- `signalPanneau('blur')` après un `focus`, plus de 250 ms après l'ouverture : `fermerPanneau('blur')`.
- `basculerBandeau()` : inverse `bandeauVoulu` ; `hide` du bandeau, ou `restore` s'il n'y a pas de panneau ouvert.
- `onAppLaunchTriggered` : `montrerBureau()` seulement sans LoL.
- `montrerBureau()` : `obtainDeclaredWindow('bureau')` puis `restore`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/fenetres.test.js
function monter(o = {}) {
  const horloge = creerHorloge(); const ow = creerOverwolf(o); let r = { ...REGLAGES_DEFAUT }; const appelsFen = [];
  const f = createFenetres({ overwolf: ow.overwolf, horloge, reglages: () => r, sourceLancement: o.source ?? '',
    appelerFenetre: (n, k) => appelsFen.push(`${n}.${k}`), surJeu: () => {}, surPanneau: () => {} });
  return { f, ow, horloge, appelsFen, regler: (p) => { r = { ...r, ...p }; } };
}
const lol = async (m, gi = jeuLoL()) => { m.ow.definirJeu(gi); m.ow.majJeu(['gameLaunched']); await m.horloge.vider(); };
test('LoL 1920×1080 : bandeau en bas à gauche et affiché, panneau préchargé caché', async () => {
  const m = monter(); m.f.demarrer(); await lol(m);
  for (const s of ['taille id-bandeau 340x132', 'position id-bandeau 16,924', 'restore id-bandeau', 'obtenir panneau']) assert.ok(m.ow.appels.includes(s), s);
  assert.ok(!m.ow.appels.includes('restore id-panneau'));
});
test('le faux changeSize n’accepte que l’objet plat de la doc (0.149+)', () => {
  const { overwolf } = creerOverwolf();
  assert.throws(() => overwolf.windows.changeSize('id-bandeau', 340, 132, () => {}), /forme attendue/);
  assert.throws(() => overwolf.windows.changeSize({ window_id: 'id-bandeau', size: { width: 340, height: 132 } }, () => {}), /forme attendue/);
  assert.doesNotThrow(() => overwolf.windows.changeSize({ window_id: 'id-bandeau', width: 340, height: 132 }, () => {}));
});
test('LoL hors focus en Plein écran (1×1) : rien ne bouge', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); const n = m.ow.appels.length;
  await lol(m, jeuLoL({ focus: false, w: 1, h: 1 }));
  assert.equal(m.ow.appels.slice(n).filter((s) => /^(position|taille)/.test(s)).length, 0);
});
test('réglage « Bord gauche, au tiers » appliqué par replacer()', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.regler({ emplacement: 'gauche-tiers' }); m.f.replacer(); await m.horloge.vider();
  assert.ok(m.ow.appels.includes('position id-bandeau 16,313'));
});
test('ouvrir le panneau : bandeau caché, panneau placé et affiché, requestOverlayFocus', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.ouvrirPanneau(); await m.horloge.vider();
  const i = (s) => m.ow.appels.indexOf(s);
  assert.ok(i('hide id-bandeau') < i('restore id-panneau') && i('restore id-panneau') < i('focus id-panneau'));
  assert.ok(m.ow.appels.includes('position id-panneau 24,124')); assert.ok(m.appelsFen.includes('panneau.surOuvert'));
});
test('requestOverlayFocus refusé ou absent : bringToFront(id, true)', async () => {
  for (const o of [{ focusAccepte: false }, { sansRequestOverlayFocus: true }]) {
    const m = monter(o); m.f.demarrer(); await lol(m); m.f.ouvrirPanneau(); await m.horloge.vider();
    assert.ok(m.ow.appels.includes('devant id-panneau true'));
  }
});
test('clic dans le jeu : ignoré à 100 ms, ferme à 300 ms', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.ouvrirPanneau(); await m.horloge.vider();
  await m.horloge.avancer(100); m.ow.clic(900, 500, true); assert.equal(m.f.panneauOuvert(), true);
  await m.horloge.avancer(200); m.ow.clic(900, 500, true); await m.horloge.vider();
  assert.equal(m.f.panneauOuvert(), false); assert.ok(m.ow.appels.includes('hide id-panneau'));
});
test('perte de focus : ignorée à 100 ms, ferme à 300 ms', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.ouvrirPanneau(); await m.horloge.vider(); m.f.signalPanneau('focus');
  await m.horloge.avancer(100); m.f.signalPanneau('blur'); assert.equal(m.f.panneauOuvert(), true);
  await m.horloge.avancer(200); m.f.signalPanneau('blur'); assert.equal(m.f.panneauOuvert(), false);
});
test('après fermeture : bandeau à la 1re touche, sinon après 3 s', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.ouvrirPanneau(); await m.horloge.vider(); m.f.fermerPanneau('echap');
  const n = m.ow.appels.filter((s) => s === 'restore id-bandeau').length;
  await m.horloge.avancer(50); m.ow.touche(81, true); assert.equal(m.ow.appels.filter((s) => s === 'restore id-bandeau').length, n);
  await m.horloge.avancer(100); m.ow.touche(81, true); await m.horloge.vider(); assert.equal(m.ow.appels.filter((s) => s === 'restore id-bandeau').length, n + 1);
  const p = monter(); p.f.demarrer(); await lol(p); p.f.ouvrirPanneau(); await p.horloge.vider(); p.f.fermerPanneau('echap');
  const k = p.ow.appels.filter((s) => s === 'restore id-bandeau').length; await p.horloge.avancer(3000);
  assert.equal(p.ow.appels.filter((s) => s === 'restore id-bandeau').length, k + 1);
});
test('1re touche partie au jeu après l’ouverture : bringToFront une fois', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.ouvrirPanneau(); await m.horloge.vider();
  await m.horloge.avancer(150); m.ow.touche(81, true); m.ow.touche(87, true); await m.horloge.vider();
  assert.equal(m.ow.appels.filter((s) => s === 'devant id-panneau true').length, 1);
});
test('fin de partie puis nouvelle partie : fenêtres redemandées, bandeau visible', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.basculerBandeau(); m.ow.definirJeu(null); m.ow.majJeu(['gameTerminated']); await m.horloge.vider();
  assert.equal(m.f.bandeauVoulu(), true); const n = m.ow.appels.filter((s) => s === 'obtenir bandeau').length;
  await lol(m); assert.equal(m.ow.appels.filter((s) => s === 'obtenir bandeau').length, n + 1);
});
test('basculerBandeau : caché puis remontré', async () => {
  const m = monter(); m.f.demarrer(); await lol(m); m.f.basculerBandeau(); await m.horloge.vider();
  assert.equal(m.ow.appels.at(-1), 'hide id-bandeau'); m.f.basculerBandeau(); await m.horloge.vider(); assert.equal(m.ow.appels.at(-1), 'restore id-bandeau');
});
test('lancement par la partie : pas de bureau ; lancement manuel hors partie : bureau', async () => {
  const a = monter({ source: 'gamelaunchevent' }); a.f.demarrer(); await a.horloge.vider(); assert.ok(!a.ow.appels.includes('restore id-bureau'));
  const b = monter(); b.f.demarrer(); await b.horloge.vider(); assert.ok(b.ow.appels.includes('restore id-bureau'));
});
test('Review Focus 1 : relance pendant une partie LoL → jamais de bureau par-dessus le jeu', async () => {
  const m = monter({ source: 'gamelaunchevent' }); m.f.demarrer(); await lol(m);
  m.ow.lancement('dock'); m.ow.lancement(undefined); await m.horloge.vider();
  assert.ok(!m.ow.appels.includes('restore id-bureau'));
  m.ow.definirJeu(null); m.ow.majJeu(['gameTerminated']); await m.horloge.vider(); m.ow.lancement('dock'); await m.horloge.vider();
  assert.ok(m.ow.appels.includes('restore id-bureau'));
});
test('restauration du bandeau refusée : nouvel essai au contrôle qui suit les 15 s', async () => {
  const m = monter({ refusRestore: ['bandeau'] }); m.f.demarrer(); await lol(m);
  const essais = () => m.ow.appels.filter((s) => s === 'restore id-bandeau').length;
  assert.equal(essais(), 1); await m.horloge.avancer(12000); assert.equal(essais(), 1);
  await m.horloge.avancer(3000); assert.equal(essais(), 2);
});
```

Le délai se compare en `≥ DELAIS.reessaiBandeau` : le contrôle de 15 s relance.

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/fenetres.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `fond/fenetres.js` et `tests/fakes/overwolf.js`**

Reprendre les structures de l'essai (`obtenir`, `montrer`, `cacher`, `placer`, `suivreJeu`, `oublierPartie`, `prechargerPanneau`, `escalader`, `surTouche`), sans journal ni compteurs de preuve, en suivant le comportement listé plus haut.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add fond/fenetres.js tests/fakes/overwolf.js tests/fenetres.test.js \
  && git commit -m "feat: détection de LoL, fenêtres en jeu, focus du panneau et bureau hors partie"
```

---

## Tâche 12 : raccourcis (`lib/hotkeys.js`, `fond/raccourcis.js`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\hotkeys.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\raccourcis.js`.
- Modify : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\fakes\overwolf.js`, pour ajouter :
  - `settings.hotkeys.{get, onPressed, onChanged, assign, getAllApps}` ;
  - les options `raccourcis` (`IHotkey[]` du jeu 5426 ; par défaut les quatre raccourcis de la spec, attribués, avec `virtualKeycode` 118, 119, 121 et 122 et `modifierKeys: 2`), `assign: (params) => result` (défaut `{success: true}`) et `autresApplis` (résultat de `getAllApps`, défaut `{apps: {}, platform: []}`) ;
  - l'aide `raccourci(nom)`, qui émet `onPressed({name: nom})`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\hotkeys.test.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\raccourcis.test.js`.

**Interfaces:**
- Consumes : `DELAIS`, `LOL` ; `DEFAUTS_RACCOURCIS` (`lib/annonces.js`).
- Produces (`lib/hotkeys.js`) :
  - constantes : `NOMS = ['pause','suivant','panneau','bandeau']`, `DEFAUTS` (= `DEFAUTS_RACCOURCIS`), `MODIFS = {alt: 1, ctrl: 2, shift: 4}` ;
  - `createGate({fusionMs = 350, repetitionMs = 600} = {})` → `{accepter(nom, source, t): boolean}` ;
  - libellés : `bindingParts(binding)` → `string[]` (Shift s'affiche « Maj »), `libelleCombo(combo)` → `string` ;
  - capture : `captureDe(ev)` → `{etat:'attente'} | {etat:'annule'} | {etat:'refus', raison:'modificateur'|'meta'} | {etat:'ok', combo:{ctrl, alt, shift, virtualKey}, libelle}` ;
  - conflits : `sommeModifs(combo)` → `number`, `conflit(combo, hotkeys, nom)` → `string|null` ;
  - lecture : `lireRaccourcis(result)` → `Raccourcis`, où `Raccourcis = {pause:{binding, libre}, suivant, panneau, bandeau}` ;
  - panneau : `nomPourTouche(ev, raccourcis)` → `nom|null`.
- Produces (`fond/raccourcis.js`) : `createRaccourcis({overwolf, horloge, uid, executer, surChangement})` → `{demarrer(), depuisPanneau(nom), liste() → Raccourcis, libres() → string[], assigner(nom, combo) → Promise<{ok:true} | {ok:false, erreur:'pris', par} | {ok:false, erreur}>}`.
  - `executer(nom, source)` reçoit `source` = `'overwolf'|'panneau'`.
  - `surChangement(Raccourcis)` est appelé à chaque relecture.

Règles de `createGate` :
- un appui d'une **autre source**, moins de 350 ms après celui qui a ouvert la fusion pour ce nom, est fusionné (refusé) ;
- un appui de la **même source**, moins de 600 ms après le précédent de cette source pour ce nom, est une répétition (refusé). Le dernier appui de chaque source est noté même quand il est refusé, pour qu'une touche tenue ne déclenche qu'une fois ;
- sinon l'appui est accepté et ouvre une fusion.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/hotkeys.test.js
test('fusion : Overwolf puis panneau 40 ms après, une seule action', () => {
  const g = createGate(); assert.equal(g.accepter('pause', 'overwolf', 0), true); assert.equal(g.accepter('pause', 'panneau', 40), false);
});
test('fusion : panneau puis Overwolf 340 ms après, une seule action', () => {
  const g = createGate(); assert.equal(g.accepter('panneau', 'panneau', 0), true); assert.equal(g.accepter('panneau', 'overwolf', 340), false);
});
test('touche tenue : une seule action ; nouvel appui 700 ms après : accepté ; noms indépendants', () => {
  const g = createGate(); const r = [0, 100, 200, 300, 400, 500, 600, 700, 800, 900].map((t) => g.accepter('suivant', 'overwolf', t));
  assert.deepEqual(r.filter(Boolean).length, 1);
  const h = createGate(); assert.equal(h.accepter('pause', 'overwolf', 0), true); assert.equal(h.accepter('pause', 'overwolf', 700), true);
  assert.equal(h.accepter('suivant', 'overwolf', 710), true);
});
test('libellés et capture', () => {
  assert.deepEqual(bindingParts('Ctrl+Shift+F7'), ['Ctrl', 'Maj', 'F7']); assert.deepEqual(bindingParts(''), []);
  assert.deepEqual(captureDe({ key: 'Control', keyCode: 17, ctrlKey: true }), { etat: 'attente' });
  assert.deepEqual(captureDe({ key: 'Escape', keyCode: 27 }), { etat: 'annule' });
  assert.deepEqual(captureDe({ key: 'F9', keyCode: 120, ctrlKey: true }), { etat: 'ok', combo: { ctrl: true, alt: false, shift: false, virtualKey: 120 }, libelle: 'Ctrl+F9' });
  assert.equal(captureDe({ key: 'F9', keyCode: 120, altKey: true, shiftKey: true }).libelle, 'Alt+Maj+F9');
  assert.deepEqual(captureDe({ key: 'q', keyCode: 81 }), { etat: 'refus', raison: 'modificateur' });
  assert.deepEqual(captureDe({ key: 'F9', keyCode: 120, metaKey: true, ctrlKey: true }), { etat: 'refus', raison: 'meta' });
});
test('conflits (modificateurs Win32 : Alt 1, Ctrl 2, Maj 4)', () => {
  assert.equal(sommeModifs({ ctrl: true }), 2); assert.equal(sommeModifs({ alt: true, shift: true }), 5);
  const hk = [{ name: 'pause', virtualKeycode: 118, modifierKeys: 2 }];
  assert.equal(conflit({ ctrl: true, virtualKey: 118 }, hk, 'suivant'), 'pause'); assert.equal(conflit({ ctrl: true, virtualKey: 118 }, hk, 'pause'), null);
});
test('Review Focus 5 : lireRaccourcis marque les raccourcis non attribués ou absents', () => {
  const r = lireRaccourcis({ success: true, globals: [], games: { 5426: [{ name: 'pause', binding: 'Ctrl+F7', IsUnassigned: false }, { name: 'panneau', binding: '', IsUnassigned: true }] } });
  assert.deepEqual(r.pause, { binding: 'Ctrl+F7', libre: false }); assert.deepEqual(r.panneau, { binding: '', libre: true }); assert.deepEqual(r.suivant, { binding: '', libre: true });
});
test('nomPourTouche suit les liaisons du moment', () => {
  const r = lireRaccourcis({ success: true, games: { 5426: ['pause:Ctrl+F7', 'suivant:Ctrl+F8', 'panneau:Ctrl+Shift+G', 'bandeau:Ctrl+F11'].map((s) => { const [name, binding] = s.split(':'); return { name, binding }; }) } });
  assert.equal(nomPourTouche({ key: 'F7', ctrlKey: true }, r), 'pause'); assert.equal(nomPourTouche({ key: 'g', ctrlKey: true, shiftKey: true }, r), 'panneau');
  assert.equal(nomPourTouche({ key: 'F7' }, r), null); assert.equal(nomPourTouche({ key: 'F7', ctrlKey: true, repeat: true }, r), null);
});
```

```js
// tests/raccourcis.test.js
const HK = [['pause', 'Ctrl+F7', 118], ['suivant', 'Ctrl+F8', 119], ['panneau', 'Ctrl+F10', 121], ['bandeau', 'Ctrl+F11', 122]]
  .map(([name, binding, vk]) => ({ name, binding, virtualKeycode: vk, modifierKeys: 2, IsUnassigned: false, extensionuid: 'monuid' }));
function monter(o = {}) { const horloge = creerHorloge(); const ow = creerOverwolf({ raccourcis: HK, ...o }); const faits = []; const listes = [];
  const r = createRaccourcis({ overwolf: ow.overwolf, horloge, uid: 'monuid', executer: (n, s) => faits.push([n, s]), surChangement: (l) => listes.push(l) });
  return { r, ow, horloge, faits, listes }; }
test('Overwolf puis panneau 40 ms après : une seule exécution', async () => {
  const m = monter(); m.r.demarrer(); await m.horloge.vider(); m.ow.raccourci('pause'); await m.horloge.avancer(40); m.r.depuisPanneau('pause');
  assert.deepEqual(m.faits, [['pause', 'overwolf']]);
});
test('lecture au démarrage, relecture sur onChanged', async () => {
  const m = monter(); m.r.demarrer(); await m.horloge.vider(); assert.equal(m.r.liste().panneau.binding, 'Ctrl+F10');
  m.ow.overwolf.settings.hotkeys.onChanged._emit({ name: 'panneau', gameId: 5426, binding: 'Ctrl+F9' }); await m.horloge.vider();
  assert.ok(m.listes.length >= 2);
});
test('assigner : refus si déjà pris par un raccourci de l’appli, sans appel à Overwolf', async () => {
  const m = monter(); m.r.demarrer(); await m.horloge.vider();
  assert.deepEqual(await m.r.assigner('suivant', { ctrl: true, alt: false, shift: false, virtualKey: 118 }), { ok: false, erreur: 'pris', par: 'pause' });
  assert.ok(!m.ow.appels.some((s) => s.startsWith('assign')));
});
test('assigner : paramètres d’Overwolf, puis relecture', async () => {
  const vus = []; const m = monter({ assign: (p) => { vus.push(p); return { success: true }; } }); m.r.demarrer(); await m.horloge.vider();
  assert.deepEqual(await m.r.assigner('suivant', { ctrl: true, alt: false, shift: false, virtualKey: 120 }), { ok: true });
  assert.deepEqual(vus[0], { name: 'suivant', gameId: 5426, modifiers: { ctrl: true, alt: false, shift: false }, virtualKey: 120 });
});
test('assigner : refus d’Overwolf ou d’une autre appli', async () => {
  const a = monter({ assign: () => ({ success: false, error: 'Hotkey in use' }) }); a.r.demarrer(); await a.horloge.vider();
  assert.deepEqual(await a.r.assigner('suivant', { ctrl: true, alt: false, shift: false, virtualKey: 120 }), { ok: false, erreur: 'Hotkey in use' });
  const b = monter({ autresApplis: { apps: { autre: { games: { 5426: [{ name: 'x', title: 'Porofessor : ouvrir', virtualKeycode: 120, modifierKeys: 2, extensionuid: 'autre' }] } } }, platform: [] } });
  b.r.demarrer(); await b.horloge.vider();
  assert.deepEqual(await b.r.assigner('suivant', { ctrl: true, alt: false, shift: false, virtualKey: 120 }), { ok: false, erreur: 'pris', par: 'Porofessor : ouvrir' });
});
test('Review Focus 5 : raccourci non attribué au démarrage → libres()', async () => {
  const m = monter({ raccourcis: HK.map((h) => (h.name === 'panneau' ? { ...h, binding: '', IsUnassigned: true } : h)) }); m.r.demarrer(); await m.horloge.vider();
  assert.deepEqual(m.r.libres(), ['panneau']);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/hotkeys.test.js tests/raccourcis.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/hotkeys.js`, `fond/raccourcis.js` et étendre le faux `overwolf`**

`captureDe` :
- une touche de modificateur seule (`Control`, `Alt`, `Shift`, `Meta`) donne `attente` ; Échap seul donne `annule` ;
- `metaKey` donne un refus `meta` ; ni Ctrl ni Alt, un refus `modificateur` (un raccourci sans modificateur volerait une touche à LoL, `passthrough: false`) ;
- le libellé de la touche vaut `ev.key` en majuscules pour une lettre, sinon `ev.key`, et le virtual key vaut `ev.keyCode`.

`assigner` :
- conflit avec nos propres raccourcis (`conflit`) ;
- puis, si `getAllApps` existe, conflit avec les raccourcis d'`apps` (en sautant `extensionuid === uid`) et `platform`. `par` vaut le `title` du raccourci, sinon son `name` ;
- puis `overwolf.settings.hotkeys.assign({name, gameId: LOL, modifiers: {ctrl, alt, shift}, virtualKey}, cb)` ;
- relecture par `get`.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/hotkeys.js fond/raccourcis.js tests/fakes/overwolf.js tests/hotkeys.test.js tests/raccourcis.test.js \
  && git commit -m "feat: raccourcis Overwolf (fusion, répétition, capture, réattribution)"
```

---

## Tâche 13 : actions du lecteur (`fond/actions.js`)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\actions.js`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\actions.test.js`.

**Interfaces:**
- Consumes :
  - les méthodes de `api` (tâche 8) ;
  - `deckToast`, `errorToast`, `LECTEUR_DECK` (tâche 6) ; `t` (tâche 5) ; `motifAction` (tâche 5) ;
  - `expectedOf`, `isQueueMoved`, `moveIndices`, `addPayloadOf`, `addedCopy`, `errorCopy`, `looksLikeUrl`, `normalizeSuggestions` (tâche 4) ;
  - `classifyLink` ; `parseTitle` ; `DELAIS`, `SUGGESTIONS`.
- Produces : `createActions({api, horloge, lecteur, annoncer, demanderEtat, rafraichir, surErreur})` donne les méthodes suivantes, qui renvoient toutes `Promise<boolean>`, sauf `suggerer` :
  - `basculerPause()`, `suivant()`, `stop()`, `recommencer()`, `boucle()` ;
  - `ajouter(entree)` ;
  - `retirer(key)`, `jouerMaintenant(key)`, `enTete(key)`, `deplacer(key, beforeKey)` ;
  - `suggerer(q)` → `Promise<Suggestion[]>`.
  - Paramètres :
    - `lecteur()` → `{lie, serveur, current, queue, paused, repeat}`, où `queue` porte des titres avec `raw` ;
    - `annoncer(ToastInput)` ;
    - `rafraichir()`, appelé après chaque succès ;
    - `surErreur(e)`, appelé pour toute erreur sauf 401.

Comportement :
- Précondition (`motifAction`) : un échec annonce `deckToast(motif)` avec `bandeau: true`, sans requête, et renvoie `false`.
- Succès, annoncés avec la sorte du deck et sans action d'annulation :
  - `basculerPause` : `toast.paused` si le lecteur jouait, sinon `toast.resumed` ;
  - `suivant` : `toast.skipped.textWithTitle` avec `{title: parseTitle(current.title, current.artist).song}`, ou `toast.skipped` sans titre en cours ;
  - `stop` : `toast.stopped` ; `recommencer` : `toast.restarted` ; `boucle` : `toast.repeatOn` si la boucle était coupée, sinon `toast.repeatOff` ;
  - `ajouter` : `addedCopy(res, fallback, link)`, avec le texte `t(path, vars)` plus `t(suffix, vars)` le cas échéant ;
  - `retirer` : `toast.removed` ; `jouerMaintenant` : `toast.playNow` ; `enTete` : `toast.playNext`, ou `toast.alreadyNext` sans requête pour le premier de la file ; `deplacer` : `toast.moved {pos: dst + 1}`.
- `retirer`, `jouerMaintenant`, `enTete` et `deplacer` trouvent l'index par la clé dans `lecteur().queue`, envoient `expectedOf` du titre visé, et renvoient `false` si la clé est inconnue.
- `ajouter` avec une requête vide (`addPayloadOf(entree).query === ''`) renvoie `false` sans requête.
- `ajouter` et `jouerMaintenant` réussis : `api.voiceJoin(serveur)` au plus une fois toutes les 10 s ; ses erreurs sont avalées.
- Erreurs :
  - `ApiError` 401 : aucune annonce (la connexion s'en charge) ;
  - `isQueueMoved(e)` sur retirer, jouer maintenant, en tête ou déplacer : `demanderEtat()` puis annonce `ow.toast.stale` avec `bandeau: true` ;
  - sinon : `errorToast(errorCopy(e, ctx))` avec `bandeau: true`. `ctx` vaut `{q, link}` pour un ajout (`q` seulement si ce n'est pas un lien), et `{action: 'move'}` pour un déplacement ;
  - `surErreur(e)` est appelé pour toute erreur sauf 401.
- `suggerer(q)` :
  - `[]` sans requête si `q.trim().length < 2` ou `looksLikeUrl(q)` ;
  - sinon `normalizeSuggestions(await api.autocomplete(q.trim(), 6))`, et `[]` en cas d'erreur.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/actions.test.js
const it = (key, o) => ({ key, title: o.title, artist: o.artist ?? '', url: o.url, raw: { url: o.url, added_by: o.by, ts: o.ts } });
const Q = [it('k1', { title: 'Thunderstruck', url: 'u1', by: '7', ts: 1 }), it('k2', { title: 'Sandstorm', url: 'u2', by: '42', ts: 2 }),
  it('k3', { title: 'Tout va bien', url: 'u3', by: '7', ts: 3 }), it('k4', { title: 'Sweet Dreams', url: 'u4', by: '42', ts: 4 })];
function monter({ api = {}, etat = {} } = {}) {
  const horloge = creerHorloge(); const appels = []; const annonces = []; let demandes = 0; const erreurs = [];
  const fauxApi = new Proxy({}, { get: (_, nom) => api[nom] ?? (async (...a) => { appels.push([nom, ...a]); return { ok: true }; }) });
  const L = { lie: true, serveur: '123', current: { key: 'c', title: 'Daft Punk - Around the World', artist: 'Daft Punk' }, queue: Q, paused: false, repeat: false, ...etat };
  const a = createActions({ api: fauxApi, horloge, lecteur: () => L, annoncer: (x) => annonces.push(x), demanderEtat: () => { demandes++; }, rafraichir: () => {}, surErreur: (e) => erreurs.push(e) });
  return { a, appels, annonces, horloge, demandes: () => demandes, erreurs };
}
const err = (status, body) => async () => { throw new ApiError(status, body); };
test('sans liaison ou sans serveur : aucune requête, message sur le bandeau', async () => {
  const m = monter({ etat: { lie: false } }); assert.equal(await m.a.suivant(), false); assert.equal(m.appels.length, 0);
  assert.deepEqual([m.annonces[0].fact, m.annonces[0].bandeau], ['Greg n’est pas encore lié\u00a0: ouvrez la fenêtre Greg hors partie.', true]);
  const n = monter({ etat: { serveur: '' } }); await n.a.basculerPause(); assert.match(n.annonces[0].fact, /^Aucun serveur choisi/);
});
test('suivant : skip du serveur puis « Titre passé : Around the World »', async () => {
  const m = monter(); await m.a.suivant(); assert.deepEqual(m.appels[0], ['skip', '123']); assert.equal(m.annonces[0].fact, 'Titre passé\u00a0: Around the World');
});
test('retirer : index et expected du titre visé', async () => {
  const m = monter(); await m.a.retirer('k2'); assert.deepEqual(m.appels[0], ['remove', '123', 1, { url: 'u2', added_by: '42', ts: 2 }]);
});
test('retirer 409 STALE : request_state puis « La file a bougé, réessayez. »', async () => {
  const m = monter({ api: { remove: err(409, { ok: false, error: 'STALE', message: 'La file a bougé : réessayez.' }) } });
  assert.equal(await m.a.retirer('k2'), false); assert.equal(m.demandes(), 1);
  assert.deepEqual([m.annonces[0].fact, m.annonces[0].kind, m.annonces[0].bandeau], ['La file a bougé, réessayez.', 'warn', true]);
});
test('jouer maintenant 409 sans code (hors bornes) : même traitement', async () => {
  const m = monter({ api: { playAt: err(409, { ok: false }) } }); await m.a.jouerMaintenant('k3'); assert.equal(m.demandes(), 1);
});
test('en tête : premier de la file sans requête ; sinon move vers 0', async () => {
  const m = monter(); await m.a.enTete('k1'); assert.equal(m.appels.length, 0); assert.equal(m.annonces[0].fact, 'Ce titre est déjà le prochain.');
  await m.a.enTete('k3'); assert.deepEqual(m.appels[0], ['move', '123', 2, 0, { url: 'u3', added_by: '7', ts: 3 }]);
});
test('déplacer d devant b', async () => {
  const m = monter(); await m.a.deplacer('k4', 'k2'); assert.deepEqual(m.appels[0], ['move', '123', 3, 1, { url: 'u4', added_by: '42', ts: 4 }]);
  assert.equal(m.annonces[0].fact, 'Déplacé en position 2.');
});
test('ajouter : query, « Ajouté : … », un seul voiceJoin en 10 s', async () => {
  const m = monter({ api: { add: async (g, p) => { m.appels.push(['add', g, p]); return { ok: true, added: 1, title: 'Daft Punk - Around the World' }; } } });
  await m.a.ajouter({ texte: 'around the world' }); await m.a.ajouter({ texte: 'sandstorm' });
  assert.deepEqual(m.appels[0], ['add', '123', { query: 'around the world' }]); assert.match(m.annonces[0].fact, /^Ajouté\u00a0: /);
  assert.equal(m.appels.filter((x) => x[0] === 'voiceJoin').length, 1);
  await m.horloge.avancer(10000); await m.a.ajouter({ texte: 'x y' }); assert.equal(m.appels.filter((x) => x[0] === 'voiceJoin').length, 2);
});
test('ajout refusé (pas en vocal) : erreur du deck sur le bandeau', async () => {
  const m = monter({ api: { add: err(409, { ok: false, error: 'USER_NOT_IN_VOICE' }) } }); await m.a.ajouter({ texte: 'abc' });
  assert.deepEqual([m.annonces[0].fact, m.annonces[0].kind, m.annonces[0].bandeau], ['Rejoignez d’abord un salon vocal sur ce serveur, puis réessayez.', 'err', true]);
});
test('401 : aucune annonce ; BOT_OFFLINE : surErreur', async () => {
  const m = monter({ api: { skip: err(401, { ok: false, error: 'NOT_AUTHENTICATED' }), stop: err(503, { ok: false, error: 'BOT_OFFLINE' }) } });
  await m.a.suivant(); assert.equal(m.annonces.length, 0); assert.equal(m.erreurs.length, 0);
  await m.a.stop(); assert.equal(m.erreurs[0].payload.error, 'BOT_OFFLINE');
});
test('suggestions : 2 caractères, jamais pour un lien', async () => {
  // api.autocomplete renvoie un tableau (tâche 8), le faux aussi
  const m = monter({ api: { autocomplete: async (q, l) => { m.appels.push(['autocomplete', q, l]); return [{ title: 'T', url: 'https://youtu.be/dQw4w9WgXcQ' }]; } } });
  assert.deepEqual(await m.a.suggerer('a'), []); assert.deepEqual(await m.a.suggerer('https://youtu.be/dQw4w9WgXcQ'), []);
  assert.equal((await m.a.suggerer(' noir dés ')).length, 1); assert.deepEqual(m.appels, [['autocomplete', 'noir dés', 6]]);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/actions.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `fond/actions.js`**

Suivre exactement le comportement listé plus haut.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add fond/actions.js tests/actions.test.js \
  && git commit -m "feat: actions du lecteur par l'API, expected et file qui a bougé"
```

---

## Tâche 14 : le cerveau (assemblage, `window.greg`, `fond.html`) et le banc

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\cerveau.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond\demarrage.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\fond.html`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\cerveau.bench.test.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\pages.test.js`.

**Interfaces:**
- Consumes : tout ce qui précède. En particulier :
  - `createConnexion`, `createTempsReel`, `createFenetres`, `createRaccourcis`, `createActions`, `createApi`, `createHerald` ;
  - `lireReglages`, `ecrireReglages`, `nettoyerReglages`, `pickGuild`, `stateKind`, `snapshotFromPayload`, `withClock`, `emptySnapshot`, `publicTrack`, `isStalePayload`, `joinErrorAction`, `errorCopy`, `clockSampleOf`, `createRefClock`, `copieAmi`, `copieRaccourcisLibres`.
- Produces : `createBrain(env)` → `{pont, etat() → EtatDiffuse, arreter()}`.
  - `env = {overwolf, io, fetch, storage, horloge, perfNow, sourceLancement, uid}`, où `horloge` a `now`, `setTimeout`, `clearTimeout`, `setInterval` et `clearInterval`.
- `pont` (= `window.greg`, ce que les fenêtres appellent) :
  - `abonner(nom, fonctions)`, où `nom` vaut `'bandeau'|'panneau'|'bureau'` et `fonctions = {surEtat(e), surOuvert?()}` ; `desabonner(nom)` ;
  - lecteur : `action(nom)`, où `nom` vaut `'pause'|'suivant'|'stop'|'recommencer'|'boucle'` ; `ajouter(entree)`, `suggerer(q)`, `retirer(key)`, `jouerMaintenant(key)`, `enTete(key)`, `deplacer(key, beforeKey)` ;
  - serveurs : `choisirServeur(id)`, `rafraichirServeurs()` ;
  - panneau : `fermerPanneau(raison)`, `toucheDansPanneau(nom)`, `signaler(type)` ;
  - liaison : `nouveauCode()`, `ouvrirSite()`, `delier()` ;
  - réglages : `reglages(patch)` → `Reglages`, `assignerRaccourci(nom, combo)`.
- `EtatDiffuse`, recopié en JSON à chaque diffusion :
  - `connexion` : `{statut, code, uri, expireA, user, erreur}` ; `me` : `{id, name}|null` ;
  - `serveurs` : `[{id, name, icon_url, greg_voice, user_voice, playing}]` ; `serveur` : `{id, nom}` (`''` sans serveur) ;
  - `greg` : `'ok'|'hors-ligne'` ; `tempsReel` : `boolean` ;
  - `lecteur` : `{current, queue, paused, repeat, position, duration}`, titres passés par `publicTrack` ;
  - `horloge` : `{pos, at, dur, frozen}`, avec `at` en `Date.now()` ;
  - `herault` : `Toast[]` ;
  - `reglages`, `raccourcis` ;
  - `jeu` : `{lol, panneauOuvert, bandeauVoulu}`.

Règles d'assemblage :
1. **Liaison.**
   - Quand `connexion` passe à `lie` :
     - `await rafraichirServeurs()` (`api.guilds()`) ;
     - succès : `serveur = pickGuild(guilds, reglages.serveur, serveurDefaut)`, rangé dans les réglages ;
     - échec (503 `BOT_OFFLINE` si Greg est éteint au démarrage, erreur réseau…) : `serveur = reglages.serveur || serveurDefaut || ''`, **sans le ranger**. `reglages.serveur` reste tel quel : `pickGuild([], …)` donnerait `''` et effacerait le serveur choisi. L'appartenance au serveur est de toute façon vérifiée par l'API (`join_guild`, actions) ;
     - dans les deux cas : `temps.connecter(jeton)` puis `temps.suivre(serveur)`.
   - Échec de `rafraichirServeurs()`, à la liaison ou plus tard :
     - annonce `{kind: 'warn', fact: t('ow.guilds.failed')}` (une chaîne simple, pas une entrée `{text, kind}` pour `deckToast`), au premier échec d'une série seulement ;
     - nouvel essai `DELAIS.reessaiServeur` (5 s) après chaque échec, tant que l'appli est liée ; un succès arrête les essais ;
     - au premier succès d'une liaison où le serveur était provisoire : `serveur = pickGuild(guilds, reglages.serveur, serveurDefaut)`, rangé ; s'il diffère du provisoire, `temps.suivre(serveur)` et lecteur vidé ;
     - les succès suivants (liste ouverte dans le panneau) ne mettent à jour que `serveurs` ;
     - un 401 passe par `onUnauthorized` : la connexion quitte `lie`, ce qui arrête les essais.
   - Quand elle quitte `lie` : `temps.deconnecter()`, lecteur vide, serveurs vides, nouvel essai des serveurs annulé.
2. **État reçu.**
   - `stateKind(payload, serveur) === 'other'` : ignoré.
   - `snapshotFromPayload(payload, prev, horloge.now())` nul (périmé) : `greg = 'hors-ligne'` si `backend_error` vaut `BOT_OFFLINE` ou `REDIS_UNAVAILABLE`, puis rien d'autre.
   - Sinon, comme `feedClock` du site (`services/web/src/hooks/usePlayer.ts:152-160`) :
     - `greg = 'ok'` ;
     - `const sNow = temps.heureApi() ?? horloge.now()` : l'heure de l'API, sinon l'horloge murale avant la première mesure (le `serverNow` de `services/web/src/lib/sync/live.ts`) ;
     - `const echantillon = clockSampleOf(payload, sNow)` ; s'il n'est pas nul, `refclock.ingest(echantillon)` ;
     - `const ms = refclock.positionAt(sNow)` ;
     - si `ms !== null` : `snap = withClock(snap, {pos: ms / 1000, at: horloge.now(), frozen: refclock.anchor()?.status !== 'playing'})`. `anchor` est une méthode de l'horloge de référence (tâche 3), pas une propriété ;
     - diffusion.
3. **Échecs.**
   - Un échec de sondage, `surErreur` ou `guild_join_error` qui porte `BOT_OFFLINE` / `REDIS_UNAVAILABLE`, ou un `TypeError` de sondage, donne `greg = 'hors-ligne'`.
   - `guild_join_error` de code `NOT_AUTHENTICATED` (jeton révoqué entre la connexion et l'abonnement, plan A tâche 6) donne `connexion.oublier('socket')`, sans annonce.
   - Tout autre `guild_join_error` en `show` annonce `errorToast(errorCopy({payload: p}))` avec `bandeau: true`.
   - Une erreur `STORAGE_UNAVAILABLE` (503 ou `connect_error`, plan A) n'efface jamais le jeton.
4. **Ligne d'ami.** `player_event` du serveur suivi, avec `reglages.amis` et `copieAmi(evt, me.id)` non nul : annonce `{kind: 'info', fact: t(path, vars), quip: quip('remote', seedOf(fact)), ms: DELAIS.ami, bandeau: true}`.
5. **Raccourcis.** `executer(nom)` :
   - `pause` → `actions.basculerPause()` ; `suivant` → `actions.suivant()` ;
   - `panneau` → `fenetres.basculerPanneau()` ; `bandeau` → `fenetres.basculerBandeau()`.
6. **Début de partie.** Quand `surJeu` passe `lol` à vrai et que `copieRaccourcisLibres(raccourcis.liste())` n'est pas nul : annonce `deckToast('ow.hotkey.unassigned', {vars})` avec `ms: 8000` et `bandeau: true`.
7. **Abonnements.**
   - `abonner('bureau')` pendant que le statut est `non-lie` et sans `erreur` : `connexion.nouveauCode()`.
   - `abonner('panneau')` : `fenetres.panneauAbonne()`.
   - Chaque abonnement reçoit tout de suite l'état.
   - Un abonné qui lève une exception est retiré, comme `appeler` dans l'essai.
8. **Réglages.** `reglages(patch)` :
   - nettoie, range et diffuse ;
   - `emplacement` ou `taille` changé : `fenetres.replacer()` ;
   - `serveur` ne passe pas par là : `choisirServeur(id)` range, appelle `temps.suivre(id)` et vide le lecteur.
9. **Démarrage.** `connexion.demarrer()`, `raccourcis.demarrer()`, `fenetres.demarrer()`.
   - `api` reçoit `getToken: () => connexion.jeton()` et `onUnauthorized: () => connexion.oublier('401')`.
   - `temps` reçoit `surJetonRefuse: () => connexion.oublier('socket')`.
   - `actions` reçoit :
     - `demanderEtat: () => temps.demanderEtat()` (après un `STALE`) ;
     - `rafraichir: () => { if (!temps.connecte()) temps.demanderEtat(); }`. Socket connecté, l'action attend le `playlist_update` que le serveur pousse (spec §6.3) ; socket coupé, l'état est relu tout de suite par REST, sans attendre le sondage de 5 s.

`fond.html` :
- `<!doctype html><html lang="fr">`, `meta charset utf-8`, `meta http-equiv="Content-Security-Policy"` égale à `CSP` ;
- `<script src="vendor/socket.io.min.js"></script>` puis `<script type="module" src="fond/demarrage.js"></script>`.

`fond/demarrage.js` :
- construit `env` à partir de `overwolf`, `window.io`, `fetch.bind(window)`, `localStorage`, des minuteurs du navigateur, de `performance.now`, de `sourceLancement = new URLSearchParams(location.search).get('source') ?? ''` et de `uid = location.host` ;
- affecte `window.greg = createBrain(env).pont` ;
- écrit `console.info('GregLC origine', location.origin)` (relevé dans `%LOCALAPPDATA%\Overwolf\Log\Apps\GregLC\fond.html.log`).

- [ ] **Step 1 : écrire le banc et le contrat des pages, qui échouent**

```js
// tests/pages.test.js
import { CSP } from '../lib/config.js';
const PAGES = ['fond.html'];   // les tâches 15 à 17 ajoutent bandeau.html, panneau.html, bureau.html
for (const p of PAGES) test(`${p} : CSP, langue, ressources locales présentes, ni script ni style en ligne`, () => {
  const html = readFileSync(p, 'utf8');
  assert.ok(html.startsWith('<!doctype html>')); assert.match(html, /<html lang="fr">/);
  assert.equal(/http-equiv="Content-Security-Policy" content="([^"]+)"/.exec(html)?.[1], CSP);
  assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/.test(html), 'script en ligne'); assert.ok(!/\sstyle="/.test(html), 'style en ligne');
  for (const [, ref] of html.matchAll(/(?:src|href)="([^"#:]+)"/g)) assert.ok(existsSync(ref), ref);
});
```

```js
// tests/cerveau.bench.test.js : le banc hors jeu de la spec §7
const T0 = 1_700_000_000_000;
const USER = { id: '42', username: 'paul', global_name: 'Paul', avatar: null };
const ETAT = { guild_id: 123, relay_at_ms: T0, current: { title: 'Daft Punk - Around the World', url: 'https://www.youtube.com/watch?v=K0HSD_i2DvA', artist: 'Daft Punk', duration: 429, added_by: '42', ts: 1.5 },
  queue: [{ title: 'Thunderstruck', url: 'https://www.youtube.com/watch?v=v2AC41dglnM', artist: 'AC/DC', duration: 292, added_by: '7', ts: 2.5 },
    { title: 'Sandstorm', url: 'https://www.youtube.com/watch?v=y6120QOlsfU', artist: 'Darude', duration: 225, added_by: '42', ts: 3.5 }],
  is_paused: false, paused: false, position: 134, duration: 429, progress: { elapsed: 134, duration: 429 }, repeat_all: false,
  queue_users: { 42: { id: '42', display_name: 'Paul' }, 7: { id: '7', display_name: 'Kévin' } } };
function monter({ routes = {}, stockage = creerStockage(), source = '', raccourcis } = {}) {
  const horloge = creerHorloge(T0); const f = creerFetch(routes); const { io, sockets } = creerIo(); const ow = creerOverwolf({ raccourcis });
  const b = createBrain({ overwolf: ow.overwolf, io, fetch: f.fetch, storage: stockage, horloge, perfNow: horloge.perfNow, sourceLancement: source, uid: 'monuid' });
  const vus = {}; const abonner = (nom) => { vus[nom] = []; b.pont.abonner(nom, { surEtat: (e) => vus[nom].push(e), surOuvert: () => {} }); };
  return { b, horloge, f, sockets, ow, stockage, vus, abonner, dernier: (n) => vus[n].at(-1) };
}
let jetonPret = false;
const ROUTES = {
  'POST /overlay/device': { status: 200, body: { ok: true, device_code: 'dc1', user_code: 'BCDF-GHJK', verification_uri: 'https://greg-le-consanguin.up.railway.app/lier',
    verification_uri_complete: 'https://greg-le-consanguin.up.railway.app/lier?code=BCDF-GHJK', expires_in: 600, interval: 5 } },
  'POST /overlay/token': () => (jetonPret ? { status: 200, body: { ok: true, access_token: 'greg_ow_test', token_type: 'Bearer', expires_in: 15552000, user: USER, default_guild_id: '123' } }
    : { status: 400, body: { ok: false, error: 'authorization_pending' } }),
  'GET /overlay/guilds': { status: 200, body: { ok: true, guilds: [{ id: '123', name: 'Le Donjon', icon_url: null, greg_voice: { id: '9', name: 'Taverne' }, user_voice: null, playing: true }] } },
};

test('liaison par code, abonnement, état, raccourcis, fusion, panneau, STALE, amis', async () => {
  jetonPret = false; const m = monter({ routes: { ...ROUTES } }); await m.horloge.vider();
  // bureau hors partie, code demandé dès que la fenêtre s'abonne
  assert.ok(m.ow.appels.includes('restore id-bureau')); m.abonner('bureau'); await m.horloge.vider();
  assert.deepEqual(m.f.appels.find((a) => a.chemin === '/overlay/device').corps, { client_name: 'GregLC · Overwolf' });
  assert.deepEqual([m.dernier('bureau').connexion.statut, m.dernier('bureau').connexion.code], ['code', 'BCDF-GHJK']);
  await m.horloge.avancer(5000); jetonPret = true; await m.horloge.avancer(5000);
  assert.equal(m.stockage.getItem('greg.ow.token'), 'greg_ow_test');
  assert.equal(m.f.appels.find((a) => a.chemin === '/overlay/guilds').headers.authorization, 'Bearer greg_ow_test');
  assert.deepEqual(m.sockets[0].opts.auth, { token: 'greg_ow_test' });
  // socket : abonnement et état
  m.sockets[0].ouvrir(); assert.deepEqual(m.sockets[0].emis.find((x) => x.ev === 'join_guild').data, { guild_id: '123' });
  m.sockets[0].serveur('playlist_update', ETAT); assert.equal(m.dernier('bureau').lecteur.current.title, 'Daft Punk - Around the World');
  m.sockets[0].serveur('playlist_update', { only_elapsed: true, guild_id: 999, position: 3, duration: 429, paused: false });
  assert.equal(Math.round(m.b.etat().horloge.pos), 134);
  // partie : bandeau en bas à gauche
  m.ow.definirJeu(jeuLoL()); m.ow.majJeu(['gameLaunched']); await m.horloge.vider(); m.abonner('bandeau');
  assert.ok(m.ow.appels.includes('position id-bandeau 16,924'));
  // raccourci + touche du panneau 40 ms après : une seule requête, Bearer, guild_id dans le corps
  m.ow.raccourci('pause'); await m.horloge.avancer(40); m.b.pont.toucheDansPanneau('pause'); await m.horloge.vider();
  const tp = m.f.appels.filter((a) => a.chemin === '/playlist/toggle_pause'); assert.equal(tp.length, 1);
  assert.deepEqual([tp[0].corps, tp[0].headers.authorization], [{ guild_id: '123' }, 'Bearer greg_ow_test']);
  // panneau : ouvert au raccourci, fermé par Échap, bandeau revenu à la 1re touche (le clavier est au jeu)
  await m.horloge.avancer(700); m.ow.raccourci('panneau'); await m.horloge.vider();
  for (const s of ['hide id-bandeau', 'restore id-panneau', 'focus id-panneau']) assert.ok(m.ow.appels.includes(s), s);
  m.b.pont.fermerPanneau('echap'); await m.horloge.avancer(150); const n = m.ow.appels.length; m.ow.touche(81, true); await m.horloge.vider();
  assert.ok(m.ow.appels.slice(n).includes('restore id-bandeau')); assert.ok(!m.ow.appels.slice(n).includes('devant id-panneau true'));
  // file qui a bougé
  m.f.routes['POST /queue/remove'] = { status: 409, body: { ok: false, error: 'STALE' } };
  await m.b.pont.retirer(m.b.etat().lecteur.queue[1].key);
  assert.deepEqual(m.sockets[0].emis.at(-1), { ev: 'request_state', data: { guild_id: '123' } });
  assert.equal(m.b.etat().herault[0].fact, 'La file a bougé, réessayez.');
  // Review Focus 2 : sa propre action ne fait pas de ligne d'ami ; celle de Kévin, si
  const avant = m.b.etat().herault.length;
  m.sockets[0].serveur('player_event', { guild_id: '123', action: 'skip', actor: { id: '42', display_name: 'Paul' }, title: 'x', at_ms: T0 });
  assert.equal(m.b.etat().herault.length, avant);
  m.sockets[0].serveur('player_event', { guild_id: '123', action: 'add', actor: { id: '7', display_name: 'Kévin' }, title: 'AC/DC - Thunderstruck', at_ms: T0 });
  assert.deepEqual([m.b.etat().herault[0].fact, m.b.etat().herault[0].bandeau], ['Kévin a ajouté\u00a0: Thunderstruck', true]);
});

test('Review Focus 4 : appareil délié pendant la partie → 401 une fois, jeton effacé, plus de sondage', async () => {
  const routes = { ...ROUTES, 'GET /overlay/me': { status: 200, body: { ok: true, via: 'overlay', user: USER, default_guild_id: '123' } },
    'GET /playlist': { status: 401, body: { ok: false, error: 'NOT_AUTHENTICATED' } } };
  const m = monter({ routes, stockage: creerStockage({ 'greg.ow.token': 'greg_ow_test' }), source: 'gamelaunchevent' }); await m.horloge.vider();
  m.sockets[0].ouvrir(); m.sockets[0].couper('io server disconnect');
  await m.horloge.avancer(5000); assert.equal(m.stockage.getItem('greg.ow.token'), null); assert.equal(m.b.etat().connexion.statut, 'non-lie');
  const n = m.f.appels.filter((a) => a.chemin === '/playlist').length; await m.horloge.avancer(30000);
  assert.equal(m.f.appels.filter((a) => a.chemin === '/playlist').length, n); assert.equal(m.sockets.length, 1);
});

test('serveurs illisibles à la liaison (503) : serveur rangé suivi, réglages intacts, nouvel essai 5 s après', async () => {
  const routes = { ...ROUTES, 'GET /overlay/me': { status: 200, body: { ok: true, via: 'overlay', user: USER, default_guild_id: '999' } },
    'GET /overlay/guilds': { status: 503, body: { ok: false, error: 'BOT_OFFLINE' } } };
  const m = monter({ routes, stockage: creerStockage({ 'greg.ow.token': 'greg_ow_test', 'greg.ow.reglages': JSON.stringify({ serveur: '123' }) }), source: 'gamelaunchevent' });
  await m.horloge.vider(); m.sockets[0].ouvrir();
  assert.deepEqual(m.sockets[0].emis.find((x) => x.ev === 'join_guild').data, { guild_id: '123' });
  assert.equal(m.b.etat().serveur.id, '123'); assert.equal(m.b.etat().reglages.serveur, '123');
  assert.equal(JSON.parse(m.stockage.getItem('greg.ow.reglages')).serveur, '123');
  assert.equal(m.b.etat().herault[0].fact, 'Impossible de lire vos serveurs pour l’instant. Réessayez.');
  const n = m.f.appels.filter((a) => a.chemin === '/overlay/guilds').length;
  m.f.routes['GET /overlay/guilds'] = ROUTES['GET /overlay/guilds'];
  await m.horloge.avancer(5000);
  assert.equal(m.f.appels.filter((a) => a.chemin === '/overlay/guilds').length, n + 1);
  assert.deepEqual(m.b.etat().serveurs.map((s) => s.id), ['123']); assert.equal(m.b.etat().reglages.serveur, '123');
});

test('action réussie, socket pas connecté : l’état est relu tout de suite par REST (rafraichir)', async () => {
  const routes = { ...ROUTES, 'GET /overlay/me': { status: 200, body: { ok: true, via: 'overlay', user: USER, default_guild_id: '123' } } };
  const m = monter({ routes, stockage: creerStockage({ 'greg.ow.token': 'greg_ow_test' }), source: 'gamelaunchevent' }); await m.horloge.vider();
  const n = m.f.appels.filter((a) => a.chemin === '/playlist').length;
  await m.b.pont.action('suivant'); await m.horloge.vider();
  assert.equal(m.f.appels.filter((a) => a.chemin === '/queue/skip').length, 1);
  assert.equal(m.f.appels.filter((a) => a.chemin === '/playlist').length, n + 1);
});

test('Review Focus 5 : raccourci non attribué → ligne sur le bandeau au début de la partie', async () => {
  const HK = [['pause', 'Ctrl+F7'], ['suivant', 'Ctrl+F8'], ['panneau', ''], ['bandeau', 'Ctrl+F11']].map(([name, binding]) => ({ name, binding, IsUnassigned: !binding }));
  const m = monter({ raccourcis: HK, source: 'gamelaunchevent' }); await m.horloge.vider();
  m.ow.definirJeu(jeuLoL()); m.ow.majJeu(['gameLaunched']); await m.horloge.vider();
  assert.deepEqual([m.b.etat().herault[0].fact, m.b.etat().herault[0].bandeau], ['Raccourcis non attribués par Overwolf\u00a0: Ctrl+F10. Changez-les dans la fenêtre Greg.', true]);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/cerveau.bench.test.js tests/pages.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND` pour `fond/cerveau.js`, `ENOENT` pour `fond.html`).

- [ ] **Step 3 : écrire `fond/cerveau.js`, `fond/demarrage.js` et `fond.html`**

Suivre exactement les règles 1 à 9 et l'`EtatDiffuse` ci-dessus.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add fond/cerveau.js fond/demarrage.js fond.html tests/cerveau.bench.test.js tests/pages.test.js \
  && git commit -m "feat: cerveau de l'appli (assemblage, état diffusé, window.greg) et banc hors jeu"
```

---

## Tâche 15 : socle visuel, bandeau et aperçu dans le navigateur

**Files:**
- Create (sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\`) :
  - vue : `lib\vue-bandeau.js` ;
  - styles et icônes : `css\base.css`, `css\bandeau.css`, `img\icones.svg` ;
  - page : `bandeau.html`, `ui\pont.js`, `ui\dom.js`, `ui\bandeau-rendu.js`, `ui\bandeau.js` ;
  - aperçu : `apercu\serveur.mjs`, `apercu\faux-overwolf.js`, `apercu\scenarios.js`, `apercu\index.html`.
- Modify : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\pages.test.js` (`PAGES` += `'bandeau.html'`).
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\vue-bandeau.test.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\apercu.test.js`.

**Interfaces:**
- Consumes :
  - `EtatDiffuse` (tâche 14) ; `t`, `fill` ; `kingSealSrc`, `requesterOf` ; `parseTitle` ; `fmt` ;
  - `livePosition` ; `bindingParts`, `DEFAUTS` ; `fondBandeau`.
- Produces :
  - `vueBandeau(e, now)` → `VueBandeau`, où :
    - `etat` vaut `'lecture'|'pause'|'repos'|'hors-ligne'|'non-lie'|'sans-serveur'` ;
    - `taille` vaut `'normale'|'compacte'` ;
    - `ligne` vaut `{texte, quip, sorte}|null` ;
    - `VueBandeau = {etat, taille, fond, kicker, titre, titreBrut, meta, sceau, temps, progression, ligne}`.
  - `brancher(nom, fonctions, {delai = 200} = {})` → `Promise<pont>` (`ui/pont.js`).
  - `h(tag, props, ...enfants)`, `remplacer(el, ...enfants)` (`ui/dom.js`).
  - `peindreBandeau(racine, vue)` (`ui/bandeau-rendu.js`), réutilisé par l'aperçu des réglages (tâche 17).
  - `SCENARIOS` (`apercu/scenarios.js`) : `{nom: EtatDiffuse}`.

Règles de `vueBandeau`, par ordre de priorité :
1. `connexion.statut !== 'lie'` donne `non-lie` :
   - kicker `ow.banner.kicker.notLinked`, titre `ow.banner.notLinked`, meta `ow.banner.notLinkedHint`.
2. `!serveur.id` donne `sans-serveur` :
   - kicker `ow.banner.kicker.noGuild`, titre `guild.pickFirst.title`, meta `ow.banner.noGuildHint {keys}`.
3. `greg === 'hors-ligne'` donne `hors-ligne` :
   - kicker `ow.banner.kicker.offline`, titre `now.botOffline.title`, meta `now.botOffline.body`.
4. Sans `current`, `repos` :
   - kicker `ow.banner.kicker.idle`, titre `now.idle.title`, meta `ow.banner.idleHint {keys}`.
5. Sinon `lecture` ou `pause` :
   - kicker `playing` ou `paused` ;
   - titre `parseTitle(title, artist).song || title || url`, titreBrut `title` ;
   - meta `` `${artiste} · ${par}` `` (sans « · » si l'artiste est vide), où `par` vaut `byMe`, `byOther {name}` ou `byUnknown` (`requesterOf(addedBy, me.id)`) ;
   - sceau `kingSealSrc(me.name)` si c'est le sien ;
   - `pos = livePosition(horloge, paused, now)`, temps `` `${fmt(pos)} / ${fmt(dur)}` ``, progression `dur > 0 ? pos / dur : 0`.

Partout :
- `keys = bindingParts(raccourcis.panneau.binding || DEFAUTS.panneau).join('+')` ;
- `fond = fondBandeau(reglages.opacite)`, `taille = reglages.taille` ;
- `ligne` : le toast le plus récent de `herault` avec `bandeau && !leaving`, soit `{texte: fact + (n > 1 ? ' ×' + n : ''), quip, sorte: kind}`, sinon `null`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/vue-bandeau.test.js
const NOW = 1_700_000_000_000;
const base = (o = {}) => ({ connexion: { statut: 'lie' }, me: { id: '42', name: 'Paul' }, serveur: { id: '123', nom: 'Le Donjon' }, greg: 'ok', tempsReel: true,
  lecteur: { current: { key: 'c', title: 'Daft Punk - Around the World (Official Video)', artist: 'Daft Punk', addedBy: { id: '42', name: 'Paul' }, duration: 429 }, queue: [], paused: false, repeat: false, position: 134, duration: 429 },
  horloge: { pos: 134, at: NOW, dur: 429 }, herault: [], reglages: { ...REGLAGES_DEFAUT },
  raccourcis: { pause: { binding: 'Ctrl+F7', libre: false }, suivant: { binding: 'Ctrl+F8', libre: false }, panneau: { binding: 'Ctrl+F10', libre: false }, bandeau: { binding: 'Ctrl+F11', libre: false } },
  jeu: { lol: true, panneauOuvert: false, bandeauVoulu: true }, ...o });
test('en lecture, demandé par vous', () => {
  const v = vueBandeau(base(), NOW);
  assert.deepEqual([v.etat, v.kicker, v.titre, v.meta, v.sceau, v.temps], ['lecture', 'Greg · en lecture', 'Around the World', 'Daft Punk · par vous', 'img/seals/king-seal-P.webp', '2:14 / 7:09']);
  assert.equal(vueBandeau(base(), NOW + 1000).temps, '2:15 / 7:09'); assert.ok(Math.abs(v.progression - 134 / 429) < 1e-9);
});
test('en pause : le temps ne bouge pas ; demandé par un autre', () => {
  const e = base(); e.lecteur.paused = true; assert.deepEqual([vueBandeau(e, NOW + 5000).kicker, vueBandeau(e, NOW + 5000).temps], ['Greg · en pause', '2:14 / 7:09']);
  const o = base(); o.lecteur.current.addedBy = { id: '7', name: 'Kévin' }; assert.deepEqual([vueBandeau(o, NOW).meta, vueBandeau(o, NOW).sceau], ['Daft Punk · par Kévin', null]);
});
test('rien en lecture : raccourci du moment', () => {
  const e = base(); e.lecteur.current = null; assert.deepEqual([vueBandeau(e, NOW).titre, vueBandeau(e, NOW).meta], ['Rien en lecture', 'Ctrl+F10 pour ajouter un titre']);
  e.raccourcis.panneau.binding = 'Ctrl+Shift+G'; assert.equal(vueBandeau(e, NOW).meta, 'Ctrl+Maj+G pour ajouter un titre');
});
test('priorités : pas lié > sans serveur > hors ligne > lecture', () => {
  assert.equal(vueBandeau(base({ connexion: { statut: 'non-lie' }, greg: 'hors-ligne' }), NOW).titre, 'Liez l’appli depuis la fenêtre Greg');
  assert.deepEqual([vueBandeau(base({ serveur: { id: '', nom: '' } }), NOW).etat, vueBandeau(base({ serveur: { id: '', nom: '' } }), NOW).titre], ['sans-serveur', 'Choisissez un serveur']);
  const h = vueBandeau(base({ greg: 'hors-ligne' }), NOW); assert.deepEqual([h.etat, h.kicker, h.titre], ['hors-ligne', 'Greg · hors ligne', 'Greg est hors ligne']);
});
test('ligne : refus ou ami seulement, ×N, jamais un toast qui part', () => {
  const t = (o) => ({ id: 1, kind: 'err', fact: 'X', quip: null, n: 1, leaving: false, bandeau: true, ...o });
  assert.deepEqual(vueBandeau(base({ herault: [t({ n: 2 })] }), NOW).ligne, { texte: 'X ×2', quip: null, sorte: 'err' });
  assert.equal(vueBandeau(base({ herault: [t({ bandeau: false })] }), NOW).ligne, null);
  assert.equal(vueBandeau(base({ herault: [t({ leaving: true })] }), NOW).ligne, null);
});
test('fond et taille suivent les réglages', () => {
  const v = vueBandeau(base({ reglages: { ...REGLAGES_DEFAUT, opacite: 0, taille: 'compacte' } }), NOW); assert.deepEqual([v.fond, v.taille], [0, 'compacte']);
});
```

```js
// tests/apercu.test.js
import { SCENARIOS } from '../apercu/scenarios.js';
test('chaque scénario de l’aperçu se peint sans erreur', () => {
  for (const [nom, e] of Object.entries(SCENARIOS)) assert.doesNotThrow(() => vueBandeau(e, Date.now()), nom);
  for (const nom of ['lecture', 'pause', 'repos', 'horsLigne', 'nonLie', 'sansServeur', 'refus', 'ami', 'compacte', 'fondNul']) assert.ok(SCENARIOS[nom], nom);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/vue-bandeau.test.js tests/apercu.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/vue-bandeau.js` et `apercu/scenarios.js`**

- `SCENARIOS` part d'un `EtatDiffuse` de base, celui de `tests/vue-bandeau.test.js`, avec `horloge.at = Date.now()` au chargement.
- Variantes : `lecture`, `pause`, `repos`, `horsLigne`, `nonLie`, `sansServeur` ;
  - `refus` : toast `err` « Rejoignez d’abord un salon vocal sur ce serveur, puis réessayez. » avec réplique ;
  - `ami` : toast `info` « Kévin a ajouté : Thunderstruck » ;
  - `compacte` ; `fondNul` (opacité 0) ; `fondPlein` (opacité 100).

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : écrire le socle CSS, les icônes et la page du bandeau**

Référence visuelle :
- `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.tpl.html` :
  - atomes `.glass`, `.kicker` + `.eq`, `.title`, `.meta`, `.dot`, `.seal`, `.bar` (lignes 75-97) ;
  - `.bandeau` (lignes 99-105).
- `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\2-hors-jeu.tpl.html`, « Quand quelque chose coince » (lignes 221-244) :
  - les états, `.k-off`, `.k-wait` ;
  - `.toast` avec rond rouge pour un refus, `.echo` pour l'ami.
- Le médaillon de l'essai (`C:\Users\Paul\Documents\Codage\greg-overlay-ow\essai-overwolf\style.css:34-48`) remplace la vignette des maquettes (spec §6.4).

Contenu :
- `css/base.css` :
  - `@font-face` des 7 polices de `fonts/` (Alegreya Sans 400, 500, 700 et 800 ; Grenze Gotisch et Grenze 100 à 900 ; Alegreya italique 400 à 900 ; `font-display: block`) ;
  - surcharge `--lumiere: hsl(265 78% 74%)` et `--lumiere-rgb: 180 137 240` après `tokens.css` ;
  - reset, `kbd`, `.plaque`, `.glass`, `.ico` et `.fill`, `.medaille`, anneau de focus `2px solid var(--or)` décalé de 3 px ;
  - `.toast` et `.ic` par sorte : dégradés de `services/web/src/components/Herald/herald.css:48-51` ;
  - `:root[data-repliques="off"] .quip { display: none }`.
  - `corner-shape` et `@starting-style` ne sont que des enrichissements : rien ne doit en dépendre.
- `css/bandeau.css` :
  - fond `rgb(11 9 8 / var(--fond))` et anneaux `rgb(239 231 216 / calc(.075 * var(--fond)))` ;
  - à `--fond: 0`, plus d'ombre portée ;
  - `text-shadow: 0 1px 2px rgb(0 0 0 / .85)` sur tout le texte ;
  - `[data-taille="compacte"]` : ni médaillon ni meta, titre et temps sur une ligne, puis la barre ;
  - kicker rouge (`--gueules`) en `hors-ligne`, gris (`--cendre`) en `repos` / `non-lie` / `sans-serveur` ;
  - `.eq` animée seulement en `lecture`, barre en `--cendre-2` en `pause` ;
  - la ligne sous la carte, la carte collée en haut de la fenêtre (340 × 132).
- `img/icones.svg` : les symboles `i-stop`, `i-restart`, `i-skip`, `i-repeat`, `i-pause`, `i-play`, `i-search`, `i-x`, `i-plus`, `i-chev`, `i-next`, `i-min`, `i-gear`, `i-ext` de `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\2-hors-jeu.tpl.html:89-99` et `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.tpl.html:185-195`, utilisés par `<use href="img/icones.svg#i-stop">`.
- `bandeau.html` : CSP, `css/tokens.css`, `css/base.css`, `css/bandeau.css`, `<div id="bandeau"></div>`, `<script type="module" src="ui/bandeau.js"></script>`.
- `ui/pont.js` :
  - sonde `globalThis.overwolf?.windows?.getMainWindow?.()?.greg` toutes les `delai` ms ;
  - puis `greg.abonner(nom, fonctions)`, et `addEventListener('beforeunload', () => greg.desabonner(nom))`.
- `ui/bandeau-rendu.js` : `peindreBandeau(racine, vue)` pose `data-etat`, `data-taille`, `--fond` (par `style.setProperty`) et les textes (`textContent` seulement), plus `title = titreBrut`.
- `ui/bandeau.js` :
  - `brancher('bandeau', {surEtat})` ;
  - repeint tout sur `surEtat`, puis seulement le temps et la barre toutes les 250 ms (`vueBandeau(etat, Date.now())`) ;
  - pose `document.documentElement.dataset.repliques` selon `reglages.repliques`.

- [ ] **Step 6 : écrire l'aperçu**

- `apercu/serveur.mjs` :
  - serveur HTTP en lecture seule sur `127.0.0.1:47323`, qui sert la racine du dépôt ;
  - insère `<script type="module" src="/apercu/faux-overwolf.js"></script>` juste avant le premier `<script` de chaque page HTML servie hors de `/apercu/` ;
  - refuse tout chemin hors du dépôt.
- `apercu/faux-overwolf.js` :
  - lit `?scenario=` (défaut `lecture`) ;
  - définit `globalThis.overwolf` avec `windows.getMainWindow()` → `{greg}`, `windows.getCurrentWindow`, `dragMove`, `minimize`, `hide` et `utils.openUrlInDefaultBrowser` ;
  - son faux `greg` appelle `surEtat(structuredClone(SCENARIOS[scenario]))` à l'abonnement, journalise chaque appel du pont (`console.info('greg.<méthode>', …)`) et résout `true`. `suggerer` renvoie 3 suggestions fixes, et `assignerRaccourci` renvoie `{ok:false, erreur:'pris', par:'pause'}` pour `virtualKey === 118`, sinon `{ok:true}`.
- `apercu/index.html` :
  - pour chaque scénario du bandeau, une `iframe` de 340 × 132 (300 × 92 en compacte) posée sur un décor de jeu (dégradé `.game` de `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.tpl.html:54-57`) ;
  - les tâches 16 et 17 y ajoutent leurs fenêtres.

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0` (`tests/pages.test.js` couvre maintenant `bandeau.html`).

- [ ] **Step 7 : vérifier dans un navigateur**

Run (en arrière-plan) : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node apercu/serveur.mjs`
Puis, après la vérification « Jeu en cours » des contraintes globales, ouvrir `http://127.0.0.1:47323/apercu/index.html` avec Playwright (MCP) et faire une capture. Ouvrir aussi les maquettes `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\2-hors-jeu.html` et `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.html`. Si elles n'existent pas : `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/docs/superpowers/specs/2026-11-25-overlay-overwolf-maquettes && python build.py`.

Attendu :
- aucune erreur dans la console ;
- chaque état a le texte des tests et l'aspect des maquettes (plaque, surtitre lumière, titre Grenze, barre, ligne de refus avec rond rouge et réplique, ligne d'ami) ;
- le temps avance en `lecture` et reste figé en `pause` ;
- `fondNul` ne montre que le texte et la barre, `fondPlein` un fond opaque ;
- rien ne déborde des 340 px.

- [ ] **Step 8 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/vue-bandeau.js css/base.css css/bandeau.css img/icones.svg bandeau.html ui/pont.js ui/dom.js ui/bandeau-rendu.js ui/bandeau.js apercu/serveur.mjs apercu/faux-overwolf.js apercu/scenarios.js apercu/index.html tests/vue-bandeau.test.js tests/apercu.test.js tests/pages.test.js \
  && git commit -m "feat: bandeau en jeu (états, fond réglable) et aperçu des fenêtres"
```

---

## Tâche 16 : le panneau (lecteur partagé)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\vue-lecteur.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\ui\lecteur.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\ui\panneau.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\panneau.html`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\css\lecteur.css`.
- Modify (sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\`) :
  - `apercu\scenarios.js` : scénarios `file62`, `fileVide`, `suggestions`, `choixServeur`, `raccourciLibre` ;
  - `apercu\index.html` : `iframe` 440 × 680 du panneau ;
  - `tests\pages.test.js` : `PAGES` += `'panneau.html'` ;
  - `tests\apercu.test.js` : chaque scénario passe aussi par `vueLecteur`.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\vue-lecteur.test.js`.

**Interfaces:**
- Consumes : `EtatDiffuse`, le `pont`, `brancher`, `h` ; `t`, `quip` ; `kickerKey`, `requesterOf`, `requesterKeys`, `kingSealSrc`, `seedOf` ; `parseTitle` ; `fmt`, `thumbOf` ; `livePosition`, `moveBefore`, `looksLikeUrl` ; `nomPourTouche`, `bindingParts`, `NOMS` ; `FILE_MAX`, `DELAIS`, `SUGGESTIONS`.
- Produces (`lib/vue-lecteur.js`) :
  - `vueLecteur(e, now)` → `{blocage, kicker, quip, titre, titreBrut, artiste, demandeur:{texte, sceau}, pos, duree, progression, pause, boucle, aEnCours, serveur:{id, nom, enDirect}, compte, total, file, plus, vide}`.
    - `blocage` vaut `'non-lie'|'sans-serveur'|null` ;
    - `vide` vaut `{titre, corps, quip}|null`.
  - `lignesFile(queue, me, max = FILE_MAX)` → `{lignes: [{key, titre, titreBrut, artiste, demandeur, sceau, duree, vignette, prochain}], plus}`.
  - `confirmationStop(n)` → `{titre, corps, oui, non}|null`.
  - `piedRaccourcis(raccourcis)` → `[{nom, touches, libelle, libre}]`.
  - `vueServeurs(serveurs, courantId)` → `[{id, nom, initiales, icone, statut, actif}]`.
- Produces (`ui/lecteur.js`) : `monterLecteur(racine, greg, {fenetre: 'panneau'|'bureau'})` → `{surEtat(e), focaliserRecherche(), reinitialiser()}`.

Règles :
- Surtitre :
  - `kickerKey({paused, repeat})` rendu par `t`, s'il y a un titre en cours ;
  - sinon `ow.panel.idleKicker`.
- Réplique : `quip(requesterKeys(r).quips, seedOf(current.key))`, seulement si `reglages.repliques` et si la clé existe.
- Demandeur : `t(requesterKeys(r).plain, {name})`.
- Compte : `t('ow.panel.queueHead', {n: queue.length})`.
- Total : `t('ow.panel.total', {n: Math.ceil(somme des durées / 60)})`.
- Lignes de la file :
  - `demandeur` vaut `ow.queue.mine` pour les siens, sinon le nom, sinon `''` ;
  - `sceau` seulement pour les siens ;
  - `vignette = thumbOf(titre)` ;
  - `prochain` seulement à l'index 0 ;
  - `plus = t('ow.queue.more', {n: queue.length − max})` au-delà de `max`.
- File vide : `queue.empty.title`, `queue.empty.body`, plus la réplique de `queue.empty`.
- `confirmationStop(0)` vaut `null`. Sinon : titre `confirm.stop.title`, corps `confirm.stop.body` (pluriel sur `n`), `oui` = `confirm.stop.confirm`, `non` = `confirm.stop.cancel`.
- `piedRaccourcis` :
  - libellés `ow.panel.footer.<nom>`, `touches = bindingParts(binding)` ;
  - un raccourci libre prend `touches: []` et `libelle` suivi de ` (non attribué)`.
- `vueServeurs` :
  - `statut` = `[playing ? ow.guilds.playing, greg_voice ? gregIn {channel}, user_voice ? youIn {channel}]`, joints par « · », sinon `ow.guilds.gregHere` ;
  - `initiales` : premières lettres des deux premiers mots, en majuscules ;
  - `icone` seulement si l'hôte est `cdn.discordapp.com`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/vue-lecteur.test.js
import { SCENARIOS } from '../apercu/scenarios.js';
const ME = { id: '42', name: 'Paul' };
const tr = (i, by) => ({ key: `k${i}`, title: `Titre ${i}`, artist: 'Artiste', url: '', duration: 240, addedBy: by });
test('file : 60 lignes au plus, puis « …et N autres titres »', () => {
  const q = Array.from({ length: 61 }, (_, i) => tr(i, { id: '7', name: 'Martin' }));
  assert.deepEqual([lignesFile(q, ME).lignes.length, lignesFile(q, ME).plus], [60, '…et 1 autre titre']);
  assert.equal(lignesFile([...q, tr(99, null)], ME).plus, '…et 2 autres titres');
  assert.equal(lignesFile(q.slice(0, 3), ME).plus, null);
});
test('lignes : vous avec sceau, un autre, inconnu ; « À suivre » sur la première seulement', () => {
  const l = lignesFile([tr(1, { id: '42', name: 'Paul' }), tr(2, { id: '7', name: 'Martin' }), tr(3, null)], ME).lignes;
  assert.deepEqual(l.map((x) => [x.demandeur, x.sceau, x.prochain]), [['Vous', 'img/seals/king-seal-P.webp', true], ['Martin', null, false], ['', null, false]]);
  assert.equal(l[0].duree, '4:00');
});
test('surtitre, réplique coupée, compte et total', () => {
  const e = { ...SCENARIOS.lecture, reglages: { ...SCENARIOS.lecture.reglages, repliques: false } };
  const v = vueLecteur(e, Date.now()); assert.equal(v.quip, null); assert.equal(v.kicker, 'En lecture');
  assert.equal(vueLecteur({ ...e, lecteur: { ...e.lecteur, paused: true } }, Date.now()).kicker, 'En pause');
  assert.equal(vueLecteur({ ...e, lecteur: { ...e.lecteur, repeat: true } }, Date.now()).kicker, 'En boucle');
  const q4 = [tr(1, null), tr(2, null), tr(3, null), { ...tr(4, null), duration: 190 }];   // 910 s → 16 min (arrondi au-dessus)
  const w = vueLecteur({ ...e, lecteur: { ...e.lecteur, queue: q4 } }, Date.now());
  assert.deepEqual([w.compte, w.total], ['À suivre · 4 titres', '16\u00a0min']);
  assert.equal(vueLecteur({ ...e, lecteur: { ...e.lecteur, queue: [tr(1, null)] } }, Date.now()).compte, 'À suivre · 1 titre');
});
test('blocages : pas lié, sans serveur', () => {
  assert.equal(vueLecteur({ ...SCENARIOS.lecture, connexion: { statut: 'non-lie' } }, Date.now()).blocage, 'non-lie');
  assert.equal(vueLecteur({ ...SCENARIOS.lecture, serveur: { id: '', nom: '' } }, Date.now()).blocage, 'sans-serveur');
});
test('confirmation de l’arrêt', () => {
  assert.equal(confirmationStop(0), null);
  assert.deepEqual(confirmationStop(3), { titre: 'Tout arrêter\u202f?', corps: 'La musique s’arrête et les 3 titres de la file sont retirés.', oui: 'Tout arrêter', non: 'Garder la musique' });
  assert.equal(confirmationStop(1).corps, 'La musique s’arrête et le titre de la file est retiré.');
});
test('Review Focus 5 : pied des raccourcis, « non attribué » au lieu d’une touche morte', () => {
  const r = { pause: { binding: 'Ctrl+F7', libre: false }, suivant: { binding: 'Ctrl+F8', libre: false }, panneau: { binding: '', libre: true }, bandeau: { binding: 'Ctrl+F11', libre: false } };
  assert.deepEqual(piedRaccourcis(r).map((x) => [x.nom, x.touches, x.libelle]),
    [['pause', ['Ctrl', 'F7'], 'pause'], ['suivant', ['Ctrl', 'F8'], 'suivant'], ['panneau', [], 'panneau (non attribué)'], ['bandeau', ['Ctrl', 'F11'], 'bandeau']]);
});
test('serveurs : statut et initiales', () => {
  const s = vueServeurs([{ id: '1', name: 'Le Donjon', icon_url: 'https://evil.example/x.png', greg_voice: { id: '9', name: 'Taverne' }, user_voice: null, playing: true },
    { id: '2', name: 'Les Copains d’abord', icon_url: null, greg_voice: null, user_voice: { id: '8', name: 'Salon' }, playing: false },
    { id: '3', name: 'Boulot', icon_url: null, greg_voice: null, user_voice: null, playing: false }], '1');
  assert.deepEqual(s.map((x) => [x.initiales, x.statut, x.actif, x.icone]), [['LD', 'En lecture · Greg est dans Taverne', true, null],
    ['LC', 'Vous êtes dans Salon', false, null], ['B', 'Greg est là', false, null]]);
});
```

(Les initiales de « Les Copains d’abord » se calculent sur les deux premiers mots : « LC ».)

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/vue-lecteur.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/vue-lecteur.js`**

Suivre exactement les règles plus haut.

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : écrire le lecteur et la page du panneau**

Référence visuelle :
- `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.tpl.html` :
  - « Le panneau » (CSS lignes 117-158, HTML lignes 266-321) ;
  - « Ajouter un morceau » (CSS lignes 169-178, HTML lignes 331-341) ;
- `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\shared.css` : lignes 52-59 pour `.btn` et `.switch`, lignes 69-86 pour le transport, la recherche et la file.

Le pied montre les raccourcis du moment (`piedRaccourcis`) et non les exemples « Ctrl Maj G » de la maquette.

`ui/lecteur.js`, `monterLecteur(racine, greg, {fenetre})`. Tout texte venu de l'état passe par `textContent`, jamais par `innerHTML`.
- **En-tête :**
  - médaillon `img/greg-face-96.webp`, « Greg » en `--f-display` ;
  - pastille du serveur (point vert si `tempsReel`, chevron), qui ouvre la liste `vueServeurs`. Un clic appelle `greg.choisirServeur(id)`, et l'ouverture de la liste appelle `greg.rafraichirServeurs()` ;
  - dans le panneau seulement, à droite de l'en-tête (spec §6.5 : « le nom du serveur … et « Échap » ») :
    - un `<kbd>Échap</kbd>` (`aria-hidden="true"`, le bouton porte déjà le libellé) juste avant la croix, avec le style `kbd` de `css/base.css` (tâche 15) ;
    - un bouton `i-x` avec `aria-label` `ow.panel.close`, qui appelle `greg.fermerPanneau('bouton')`.
- **En cours :**
  - surtitre lumière avec `.eq` animée en lecture, réplique `.quip`, titre (`title = titreBrut`) ;
  - meta : artiste, point, sceau, demandeur ;
  - barre et temps, repeints toutes les 250 ms.
- **Transport :** stop, recommencer, `.roundel` pause / lecture, suivant, boucle (`aria-pressed`), avec les `aria-label` de `controls.*`.
  - Stop appelle `confirmationStop(n)`. S'il y a une confirmation, une boîte `role="dialog"` s'ouvre, le focus sur « Garder la musique » (motif de `C:\Users\Paul\Documents\Codage\GregLeConsanguin\services\web\src\components\Stage\Transport.tsx`, lignes 50-64 pour la boîte et ligne 35 pour le focus).
- **Recherche :**
  - placeholder `search.placeholder` ;
  - suggestions après 280 ms dès 2 caractères, jamais pour un lien : `greg.suggerer(q)`, en ignorant une réponse dépassée ;
  - liste `.sugg.plaque` (`role="listbox"`), choix par ↑ / ↓, indication « ↑ ↓ choisir · Entrée ajouter » ;
  - Entrée ajoute la suggestion choisie, sinon la première affichée, sinon le texte tel quel (`greg.ajouter({suggestion})` ou `greg.ajouter({texte})`) ;
  - pendant l'ajout, Entrée est ignorée et le libellé vaut `search.submit.busy` ; après un succès, le champ est vidé ;
  - un `paste` dont le texte est un lien (`looksLikeUrl`) est ajouté aussitôt.
- **File :**
  - en-tête « À suivre · N titres » et total ;
  - lignes `.qrow` : vignette, titre, artiste, sceau, demandeur, durée, « À SUIVRE » sur la première ;
  - au survol ou au focus, `.acts` : jouer maintenant (`greg.jouerMaintenant`), en tête (`greg.enTete`), retirer (`greg.retirer`, survol en `--gueules`), avec les `aria-label` de `queue.actions.*Aria` ;
  - glisser-déposer (`draggable`) : `greg.deplacer(key, beforeKey)`. Un dépôt après la dernière ligne affichée donne `queue[60]?.key ?? null`, comme `QueuePanel.tsx:105` ;
  - sur une ligne focalisée :
    - Alt+↑ / Alt+↓ : `moveBefore(keys, key, ±1)`, puis `greg.deplacer` si le résultat n'est pas `undefined` ;
    - Entrée : jouer maintenant ; Suppr : retirer ;
  - ligne « …et N autres titres » ; état vide avec titre, corps et réplique.
- **Héraut :** les 3 toasts les plus récents non partants (`.toast.plaque`, rond par sorte, fait, réplique) en bas du lecteur.
- **Blocages :** `blocage === 'non-lie'` affiche `ow.panel.notLinked` à la place du lecteur ; `sans-serveur` ouvre directement la liste des serveurs.

`ui/panneau.js` :
- `brancher('panneau', {surEtat, surOuvert})`. `surOuvert` vide la recherche, ferme les suggestions, puis fait `window.focus()` et `focaliserRecherche()`.
- `keydown` sur le document :
  - Échap ferme d'abord les suggestions ou la boîte de dialogue, sinon `greg.fermerPanneau('echap')` ;
  - `nomPourTouche(ev, etat.raccourcis)` non nul : `preventDefault`, puis `greg.toucheDansPanneau(nom)` ;
  - Tab et Maj+Tab bouclent entre le premier et le dernier élément focalisable.
- `focus` et `blur` de la fenêtre appellent `greg.signaler('focus')` et `greg.signaler('blur')`.
- Le pied (`piedRaccourcis`) est rendu sous la file.

`panneau.html` : CSP, `css/tokens.css`, `css/base.css`, `css/lecteur.css`, `<div id="panneau"></div>`, `<script type="module" src="ui/panneau.js"></script>`.

`css/lecteur.css` :
- fond du panneau `.glass` à `rgb(11 9 8 / .84)` (maquette) ;
- largeur 100 % de la fenêtre de 440 px ;
- la file défile (`overflow: auto`), le reste est fixe.

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0` (`pages.test.js` couvre `panneau.html`).

- [ ] **Step 6 : vérifier dans un navigateur**

Le serveur d'aperçu tourne (`cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node apercu/serveur.mjs`, en arrière-plan, s'il ne tourne plus). Après la vérification « Jeu en cours », ouvrir `http://127.0.0.1:47323/panneau.html?scenario=<nom>` pour `lecture`, `pause`, `fileVide`, `file62`, `suggestions`, `choixServeur`, `raccourciLibre` et `nonLie`, avec Playwright. Comparer les captures à `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\1-en-jeu.html`.

Attendu :
- pas d'erreur console ;
- l'en-tête montre `Échap` à côté de la croix ;
- la file de 62 titres montre 60 lignes puis « …et 2 autres titres » ;
- clavier :
  - Tab ne sort jamais du panneau ;
  - Échap journalise `greg.fermerPanneau echap` ;
  - Ctrl+F8 journalise `greg.toucheDansPanneau suivant` ;
  - Alt+↓ sur la 1re ligne journalise `greg.deplacer k1 k3` ;
- souris :
  - un glisser de la 4e ligne sur la 2e journalise `greg.deplacer k4 k2` ;
  - Stop avec une file non vide ouvre la confirmation, le focus sur « Garder la musique » ;
  - coller `https://youtu.be/dQw4w9WgXcQ` journalise `greg.ajouter` aussitôt.

- [ ] **Step 7 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/vue-lecteur.js ui/lecteur.js ui/panneau.js panneau.html css/lecteur.css apercu/scenarios.js apercu/index.html tests/vue-lecteur.test.js tests/apercu.test.js tests/pages.test.js \
  && git commit -m "feat: panneau en jeu (lecture, transport, recherche, file, raccourcis du moment)"
```

---

## Tâche 17 : la fenêtre bureau (connexion, lecteur, réglages)

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\lib\vue-bureau.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\ui\bureau.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\ui\reglages.js`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\bureau.html`, `C:\Users\Paul\Documents\Codage\greg-overlay-ow\css\bureau.css`.
- Modify (sous `C:\Users\Paul\Documents\Codage\greg-overlay-ow\`) :
  - `apercu\scenarios.js` : scénarios `code`, `codeExpire`, `codeRefuse`, `trop`, `verification`, `lieSansServeur`, `reglages` ;
  - `apercu\index.html` : `iframe` 480 × 780 du bureau ;
  - `tests\pages.test.js` : `PAGES` += `'bureau.html'` ;
  - `tests\apercu.test.js` : `vueConnexion` et `vueReglages` sur chaque scénario.
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\vue-bureau.test.js`.

**Interfaces:**
- Consumes : `EtatDiffuse`, le `pont`, `brancher`, `h`, `monterLecteur`, `peindreBandeau`, `vueBandeau`, `vueServeurs` ; `t`, `quip` ; `fmt`, `discordAvatar` ; `bindingParts`, `captureDe`, `NOMS` ; `EMPLACEMENTS`.
- Produces (`lib/vue-bureau.js`) :
  - `vueConnexion(connexion, now)` → `{ecran, code, restant, message, bouton: {libelle, action}|null}`, où :
    - `ecran` vaut `'verification'|'preparation'|'code'|'expire'|'refuse'|'erreur'|'lie'` ;
    - `bouton.action` vaut `'ouvrirSite'|'nouveauCode'`.
  - `vueReglages(e)` → `{raccourcis: [{nom, libelle, touches, libre}], emplacements: [{valeur, libelle, actif}], tailles: [{valeur, libelle, actif}], opacite, amis, repliques, compte: {nom, avatar}}`.

Correspondances de `vueConnexion` :

| `statut` / `erreur` | `ecran` | `message` | `bouton` |
|---|---|---|---|
| `verification` | `verification` | `ow.device.checking` | aucun |
| `non-lie`, pas d'erreur | `preparation` | `ow.device.preparing` | `nouveauCode` |
| `non-lie`, `RATE_LIMITED` | `erreur` | `ow.device.rateLimited` | `nouveauCode` |
| `non-lie`, `RESEAU` | `erreur` | `ow.device.failed` | `nouveauCode` |
| `code` | `code` | `ow.device.waiting` | `ouvrirSite` (« Ouvrir le site pour l’autoriser ») |
| `code-expire` | `expire` | `ow.device.expired` | `nouveauCode` (« Nouveau code ») |
| `refuse` | `refuse` | `ow.device.denied` | `nouveauCode` |
| `lie` | `lie` | `''` | aucun |

`restant` vaut `fmt(Math.max(0, expireA − now) / 1000)` en `code`, sinon `null`.

- [ ] **Step 1 : écrire les tests qui échouent**

```js
// tests/vue-bureau.test.js
import { SCENARIOS } from '../apercu/scenarios.js';   // `reglages` : réglages par défaut, raccourcis de la spec
const NOW = 1_700_000_000_000;
test('code en attente : grand code, temps restant, bouton du site', () => {
  const v = vueConnexion({ statut: 'code', code: 'BCDF-GHJK', uri: 'https://site/lier?code=BCDF-GHJK', expireA: NOW + 582_000, erreur: null }, NOW);
  assert.deepEqual([v.ecran, v.code, v.restant, v.message], ['code', 'BCDF-GHJK', '9:42', 'En attente de votre accord sur le site…']);
  assert.deepEqual(v.bouton, { libelle: 'Ouvrir le site pour l’autoriser', action: 'ouvrirSite' });
  assert.equal(vueConnexion({ statut: 'code', code: 'X', expireA: NOW - 5, erreur: null }, NOW).restant, '0:00');
});
test('expiré, refusé, trop de demandes, site injoignable ou refus : « Nouveau code »', () => {
  for (const [c, msg] of [[{ statut: 'code-expire' }, 'Ce code a expiré.'], [{ statut: 'refuse' }, 'Demande refusée sur le site.'],
    [{ statut: 'non-lie', erreur: 'RATE_LIMITED' }, 'Trop de demandes de code\u00a0: réessayez dans une minute.'],
    [{ statut: 'non-lie', erreur: 'RESEAU' }, 'Le site ne répond pas\u00a0: réessayez dans un instant.']]) {   // RESEAU : réseau ou tout autre refus de deviceStart (tâche 9)
    const v = vueConnexion({ erreur: null, ...c }, NOW); assert.equal(v.message, msg); assert.deepEqual(v.bouton, { libelle: 'Nouveau code', action: 'nouveauCode' });
  }
  assert.equal(vueConnexion({ statut: 'verification', erreur: null }, NOW).bouton, null);
});
test('réglages : libellés de la spec et valeurs actives', () => {
  const v = vueReglages(SCENARIOS.reglages);
  assert.deepEqual(v.emplacements.map((x) => [x.libelle, x.actif]), [['En bas à gauche', true], ['Bord gauche, au tiers', false], ['En haut à gauche', false]]);
  assert.deepEqual(v.tailles.map((x) => x.libelle), ['Compacte', 'Normale']);
  assert.deepEqual(v.raccourcis.map((x) => x.libelle), ['Pause ou reprise', 'Titre suivant', 'Ouvrir ou fermer le panneau', 'Afficher ou cacher le bandeau']);
  assert.deepEqual(v.raccourcis[0].touches, ['Ctrl', 'F7']); assert.equal(v.opacite, 70);
});
```

- [ ] **Step 2 : vérifier l'échec**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/vue-bureau.test.js`
Expected : FAIL (`ERR_MODULE_NOT_FOUND`).

- [ ] **Step 3 : écrire `lib/vue-bureau.js` et les scénarios du bureau**

- Suivre exactement la table plus haut. `compte.avatar = discordAvatar(me, 64)`, en ne gardant que `cdn.discordapp.com`.
- Ajouter à `apercu/scenarios.js` les scénarios `code`, `codeExpire`, `codeRefuse`, `trop`, `verification`, `lieSansServeur` et `reglages`. `reglages` est l'état de base (réglages par défaut, raccourcis de la spec).

- [ ] **Step 4 : vérifier le succès**

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0`.

- [ ] **Step 5 : écrire la fenêtre bureau**

Référence visuelle :
- `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\2-hors-jeu.tpl.html` :
  - fenêtres `.win`, `.wbar`, `.wbody` (lignes 10-16) ;
  - étape 1 « code » (CSS lignes 22-27, HTML lignes 114-129), étape 3 « serveur » (lignes 40-47 et 148-164) ;
  - « Entre deux parties » : lecteur et réglages (CSS lignes 48-68, HTML lignes 170-219).
- Écarts avec la maquette :
  - le code au format `XXXX-XXXX` ;
  - les emplacements sont les trois de la spec, en `.seg`, au lieu des quatre coins ;
  - deux tailles ;
  - un curseur d'opacité avec aperçu ;
  - les raccourcis du moment, pas « Ctrl Maj G ».

`ui/bureau.js` :
- `brancher('bureau', {surEtat})`.
- **Barre de titre :**
  - « Greg » ; roue dentée (onglet Réglages) une fois lié ; boutons réduire (`overwolf.windows.minimize`) et fermer (`overwolf.windows.hide` : l'appli reste en fond) ;
  - `mousedown` sur la barre : `overwolf.windows.dragMove(id)` (id lu par `getCurrentWindow`).
- **Écrans selon `vueConnexion` :**
  - connexion : portrait `img/greg-face-192.webp`, kicker `auth.kicker`, titre `auth.title`, texte `ow.device.intro`, code `.code.plaque` en grand, « Valable encore m:ss » repeint chaque seconde, message, bouton, réplique de `auth.quips` si les répliques sont actives ;
  - `nouveauCode` appelle `greg.nouveauCode()` et `ouvrirSite` appelle `greg.ouvrirSite()`.
- **Lié sans serveur :** écran de l'étape 3 (« À votre service, Sire. », « Sur quel serveur dois-je jouer ? », `vueServeurs`, « Continuer » → `greg.choisirServeur(id)`).
- **Lié avec serveur :** onglets « Lecteur » (`monterLecteur(racine, greg, {fenetre: 'bureau'})`) et « Réglages » (`ui/reglages.js`).

`ui/reglages.js`, `monterReglages(racine, greg)` → `{surEtat(e)}` :
- **Raccourcis :**
  - une `.line` par raccourci, avec les `kbd` (ou « Non attribué ») et « Changer » ;
  - « Changer » passe en capture (« Appuyez sur la combinaison… », aide `captureHelp`), avec `keydown` → `captureDe(ev)` :
    - `attente` : on continue ; `annule` : fin ;
    - `refus` : message `needModifier` ;
    - `ok` : `greg.assignerRaccourci(nom, combo)`, puis le message `taken {name}` (avec le libellé de `hotkeyLabels[par]` si `par` est un de nos noms, sinon `par`) ou `assignFailed`, ou la fin de la capture.
- **Le bandeau en jeu :**
  - « Emplacement » (`.seg` à 3) ; « Taille » (`.seg` à 2) ;
  - « Fond du bandeau » (`<input type="range" min="0" max="100" step="5">` avec la valeur en %, aide `opacityHelp`) ;
  - « Annoncer ce que font les amis » (`.switch`, `role="switch"`, `aria-checked`) ;
  - chaque changement appelle `greg.reglages({…})`. Le curseur l'envoie sur `input`, pour l'appliquer en direct.
  - aperçu : `peindreBandeau(apercu, vueBandeau(e, Date.now()))` sur le décor `.stage` de la maquette, repeint à chaque état.
- **Greg :** `header.settings.quips` et `header.settings.quipsHelp` (`.switch`).
- **Compte :**
  - avatar avec `img/crown-badge-64.webp` posé en haut à droite (c'est le Roi), « Lié au compte de {name} », aide `unlinkHelp` ;
  - « Délier cet appareil » ouvre une boîte `role="dialog"` (`unlinkConfirm`), le focus sur « Garder », puis appelle `greg.delier()`.

`bureau.html` : CSP, `css/tokens.css`, `css/base.css`, `css/lecteur.css`, `css/bureau.css`, `<div id="bureau"></div>`, `<script type="module" src="ui/bureau.js"></script>`.

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
Expected : `# fail 0` (`pages.test.js` couvre `bureau.html`).

- [ ] **Step 6 : vérifier dans un navigateur**

Le serveur d'aperçu tourne (`cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node apercu/serveur.mjs`, en arrière-plan, s'il ne tourne plus). Après la vérification « Jeu en cours », ouvrir `http://127.0.0.1:47323/bureau.html?scenario=<nom>` pour `code`, `codeExpire`, `codeRefuse`, `trop`, `verification`, `lieSansServeur`, `lecture` et `reglages`, avec Playwright. Comparer les captures à `C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-maquettes\2-hors-jeu.html`.

Attendu :
- pas d'erreur console ; le code `BCDF-GHJK` en grand, le temps restant qui décompte ;
- « Ouvrir le site pour l’autoriser » journalise `greg.ouvrirSite` ;
- dans Réglages :
  - Changer puis Ctrl+F9 journalise `greg.assignerRaccourci` avec `{ctrl: true, alt: false, shift: false, virtualKey: 120}` ;
  - Changer puis Ctrl+F7 affiche « Déjà prise par « Pause ou reprise ». » ;
  - Changer puis Q affiche « Ajoutez Ctrl ou Alt. » ;
- le curseur d'opacité modifie l'aperçu en direct (texte seul à 0 %) ;
- Délier ouvre la confirmation, le focus sur « Garder ».

- [ ] **Step 7 : commit**

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/vue-bureau.js ui/bureau.js ui/reglages.js bureau.html css/bureau.css apercu/scenarios.js apercu/index.html tests/vue-bureau.test.js tests/apercu.test.js tests/pages.test.js \
  && git commit -m "feat: fenêtre bureau (liaison par code, lecteur, réglages avec aperçu du bandeau)"
```

---

## Tâche 18 : README, vérification finale et PR

**Files:**
- Create : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\README.md`.
- Modify : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\manifest.test.js` (ajout ci-dessous).
- Test : `C:\Users\Paul\Documents\Codage\greg-overlay-ow\tests\manifest.test.js`.

- [ ] **Step 1 : écrire le test de cohérence du manifeste**

```js
test('chaque fenêtre du manifeste a sa page', () => {
  for (const [nom, w] of Object.entries(m.data.windows)) assert.ok(existsSync(w.file), `${nom} : ${w.file}`);
  assert.ok(existsSync(m.meta.icon));
});
```

Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node --test tests/manifest.test.js`
Expected : PASS, puisque les pages existent depuis les tâches 14 à 17. S'il échoue, corriger la page manquante.

- [ ] **Step 2 : écrire `README.md`**

En français, sans emoji, sections :
1. **Ce que c'est** : le bandeau, le panneau, la fenêtre bureau et les raccourcis par défaut (Ctrl+F7 pause, Ctrl+F8 suivant, Ctrl+F10 panneau, Ctrl+F11 bandeau). Pour Paul seul : un compte développeur Overwolf approuvé est nécessaire, et les amis passent par le site.
2. **Charger l'appli (Load unpacked)** :
   - `overwolf://packages` : retirer la carte de l'ancienne GregLC et désactiver « Greg essai » ;
   - Load unpacked → `C:\Users\Paul\Documents\Codage\greg-overlay-ow` ;
   - vérifier que l'UID affiché est `ahnflfbohhimdmoeoogpiohdmjdokiioleialagk`. Au besoin, lire `GregLC origine` dans `%LOCALAPPDATA%\Overwolf\Log\Apps\GregLC\fond.html.log` ;
   - si la fumée de la tâche 1 (étape 7) a fait passer `bureau` en fenêtre non native, le dire ici, avec la raison (le pont n'atteignait pas la page de fond).
3. **Réglages Railway (service API)**, à faire seulement avec l'accord de Paul :
   - `OVERLAY_ORIGINS=overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk` ;
   - `GREG_OWNER_ID` avec la même valeur que le service BOT DISCORD ;
   - sans eux : CORS et socket refusés, et l'autorisation du code refusée (403 `NOT_OWNER`).
4. **Lier** : ouvrir la fenêtre Greg, « Ouvrir le site pour l’autoriser », puis Autoriser sur `/lier`.
5. **Délier** : Réglages → « Délier cet appareil », ou le site → « Appareils liés » → Délier.
6. **Désactiver ou retirer l'appli** : interrupteur « App activated » de la carte GregLC dans `overwolf://packages`, ou Uninstall. Fermer la fenêtre ne l'arrête pas : la page de fond attend la prochaine partie.
7. **Développer** :
   - `npm test` ;
   - `npm run sync-web` (après un changement de la DA ou du deck du site), puis commiter les sorties ;
   - `npm run apercu`, puis `http://127.0.0.1:47323/apercu/index.html`.

- [ ] **Step 3 : lancer toute la suite**

La sortie de `npm test` est gardée dans le scratchpad (contrainte « Scratchpad ») pour le corps de la PR.

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && SCRATCHPAD='<scratchpad>' && test -d "$SCRATCHPAD" \
  && npm test > "$SCRATCHPAD/npm-test.log" 2>&1 \
  && grep -E '^# (tests|pass|fail|skipped) ' "$SCRATCHPAD/npm-test.log" | tee "$SCRATCHPAD/npm-test.txt" \
  && node scripts/sync-web.mjs --check
```
Expected :
- quatre lignes `# tests N`, `# pass N`, `# fail 0`, `# skipped 0`, avec le même N (le test `--check` de `tests/sync-web.test.js` n'est pas sauté, puisque le site est là) ;
- `--check` renvoie 0, sans écart.

- [ ] **Step 4 : repasser les aperçus**

Run (en arrière-plan) : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && node apercu/serveur.mjs`
Puis ouvrir `http://127.0.0.1:47323/apercu/index.html` dans Playwright, après la vérification « Jeu en cours » des contraintes globales.

Attendu :
- les trois fenêtres dans tous leurs scénarios ;
- aucune erreur console ;
- une capture par fenêtre, gardée dans le scratchpad et non commitée.

- [ ] **Step 5 : relecture indépendante**

Faire relire la branche par un relecteur qui n'a pas écrit le code (spec §7), avec la spec, ce plan et sa section « Review Focus ». Corriger ce qu'il trouve, chaque correctif dans son propre commit.

- [ ] **Step 6 : corps de la PR, commit, push et PR**

Écrire le corps de la PR dans le fichier `pr-overlay-v3.md` du scratchpad de la session (Write, chemin Windows absolu de ce scratchpad ; c'est `$SCRATCHPAD/pr-overlay-v3.md` côté Git Bash). Texte exact ci-dessous, en français, sans aucune mention d'IA (ni `Co-Authored-By`, ni « Generated with », ni nom d'outil). Le bloc indenté de « Tests » reçoit les quatre lignes de `$SCRATCHPAD/npm-test.txt` (étape 3), recopiées telles quelles, à la place de la ligne `# …`.

```markdown
## Résumé

Nouvelle appli Overwolf de Greg (OW-native, version 3.0.0). Elle remplace l'ancienne GregLC, retirée de l'arbre et gardée dans l'historique.

- **Bandeau** en jeu, en bas à gauche par défaut : titre en cours, demandeur, temps, barre, refus et lignes d'amis. Il ne prend jamais le clavier ni les clics.
- **Panneau** en jeu (Ctrl+F10) : titre en cours, commandes, recherche avec suggestions, file (glisser-déposer, Alt+↑/↓) et raccourcis du moment. Il prend le clavier à l'ouverture et le rend à Échap, à Ctrl+F10 ou au premier clic dans le jeu.
- **Fenêtre bureau**, hors partie seulement : liaison par code avec le site (/lier), lecteur, réglages (raccourcis, emplacement, taille et fond du bandeau, lignes d'amis, répliques, délier).
- **Raccourcis** : Ctrl+F7 pause, Ctrl+F8 suivant, Ctrl+F10 panneau, Ctrl+F11 bandeau. Un raccourci qu'Overwolf n'a pas pu attribuer est signalé sur le bandeau au début de la partie.

L'appli parle à l'API publique avec un jeton porteur (`Authorization: Bearer`), jamais avec un cookie. Le jeton reste dans le stockage local de l'appli et n'apparaît jamais dans une URL.

## Dépendance

Le plan A (dépôt GregLeConsanguin : API, bot, page /lier) doit être déployé, avec sur le service API :

- `OVERLAY_ORIGINS=overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk` ;
- `GREG_OWNER_ID`, avec la même valeur que sur le service BOT DISCORD.

Sans eux, l'API refuse l'origine de l'appli, le socket et l'autorisation du code.

## Tests

`npm test` (Node 22, `node --test`) :

    # …

`node scripts/sync-web.mjs --check` : aucun écart avec le site.

Le banc hors jeu (faux Overwolf, fausse API, faux socket) couvre la liaison par code, l'abonnement, les actions, les raccourcis et leur fusion, le panneau qui rend le clavier, l'appareil délié en pleine partie et les serveurs illisibles au démarrage.

## Protocole en jeu (Paul, outil d'entraînement, Plein écran)

1. `overwolf://packages` : retirer l'ancienne GregLC, désactiver Greg essai, puis Load unpacked → `C:\Users\Paul\Documents\Codage\greg-overlay-ow`.
2. Hors partie, la fenêtre Greg montre un code. Cliquer « Ouvrir le site pour l’autoriser », puis Autoriser. La fenêtre passe au lecteur ; choisir le serveur si elle le demande.
3. Lancer une partie d'entraînement :
   - le bandeau apparaît en bas à gauche ;
   - cliquer dessus 4 ou 5 fois : les clics passent au jeu ;
   - ouvrir le chat (Entrée) et taper quelques lettres sans les envoyer, puis prendre une capture de tout l'écran avec Win+Alt+Impr. écran (Xbox Game Bar, fichier dans `C:\Users\Paul\Videos\Captures`). Envoyer le chemin du fichier : la capture sert à régler la marge du bas pour que le bandeau ne couvre pas le chat. Si l'image est noire ou sans bandeau, repasser LoL en « Fenêtré sans bordure » le temps de la capture. Échap ferme le chat.
4. Ctrl+F7 puis Ctrl+F8 : le bandeau passe en pause, puis au titre suivant.
5. Ctrl+F10 ouvre le panneau :
   - taper un titre puis Entrée l'ajoute ;
   - Échap ferme ; lancer aussitôt un sort sans toucher la souris : il part.
6. Ctrl+F10 pour ouvrir, Ctrl+F10 pour fermer, puis un sort. Ctrl+F10, puis un clic dans le jeu : le panneau se ferme.
7. Ctrl+F11 cache le bandeau, Ctrl+F11 le remontre.
8. Hors partie, dans Réglages :
   - fond à 0 %, puis à 100 % ;
   - « Bord gauche, au tiers » ; taille Compacte ;
   - revérifier en jeu.
9. Depuis le site ou par un ami : ajouter un titre ; une ligne apparaît 5 s sous le bandeau.
10. Réglages → Délier : le bandeau dit « Liez l’appli depuis la fenêtre Greg ».

Ne pas fusionner sans l'accord de Paul.
```

Puis :

```bash
cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && SCRATCHPAD='<scratchpad>' && test -f "$SCRATCHPAD/pr-overlay-v3.md" \
  && ! grep -qiE 'co-authored|generated with|claude|anthropic' "$SCRATCHPAD/pr-overlay-v3.md" \
  && git add README.md tests/manifest.test.js \
  && git commit -m "docs: README de l'appli v3 (chargement, Railway, délier, désactiver)" \
  && git push -u origin feat/overlay-v3 \
  && gh pr create --base master --head feat/overlay-v3 --title "Overlay v3 : appli Overwolf de Greg (bandeau, panneau, liaison par code)" --body-file "$SCRATCHPAD/pr-overlay-v3.md"
```
Expected : la dernière ligne est l'adresse de la PR (`https://github.com/…/pull/N`).

La fumée de la tâche 1 (étape 7) a déjà vérifié le pont du bureau. Si la fenêtre bureau reste quand même vide en jeu réel, relever `C:\Users\Paul\AppData\Local\Overwolf\Log\Apps\GregLC\bureau.html.log`. Le repli est de passer `bureau.native_window` à `false`, sur accord de Paul (même marche à suivre qu'à la tâche 1, étape 7, point 5).

- [ ] **Step 7 : demander à Paul**

Donner le lien de la PR. Lui demander de suivre le protocole en jeu du corps de la PR et d'envoyer le chemin de la capture du point 3. Ne pas fusionner.

- [ ] **Step 8 : ajuster `MARGE_BAS` sur la capture de Paul**

1. Lire la capture (Read sur le chemin donné par Paul). Elle n'est jamais commitée. Relever :
   - `H`, la hauteur de l'image en pixels (la hauteur logique du jeu à 100 % d'échelle ; sinon, ramener les mesures à `logicalHeight`) ;
   - `y_chat`, le haut de la zone du chat ouvert (messages et ligne de saisie), dans la colonne `x` de 16 à 356 où se tient le bandeau.
2. Le bandeau normal occupe `x` de 16 à 356 et `y` de `H − 132 − MARGE_BAS` à `H − MARGE_BAS`.
   - S'il ne touche pas la zone du chat : garder `MARGE_BAS = 24`, et le dire en commentaire de la PR.
   - Sinon : `MARGE_BAS = H − y_chat + 8`, pour que le bas du bandeau reste 8 px au-dessus du chat.
3. Si la valeur change, `M` étant la nouvelle :
   - `lib/placement.js` : `MARGE_BAS = M` ;
   - `tests/placement.test.js` : `assert.equal(MARGE_BAS, M)`. Les hauts attendus deviennent `Math.max(16, 1080 − 132 − M)`, `Math.max(16, 1080 − 92 − M)` et `Math.max(16, 1440 − 132 − M)` dans « bas à gauche par défaut », et `Math.max(16, 200 − 132 − M)` pour `hauteurJeu: 200` dans « jamais de déplacement sous 200 px » ; tous écrits en nombres ;
   - `tests/fenetres.test.js` (« LoL 1920×1080 ») et `tests/cerveau.bench.test.js` (premier test) : `'position id-bandeau 16,924'` devient `'position id-bandeau 16,<1080 − 132 − M>'`, écrit en nombre.

   Run : `cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && npm test`
   Expected : `# fail 0`.

   ```bash
   cd /c/Users/Paul/Documents/Codage/greg-overlay-ow && git add lib/placement.js tests/placement.test.js tests/fenetres.test.js tests/cerveau.bench.test.js \
     && git commit -m "fix: marge basse du bandeau réglée sur une capture de LoL, chat dégagé" \
     && git push
   ```
4. Demander à Paul de revérifier le point 3 du protocole en jeu, puis son accord pour fusionner. Ne pas fusionner sans lui.

---

## Auto-relecture (faite à l'écriture, corrections déjà en place)

- **Couverture de la spec :**

  | Spec | Tâches |
  |---|---|
  | §6.1 dépôt et outillage | 1, 2, 10, 18 |
  | §6.2 manifeste et CSP | 1, 14 à 17 (`pages.test.js`) |
  | §6.3 cerveau : jeton | 9 |
  | §6.3 cerveau : socket, `time_sync`, repli 5 s | 10 |
  | §6.3 cerveau : actions, `expected`, STALE | 13 |
  | §6.3 cerveau : jeu, fenêtres, moins de 200 px | 11 |
  | §6.3 cerveau : raccourcis, fusion, répétition, message sans serveur ni liaison | 12, 13 |
  | §6.4 bandeau | 7, 15, 18 (marge du bas réglée sur une capture, chat dégagé) |
  | §6.5 panneau | 11, 16 (en-tête avec « Échap ») |
  | §6.6 bureau | 9, 12, 17 |
  | §6.7 DA | 2, 15 |
  | §7 vérification de l'appli | 14 (banc), 15 à 17 (aperçus), 18 (protocole en jeu, relecture) |

  §1 (anti-objectifs) : le clavier rendu et les clics qui traversent (tâches 11 et 14), pas de focus du bandeau (manifeste, tâche 1), aucune donnée de partie.
- **Marqueurs vides :** aucun. Les textes dont la spec laisse le détail au constructeur sont fixés dans `lib/copy.overlay.js` (tâche 5).
- **Types et noms :**
  - `EtatDiffuse` (tâche 14) est la seule forme lue par `vue-bandeau`, `vue-lecteur`, `vue-bureau` et `SCENARIOS` ;
  - `Raccourcis` vaut `{nom: {binding, libre}}` partout (tâches 5, 12, 14, 15, 16, 17) ;
  - `ToastInput` et `Toast` ont un champ `bandeau` (tâches 6, 13, 14, 15) ;
  - `DEFAUTS` (tâche 12) = `DEFAUTS_RACCOURCIS` (tâche 5) ;
  - `STORAGE.reglages` porte le même nom aux tâches 1 et 7 ;
  - `DELAIS.reessaiServeur` (5 s, tâche 1) sert au `join_guild` réessayé et à la relance du socket (tâche 10), et au nouvel essai des serveurs (tâche 14) ;
  - `FauxSocket.active` (tâche 10) suit la doc de socket.io-client 4 ; `api.autocomplete` renvoie un tableau, et le faux de la tâche 13 aussi ;
  - `changeSize` prend l'objet plat `{window_id, width, height}` de la doc Overwolf (0.149+), et le faux de la tâche 11 refuse toute autre forme ;
  - `refclock.anchor()` est une méthode (tâches 3 et 14).
- **Contrôles réels, dans Overwolf :** l'étape 7 de la tâche 1 vérifie tôt les modules ES sous CSP, l'origine (l'UID du plan A) et le pont du bureau natif ; la tâche 18 garde le protocole complet en jeu.
- **Review Focus :** les cinq lignes ont leur test, marqué « Review Focus n », dans la tâche qui possède le code : 1 → 11 ; 2 → 5 et 14 ; 3 → 9 ; 4 → 10 et 14 ; 5 → 12, 14 et 16.
- **Proportion :** pas de corps de fonction, sauf les règles que les tests ne fixent pas seuls :
  - la fusion des raccourcis, la table de `copieAmi` et l'assemblage du cerveau, en prose ;
  - le texte exact de `copy.overlay.js` et le manifeste, valeurs que la spec ou le constructeur doivent figer.
