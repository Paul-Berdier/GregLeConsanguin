# Overlay Overwolf, côté API, bot et site : plan d'implémentation (plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** donner à l'appli Overwolf de Paul une entrée sûre dans `GregLeConsanguin` : un code d'appareil autorisé sur le site (/lier), un jeton porteur révocable valable pour le lecteur et le socket, les données qui manquent à l'appli (serveurs, `player_event`, `guild_id` des ticks), et une garde `expected` contre la file qui a bougé.

**Architecture:** l'API gagne une garde CSRF, une liste d'origines à deux étages (site / site + appli), un magasin Redis `overlay_tokens` (codes, jetons, limites de débit) et une identité « session OU porteur » (`require_identity`) posée sur le lecteur, l'historique et la recherche. Un nouveau blueprint `/overlay/*` porte le parcours RFC 8628, et le socket accepte `auth.token`. Le bot répond à `user_guilds`, publie `greg:player:event` après chaque commande réussie qui change l'état, et refuse `STALE` quand l'élément attendu n'est plus à l'index. Le site ajoute /lier, l'entrée « Appareils liés » du propriétaire et `expected` sur retirer / déplacer / jouer maintenant.

**Tech Stack:** API : Flask 3.1.3, Flask-SocketIO 5.7.2 (python-socketio 5.18.1, `async_mode="threading"`), flask-cors 6.0.5, redis-py 8.2.0, pytest. Bot : discord.py 2.7, `redis.asyncio`, pytest + pytest-asyncio. Site : Next.js 14.2 (App Router), React 18, TypeScript 5, zustand 4, `node:test` sous Node 24.19.

**Spec:** C:\Users\Paul\Documents\Codage\GregLeConsanguin\docs\superpowers\specs\2026-11-25-overlay-overwolf-design.md (§3 API, §4 bot, §5 site, §7 vérification ; §6 est le plan B, lié seulement par le contrat ci-dessous).

## Global Constraints

- **Branche** `feat/overlay-overwolf` (déjà suivie sur `origin`). Une seule PR vers `main` ; la fusion attend l'accord explicite de Paul (elle déploie sur Railway).
- **Git.** Aucune mention d'IA : ni `Co-Authored-By`, ni « Generated with », ni nom d'outil, dans les commits, la PR et les commentaires. Messages en français, style du dépôt (`feat(api): …`, `test(bot): …`). Toujours `git add <chemins explicites>`, jamais `git add -A` ni `git add .`.
- **Jamais commités :** `services/web/tsconfig.json` (modifié localement), `services/web/next-env.d.ts`, `.claude/`, `.serena/`, `.playwright-mcp/`, `CHANGELOG.md`, `assets.zip`, `services/GREG.zip`.
- **Fins de ligne.** `core.autocrlf=false`. Sont en CRLF et le restent : `services/api/api/routes/history.py`, `services/api/tests/conftest.py`. Les autres fichiers touchés sont en LF.
- **Commandes** (Git Bash, chemins absolus ; écrire la commande en entier à chaque étape, l'état du shell ne persiste pas) :
  - `[API]` = `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/api && uv run --no-project --python 3.12 --with-requirements requirements.txt --with pydantic-settings --with pytest python -m pytest -q` (suivi d'un chemin de test, ou `tests`). Base vérifiée le 2026-11-25 : `722 passed` en ~10 s.
  - `[BOT]` = `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/bot && uv run --no-project --python 3.12 --with-requirements requirements.txt --with pydantic-settings --with pytest --with pytest-asyncio python -m pytest -q` (suivi d'un chemin, ou `tests`). Base : `270 passed, 1 warning` (audioop) en ~50 s.
  - `[WEB]` = `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npm test` (base `pass 545`), puis `GREG_TEST_TRANSPILE=1 npm test` (base `pass 545`), puis `npx tsc --noEmit` (sortie vide, code 0).
  - Lint des fichiers Python **créés** : `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && uvx ruff check --select E4,E7,E9,F --ignore F811 <fichiers>` → `All checks passed!` (le reste du dépôt a déjà des alertes : ne pas les corriger ici).
- **API publique** `https://greg-api.up.railway.app/api/v1` ; préfixe `API_PREFIX = "/api/v1"`.
- **Codes.** `user_code` : 8 caractères de `BCDFGHJKLMNPQRSTVWXZ`, affiché `XXXX-XXXX`, saisie normalisée (majuscules, tout caractère non alphanumérique retiré). `device_code` : `secrets.token_urlsafe(32)`. Jeton : `"greg_ow_" + secrets.token_urlsafe(32)` (51 caractères), stocké seulement en `sha256` hexadécimal.
- **Durées.** Appareil 600 s, `interval` 5 s, `slow_down` +5 s ; jeton `OVERLAY_TOKEN_TTL_DAYS` (défaut 180, soit 15 552 000 s) ; `last_used_at` écrit au plus une fois par 300 s ; tous les horodatages en secondes epoch entières.
- **Limites de débit.** Démarrer : 5 par minute par IP, vérifiée **en premier** ; seules les requêtes qu'elle laisse passer comptent dans le plafond de 30 par heure au total (une IP seule ne peut donc pas bloquer la liaison de Paul). Autoriser : 5 par minute par uid. Dépassement : 429 `{ok:false, error:"RATE_LIMITED"}`. `POST /overlay/device` et `POST /overlay/token` exigent `request.is_json` (sinon 400 `INVALID_REQUEST`, aucun compteur touché) : un formulaire ou un `text/plain` venu d'une page tierce n'entame aucun seau ; l'appli (plan B) envoie du JSON aux deux.
- **Clés Redis.** `greg:overlay:device:{sha256(device_code)}` EX 600 ; `greg:overlay:user_code:{CODE}` EX 600 (SET NX) ; `greg:overlay:token:{sha256(jeton)}` EX ttl ; `greg:overlay:tokens:{uid}` HASH `tid → empreinte` ; `greg:ratelimit:{seau}:{sujet}` par `MULTI` · `INCR` · `EXPIRE … NX` · `EXEC` (un compteur a toujours une échéance ; `EXPIRE NX` demande Redis ≥ 7.0 : prod `redis:8.2.9` et local `redis:7-alpine`, vérifiés le 2026-11-25).
- **Propriétaire** = `settings.owner_id_int` (`GREG_OWNER_ID`). Valeur absente ou 0 : lookup et approve répondent toujours 403 `NOT_OWNER`.
- **Identité.** En-tête `Authorization` présent : il doit valoir `Bearer <jeton valide>`, sinon 401 `{ok:false, error:"NOT_AUTHENTICATED", message:"Connecte-toi avec Discord pour contrôler Greg."}`, sans repli sur le cookie. Sinon, la session. Les requêtes porteuses ne passent pas la garde CSRF. Sur les routes en session seule (`require_session_user` : chansonnier, `/overlay/device/lookup`, `/overlay/device/approve`), un en-tête `Authorization` présent donne toujours ce 401, cookie ou pas.
- **CSRF** (`csrf_ok`) : méthodes `GET/HEAD/OPTIONS` toujours admises ; sinon `request.is_json` obligatoire, puis `Origin` (s'il est présent) normalisé ∈ `WEB_ORIGINS`, sinon `Referer` (s'il est présent) normalisé ∈ `WEB_ORIGINS`, sinon admis. Échec : 403 `{ok:false, error:"CSRF_FAILED", message}`.
- **Origines.** `OVERLAY_ORIGINS` : liste séparée par des virgules, chaque entrée (espaces retirés, minuscules) doit vérifier `re.fullmatch(r"overwolf-extension://[a-z]{20,64}", s)`, sinon ignorée avec un avertissement. `app.config["WEB_ORIGINS"] = cors_origins()` ; `app.config["ALLOWED_ORIGINS"]` = site puis appli, utilisée par CORS et `cors_allowed_origins`. Origine attendue : `overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk`.
- **Socket.IO.** Le jeton voyage dans `auth: {token}` du paquet CONNECT ; jeton invalide → `connect_error` de message `"NOT_AUTHENTICATED"`. Aucun nouvel événement `overlay_*` ; l'appli utilise `join_guild`, `leave_guild`, `request_state`, `time_sync`.
- **`player_event`** `{guild_id, action, actor:{id, display_name}, title: string|null, at_ms}`, `action` ∈ `add skip stop pause resume remove move play_at repeat restart`, canal Redis `greg:player:event`, salle `guild:<id>`.
- **`expected`** `{url, added_by, ts}` sur `/queue/remove`, `DELETE /player/queue/<i>`, `/player/move`, `/playlist/play_at`. Différence → bot `{ok:false, error:"STALE"}` sans rien changer → API 409 `{ok:false, error:"STALE", message:"La file a bougé : réessayez."}`. Sans `expected` : comportement inchangé.
- **Durcissement 2026-09.** `tests/test_auth.py`, `test_cors.py`, `test_socketio.py`, `test_authz.py` restent verts ; on n'y fait que des ajouts. `library.py` reste en session seule (`require_session_user`). Jamais d'identité lue dans le corps ou `X-User-ID`.
- **Textes du site.** Tout nouveau texte va dans `EXTRA` de `services/web/src/theme/copy.extra.ts` (jamais dans `copy.v2.json`), typographie du deck imposée par `tests/copy-extra.test.mjs` : U+00A0 avant « : » et dans « », U+202F avant ; ! ?, apostrophe courbe ’ ; écrire `\u00a0` et `\u202f` en clair dans la source. Greg est le valet et vouvoie ; l'utilisateur est le Roi (« Sire ») ; jamais de couronne ni de sceau pour Greg.
- **Modules purs du site** (`src/lib/*.ts` testés) : aucun import à l'exécution (`import type` seulement), ni `enum` ni `namespace` ; leurs tests passent en natif et avec `GREG_TEST_TRANSPILE=1`.
- **Blocs de test.** Côté API, ils omettent les imports évidents : `pytest`, `redis`, `re`, `types`, `asyncio`, `threading`, `import api.services.overlay_tokens as ot`, `from api.services import authz`, `from greg_shared.config import settings`, et côté site `test`, `assert`, `loadTs`, `read`. Les fixtures importées d'un autre fichier de test sont citées, avec `# noqa: F401`. Côté bot, chaque fichier de test donne son en-tête d'imports en entier : `services/bot` n'a pas d'`asyncio_mode=auto` et pytest 9 fait échouer un `async def` non marqué, donc tout module de tests `async def` porte `pytestmark = pytest.mark.asyncio` (comme `test_playback.py`), et les tests synchrones vont dans un module à part.
- **Remplaçabilité.** `authz.py` et `events.py` appellent le magasin par le module (`ot.resolve`, `ot.is_live`), et `routes/overlay.py` appelle `send_command` par son nom de module : les tests les remplacent par `monkeypatch.setattr`.
- **Railway.** `GREG_OWNER_ID` (même valeur que le service BOT DISCORD) et `OVERLAY_ORIGINS` ne se règlent que sur le service API, et seulement après un « oui » explicite de Paul ; l'UID est d'abord confirmé dans `overwolf://packages`. Avant la fusion, les domaines publics du service WEB sont comparés à `WEB_URL` du service API (tâche 14) : la garde CSRF n'admet que `WEB_ORIGINS` = `cors_origins()` = `CORS_ORIGINS` ∪ `WEB_URL`, et le service API n'a pas de `CORS_ORIGINS`. Une origine du site absente se règle par `CORS_ORIGINS`, elle aussi après un « oui » de Paul. Lecture seule : noms de variables et domaines, jamais la valeur d'un secret (pas de `railway variable list --kv` ni de `--json` non filtré).

## Review Focus

Cinq cas que la spec implique sans qu'un test de tâche « normal » les couvre ; chacun est épinglé par un test dans la tâche qui possède le code.

1. **Redis indisponible pendant la vérification d'un jeton porteur** (HTTP ou CONNECT du socket) → 503 `STORAGE_UNAVAILABLE` ou `connect_error` `"STORAGE_UNAVAILABLE"`, jamais 401 `NOT_AUTHENTICATED` : l'appli efface son jeton sur un 401 (spec §6.3). Tests : tâche 4 `test_redis_down_on_bearer_is_503_never_401`, tâche 6 `test_redis_down_at_connect_is_storage_unavailable`.
2. **Jeton révoqué pendant qu'une requête l'utilise** : l'écriture de `last_used_at` ne doit pas recréer la clé supprimée (`SET … XX KEEPTTL`). Test : tâche 3 `test_last_used_write_never_recreates_a_revoked_token`.
3. **Sondage avec gigue** : l'appli sonde à 4,1 s pour un intervalle de 5 s → `authorization_pending`, pas `slow_down` (marge de 1 s) ; à 3,9 s → `slow_down`. Test : tâche 3 `test_poll_jitter_within_one_second_is_not_slow_down`.
4. **Id Discord au-delà de 2^53** (`1234567890123456789`) dans un tick, un `player_event` ou `user_guilds` → chaîne décimale exacte (un nombre JSON serait arrondi en JS et l'appli comparerait mal). Tests : tâche 7 `test_user_guilds_ids_are_exact_strings`, tâche 8 `test_publish_player_event_keeps_snowflake_as_string`, tâche 10 `test_tick_guild_id_keeps_snowflake_precision`.
5. **Code en attente sur le site** : le Roi se connecte, revient sur « / », est renvoyé vers /lier, puis revient sur « / » sans décider → pas de deuxième redirection (le code est consommé sur /lier dès que `getMe()` réussit, avant la branche `is_owner` : un connecté non propriétaire, ou un échec de `/overlay/me`, ne tourne pas en boucle entre « / » et /lier). Tests : tâche 11 `takePendingCode consomme le code`, tâche 12 `/lier consomme le code en attente au montage` et `/lier lit ?code= sans useSearchParams et prend le code avant la branche is_owner`.

## File Structure

API (`services/api`) :
- `api/services/authz.py` (modifié) : CSRF, `Identity`, `current_identity`, `current_user_id`, décorateurs `require_session_user` (avec CSRF), `require_identity`, `require_bearer`, `require_owner`, `is_owner`.
- `api/__init__.py` (modifié) : `overlay_origins()`, `WEB_ORIGINS` / `ALLOWED_ORIGINS`, enregistrement du blueprint overlay.
- `api/services/overlay_tokens.py` (créé) : magasin Redis des appareils, codes, jetons et limites de débit.
- `api/routes/overlay.py` (créé) : `/overlay/device`, `/device/lookup`, `/device/approve`, `/token`, `/me`, `/tokens`, `/tokens/revoke`, `/logout`, `/guilds`.
- `api/routes/auth.py` (modifié) : CSRF sur `/auth/logout`.
- `api/routes/player.py`, `api/routes/history.py`, `api/routes/search.py` (modifiés) : `require_identity`, `expected`, `STALE`, `limit` borné.
- `api/websocket/events.py` (modifié) : `on_connect(auth)`, registre `{tid: sids}`, revérification du jeton dans `_subscribe`, `disconnect_token`.
- `api/services/redis_listener.py` (modifié) : canal `greg:player:event`, `guild_id` dans les ticks.
- Tests créés : `tests/test_csrf.py`, `tests/overlay_fakes.py`, `tests/test_overlay_tokens.py`, `tests/test_identity.py`, `tests/test_overlay_routes.py`, `tests/test_overlay_socket.py`, `tests/test_player_event_relay.py`, `tests/test_queue_stale.py`. Modifiés : `tests/conftest.py`, `tests/test_cors.py`, `tests/test_library_routes.py`, `tests/test_search.py`, `tests/test_sync_relay.py`.

Bot (`services/bot`) :
- `bot/services/redis_bridge.py` (modifié) : action `user_guilds`, publication `greg:player:event`, transmission de `expected`, `STALE`.
- `bot/services/playlist_manager.py` (modifié) : `StaleQueueError`, `queue_item_matches`.
- `bot/services/player_service.py` (modifié) : `title_at`, `expected` dans `remove_at`, `move`, `play_at`.
- Tests créés : `tests/test_overlay_bot.py`, `tests/test_queue_expected.py` (modules `async`, `pytestmark = pytest.mark.asyncio`), `tests/test_queue_item_matches.py` (synchrone).

Site (`services/web`) :
- `src/lib/devices.ts` (créé, pur) : code, code en attente, serveur par défaut, erreurs de /lier.
- `src/lib/api.ts` (modifié) : `api.device*`, `expected` sur `queueRemove`, `move`, `playAt`.
- `src/theme/copy.extra.ts` (modifié) : section `devices`, `error.STALE`.
- `src/app/lier/page.tsx`, `src/components/Lier/lier.css` (créés) ; `src/app/globals.css` (import).
- `src/components/Header/AccountMenu.tsx`, `src/hooks/usePlayer.ts`, `src/lib/playerUtils.ts` (modifiés).
- Tests créés : `tests/devices.test.mjs`, `tests/lier-contract.test.mjs`, `tests/queue-expected.test.mjs`.

---

### Tâche 1 : garde CSRF sur les routes de session

**Files:**
- Modify : `services/api/api/services/authz.py` (l. 11-57)
- Modify : `services/api/api/__init__.py` (l. 87-90 : poser `app.config["WEB_ORIGINS"] = origins`, même liste que `ALLOWED_ORIGINS` dans cette tâche)
- Modify : `services/api/api/routes/auth.py` (l. 130-133)
- Modify : `services/api/tests/test_library_routes.py` (l. 531-532)
- Create : `services/api/tests/test_csrf.py`

**Interfaces:**
- Consumes : `api._normalize_origin(raw: str) -> Optional[str]` (`api/__init__.py:33`), importé dans la fonction pour éviter un import circulaire.
- Produces :
  - `authz.MSG_CSRF_FAILED: str = "Requête refusée : elle ne vient pas du site de Greg."`
  - `authz.SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})`
  - `authz.csrf_ok() -> bool` (règle des Global Constraints, lit `current_app.config["WEB_ORIGINS"]`)
  - `authz.csrf_failed() -> tuple[Response, int]` → 403 `{"ok": False, "error": "CSRF_FAILED", "message": MSG_CSRF_FAILED}`
  - `require_session_user(view)` : 401 sans session (inchangé), puis 403 si `request.method not in SAFE_METHODS and not csrf_ok()`.
  - `app.config["WEB_ORIGINS"]: list[str]`.

- [ ] **Étape 1 : écrire les tests qui échouent** dans `tests/test_csrf.py` :

```python
import pytest
from api.services.authz import MSG_CSRF_FAILED

BASE = "/api/v1"
EVIL = "https://evil.example"
CSRF_BODY = {"ok": False, "error": "CSRF_FAILED", "message": MSG_CSRF_FAILED}
# Formulaire tiers (guild_id dans l'URL) : passait avant le correctif (spec §3.2)
FORM_TARGETS = [("post", "/player/skip"), ("post", "/queue/skip"), ("post", "/player/stop"), ("post", "/queue/stop"),
                ("post", "/player/pause"), ("post", "/playlist/toggle_pause"), ("post", "/player/repeat"),
                ("post", "/playlist/repeat"), ("post", "/playlist/restart"), ("post", "/voice/join"),
                ("post", "/playlist/play_at"), ("post", "/queue/remove"), ("post", "/player/move"),
                ("delete", "/player/queue/0"), ("post", "/queue/add")]

@pytest.mark.parametrize("method,path", FORM_TARGETS)
def test_cross_site_form_is_refused_before_the_bot(logged_client, fake_send, method, path):
    r = getattr(logged_client, method)(f"{BASE}{path}?guild_id=5", data="src=1&dst=0&index=0&query=x",
                                       content_type="application/x-www-form-urlencoded", headers={"Origin": EVIL})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY
    assert fake_send.calls == []

def test_text_plain_body_is_refused_even_without_origin(logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/skip?guild_id=5", data='{"guild_id": "5"}', content_type="text/plain")
    assert r.status_code == 403 and fake_send.calls == []

@pytest.mark.parametrize("origin", [EVIL, "null", "https://greg-le-consanguin.up.railway.app.evil.example"])
def test_json_from_a_foreign_or_null_origin_is_refused(logged_client, fake_send, origin):
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Origin": origin})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY and fake_send.calls == []

def test_json_from_the_site_is_accepted(app, logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Origin": app.config["WEB_ORIGINS"][0]})
    assert r.status_code == 200 and fake_send.calls[-1]["action"] == "skip"

def test_json_without_origin_nor_referer_is_accepted(logged_client, fake_send):
    assert logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}).status_code == 200

def test_referer_is_checked_when_origin_is_absent(app, logged_client, fake_send):
    web = app.config["WEB_ORIGINS"][0]
    assert logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"},
                              headers={"Referer": f"{web}/lier?code=BCDF-GHJK"}).status_code == 200
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Referer": f"{EVIL}/page"})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY

def test_safe_methods_are_never_checked(logged_client, fake_send):
    fake_send.result = {"ok": True, "state": {"queue": []}}
    assert logged_client.get(f"{BASE}/playlist?guild_id=5", headers={"Origin": EVIL}).status_code == 200

def test_without_session_identity_still_comes_first(client, fake_send):
    r = client.post(f"{BASE}/player/skip?guild_id=5", data="a=1", content_type="application/x-www-form-urlencoded",
                    headers={"Origin": EVIL})
    assert r.status_code == 401 and r.get_json()["error"] == "NOT_AUTHENTICATED"

def test_logout_form_from_another_site_keeps_the_session(logged_client):
    r = logged_client.post(f"{BASE}/auth/logout", data="x=1", content_type="application/x-www-form-urlencoded",
                           headers={"Origin": EVIL})
    assert r.status_code == 403 and r.get_json() == CSRF_BODY
    with logged_client.session_transaction() as s:
        assert s["discord_user"]["id"] == "777"

def test_logout_json_from_the_site_clears_the_session(app, logged_client):
    r = logged_client.post(f"{BASE}/auth/logout", json={}, headers={"Origin": app.config["WEB_ORIGINS"][0]})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    with logged_client.session_transaction() as s:
        assert "discord_user" not in s

@pytest.mark.parametrize("method,ctype,headers,expected", [
    ("GET", None, {"Origin": EVIL}, True), ("OPTIONS", None, {"Origin": EVIL}, True),
    ("POST", "application/json", {}, True), ("POST", "application/json", {"Origin": "{web}"}, True),
    ("POST", "application/json", {"Origin": "{web}/"}, True), ("POST", "application/json", {"Origin": EVIL}, False),
    ("POST", "application/json", {"Origin": "null"}, False), ("POST", "text/plain", {}, False),
    ("POST", "application/x-www-form-urlencoded", {"Origin": "{web}"}, False),
    ("DELETE", "application/json", {"Referer": "{web}/x"}, True), ("PUT", "application/json", {"Referer": EVIL}, False),
])
def test_csrf_ok_rules(app, method, ctype, headers, expected):
    from api.services.authz import csrf_ok
    web = app.config["WEB_ORIGINS"][0]
    hdrs = {k: v.replace("{web}", web) for k, v in headers.items()}
    with app.test_request_context("/", method=method, content_type=ctype, data="{}" if ctype else None, headers=hdrs):
        assert csrf_ok() is expected
```

  Puis dans `tests/test_library_routes.py`, l. 531-532 : la ligne qui envoie `data="track=x"` en `application/x-www-form-urlencoded` attend désormais `err(…, 403, "CSRF_FAILED")` au lieu de `400, "INVALID_REQUEST"` (les deux autres lignes ne changent pas ; `fr.log == []` reste vrai).
- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_csrf.py tests/test_library_routes.py` → `ImportError: cannot import name 'MSG_CSRF_FAILED'`, puis, une fois la constante ajoutée seule, `assert 200 == 403` sur les formulaires.
- [ ] **Étape 3 : implémenter.** Dans `authz.py` : `MSG_CSRF_FAILED`, `SAFE_METHODS`, `csrf_ok()`, `csrf_failed()`, et la garde dans `require_session_user` (après le 401). Dans `__init__.py` : `app.config["WEB_ORIGINS"] = origins` à côté de `ALLOWED_ORIGINS`. Dans `auth.py` `logout()` : `if not csrf_ok(): return csrf_failed()` avant `session.clear()`.
- [ ] **Étape 4 : les voir passer.** `[API] tests/test_csrf.py tests/test_library_routes.py` → tout vert. Puis `[API] tests` → `722 + nouveaux passed`, 0 failed (les quatre gardes 2026-09 comprises).
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/services/authz.py services/api/api/__init__.py services/api/api/routes/auth.py services/api/tests/test_csrf.py services/api/tests/test_library_routes.py && git commit -m "fix(api): garde CSRF sur les routes de session et la déconnexion (JSON et origine du site)"`

---

### Tâche 2 : origines de l'appli (site seul / site + appli)

**Files:**
- Modify : `services/api/api/__init__.py` (après `cors_origins`, l. 65 ; `create_app` l. 84-98)
- Modify : `services/api/tests/conftest.py` (CRLF ; constante après l. 39, fixture `app` l. 23-30)
- Modify : `services/api/tests/test_cors.py` (ajouts en fin de fichier)

**Interfaces:**
- Consumes : `cors_origins() -> List[str]`, `csrf_ok()` (tâche 1).
- Produces :
  - `api.OVERLAY_ORIGIN_RE = re.compile(r"overwolf-extension://[a-z]{20,64}")`
  - `api.overlay_origins() -> List[str]` : `OVERLAY_ORIGINS` découpée par virgules, chaque entrée `strip().lower()` puis `fullmatch`, doublons retirés, entrées invalides journalisées (`log.warning`) et ignorées ; vide si non définie.
  - `app.config["WEB_ORIGINS"] = cors_origins()` ; `app.config["ALLOWED_ORIGINS"] = web + [o for o in overlay if o not in web]`, passée à `CORS(...)` et à `socketio.init_app(cors_allowed_origins=...)`.
  - `conftest.OVERLAY_ORIGIN = "overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk"`, posée dans `os.environ["OVERLAY_ORIGINS"]` par la fixture `app` juste avant `create_app()`.

- [ ] **Étape 1 : écrire les tests qui échouent** (fin de `tests/test_cors.py`) :

```python
from conftest import OVERLAY_ORIGIN

def test_overlay_origins_unset_is_empty(monkeypatch):
    monkeypatch.delenv("OVERLAY_ORIGINS", raising=False)
    assert api.overlay_origins() == []

def test_overlay_origins_keeps_exact_uids_once(monkeypatch):
    monkeypatch.setenv("OVERLAY_ORIGINS", f" {OVERLAY_ORIGIN} ,overwolf-extension://AHNFLFBOHHIMDMOEOOGPIOHDMJDOKIIOLEIALAGK")
    assert api.overlay_origins() == [OVERLAY_ORIGIN]

@pytest.mark.parametrize("bad", ["*", "overwolf-extension://*", "overwolf-extension://abc", f"{OVERLAY_ORIGIN}/",
    f"{OVERLAY_ORIGIN}/x", f"{OVERLAY_ORIGIN}:80", "overwolf-extension://ahnflfbohhimdmoeoogp.*",
    "overwolf-extension://" + "a" * 65, "https://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk",
    "chrome-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk", "null"])
def test_overlay_origins_rejects_wildcards_paths_and_regex(monkeypatch, bad):
    monkeypatch.setenv("OVERLAY_ORIGINS", bad)
    assert api.overlay_origins() == []

def test_app_splits_site_and_overlay_origins(app):
    assert OVERLAY_ORIGIN not in app.config["WEB_ORIGINS"]
    assert app.config["ALLOWED_ORIGINS"] == app.config["WEB_ORIGINS"] + [OVERLAY_ORIGIN]
    assert socketio.server.eio.cors_allowed_origins == app.config["ALLOWED_ORIGINS"]

def test_overlay_preflight_allows_authorization(client, fake_send):
    r = client.options(f"{BASE}/queue/add", headers={"Origin": OVERLAY_ORIGIN, "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "authorization, content-type"})
    assert 200 <= r.status_code < 300 and r.headers.get("Access-Control-Allow-Origin") == OVERLAY_ORIGIN
    assert "authorization" in r.headers.get("Access-Control-Allow-Headers", "").lower()
    assert fake_send.calls == []

def test_socketio_handshake_accepts_overlay_origin(client):
    r = client.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": OVERLAY_ORIGIN})
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == OVERLAY_ORIGIN

def test_overlay_origin_never_passes_the_csrf_gate(logged_client, fake_send):
    r = logged_client.post(f"{BASE}/player/skip", json={"guild_id": "5"}, headers={"Origin": OVERLAY_ORIGIN})
    assert r.status_code == 403 and r.get_json()["error"] == "CSRF_FAILED" and fake_send.calls == []
```

- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_cors.py` → `ImportError: cannot import name 'OVERLAY_ORIGIN' from 'conftest'`, puis `AttributeError: module 'api' has no attribute 'overlay_origins'`.
- [ ] **Étape 3 : implémenter.** `OVERLAY_ORIGIN` et l'`os.environ` dans `conftest.py` (garder le CRLF). `OVERLAY_ORIGIN_RE`, `overlay_origins()` et les deux listes dans `api/__init__.py` ; le `log.info` cite les deux listes.
- [ ] **Étape 4 : les voir passer.** `[API] tests/test_cors.py tests/test_csrf.py` → tout vert ; `[API] tests` → 0 failed.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/__init__.py services/api/tests/conftest.py services/api/tests/test_cors.py && git commit -m "feat(api): OVERLAY_ORIGINS strictes, origines du site séparées de celles de l'appli"`

---

### Tâche 3 : magasin Redis `overlay_tokens`

**Files:**
- Create : `services/api/api/services/overlay_tokens.py`
- Create : `services/api/tests/overlay_fakes.py`
- Create : `services/api/tests/test_overlay_tokens.py`

**Interfaces:**
- Consumes : `greg_shared.config.settings.redis_url` ; le modèle de client de `library_store._build_client` (timeouts 3 s / 5 s, `Retry(NoBackoff(), 1)`).
- Produces (module `api.services.overlay_tokens`, importé `as ot`) :
  - Constantes : `DEVICE_TTL_S = 600`, `POLL_INTERVAL_S = 5`, `SLOW_DOWN_STEP_S = 5`, `SLOW_DOWN_GRACE_S = 1`, `LAST_USED_EVERY_S = 300`, `DEFAULT_TOKEN_TTL_DAYS = 180`, `USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"`, `USER_CODE_LEN = 8`, `MAX_CODE_TRIES = 5`, `MAX_TRIES = 3` (WATCH), `TOKEN_PREFIX = "greg_ow_"`, `CLIENT_NAME_MAX = 40`, `MSG_STORAGE_UNAVAILABLE = "Impossible de vérifier l'appareil pour le moment, réessayez dans un instant."`.
  - `class OverlayError(Exception)` : `code: str`, `status: int`, `body() -> dict` = `{"ok": False, "error": code}` (+ `"message": MSG_STORAGE_UNAVAILABLE` pour `STORAGE_UNAVAILABLE`). Codes : `CODE_EXPIRED` 404, `ALREADY_USED` 409, `STORAGE_UNAVAILABLE` 503.
  - `@dataclass(frozen=True) DeviceStart(device_code: str, user_code: str, expires_in: int, interval: int)` (`user_code` au format `XXXX-XXXX`).
  - `@dataclass(frozen=True) TokenRecord(tid: str, uid: int, label: str, created_at: int, last_used_at: int, expires_at: int, user: dict, default_guild_id: Optional[str], token_hash: str)` avec `public() -> dict` = `{id, label, created_at, last_used_at, expires_at}`.
  - `@dataclass(frozen=True) Minted(access_token: str, record: TokenRecord, expires_in: int)`.
  - `_now() -> float` (= `time.time()`, remplacée dans les tests), `_get_redis() -> redis.Redis`, `_draw_user_code() -> str` (8 tirages `secrets.choice`).
  - `hash_secret(s: str) -> str` (sha256 hex) ; `token_ttl_s() -> int` (`OVERLAY_TOKEN_TTL_DAYS` entier ≥ 1, sinon 180, × 86 400) ; `normalize_user_code(raw: object) -> Optional[str]` ; `format_user_code(code: str) -> str`.
  - `start_device(client_name: str) -> DeviceStart` : SET NX de l'index (nouveau tirage sur collision, au plus `MAX_CODE_TRIES`, sinon `STORAGE_UNAVAILABLE`), puis l'enregistrement `{user_code, status:"pending", client_name, created_at, interval:5, last_poll_at:None}` EX 600.
  - `lookup_user_code(code: str) -> Optional[dict]` → `{"client_name", "created_at", "expires_in"}` (`expires_in` = TTL restant de l'appareil), `None` si inconnu, consommé ou expiré.
  - `decide(code: str, *, approve: bool, uid: int, user: dict, guild_id: Optional[str]) -> None` : usage unique par `SET greg:overlay:user_code:{CODE} "used" XX GET KEEPTTL` (ancienne valeur `None` → `CODE_EXPIRED`, `"used"` → `ALREADY_USED`), puis mise à jour de l'appareil sous WATCH/MULTI (`status` `approved` ou `denied`, `uid`, `user`, `guild_id`, `SET … XX KEEPTTL`).
  - `poll(device_code: str) -> Union[Minted, str]` : chaînes RFC 8628 `"authorization_pending"`, `"slow_down"`, `"access_denied"`, `"expired_token"`. Tout passe sous WATCH de la clé de l'appareil. En attente : `slow_down` si `last_poll_at` existe et `now - last_poll_at < interval - SLOW_DOWN_GRACE_S` (alors `interval += 5`) ; `last_poll_at = now` dans les deux cas. Refusé : DEL puis `access_denied`. Autorisé : dans un seul MULTI, DEL de l'appareil, SET `greg:overlay:token:{h}` EX ttl et HSET `greg:overlay:tokens:{uid}` `tid → h` (`tid = secrets.token_hex(8)`, `label = client_name`, `last_used_at = created_at = now`). Une WatchError relit (au plus `MAX_TRIES`) : un second sondage concurrent trouve l'appareil supprimé → `expired_token`.
  - `resolve(token: str) -> Optional[TokenRecord]` : `None` si le préfixe manque ou si la clé est absente ; `last_used_at` réécrit par `SET … XX KEEPTTL` seulement si `now - last_used_at >= 300`.
  - `is_live(uid: int, tid: str) -> bool` : HGET puis EXISTS.
  - `list_tokens(uid: int) -> list[TokenRecord]` : du plus récent au plus ancien ; les entrées dont la clé a expiré sont retirées du HASH (HDEL).
  - `revoke(uid: int, tid: str) -> bool` : HGET `tid` ; absent → `False` ; sinon DEL de la clé et HDEL dans un MULTI → `True`.
  - `hit_rate_limit(bucket: str, subject: str, limit: int, window_s: int) -> bool` : un seul `pipeline(transaction=True)` = `MULTI` · `INCR greg:ratelimit:{bucket}:{subject}` · `EXPIRE … window_s NX` · `EXEC` (redis-py 8.2.0 : `pipe.incr(k)`, `pipe.expire(k, window_s, nx=True)`, puis `pipe.execute()`) ; `True` si le compte dépasse `limit`. Jamais d'INCR puis d'EXPIRE séparés : une coupure entre les deux laisserait un compteur sans échéance, donc un 429 permanent sur le seau global. `NX` ne prolonge jamais la fenêtre en cours et rattrape un compteur resté sans TTL.
  - Toute `redis.RedisError` / `OSError` / `ValueError` de construction → `OverlayError("STORAGE_UNAVAILABLE", 503)`, détail seulement dans les journaux.
- `tests/overlay_fakes.py` :
  - `FakeOverlayRedis` : Redis en mémoire avec une horloge `now: float` (expiration évaluée à chaque accès), et les commandes `get`, `set(name, value, ex=None, nx=False, xx=False, get=False, keepttl=False)`, `delete(*names)`, `exists(*names)`, `ttl(name)` (entier ; `-1` sans échéance, `-2` absente), `hget`, `hset(name, key, value)`, `hgetall`, `hdel(name, *keys)`, `incr(name)` (valeur gardée en texte décimal, comme `decode_responses=True`), `expire(name, time, nx=False)` (avec `nx=True`, ne pose l'échéance que si la clé n'en a pas), `pipeline(transaction=True)`. Le pipeline offre `watch`, `get`, `hget`, `multi`, `set`, `delete`, `hset`, `hdel`, `incr`, `expire(name, time, nx=False)`, `execute`, `reset` et le gestionnaire de contexte ; hors `watch`, chaque commande est mise en file et jouée d'un bloc par `execute` (rendu : la liste des résultats), comme redis-py ; `execute` lève `redis.WatchError` si une clé surveillée a changé de version. Attributs : `kv` (valeurs texte stockées, chaînes et HASH), `fail` (exception levée par toute commande), `interleave` (liste d'appels joués avant le prochain EXEC, un par EXEC, comme le faux du chansonnier), `on_get` (appel `(key)` après chaque GET hors transaction), `log`.
  - Fixture `overlay_redis(monkeypatch) -> FakeOverlayRedis` : `now = 1_800_000_000.0`, branchée sur `ot._get_redis` et `ot._now`.
  - Fixture `issue_token(overlay_redis)` → `issue(uid=777, guild_id="42", label="GregLC") -> str` : `start_device`, `decide(approve=True, user={"id": str(uid), "username": f"user{uid}", "global_name": None, "avatar": None})`, `now += 5`, `poll` → `access_token`.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/test_overlay_tokens.py`, avec `from overlay_fakes import overlay_redis, issue_token  # noqa: F401` et `T0 = 1_800_000_000`) :

```python
DEV = "greg:overlay:device:"; IDX = "greg:overlay:user_code:"; TOK = "greg:overlay:token:"; TOKS = "greg:overlay:tokens:"
USER = {"id": "777", "username": "paul", "global_name": "Paul", "avatar": None}

def _approved(fr, guild_id="42"):
    d = ot.start_device("GregLC"); ot.poll(d.device_code); fr.now += 5
    ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=guild_id)
    return d

def test_start_device_shape_and_ttls(overlay_redis):
    d = ot.start_device("GregLC")
    assert re.fullmatch(r"[BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}", d.user_code)
    assert (d.expires_in, d.interval) == (600, 5) and len(d.device_code) >= 43
    assert overlay_redis.ttl(DEV + ot.hash_secret(d.device_code)) == 600
    assert overlay_redis.ttl(IDX + d.user_code.replace("-", "")) == 600
    assert d.device_code not in repr(overlay_redis.kv)          # jamais en clair

@pytest.mark.parametrize("raw,code", [("bcdf-ghjk", "BCDFGHJK"), ("BCDF GHJK", "BCDFGHJK"), (" bcdfghjk ", "BCDFGHJK"),
    ("BCDF—GHJK", "BCDFGHJK"), ("BCDF-GHJ", None), ("BCDF-GHJA", None), ("", None), (None, None), (12345678, None)])
def test_normalize_user_code(raw, code):
    assert ot.normalize_user_code(raw) == code

def test_user_code_collision_draws_another(overlay_redis, monkeypatch):
    overlay_redis.set(IDX + "BCDFGHJK", "x", ex=600)
    draws = iter(["BCDFGHJK", "BCDFGHJL"]); monkeypatch.setattr(ot, "_draw_user_code", lambda: next(draws))
    assert ot.start_device("GregLC").user_code == "BCDF-GHJL"

def test_lookup_returns_name_age_and_remaining_time(overlay_redis):
    d = ot.start_device("GregLC"); overlay_redis.now += 100
    assert ot.lookup_user_code(d.user_code.lower()) == {"client_name": "GregLC", "created_at": T0, "expires_in": 500}
    assert ot.lookup_user_code("BCDF-GHJK") is None

def test_full_flow_mints_one_bearer_token(overlay_redis):
    d = ot.start_device("GregLC")
    assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 5; ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id="42"); overlay_redis.now += 5
    m = ot.poll(d.device_code)
    assert isinstance(m, ot.Minted) and m.access_token.startswith("greg_ow_") and len(m.access_token) == 51
    assert (m.record.uid, m.record.default_guild_id, m.record.user, m.record.label) == (777, "42", USER, "GregLC")
    assert m.expires_in == 15_552_000 and overlay_redis.ttl(TOK + ot.hash_secret(m.access_token)) == 15_552_000
    assert overlay_redis.hgetall(TOKS + "777") == {m.record.tid: ot.hash_secret(m.access_token)}
    assert m.access_token not in repr(overlay_redis.kv) and not overlay_redis.exists(DEV + ot.hash_secret(d.device_code))
    assert ot.poll(d.device_code) == "expired_token" and ot.lookup_user_code(d.user_code) is None

def test_concurrent_polls_mint_exactly_one_token(overlay_redis):
    d = _approved(overlay_redis); overlay_redis.now += 5
    other = []; overlay_redis.interleave.append(lambda: other.append(ot.poll(d.device_code)))
    first = ot.poll(d.device_code)
    assert sorted(type(x).__name__ for x in (first, other[0])) == ["Minted", "str"]
    assert len(overlay_redis.hgetall(TOKS + "777")) == 1

def test_poll_never_overwrites_a_concurrent_approval(overlay_redis):
    d = ot.start_device("GregLC"); overlay_redis.now += 5
    overlay_redis.interleave.append(lambda: ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=None))
    assert isinstance(ot.poll(d.device_code), ot.Minted)

def test_poll_faster_than_interval_is_slow_down_and_adds_5s(overlay_redis):
    d = ot.start_device("GregLC"); assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 2; assert ot.poll(d.device_code) == "slow_down"        # intervalle passé à 10 s
    overlay_redis.now += 9.5; assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 5; assert ot.poll(d.device_code) == "slow_down"        # resté à 10 s, passe à 15 s

def test_poll_jitter_within_one_second_is_not_slow_down(overlay_redis):          # Review Focus 3
    d = ot.start_device("GregLC"); ot.poll(d.device_code)
    overlay_redis.now += 4.1; assert ot.poll(d.device_code) == "authorization_pending"
    overlay_redis.now += 3.9; assert ot.poll(d.device_code) == "slow_down"

def test_denied_is_access_denied_once(overlay_redis):
    d = ot.start_device("GregLC"); ot.decide(d.user_code, approve=False, uid=777, user=USER, guild_id=None)
    assert ot.poll(d.device_code) == "access_denied"; overlay_redis.now += 5
    assert ot.poll(d.device_code) == "expired_token"

def test_expired_device_and_unknown_code(overlay_redis):
    d = ot.start_device("GregLC"); overlay_redis.now += 601
    assert ot.poll(d.device_code) == "expired_token" and ot.poll("inconnu") == "expired_token"
    with pytest.raises(ot.OverlayError) as e:
        ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=None)
    assert (e.value.code, e.value.status) == ("CODE_EXPIRED", 404)

def test_code_is_single_use(overlay_redis):
    d = ot.start_device("GregLC"); ot.decide(d.user_code, approve=True, uid=777, user=USER, guild_id=None)
    for approve in (True, False):
        with pytest.raises(ot.OverlayError) as e:
            ot.decide(d.user_code, approve=approve, uid=777, user=USER, guild_id=None)
        assert (e.value.code, e.value.status) == ("ALREADY_USED", 409)

def test_resolve_updates_last_used_at_at_most_every_5_min(overlay_redis, issue_token):
    tok = issue_token(); minted_at = int(overlay_redis.now)
    overlay_redis.now += 10; assert ot.resolve(tok).last_used_at == minted_at
    overlay_redis.now += 300; assert ot.resolve(tok).last_used_at == int(overlay_redis.now)
    assert overlay_redis.ttl(TOK + ot.hash_secret(tok)) == 15_552_000 - 310        # TTL gardé

@pytest.mark.parametrize("bad", ["", "greg_ow_inconnu", "Bearer greg_ow_x", "x" * 51])
def test_resolve_rejects_unknown_and_malformed(overlay_redis, bad):
    assert ot.resolve(bad) is None

def test_last_used_write_never_recreates_a_revoked_token(overlay_redis, issue_token):  # Review Focus 2
    tok = issue_token(); key = TOK + ot.hash_secret(tok); overlay_redis.now += 301
    overlay_redis.on_get = lambda k: overlay_redis.delete(k) if k == key else None
    ot.resolve(tok)
    assert not overlay_redis.exists(key)

def test_list_revoke_and_is_live(overlay_redis, issue_token):
    a = ot.resolve(issue_token()); overlay_redis.now += 1; b = ot.resolve(issue_token())
    assert [r.tid for r in ot.list_tokens(777)] == [b.tid, a.tid]
    assert set(a.public()) == {"id", "label", "created_at", "last_used_at", "expires_at"}
    assert ot.revoke(888, a.tid) is False and ot.is_live(777, a.tid)
    assert ot.revoke(777, a.tid) is True and not ot.is_live(777, a.tid)
    assert not overlay_redis.exists(TOK + a.token_hash) and a.tid not in overlay_redis.hgetall(TOKS + "777")
    overlay_redis.delete(TOK + b.token_hash)                                       # expiré
    assert ot.list_tokens(777) == [] and overlay_redis.hgetall(TOKS + "777") == {}

def test_rate_limit_counts_per_window(overlay_redis):
    assert [ot.hit_rate_limit("approve", "777", 5, 60) for _ in range(6)] == [False] * 5 + [True]
    assert overlay_redis.ttl("greg:ratelimit:approve:777") == 60
    overlay_redis.now += 61; assert ot.hit_rate_limit("approve", "777", 5, 60) is False

def test_rate_limit_counter_always_gets_an_expiry(overlay_redis):
    key = "greg:ratelimit:device_start:all"
    overlay_redis.set(key, "40"); assert overlay_redis.ttl(key) == -1             # compteur resté sans échéance
    assert ot.hit_rate_limit("device_start", "all", 30, 3600) is True and overlay_redis.ttl(key) == 3600
    overlay_redis.now += 100; ot.hit_rate_limit("device_start", "all", 30, 3600)
    assert overlay_redis.ttl(key) == 3500                                          # NX : la fenêtre n'est jamais prolongée
    assert overlay_redis.get(key) == "42"

@pytest.mark.parametrize("call", [lambda: ot.start_device("x"), lambda: ot.lookup_user_code("BCDFGHJK"),
    lambda: ot.poll("d"), lambda: ot.resolve("greg_ow_" + "a" * 43), lambda: ot.list_tokens(777),
    lambda: ot.revoke(777, "t"), lambda: ot.is_live(777, "t"), lambda: ot.hit_rate_limit("b", "s", 1, 60),
    lambda: ot.decide("BCDFGHJK", approve=True, uid=777, user=USER, guild_id=None)])
def test_redis_down_is_storage_unavailable(overlay_redis, call):
    overlay_redis.fail = redis.ConnectionError("Error 111 connecting to redis:6379")
    with pytest.raises(ot.OverlayError) as e:
        call()
    assert e.value.status == 503 and e.value.body() == {"ok": False, "error": "STORAGE_UNAVAILABLE",
                                                        "message": ot.MSG_STORAGE_UNAVAILABLE}
    assert "redis" not in str(e.value.body()).lower()

@pytest.mark.parametrize("env,ttl", [(None, 15_552_000), ("30", 2_592_000), ("abc", 15_552_000), ("0", 15_552_000), ("-3", 15_552_000)])
def test_token_ttl_env(monkeypatch, env, ttl):
    if env is None: monkeypatch.delenv("OVERLAY_TOKEN_TTL_DAYS", raising=False)
    else: monkeypatch.setenv("OVERLAY_TOKEN_TTL_DAYS", env)
    assert ot.token_ttl_s() == ttl
```

- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_overlay_tokens.py` → `ModuleNotFoundError: No module named 'api.services.overlay_tokens'` (et `overlay_fakes` tant qu'il n'existe pas : écrire le faux d'abord, il fait partie des tests).
- [ ] **Étape 3 : implémenter** `overlay_tokens.py` selon les signatures ci-dessus. Chaque lecture-modification-écriture d'une clé d'appareil passe par `pipeline(transaction=True)` + `watch` + `multi`, comme `library_store` ; jamais de jeton ni de `device_code` en clair dans Redis ni dans les journaux.
- [ ] **Étape 4 : les voir passer.** `[API] tests/test_overlay_tokens.py` → tout vert ; `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && uvx ruff check --select E4,E7,E9,F --ignore F811 services/api/api/services/overlay_tokens.py services/api/tests/overlay_fakes.py services/api/tests/test_overlay_tokens.py` → `All checks passed!`.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/services/overlay_tokens.py services/api/tests/overlay_fakes.py services/api/tests/test_overlay_tokens.py && git commit -m "feat(api): magasin Redis des codes d'appareil et jetons de l'appli (usage unique, slow_down, révocation)"`

---

### Tâche 4 : identité « session ou porteur » sur le lecteur, l'historique et la recherche

**Files:**
- Modify : `services/api/api/services/authz.py` (après `session_user_id`, l. 33)
- Modify : `services/api/api/routes/player.py` (import l. 8, `_uid` l. 60-62, chaque `@require_session_user` l. 102-344 → `@require_identity`)
- Modify : `services/api/api/routes/history.py` (CRLF ; import l. 7, l. 24-47 : décorateurs et `session_user_id()` → `current_user_id()`)
- Modify : `services/api/api/routes/search.py` (l. 281-320 : `@require_identity` sur `/search/autocomplete`, `/autocomplete`, `/search/suggest` ; `limit` borné à 1..10 dans `_do_autocomplete` et `suggest`)
- Modify : `services/api/tests/test_search.py` (l. 55-71 : les trois tests prennent `logged_client` au lieu de `client`)
- Create : `services/api/tests/test_identity.py`

**Interfaces:**
- Consumes : `ot.resolve`, `ot.OverlayError`, `csrf_ok`, `csrf_failed`, `not_authenticated` (`authz.py:36`).
- Produces (dans `authz.py`) :
  - `@dataclass(frozen=True) Identity(uid: int, via: Literal["session", "overlay"], tid: Optional[str] = None)`
  - `current_identity() -> Optional[Identity]`. Contexte socket (`getattr(request, "sid", None)`) : `session["_ident"]` s'il est posé (`{"via": "overlay", "uid", "tid"}`), sinon la session ; l'en-tête `Authorization` y est ignoré et rien n'est mis en cache. Contexte HTTP : en-tête présent → il doit correspondre à `^Bearer (\S+)$` (schéma insensible à la casse) et `ot.resolve` doit rendre un enregistrement, sinon `None` ; en-tête absent → la session. Résultat mis en cache dans `flask.g._greg_identity`. `ot.OverlayError` remonte telle quelle.
  - `current_user_id() -> Optional[int]`
  - `require_identity(view)` : `OverlayError` → `jsonify(e.body()), e.status` ; `None` → `not_authenticated()` ; `via == "session"` et méthode non sûre et `not csrf_ok()` → `csrf_failed()`.
  - `require_session_user(view)` (modifié) : `"Authorization" in request.headers` → `not_authenticated()` (401), avant le test de session et la garde CSRF de la tâche 1. Le contrat « `Authorization` présent ⇒ porteur valide, sans repli sur le cookie » vaut aussi pour les routes en session seule, qui n'acceptent jamais de porteur.
  - `search.SEARCH_LIMIT_MAX = 10`.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/test_identity.py`) :

```python
from overlay_fakes import overlay_redis, issue_token  # noqa: F401
from test_authz import GUILD_ROUTES, NOT_AUTHENTICATED_BODY, _IDS, _call
import api.routes.search as search_mod

BASE = "/api/v1"
def bearer(tok): return {"Authorization": f"Bearer {tok}"}

@pytest.mark.parametrize("method,path,body", GUILD_ROUTES, ids=_IDS)
def test_every_guild_route_accepts_a_bearer(client, fake_send, issue_token, method, path, body):
    fake_send.result = {"ok": True, "state": {"current": None, "queue": []}}
    _call(client, method, path, body, headers=bearer(issue_token(uid=4242)))
    assert fake_send.calls and all(c["user_id"] == 4242 for c in fake_send.calls)

def test_bearer_wins_over_the_cookie(logged_client, fake_send, issue_token):
    logged_client.post(f"{BASE}/queue/skip", json={"guild_id": "5"}, headers=bearer(issue_token(uid=4242)))
    assert fake_send.calls[-1]["user_id"] == 4242

@pytest.mark.parametrize("value", ["Bearer greg_ow_nope", "Bearer ", "Basic abc", "bearer", "Token greg_ow_x", ""])
def test_bad_authorization_never_falls_back_to_the_cookie(logged_client, fake_send, overlay_redis, value):
    r = logged_client.post(f"{BASE}/queue/skip", json={"guild_id": "5"}, headers={"Authorization": value})
    assert r.status_code == 401 and r.get_json() == NOT_AUTHENTICATED_BODY and fake_send.calls == []

def test_bearer_requests_skip_csrf(client, fake_send, issue_token):
    r = client.post(f"{BASE}/queue/skip", json={"guild_id": "5"},
                    headers={**bearer(issue_token()), "Origin": "https://evil.example"})
    assert r.status_code == 200

def test_revoked_token_is_401(client, fake_send, issue_token):
    tok = issue_token(); rec = ot.resolve(tok); ot.revoke(rec.uid, rec.tid)
    assert client.get(f"{BASE}/playlist?guild_id=5", headers=bearer(tok)).status_code == 401

def test_redis_down_on_bearer_is_503_never_401(client, fake_send, issue_token, overlay_redis):  # Review Focus 1
    tok = issue_token(); overlay_redis.fail = redis.ConnectionError("down")
    r = client.post(f"{BASE}/queue/skip", json={"guild_id": "5"}, headers=bearer(tok))
    assert r.status_code == 503 and r.get_json()["error"] == "STORAGE_UNAVAILABLE" and fake_send.calls == []

def test_identity_is_resolved_once_per_request(app, issue_token, monkeypatch):
    tok = issue_token(uid=4242); seen = []; real = ot.resolve
    monkeypatch.setattr(ot, "resolve", lambda t: seen.append(t) or real(t))
    with app.test_request_context("/", headers=bearer(tok)):
        assert authz.current_identity() == authz.current_identity()
        assert authz.current_identity().via == "overlay" and authz.current_user_id() == 4242
    assert len(seen) == 1

def test_search_requires_identity_and_clamps_limit(client, logged_client, issue_token, monkeypatch):
    limits = []
    monkeypatch.setattr(search_mod, "_innertube_search", lambda q, limit=8: limits.append(limit) or [{"title": "t"}])
    assert client.get(f"{BASE}/search/autocomplete?q=abba").status_code == 401
    assert client.get(f"{BASE}/search/suggest?q=abba").status_code == 401
    for lim in ("50", "0", "-4", "7"):
        assert client.get(f"{BASE}/search/autocomplete?q=abba&limit={lim}", headers=bearer(issue_token())).status_code == 200
    assert limits == [10, 1, 1, 7]

def test_library_stays_session_only(client, issue_token):
    assert client.get(f"{BASE}/library", headers=bearer(issue_token())).status_code == 401

def test_session_only_route_refuses_an_authorization_header_even_with_a_cookie(logged_client):
    r = logged_client.get(f"{BASE}/library", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401 and r.get_json() == NOT_AUTHENTICATED_BODY
```

  Dans `tests/test_search.py`, les trois tests (l. 55, 63, 70) prennent la fixture `logged_client` et l'utilisent à la place de `client`.
- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_identity.py tests/test_search.py` → `assert 401 == 200`-type échecs sur le porteur, `test_search_requires_identity…` en `assert 200 == 401`, `test_session_only_route_refuses…` tant que le cookie suffit encore (statut différent de 401).
- [ ] **Étape 3 : implémenter** `Identity`, `current_identity`, `current_user_id`, `require_identity`, et le refus de l'en-tête `Authorization` en tête de `require_session_user` ; remplacer les décorateurs et `_uid()` (= `current_user_id() or 0`) ; `limit = max(1, min(SEARCH_LIMIT_MAX, request.args.get("limit", 8, type=int)))` (6 par défaut pour `suggest`). `library.py` et `guilds.py` ne changent pas.
- [ ] **Étape 4 : les voir passer.** `[API] tests/test_identity.py tests/test_search.py tests/test_authz.py` → tout vert ; `[API] tests` → 0 failed.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/services/authz.py services/api/api/routes/player.py services/api/api/routes/history.py services/api/api/routes/search.py services/api/tests/test_search.py services/api/tests/test_identity.py && git commit -m "feat(api): identité par session ou jeton porteur pour le lecteur, l'historique et la recherche"`

---

### Tâche 5 : blueprint `/overlay/*`

**Files:**
- Create : `services/api/api/routes/overlay.py`
- Modify : `services/api/api/services/authz.py` (`is_owner`, `require_owner`, `require_bearer`)
- Modify : `services/api/api/__init__.py` (l. 100-115 : `from api.routes.overlay import bp as overlay_bp` et `app.register_blueprint(overlay_bp, url_prefix=API_PREFIX)`)
- Create : `services/api/tests/test_overlay_routes.py`

**Interfaces:**
- Consumes : tout `ot.*` (tâche 3), `require_identity`, `current_identity`, `Identity` (tâche 4), `require_session_user`, `csrf_ok` (tâche 1), `api.web_url()`, `api.services.bot_bridge.send_command`, `api.routes.player.error_status`.
- Produces :
  - `authz.is_owner(uid: Optional[int]) -> bool` (`settings.owner_id_int > 0 and uid == settings.owner_id_int`), `authz.require_owner(view)` (posé sous `require_session_user` ; 403 `{"ok": False, "error": "NOT_OWNER"}`), `authz.require_bearer(view)` (identité `via == "overlay"`, sinon 401 `not_authenticated()`).
  - `overlay.bp = Blueprint("overlay", __name__)`, `overlay.send_command` (importé, remplaçable en test), `DEFAULT_CLIENT_NAME = "Appli Overwolf"`, `RATE_START_GLOBAL = ("device_start", 30, 3600)`, `RATE_START_IP = ("device_start_ip", 5, 60)`, `RATE_APPROVE = ("approve", 5, 60)`, `_user_snapshot(discord_user: dict) -> dict` (`{id: str, username, global_name, avatar}`, valeurs absentes → `None`).
  - Routes (réponses exactes du contrat) :
    - `POST /overlay/device` (sans auth ; dans cet ordre : `request.is_json` faux → 400 `{"ok": False, "error": "INVALID_REQUEST"}` sans toucher Redis ; puis `RATE_START_IP` sur `request.remote_addr or "unknown"` (`ProxyFix(x_for=1)` le tire déjà de `X-Forwarded-For`) ; puis, seulement si la limite par IP passe, `RATE_START_GLOBAL` sur le sujet `"all"` : une requête refusée par IP ne compte jamais dans le plafond global ; puis `client_name` facultatif, chaîne ≤ 40 après `strip()`, sinon 400 `INVALID_REQUEST` ; vide → `DEFAULT_CLIENT_NAME`) → 200 `{ok, device_code, user_code, verification_uri: web_url()+"/lier", verification_uri_complete: web_url()+"/lier?code="+user_code, expires_in: 600, interval: 5}`.
    - `GET /overlay/device/lookup?user_code=` (`require_session_user`, `require_owner`) → 200 `{ok, client_name, created_at, expires_in}` ; format invalide 400 `INVALID_REQUEST` ; inconnu 404 `CODE_EXPIRED`.
    - `POST /overlay/device/approve` (`require_session_user` (CSRF compris), `require_owner`, puis limite `RATE_APPROVE` par uid, puis validation : `user_code` normalisable, `decision` ∈ {`approve`, `deny`}, `guild_id` absent ou `^[0-9]{1,20}$`, sinon 400 `INVALID_REQUEST`). Pour `approve` avec `guild_id`, appel de `send_command("user_guilds", 0, uid, timeout=5)` : échec → `error_status(res, 503)` ; serveur absent de `guilds` → 403 `NOT_GUILD_MEMBER`, **avant** de consommer le code. Puis `ot.decide(...)` avec `user=_user_snapshot(session["discord_user"])` → 200 `{"ok": True}`.
    - `POST /overlay/token {device_code}` (sans auth ; `request.is_json` faux → 400 `{"ok": False, "error": "INVALID_REQUEST"}` sans toucher Redis ; corps JSON dont `device_code` est absent, non textuel ou inconnu → `expired_token`) → 200 `{ok, access_token, token_type: "Bearer", expires_in, user, default_guild_id}` ou 400 `{"ok": False, "error": <code RFC 8628>}`.
    - `GET /overlay/me` (`require_identity`) → `{ok, via, user, default_guild_id, is_owner}` (session : `_user_snapshot(session["discord_user"])` et `default_guild_id: None`).
    - `GET /overlay/tokens` (`require_identity`) → `{ok, tokens: [r.public() | {"current": r.tid == ident.tid}]}`.
    - `POST /overlay/tokens/revoke {id}` (`require_identity`) : session → `is_owner` sinon 403 `NOT_OWNER` ; porteur → `id` doit valoir son `tid`, sinon 404 `{"ok": False, "error": "NOT_FOUND"}` ; `ot.revoke` faux → 404 `NOT_FOUND`.
    - `POST /overlay/logout` (`require_bearer`) → `ot.revoke(ident.uid, ident.tid)` → `{"ok": True}`.
    - `GET /overlay/guilds` (`require_identity`) → `send_command("user_guilds", 0, uid, timeout=5)` → `{"ok": True, "guilds": res["guilds"]}` ; échec → `jsonify(res), error_status(res, 503)`.
    - `OverlayError` → `jsonify(e.body()), e.status` partout ; `RATE_LIMITED` → 429 `{"ok": False, "error": "RATE_LIMITED"}`.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/test_overlay_routes.py`) :

```python
from conftest import FakeSendCommand
from overlay_fakes import overlay_redis, issue_token  # noqa: F401
import api.routes.overlay as overlay_mod
from api import web_url

BASE = "/api/v1"
GUILD42 = {"id": "42", "name": "Taverne", "icon_url": None, "greg_voice": None, "user_voice": None, "playing": False}

@pytest.fixture()
def owner(monkeypatch):
    monkeypatch.setattr(settings, "greg_owner_id", "777")

@pytest.fixture()
def bot(monkeypatch):
    fake = FakeSendCommand({"ok": True, "guilds": [GUILD42]}); monkeypatch.setattr(overlay_mod, "send_command", fake)
    return fake

def start(client, **body): return client.post(f"{BASE}/overlay/device", json=body).get_json()
def approve(c, code, **kw): return c.post(f"{BASE}/overlay/device/approve", json={"user_code": code, "decision": "approve", **kw})

def test_device_start_shape(client, overlay_redis):
    d = start(client, client_name="GregLC")
    assert set(d) == {"ok", "device_code", "user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval"}
    assert d["verification_uri"] == web_url() + "/lier"
    assert d["verification_uri_complete"] == web_url() + "/lier?code=" + d["user_code"]
    assert (d["expires_in"], d["interval"]) == (600, 5)

@pytest.mark.parametrize("name", ["x" * 41, 12, ["a"]])
def test_device_start_rejects_bad_names(client, overlay_redis, name):
    r = client.post(f"{BASE}/overlay/device", json={"client_name": name})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "INVALID_REQUEST"}

def test_device_start_rate_limits(client, overlay_redis):
    codes = [client.post(f"{BASE}/overlay/device", json={}).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    assert client.post(f"{BASE}/overlay/device", json={}).get_json() == {"ok": False, "error": "RATE_LIMITED"}
    total = [client.post(f"{BASE}/overlay/device", json={}, environ_base={"REMOTE_ADDR": f"10.0.0.{i}"}).status_code
             for i in range(30)]
    assert total == [200] * 25 + [429] * 5                       # plafond global de 30 par heure, dont 5 déjà pris ci-dessus

def test_one_ip_never_exhausts_the_global_bucket(client, overlay_redis):
    assert [client.post(f"{BASE}/overlay/device", json={}).status_code for _ in range(30)] == [200] * 5 + [429] * 25
    assert overlay_redis.get("greg:ratelimit:device_start:all") == "5"       # refusées par IP : jamais comptées
    assert client.post(f"{BASE}/overlay/device", json={}, environ_base={"REMOTE_ADDR": "10.9.9.9"}).status_code == 200

@pytest.mark.parametrize("path", ["/overlay/device", "/overlay/token"])
@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded"])
def test_device_and_token_require_json_before_any_counter(client, overlay_redis, path, ctype):
    r = client.post(f"{BASE}{path}", data='{"device_code": "x", "client_name": "x"}', content_type=ctype)
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "INVALID_REQUEST"}
    assert overlay_redis.kv == {}                                                # ni compteur greg:ratelimit:*, ni appareil

def test_lookup_is_owner_only(app, client, logged_client, login, owner, overlay_redis, monkeypatch):
    code = start(client, client_name="GregLC")["user_code"]
    body = logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}").get_json()
    assert body == {"ok": True, "client_name": "GregLC", "created_at": 1_800_000_000, "expires_in": 600}
    other = login(app.test_client(), 888)
    assert other.get(f"{BASE}/overlay/device/lookup?user_code={code}").get_json() == {"ok": False, "error": "NOT_OWNER"}
    assert app.test_client().get(f"{BASE}/overlay/device/lookup?user_code={code}").status_code == 401
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code=nope").status_code == 400
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code=BCDF-GHJK").get_json() == {"ok": False, "error": "CODE_EXPIRED"}
    monkeypatch.setattr(settings, "greg_owner_id", "")
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}").get_json() == {"ok": False, "error": "NOT_OWNER"}

def test_approve_then_token(client, logged_client, owner, bot, overlay_redis):
    d = start(client, client_name="GregLC")
    r = approve(logged_client, d["user_code"], guild_id="42", user_id="999", user={"id": "999"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert bot.calls == [{"action": "user_guilds", "guild_id": 0, "user_id": 777, "data": None, "timeout": 5}]
    overlay_redis.now += 5
    t = client.post(f"{BASE}/overlay/token", json={"device_code": d["device_code"]}).get_json()
    assert t["ok"] is True and t["token_type"] == "Bearer" and t["expires_in"] == 15_552_000
    assert t["access_token"].startswith("greg_ow_") and t["default_guild_id"] == "42"
    assert t["user"] == {"id": "777", "username": "greg-fan", "global_name": None, "avatar": None}   # jamais du corps

def test_approve_csrf_owner_and_guild_checks_keep_the_code(app, client, logged_client, login, owner, bot, overlay_redis):
    code = start(client)["user_code"]
    form = logged_client.post(f"{BASE}/overlay/device/approve", data=f"user_code={code}&decision=approve",
                              content_type="application/x-www-form-urlencoded", headers={"Origin": "https://evil.example"})
    assert form.status_code == 403 and form.get_json()["error"] == "CSRF_FAILED"
    assert approve(login(app.test_client(), 888), code).get_json() == {"ok": False, "error": "NOT_OWNER"}
    bot.result = {"ok": True, "guilds": []}
    assert approve(logged_client, code, guild_id="43").get_json()["error"] == "NOT_GUILD_MEMBER"
    assert logged_client.get(f"{BASE}/overlay/device/lookup?user_code={code}").status_code == 200   # pas consommé

@pytest.mark.parametrize("body", [{"user_code": "nope", "decision": "approve"}, {"user_code": "BCDF-GHJK", "decision": "oui"},
                                  {"user_code": "BCDF-GHJK", "decision": "approve", "guild_id": "abc"}])
def test_approve_invalid_bodies(logged_client, owner, bot, overlay_redis, body):
    r = logged_client.post(f"{BASE}/overlay/device/approve", json=body)
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "INVALID_REQUEST"}

def test_approve_expired_used_and_rate_limited(client, logged_client, owner, bot, overlay_redis):
    assert approve(logged_client, "BCDF-GHJK").status_code == 404
    code = start(client)["user_code"]
    assert approve(logged_client, code).status_code == 200
    r = approve(logged_client, code); assert r.status_code == 409 and r.get_json()["error"] == "ALREADY_USED"
    statuses = [approve(logged_client, "BCDF-GHJK").status_code for _ in range(4)]
    assert statuses[-1] == 429                                                    # 5 par minute et par uid

def test_deny_then_access_denied(client, logged_client, owner, overlay_redis):
    d = start(client)
    logged_client.post(f"{BASE}/overlay/device/approve", json={"user_code": d["user_code"], "decision": "deny"})
    r = client.post(f"{BASE}/overlay/token", json={"device_code": d["device_code"]})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "access_denied"}

def test_token_errors_follow_rfc8628(client, overlay_redis):
    d = start(client)
    poll = lambda body: client.post(f"{BASE}/overlay/token", json=body).get_json()["error"]
    assert poll({"device_code": d["device_code"]}) == "authorization_pending"
    assert poll({"device_code": d["device_code"]}) == "slow_down"
    assert poll({"device_code": "inconnu"}) == poll({}) == poll({"device_code": 5}) == "expired_token"

def test_me_tokens_revoke_and_logout(client, logged_client, owner, overlay_redis, issue_token):
    tok = issue_token(); h = {"Authorization": f"Bearer {tok}"}
    me = client.get(f"{BASE}/overlay/me", headers=h).get_json()
    assert (me["via"], me["default_guild_id"], me["is_owner"], me["user"]["id"]) == ("overlay", "42", True, "777")
    sme = logged_client.get(f"{BASE}/overlay/me").get_json()
    assert (sme["via"], sme["default_guild_id"], sme["is_owner"]) == ("session", None, True)
    [row] = client.get(f"{BASE}/overlay/tokens", headers=h).get_json()["tokens"]
    assert set(row) == {"id", "label", "created_at", "last_used_at", "expires_at", "current"} and row["current"] is True
    assert logged_client.get(f"{BASE}/overlay/tokens").get_json()["tokens"][0]["current"] is False
    assert client.post(f"{BASE}/overlay/tokens/revoke", json={"id": "autre"}, headers=h).status_code == 404
    form = logged_client.post(f"{BASE}/overlay/tokens/revoke", data=f"id={row['id']}",
                              content_type="application/x-www-form-urlencoded", headers={"Origin": "https://evil.example"})
    assert form.status_code == 403
    assert logged_client.post(f"{BASE}/overlay/tokens/revoke", json={"id": row["id"]}).get_json() == {"ok": True}
    assert client.get(f"{BASE}/overlay/me", headers=h).status_code == 401

def test_bearer_revokes_itself_and_logout(client, logged_client, overlay_redis, issue_token):
    a, b = issue_token(), issue_token()
    assert logged_client.post(f"{BASE}/overlay/logout", json={}).status_code == 401   # session seule : refusé
    assert client.post(f"{BASE}/overlay/logout", json={}, headers={"Authorization": f"Bearer {a}"}).get_json() == {"ok": True}
    assert client.get(f"{BASE}/overlay/me", headers={"Authorization": f"Bearer {a}"}).status_code == 401
    tid = ot.resolve(b).tid
    assert client.post(f"{BASE}/overlay/tokens/revoke", json={"id": tid},
                       headers={"Authorization": f"Bearer {b}"}).get_json() == {"ok": True}

def test_guilds_come_from_the_bot(client, bot, overlay_redis, issue_token):
    r = client.get(f"{BASE}/overlay/guilds", headers={"Authorization": f"Bearer {issue_token(uid=4242)}"})
    assert r.get_json() == {"ok": True, "guilds": [GUILD42]}
    assert bot.calls[-1] == {"action": "user_guilds", "guild_id": 0, "user_id": 4242, "data": None, "timeout": 5}
    bot.result = {"ok": False, "error": "BOT_OFFLINE", "message": "Greg est hors ligne."}
    assert client.get(f"{BASE}/overlay/guilds", headers={"Authorization": f"Bearer {issue_token()}"}).status_code == 503
```

- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_overlay_routes.py` → `ModuleNotFoundError: No module named 'api.routes.overlay'`.
- [ ] **Étape 3 : implémenter** `is_owner`, `require_owner`, `require_bearer` puis `routes/overlay.py` et son enregistrement. Le portrait vient toujours de `session["discord_user"]` ou de l'enregistrement du jeton, jamais du corps.
- [ ] **Étape 4 : les voir passer.** `[API] tests/test_overlay_routes.py` → tout vert ; `[API] tests` → 0 failed ; `uvx ruff check --select E4,E7,E9,F --ignore F811 services/api/api/routes/overlay.py services/api/tests/test_overlay_routes.py` → `All checks passed!`.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/routes/overlay.py services/api/api/services/authz.py services/api/api/__init__.py services/api/tests/test_overlay_routes.py && git commit -m "feat(api): parcours par code d'appareil /overlay (propriétaire seul), jetons listés et révocables"`

---

### Tâche 6 : Socket.IO à jeton

**Files:**
- Modify : `services/api/api/websocket/events.py` (imports l. 12-23, `_subscribe` l. 62-86, `on_connect` / `on_disconnect` l. 91-101, registre ajouté après l. 32)
- Modify : `services/api/api/routes/overlay.py` (révocation et logout appellent `disconnect_token`)
- Create : `services/api/tests/test_overlay_socket.py`

**Interfaces:**
- Consumes : `ot.resolve`, `ot.is_live`, `ot.OverlayError`, `current_identity` (tâche 4), routes de révocation (tâche 5).
- Produces (dans `events.py`) :
  - `on_connect(auth=None)` : `auth` dict avec la clé `"token"` → `ot.resolve` ; jeton non textuel ou invalide → `raise ConnectionRefusedError("NOT_AUTHENTICATED")` ; `OverlayError` → `raise ConnectionRefusedError("STORAGE_UNAVAILABLE")` ; valide → `session["_ident"] = {"via": "overlay", "uid": rec.uid, "tid": rec.tid}`, `register_token_sid(rec.tid, request.sid)`, `join_room(ROOM_AUTHENTICATED)`. Sans clé `"token"` : comportement actuel (session).
  - `_TOKEN_SIDS: dict[str, set[str]]`, `_SID_TOKEN: dict[str, str]` sous `_REGISTRY_LOCK = threading.Lock()` (non réentrant).
  - `register_token_sid(tid: str, sid: str) -> None`.
  - `forget_sid(sid: str) -> None` (appelée par `on_disconnect`) : sous le verrou, `tid = _SID_TOKEN.pop(sid, None)` puis, si `tid`, `discard` du sid dans `_TOKEN_SIDS.get(tid)` et retrait de la clé quand l'ensemble est vide ; une entrée absente n'est jamais une erreur.
  - `disconnect_token(tid: str) -> int` : sous le verrou, `sids = _TOKEN_SIDS.pop(tid, set())` et `_SID_TOKEN.pop(sid, None)` pour chacun ; **verrou relâché**, puis `socketio.server.disconnect(sid, namespace="/")` pour chaque sid de cette copie ; rend `len(sids)`. Raison : en mode `threading`, python-socketio 5.18.1 (`Server.disconnect` → `_trigger_event("disconnect", …)`) exécute `on_disconnect`, donc `forget_sid`, sur le fil appelant ; sous le verrou, cela interbloquerait, et parcourir l'ensemble vivant pendant que `forget_sid` le modifie lèverait `RuntimeError`.
  - `_subscribe(gid)` : `ident = current_identity()` ; absent → refus `NOT_AUTHENTICATED` actuel ; `via == "overlay"` → `ot.is_live(ident.uid, ident.tid)` avant `send_command` : faux → `_deny(gid, "NOT_AUTHENTICATED", MSG_NOT_AUTHENTICATED, False)`, `OverlayError` → `_deny(gid, "REDIS_UNAVAILABLE", _MSG_BRIDGE_ERROR, True)`.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/test_overlay_socket.py`, avec `FakeBot`, `fake_bot`, `_events` importés de `test_socketio`) :

```python
from flask_socketio import ConnectionRefusedError
from api import socketio
from api.services.redis_listener import CHANNEL_BOT_STATUS, _handle_message
from api.websocket import events
from overlay_fakes import overlay_redis, issue_token  # noqa: F401
from test_socketio import FakeBot, fake_bot, _events  # noqa: F401

def sock(app, tok, flask_client=None):
    return socketio.test_client(app, auth={"token": tok}, flask_test_client=flask_client)

def test_valid_token_connects_and_joins_its_guild(app, fake_bot, issue_token):
    c = sock(app, issue_token(uid=4242)); assert c.is_connected(); c.get_received()
    c.emit("join_guild", {"guild_id": "42"}); got = c.get_received()
    assert _events(got, "joined") and _events(got, "playlist_update")
    assert fake_bot.calls[-1]["user_id"] == 4242

def test_invalid_token_is_refused_even_with_a_cookie(app, login, overlay_redis):
    assert not sock(app, "greg_ow_nope").is_connected()
    assert not sock(app, "greg_ow_nope", login(app.test_client())).is_connected()
    assert not socketio.test_client(app, auth={"token": 5}).is_connected()

def test_refusal_message_is_not_authenticated(app, overlay_redis):
    with app.test_request_context("/"), pytest.raises(ConnectionRefusedError) as e:
        events.on_connect({"token": "greg_ow_nope"})
    assert e.value.error_args == {"message": "NOT_AUTHENTICATED"}

def test_redis_down_at_connect_is_storage_unavailable(app, overlay_redis, issue_token):   # Review Focus 1
    tok = issue_token(); overlay_redis.fail = redis.ConnectionError("down")
    with app.test_request_context("/"), pytest.raises(ConnectionRefusedError) as e:
        events.on_connect({"token": tok})
    assert e.value.error_args == {"message": "STORAGE_UNAVAILABLE"}

def test_token_socket_receives_bot_status(app, issue_token):
    c = sock(app, issue_token()); c.get_received()
    _handle_message(socketio, CHANNEL_BOT_STATUS, {"status": "ready", "guilds": []})
    assert _events(c.get_received(), "bot_status")

def test_revocation_disconnects_exactly_that_tokens_sockets(app, client, issue_token):
    a, b = issue_token(), issue_token()
    a1, a2, b1 = sock(app, a), sock(app, a), sock(app, b)
    r = client.post("/api/v1/overlay/tokens/revoke", json={"id": ot.resolve(a).tid}, headers={"Authorization": f"Bearer {a}"})
    assert r.status_code == 200
    assert (a1.is_connected(), a2.is_connected(), b1.is_connected()) == (False, False, True)

def test_logout_disconnects(app, client, issue_token):
    t = issue_token(); c = sock(app, t)
    client.post("/api/v1/overlay/logout", json={}, headers={"Authorization": f"Bearer {t}"})
    assert not c.is_connected()

def test_revoked_token_cannot_join_on_an_open_socket(app, fake_bot, issue_token):
    t = issue_token(); c = sock(app, t); c.get_received(); rec = ot.resolve(t)
    ot.revoke(rec.uid, rec.tid)                                    # sans déconnexion : la revérification joue
    c.emit("join_guild", {"guild_id": "42"}); got = c.get_received()
    assert not _events(got, "playlist_update") and fake_bot.calls == []
    assert _events(got, "guild_join_error")[0]["args"][0]["error"] == "NOT_AUTHENTICATED"

def test_disconnect_forgets_the_sid(app, issue_token):
    t = issue_token(); tid = ot.resolve(t).tid; c = sock(app, t)
    assert events._TOKEN_SIDS.get(tid); c.disconnect()
    assert not events._TOKEN_SIDS.get(tid) and tid not in events._SID_TOKEN.values()   # le registre est partagé entre tests

def test_disconnect_token_disconnects_outside_the_lock(app, issue_token):
    t = issue_token(); tid = ot.resolve(t).tid; c1, c2 = sock(app, t), sock(app, t)
    out = []; th = threading.Thread(target=lambda: out.append(events.disconnect_token(tid)), daemon=True)
    th.start(); th.join(5)
    assert not th.is_alive() and out == [2]          # on_disconnect → forget_sid sur ce même fil : pas d'interblocage
    assert (c1.is_connected(), c2.is_connected()) == (False, False)
    assert tid not in events._TOKEN_SIDS and tid not in events._SID_TOKEN.values()
    events.forget_sid("sid-inconnu")                 # entrée absente : sans erreur
    assert events.disconnect_token(tid) == 0

def test_auth_without_token_keeps_the_cookie_path(app, login, fake_bot, session_uid):
    c = socketio.test_client(app, auth={}, flask_test_client=login(app.test_client())); c.get_received()
    c.emit("join_guild", {"guild_id": "42"})
    assert _events(c.get_received(), "joined") and fake_bot.calls[-1]["user_id"] == session_uid
```

- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_overlay_socket.py` → `assert not True` (jeton invalide accepté), `AttributeError: … '_TOKEN_SIDS'`.
- [ ] **Étape 3 : implémenter** le registre (`disconnect_token` vide l'entrée sous le verrou et déconnecte hors du verrou), `on_connect(auth=None)`, `on_disconnect` → `forget_sid`, la revérification dans `_subscribe`, et l'appel `disconnect_token(tid)` après chaque `ot.revoke` réussi dans `routes/overlay.py` (import local `from api.websocket.events import disconnect_token`).
- [ ] **Étape 4 : les voir passer.** `[API] tests/test_overlay_socket.py tests/test_socketio.py tests/test_overlay_routes.py` → tout vert ; `[API] tests` → 0 failed.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/websocket/events.py services/api/api/routes/overlay.py services/api/tests/test_overlay_socket.py && git commit -m "feat(api): socket à jeton porteur (auth du CONNECT), révocation qui déconnecte"`

---

### Tâche 7 : bot, action `user_guilds`

**Files:**
- Modify : `services/bot/bot/services/redis_bridge.py` (`_READ_ONLY_ACTIONS` l. 69 ; branche dans `_handle_command` l. 376-472 ; méthode après `publish_bot_guilds` l. 523-534)
- Create : `services/bot/tests/test_overlay_bot.py`

**Interfaces:**
- Consumes : `self.bot.guilds`, `guild.get_member(uid)`, `guild.voice_client`, `member.voice.channel` (cache, intents `members` et `voice_states` déjà actifs).
- Produces :
  - `_READ_ONLY_ACTIONS = frozenset({"get_state", "get_history", "user_guilds"})`
  - `RedisBridge.user_guilds(self, user_id: int) -> list[dict]` : serveurs du cache où `get_member(user_id)` existe, triés par `name.casefold()`, chacun `{"id": str(g.id), "name": g.name, "icon_url": str(g.icon.url) | None, "greg_voice": {"id": str, "name"} | None, "user_voice": {"id": str, "name"} | None, "playing": bool(vc and (vc.is_playing() or vc.is_paused()))}` ; `user_id <= 0` → `[]`.
  - Branche `action == "user_guilds"` → `{"ok": True, "guilds": self.user_guilds(user_id)}`.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/test_overlay_bot.py`, `pytestmark = pytest.mark.asyncio` comme `test_redis_bridge.py`, donc toutes les fonctions de test en `async def` ; en-tête complet ci-dessous, les tâches 8 et 9 y ajoutent leurs imports à la place indiquée, dans l'ordre que `ruff` attend) :

```python
"""Appli Overwolf côté bot : user_guilds, greg:player:event, expected et STALE."""
from __future__ import annotations

import asyncio
import types

import pytest
from test_redis_bridge import MEMBER, _cmd, _make_bridge, _responses

pytestmark = pytest.mark.asyncio


def _vc(ch, playing=False, paused=False):
    return types.SimpleNamespace(channel=ch, is_playing=lambda: playing, is_paused=lambda: paused)

def _guild(gid, name, members=(MEMBER,), user_ch=None, vc=None, icon=None):
    m = types.SimpleNamespace(id=MEMBER, display_name="Kévin", voice=types.SimpleNamespace(channel=user_ch) if user_ch else None)
    return types.SimpleNamespace(id=gid, name=name, icon=icon, voice_client=vc,
                                 get_member=lambda uid: m if uid in members else None)

TAVERNE = types.SimpleNamespace(id=11, name="Taverne")

def _bridge_with(*guilds):
    b = _make_bridge(); b.bot._guilds = {g.id: g for g in guilds}; return b

async def test_user_guilds_lists_shared_guilds_with_voice_and_playing():
    b = _bridge_with(_guild(2, "zèbre"), _guild(1, "Abbaye", user_ch=TAVERNE, vc=_vc(TAVERNE, paused=True),
                     icon=types.SimpleNamespace(url="https://cdn.discordapp.com/icons/1/a.png")), _guild(3, "Autre", members=()))
    assert b.user_guilds(MEMBER) == [
        {"id": "1", "name": "Abbaye", "icon_url": "https://cdn.discordapp.com/icons/1/a.png",
         "greg_voice": {"id": "11", "name": "Taverne"}, "user_voice": {"id": "11", "name": "Taverne"}, "playing": True},
        {"id": "2", "name": "zèbre", "icon_url": None, "greg_voice": None, "user_voice": None, "playing": False}]
    assert b.user_guilds(0) == []

async def test_user_guilds_ids_are_exact_strings():                            # Review Focus 4
    b = _bridge_with(_guild(1234567890123456789, "Grand"))
    assert b.user_guilds(MEMBER)[0]["id"] == "1234567890123456789"

async def test_user_guilds_command_is_read_only_and_never_member_checked():
    b = _bridge_with(_guild(1, "Abbaye"))
    await asyncio.wait_for(b._dispatch(_cmd("user_guilds", gid=0, rid="u")), 1)
    assert _responses(b)["u"]["ok"] is True and _responses(b)["u"]["guilds"][0]["id"] == "1"
    assert b._cmd_locks == {} and b.bot.emits == []
    assert [ch for ch, _ in b.published if not ch.startswith("greg:response:")] == []
```

- [ ] **Étape 2 : les voir échouer.** `[BOT] tests/test_overlay_bot.py` → `AttributeError: 'RedisBridge' object has no attribute 'user_guilds'`.
- [ ] **Étape 3 : implémenter** l'ajout à `_READ_ONLY_ACTIONS`, `user_guilds` et la branche de `_handle_command`.
- [ ] **Étape 4 : les voir passer.** `[BOT] tests/test_overlay_bot.py tests/test_redis_bridge.py` → tout vert ; `[BOT] tests` → `270 + nouveaux passed`.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/bot/bot/services/redis_bridge.py services/bot/tests/test_overlay_bot.py && git commit -m "feat(bot): action user_guilds (serveurs communs, salons vocaux, lecture) en lecture seule"`

---

### Tâche 8 : bot, événement `greg:player:event`

**Files:**
- Modify : `services/bot/bot/services/redis_bridge.py` (canal l. 55-61 ; `_handle_command` l. 361-492 ; nouvelle méthode après `publish_progress` l. 501-512)
- Modify : `services/bot/bot/services/player_service.py` (méthode `title_at` après `get_state`, l. 650)
- Modify : `services/bot/tests/test_overlay_bot.py` (ajouts)
- Create : `services/bot/tests/test_queue_expected.py` (module `async`, `pytestmark = pytest.mark.asyncio`)

**Interfaces:**
- Consumes : résultat de `_handle_command`, `PlayerService.now_playing`, `current_song`, `_known_pm(gid).peek_all()`.
- Produces :
  - `redis_bridge.CHANNEL_PLAYER_EVENT = "greg:player:event"`
  - `redis_bridge._event_action(action: str, result: dict) -> Optional[str]` : `play_for_user` et `enqueue` → `"add"` ; `toggle_pause` → `result["action"]` s'il vaut `pause` ou `resume` ; `skip stop pause resume remove move play_at repeat restart` → même nom ; tout autre cas, ou `result["ok"]` faux → `None`.
  - `PlayerService.title_at(self, guild_id: int, index: Optional[int] = None) -> Optional[str]` : `None` → titre en cours (`now_playing` puis `current_song`) ; entier → titre de `queue[index]` s'il est dans les bornes ; ne crée jamais de `PlaylistManager`.
  - `RedisBridge._title_before(self, action: str, guild_id: int, cmd_data: dict) -> Optional[str]` : lu **avant** l'exécution (`remove`/`play_at` → `index`, `move` → `src`, `skip stop pause resume toggle_pause restart` → titre en cours, sinon `None`) ; toute exception → `None`.
  - `RedisBridge.publish_player_event` : `async def publish_player_event(self, guild_id: int, action: str, user_id: int, title: Optional[str]) -> None` (coroutine comme `publish_progress` l. 501 : le test l'`await`, `_handle_command` aussi) → `await self._publish(CHANNEL_PLAYER_EVENT, …)` de `{"guild_id": str(guild_id), "action": action, "actor": {"id": str(user_id), "display_name": <member.display_name, sinon str(user_id)>}, "title": title, "at_ms": int(time.time() * 1000)}`.
  - Dans `_handle_command`, après la réponse : si `_event_action(...)` rend une action, `await self.publish_player_event(...)` avec `title = result.get("title")` pour `add`, sinon le titre lu avant ; une erreur de publication ne change jamais la réponse.

- [ ] **Étape 1 : écrire les tests qui échouent** (ajouts dans `tests/test_overlay_bot.py` ; son bloc d'imports devient, `rb` et `FakeSvc` ajoutés) :

```python
import asyncio
import types

import bot.services.redis_bridge as rb
import pytest
from test_redis_bridge import MEMBER, FakeSvc, _cmd, _make_bridge, _responses
```

  puis, en fin de fichier :

```python
class EventSvc(FakeSvc):
    """FakeSvc complété : chaque mutation réussit, title_at suit un « avant » modifiable."""
    def __init__(self): super().__init__(); self.titles = {None: "Avant", 0: "Q0", 1: "Q1"}
    def title_at(self, gid, index=None): return self.titles.get(index)
    def remove_at(self, gid, uid, index, expected=None): return True
    def move(self, gid, uid, src, dst, expected=None): return True
    async def play_at(self, gid, uid, index, expected=None): return True
    async def restart(self, gid, requester_id=None): return True
    async def pause(self, gid, requester_id=None): return True
    async def resume(self, gid, requester_id=None): return True
    async def toggle_repeat(self, gid, mode=None): return True

def _events_of(b): return [d for ch, d in b.published if ch == rb.CHANNEL_PLAYER_EVENT]

@pytest.fixture
def eb():
    b = _make_bridge(); b.bot.player_service = EventSvc()
    b.bot._guilds[1].get_member = lambda uid: types.SimpleNamespace(id=uid, display_name="Kévin", voice=None)
    return b

@pytest.mark.parametrize("action,data,ev,title", [
    ("play_for_user", {"item": {"url": "x"}}, "add", "t"), ("skip", {}, "skip", "Avant"), ("stop", {}, "stop", "Avant"),
    ("pause", {}, "pause", "Avant"), ("resume", {}, "resume", "Avant"), ("restart", {}, "restart", "Avant"),
    ("repeat", {"mode": "on"}, "repeat", None), ("remove", {"index": 1}, "remove", "Q1"),
    ("move", {"src": 1, "dst": 0}, "move", "Q1"), ("play_at", {"index": 1}, "play_at", "Q1")])
async def test_successful_mutation_publishes_one_player_event(eb, action, data, ev, title):
    await eb._handle_command(_cmd(action, rid="r", **data))
    [e] = _events_of(eb)
    at = e.pop("at_ms")
    assert isinstance(at, int) and e == {"guild_id": "1", "action": ev, "actor": {"id": str(MEMBER), "display_name": "Kévin"},
                                         "title": title}

async def test_toggle_pause_event_names_what_happened(eb):
    eb.bot._guilds[1].voice_client = types.SimpleNamespace(is_paused=lambda: True, is_playing=lambda: False)
    await eb._handle_command(_cmd("toggle_pause", rid="t"))
    assert _events_of(eb)[0]["action"] == "resume"

async def test_event_title_is_read_before_the_change(eb):
    async def skip(gid, requester_id=None): eb.bot.player_service.titles[None] = "Après"; return True
    eb.bot.player_service.skip = skip
    await eb._handle_command(_cmd("skip", rid="s"))
    assert _events_of(eb)[0]["title"] == "Avant"

@pytest.mark.parametrize("action,data", [("get_state", {}), ("join", {}), ("get_history", {})])
async def test_reads_and_join_publish_no_event(eb, action, data):
    await eb._handle_command(_cmd(action, rid="x", **data)); assert _events_of(eb) == []

async def test_failures_publish_no_event(eb):
    eb.bot.player_service.remove_at = lambda *a, **k: False
    async def forbidden(*a, **k): raise PermissionError("insufficient_rank")
    eb.bot.player_service.play_at = forbidden
    await eb._handle_command(_cmd("remove", rid="a", index=0)); await eb._handle_command(_cmd("play_at", rid="b", index=0))
    assert _events_of(eb) == []

async def test_actor_falls_back_to_the_id_and_title_errors_are_harmless(eb):
    eb.bot._guilds[1].get_member = lambda uid: None
    def boom(*a, **k): raise RuntimeError("cache")
    eb.bot.player_service.title_at = boom
    await eb._handle_command(_cmd("skip", rid="s"))
    assert _responses(eb)["s"]["ok"] is True
    assert _events_of(eb)[0]["actor"] == {"id": str(MEMBER), "display_name": str(MEMBER)} and _events_of(eb)[0]["title"] is None

async def test_publish_player_event_keeps_snowflake_as_string(eb):               # Review Focus 4
    await eb.publish_player_event(1234567890123456789, "add", 7, "T")
    assert _events_of(eb)[0]["guild_id"] == "1234567890123456789"
```

  Et dans `tests/test_queue_expected.py` (créé ici ; module `async`, donc `pytestmark` ; le harnais est rendu visible par `harness = core_fakes.harness` comme dans `test_play_many.py`, ce qui évite le F811 de `ruff` qu'un `from core_fakes import harness` donnerait à chaque test) :

```python
"""PlayerService : title_at, puis la garde expected (tâche 9)."""
from __future__ import annotations

import core_fakes
import pytest
from core_fakes import BOT_CHANNEL, yt_entry

harness = core_fakes.harness  # fixture du harnais rendue visible ici, comme dans test_play_many.py

pytestmark = pytest.mark.asyncio

A, B, C = yt_entry(1, title="A"), yt_entry(2, title="B"), yt_entry(3, title="C")


async def test_title_at_reads_current_and_queue(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    await h.svc.enqueue(h.gid, 2, A); await h.svc.enqueue(h.gid, 2, B)
    assert [h.svc.title_at(h.gid, i) for i in range(len(h.queue()))] == [it["title"] for it in h.queue()]
    assert h.svc.title_at(h.gid, 99) is None and h.svc.title_at(424242, 0) is None
    h.svc.now_playing[h.gid] = {"title": "En cours"}
    assert h.svc.title_at(h.gid) == "En cours"
```
- [ ] **Étape 2 : les voir échouer.** `[BOT] tests/test_overlay_bot.py tests/test_queue_expected.py` → `AttributeError: module 'bot.services.redis_bridge' has no attribute 'CHANNEL_PLAYER_EVENT'`, `'PlayerService' object has no attribute 'title_at'`.
- [ ] **Étape 3 : implémenter** `CHANNEL_PLAYER_EVENT`, `_event_action`, `_title_before`, `publish_player_event`, l'appel dans `_handle_command`, et `PlayerService.title_at`.
- [ ] **Étape 4 : les voir passer.** `[BOT] tests` → 0 failed (les tests existants de `test_redis_bridge.py` ne regardent que `greg:response:*` ou des commandes non exécutées).
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/bot/bot/services/redis_bridge.py services/bot/bot/services/player_service.py services/bot/tests/test_overlay_bot.py services/bot/tests/test_queue_expected.py && git commit -m "feat(bot): greg:player:event après chaque commande réussie qui change l'état (auteur, titre)"`

---

### Tâche 9 : bot, garde `expected` et refus `STALE`

**Files:**
- Modify : `services/bot/bot/services/playlist_manager.py` (avant la classe : `StaleQueueError`, `queue_item_matches`)
- Modify : `services/bot/bot/services/player_service.py` (`remove_at` l. 1383-1397, `move` l. 1399-1419, `play_at` l. 1421-1458)
- Modify : `services/bot/bot/services/redis_bridge.py` (branches `remove`, `move`, `play_at` l. 422-440 ; `except` l. 474)
- Modify : `services/bot/tests/test_queue_expected.py`, `services/bot/tests/test_overlay_bot.py` (ajouts)
- Create : `services/bot/tests/test_queue_item_matches.py` (tests synchrones, hors du `pytestmark` asyncio)

**Interfaces:**
- Produces :
  - `playlist_manager.StaleQueueError(Exception)`
  - `playlist_manager.queue_item_matches(item: dict, expected: dict) -> bool` : `(item.url or "") == (expected.url or "")`, `str(item.added_by or "") == str(expected.added_by or "")`, `ts` comparés après `int(float(v))` (`None` si absent ou illisible ; deux `None` sont égaux : l'appli envoie `ts: null` pour un titre qui n'en a pas, plan B `expectedOf`).
  - `PlayerService.remove_at(self, guild_id, requester_id, index, expected: Optional[dict] = None) -> bool`, `move(self, guild_id, requester_id, src, dst, expected: Optional[dict] = None) -> bool`, `async play_at(self, guild_id, user_id, index, expected: Optional[dict] = None) -> bool` : avec `expected`, index hors bornes ou élément différent → `raise StaleQueueError` **avant** tout contrôle de droits et sans rien modifier (dans `play_at`, sous `_queue_lock`). Sans `expected` : inchangé (hors bornes → `False`).
  - `redis_bridge._expected_arg(cmd_data: dict) -> Optional[dict]` : `cmd_data["expected"]` s'il est un dict, sinon `None`, passé en `expected=` aux trois méthodes ; `except StaleQueueError` → `{"ok": False, "error": "STALE"}` (placé avant `except PermissionError`).

- [ ] **Étape 1 : écrire les tests qui échouent.** `tests/test_queue_item_matches.py` (créé ; synchrone, donc sans `pytestmark`) :

```python
"""queue_item_matches : comparaison de l'élément attendu (tests synchrones, hors du pytestmark asyncio)."""
from __future__ import annotations

import pytest
from bot.services.playlist_manager import queue_item_matches


@pytest.mark.parametrize("item,exp,ok", [
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": "2", "ts": 1700000000}, True),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": 2, "ts": 1700000000.0}, True),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "v", "added_by": "2", "ts": 1700000000}, False),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": "3", "ts": 1700000000}, False),
    ({"url": "u", "added_by": "2", "ts": 1700000000}, {"url": "u", "added_by": "2", "ts": None}, False),
    ({"url": None, "added_by": None, "ts": 5}, {"url": "", "added_by": None, "ts": "5"}, True)])
def test_queue_item_matches(item, exp, ok):
    assert queue_item_matches(item, exp) is ok

def test_two_missing_ts_match():                     # plan B : expectedOf envoie ts: null pour un titre sans ts
    assert queue_item_matches({"url": "u", "added_by": "2", "ts": None}, {"url": "u", "added_by": "2", "ts": None}) is True
    assert queue_item_matches({"url": "u", "added_by": None}, {"url": "u", "added_by": None, "ts": None}) is True
```

  Dans `tests/test_queue_expected.py`, le bloc d'imports gagne `StaleQueueError` (ordre attendu par `ruff`) :

```python
import core_fakes
import pytest
from bot.services.playlist_manager import StaleQueueError
from core_fakes import BOT_CHANNEL, yt_entry
```

  puis, en fin de fichier :

```python
def _exp(it): return {"url": it["url"], "added_by": it["added_by"], "ts": it["ts"]}

async def test_matching_expected_acts(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    for x in (A, B, C): await h.svc.enqueue(h.gid, 2, x)
    q = h.queue()
    assert h.svc.remove_at(h.gid, 2, 0, expected=_exp(q[0])) is True
    q = h.queue(); assert h.svc.move(h.gid, 2, 1, 0, expected=_exp(q[1])) is True and h.urls()[0] == C["url"]

@pytest.mark.parametrize("op", ["remove", "move", "play_at", "out_of_bounds"])
async def test_stale_expected_raises_and_changes_nothing(harness, op):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL)
    for x in (A, B): await h.svc.enqueue(h.gid, 2, x)
    before, wrong = h.urls(), _exp(h.queue()[0])
    with pytest.raises(StaleQueueError):
        if op == "remove": h.svc.remove_at(h.gid, 2, 1, expected=wrong)
        elif op == "move": h.svc.move(h.gid, 2, 1, 0, expected=wrong)
        elif op == "play_at": await h.svc.play_at(h.gid, 2, 1, expected=wrong)
        else: h.svc.remove_at(h.gid, 2, 5, expected=wrong)
    assert h.urls() == before

async def test_stale_is_checked_before_permissions(harness):
    h = harness; h.guild.add_member(1, admin=True, channel_id=BOT_CHANNEL); h.guild.add_member(2, channel_id=BOT_CHANNEL)
    await h.svc.enqueue(h.gid, 1, A)                               # titre de l'admin : 2 n'a pas le droit
    with pytest.raises(StaleQueueError):
        h.svc.remove_at(h.gid, 2, 0, expected={"url": "autre", "added_by": "1", "ts": 1})

async def test_without_expected_nothing_changes(harness):
    h = harness; h.guild.add_member(2, channel_id=BOT_CHANNEL); await h.svc.enqueue(h.gid, 2, A)
    assert h.svc.remove_at(h.gid, 2, 5) is False and h.svc.move(h.gid, 2, 0, 3) is False
```
  (`A`, `B`, `C` et `harness` : posés en tête du fichier à la tâche 8.) Dans `tests/test_overlay_bot.py`, le bloc d'imports devient (bloc final du fichier, `StaleQueueError` ajouté) :

```python
import asyncio
import types

import bot.services.redis_bridge as rb
import pytest
from bot.services.playlist_manager import StaleQueueError
from test_redis_bridge import MEMBER, FakeSvc, _cmd, _make_bridge, _responses
```

  puis, en fin de fichier :

```python
async def test_bridge_forwards_expected_and_maps_stale(eb):
    seen = {}
    def remove_at(gid, uid, index, expected=None): seen["expected"] = expected; raise StaleQueueError()
    eb.bot.player_service.remove_at = remove_at
    E = {"url": "u", "added_by": "7", "ts": 1700000000}
    await eb._handle_command(_cmd("remove", rid="r", index=1, expected=E))
    assert _responses(eb)["r"] == {"request_id": "r", "ok": False, "error": "STALE"}
    assert seen["expected"] == E and _events_of(eb) == []

async def test_bridge_ignores_a_non_object_expected(eb):
    seen = {}
    eb.bot.player_service.move = lambda gid, uid, s, d, expected=None: seen.setdefault("e", expected) or True
    await eb._handle_command(_cmd("move", rid="m", src=1, dst=0, expected="x"))
    assert seen["e"] is None
```
- [ ] **Étape 2 : les voir échouer.** `[BOT] tests/test_queue_item_matches.py tests/test_queue_expected.py tests/test_overlay_bot.py` → `ImportError: cannot import name 'queue_item_matches'` puis `'StaleQueueError'` (erreurs de collecte des trois modules).
- [ ] **Étape 3 : implémenter** `StaleQueueError`, `queue_item_matches`, le paramètre `expected` des trois méthodes, `_expected_arg` et le `except` du pont.
- [ ] **Étape 4 : les voir passer.** `[BOT] tests` → 0 failed (`test_playback.py`, `test_priority_move.py`, `test_playlist_manager.py` inchangés et verts).
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/bot/bot/services/playlist_manager.py services/bot/bot/services/player_service.py services/bot/bot/services/redis_bridge.py services/bot/tests/test_queue_item_matches.py services/bot/tests/test_queue_expected.py services/bot/tests/test_overlay_bot.py && git commit -m "feat(bot): retirer, déplacer et jouer maintenant vérifient le titre attendu (STALE sans rien changer)"`

---

### Tâche 10 : API, relais de `player_event`, `guild_id` des ticks, `expected` et `STALE`

**Files:**
- Modify : `services/api/api/services/redis_listener.py` (l. 22-24 canaux, l. 40-44 abonnement, l. 68-97 `_handle_message`)
- Modify : `services/api/api/routes/player.py` (`error_status` l. 65-78, `move` l. 233-248, `remove_at` l. 251-261, `playlist_play_at` l. 312-326)
- Modify : `services/api/tests/test_sync_relay.py` (l. 62-63 : le dict attendu gagne `"guild_id": "42"`)
- Create : `services/api/tests/test_player_event_relay.py`, `services/api/tests/test_queue_stale.py`

**Interfaces:**
- Produces :
  - `redis_listener.CHANNEL_PLAYER_EVENT = "greg:player:event"`, `CHANNELS = (CHANNEL_STATE, CHANNEL_PROGRESS, CHANNEL_BOT_STATUS, CHANNEL_PLAYER_EVENT)` (utilisée par `pubsub.subscribe(*CHANNELS)`), `PLAYER_EVENT_ACTIONS = frozenset({"add", "skip", "stop", "pause", "resume", "remove", "move", "play_at", "repeat", "restart"})`.
  - `redis_listener._player_event(data: dict) -> Optional[dict]` : ne garde que `{guild_id: str, action, actor: {id: str, display_name: str}, title: str | None, at_ms: int}` ; action inconnue, `guild_id` vide ou `actor` illisible → `None`. Émis en `player_event` à la salle `guild:<id>` seulement.
  - Tick : le payload gagne `"guild_id": guild_id` (la chaîne déjà calculée l. 69).
  - `player.MSG_STALE = "La file a bougé : réessayez."` ; `error_status` : `STALE` → 409.
  - `player._expected_of(data: dict) -> Optional[dict]` : clé absente ou `None` → `None` ; sinon un dict avec `url` texte ou `None`, `added_by` texte, entier ou `None`, `ts` nombre (pas booléen) ou `None`, rendu `{"url", "added_by", "ts"}` ; toute autre forme → `ValueError`, que les routes traduisent en 400 `{"ok": False, "error": "invalid expected"}` sans appel au bot.
  - `remove`, `move`, `play_at` ajoutent `"expected"` à `data` seulement s'il est fourni ; réponse `STALE` → `{**res, "message": MSG_STALE}` en 409.

- [ ] **Étape 1 : écrire les tests qui échouent.** `tests/test_player_event_relay.py` :

```python
from api import socketio
from api.services import redis_listener as rl
from api.services.redis_listener import _handle_message
from test_socketio import FakeBot, _events, fake_bot, member_sio  # noqa: F401
from test_sync_relay import FakeSio

EV = {"guild_id": "42", "action": "add", "actor": {"id": "7", "display_name": "Kévin"}, "title": "Thunderstruck", "at_ms": 1790846494123}

def test_listener_subscribes_player_event():
    assert rl.CHANNEL_PLAYER_EVENT == "greg:player:event" and rl.CHANNEL_PLAYER_EVENT in rl.CHANNELS

def test_player_event_goes_to_its_guild_room_only():
    sio = FakeSio(); rl._handle_message(sio, rl.CHANNEL_PLAYER_EVENT, {**EV, "secret": "x"})
    assert sio.emits == [("player_event", EV, "guild:42")]

@pytest.mark.parametrize("bad", [{**EV, "action": "jumpscare"}, {**EV, "guild_id": ""}, {**EV, "actor": "Kévin"}])
def test_player_event_drops_unknown_or_malformed(bad):
    sio = FakeSio(); rl._handle_message(sio, rl.CHANNEL_PLAYER_EVENT, bad); assert sio.emits == []

def test_tick_guild_id_keeps_snowflake_precision():                              # Review Focus 4
    sio = FakeSio(); rl._handle_message(sio, rl.CHANNEL_PROGRESS, {"guild_id": 1234567890123456789, "position": 1})
    assert sio.emits[0][1]["guild_id"] == "1234567890123456789"

def test_member_socket_receives_player_event(member_sio, fake_bot):
    member_sio.emit("join_guild", {"guild_id": "42"}); member_sio.get_received()
    t = threading.Thread(target=_handle_message, args=(socketio, rl.CHANNEL_PLAYER_EVENT, EV)); t.start(); t.join(5)
    assert [e["args"][0] for e in _events(member_sio.get_received(), "player_event")] == [EV]
```
  (`FakeSio` de `test_sync_relay`, `member_sio`, `fake_bot`, `_events` de `test_socketio`.) `tests/test_queue_stale.py` :

```python
E = {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "added_by": "7", "ts": 1700000000}
ROUTES = [("post", "/queue/remove", {"index": 1}, "remove", {"index": 1}),
          ("delete", "/player/queue/1", {}, "remove", {"index": 1}),
          ("post", "/player/move", {"src": 1, "dst": 0}, "move", {"src": 1, "dst": 0}),
          ("post", "/playlist/play_at", {"index": 1}, "play_at", {"index": 1})]

@pytest.mark.parametrize("method,path,body,action,data", ROUTES)
def test_expected_is_forwarded_only_when_given(logged_client, fake_send, method, path, body, action, data):
    getattr(logged_client, method)(f"{BASE}{path}", json={"guild_id": "5", **body})
    assert fake_send.calls[-1]["data"] == data
    getattr(logged_client, method)(f"{BASE}{path}", json={"guild_id": "5", **body, "expected": E})
    assert fake_send.calls[-1]["data"] == {**data, "expected": E}

@pytest.mark.parametrize("method,path,body,action,data", ROUTES)
def test_stale_is_409_with_french_message(logged_client, fake_send, method, path, body, action, data):
    fake_send.result = {"ok": False, "error": "STALE"}
    r = getattr(logged_client, method)(f"{BASE}{path}", json={"guild_id": "5", **body, "expected": E})
    assert r.status_code == 409 and r.get_json() == {"ok": False, "error": "STALE", "message": "La file a bougé : réessayez."}

@pytest.mark.parametrize("bad", ["x", [1], {"url": 5}, {"url": "u", "ts": "abc"}, {"url": "u", "ts": True}, {"url": "u", "added_by": [1]}])
def test_invalid_expected_is_400_without_calling_the_bot(logged_client, fake_send, bad):
    r = logged_client.post(f"{BASE}/queue/remove", json={"guild_id": "5", "index": 1, "expected": bad})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": "invalid expected"} and fake_send.calls == []
```
- [ ] **Étape 2 : les voir échouer.** `[API] tests/test_player_event_relay.py tests/test_queue_stale.py tests/test_sync_relay.py` → `AttributeError: … 'CHANNEL_PLAYER_EVENT'`, `assert {'index': 1} == {'index': 1, 'expected': …}`, et la comparaison du tick de `test_sync_relay` (une fois son dict mis à jour).
- [ ] **Étape 3 : implémenter** les canaux, `_player_event`, le `guild_id` des ticks, `MSG_STALE`, `_expected_of` et la transmission dans les trois routes.
- [ ] **Étape 4 : les voir passer.** `[API] tests` → 0 failed (`test_player_routes.py`, `test_authz.py`, `test_socketio.py` compris).
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/api/api/services/redis_listener.py services/api/api/routes/player.py services/api/tests/test_sync_relay.py services/api/tests/test_player_event_relay.py services/api/tests/test_queue_stale.py && git commit -m "feat(api): relais de player_event, guild_id dans les ticks, expected transmis et 409 STALE"`

---

### Tâche 11 : site, `lib/devices.ts`, méthodes `api.device*` et textes

**Files:**
- Create : `services/web/src/lib/devices.ts`
- Modify : `services/web/src/lib/api.ts` (commentaire d'en-tête l. 1-13 ; objet `api` l. 183-277 : six méthodes après le chansonnier)
- Modify : `services/web/src/theme/copy.extra.ts` (section `devices` insérée avant `error:` l. 179)
- Create : `services/web/tests/devices.test.mjs`

**Interfaces:**
- Produces (`src/lib/devices.ts`, pur) :
  - `USER_CODE_ALPHABET = 'BCDFGHJKLMNPQRSTVWXZ'`, `PENDING_KEY = 'greg.lier.pending'`, `PENDING_TTL_MS = 600_000`.
  - `type KV = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void }`
  - `type DeviceGuild = { id: string; name: string; icon_url: string | null; greg_voice: { id: string; name: string } | null; user_voice: { id: string; name: string } | null; playing: boolean }`
  - `type DeviceToken = { id: string; label: string; created_at: number; last_used_at: number; expires_at: number; current: boolean }`
  - `normalizeUserCode(raw: unknown): string | null`, `formatUserCode(code: string): string`
  - `browserSession(): KV | null` (`globalThis.sessionStorage` sous try/catch)
  - `savePendingCode(kv: KV | null, raw: string, now: number): void` (JSON `{code, at}` ; code invalide ignoré ; exceptions avalées)
  - `peekPendingCode(kv: KV | null, now: number): string | null` (illisible ou `now - at >= PENDING_TTL_MS` → retiré, `null`)
  - `takePendingCode(kv: KV | null, now: number): string | null` (lit puis retire)
  - `pickDeviceGuild(guilds: readonly DeviceGuild[], saved: string | null): string | null` : `saved` s'il est listé, sinon le premier avec `user_voice`, sinon le premier `playing`, sinon le premier, sinon `null`.
  - `ageMinutes(createdAtS: number, nowMs: number): number` (entier ≥ 0)
  - `deviceErrorKey(e: unknown): string` : `payload.error` → `CODE_EXPIRED`, `ALREADY_USED`, `RATE_LIMITED`, `NOT_GUILD_MEMBER` → `'devices.error.<code>'` ; `INVALID_REQUEST` → `'devices.error.INVALID_CODE'` ; sinon `'devices.error.generic'`.
- Produces (`api`) : `deviceMe: () => get('/overlay/me')`, `deviceGuilds: () => get('/overlay/guilds')`, `deviceLookup: (code: string) => get('/overlay/device/lookup', { user_code: code })`, `deviceDecide: (code: string, decision: 'approve' | 'deny', guildId?: string) => post('/overlay/device/approve', guildId ? { user_code: code, decision, guild_id: guildId } : { user_code: code, decision })`, `deviceTokens: () => get('/overlay/tokens')`, `deviceRevoke: (id: string) => post('/overlay/tokens/revoke', { id })`.
- Produces (`EXTRA.devices`, texte exact) :

```ts
devices: {
  menu: 'Appareils liés',
  kicker: 'Appli Greg',
  title: 'Lier un appareil',
  intro: 'L’appli Greg affiche un code de 8\u00a0lettres. Saisissez-le ici pour la lier à votre compte.',
  codeLabel: 'Code affiché par l’appli',
  device: '«\u00a0{name}\u00a0» attend votre accord.',
  age: { one: 'Demandé il y a 1\u00a0min', other: 'Demandé il y a {n}\u00a0min' },
  ageNow: 'Demandé à l’instant',
  guildLabel: 'Serveur par défaut',
  guildNone: 'Greg n’est sur aucun de vos serveurs pour l’instant.',
  approve: 'Autoriser',
  deny: 'Refuser',
  approved: 'C’est fait, Sire. Retournez à votre jeu.',
  denied: 'Demande refusée. L’appli ne sera pas liée.',
  login: 'Connectez-vous avec Discord pour autoriser l’appli. Le code vous attendra dix minutes.',
  notAllowed: 'Cette page ne vous est pas ouverte.',
  listTitle: 'Appareils liés',
  listEmpty: 'Aucun appareil lié.',
  lastUsed: 'Dernière utilisation\u00a0: {date}',
  expires: 'Échéance\u00a0: {date}',
  unlink: 'Délier',
  confirm: { title: 'Délier «\u00a0{name}\u00a0»\u202f?', body: 'L’appli devra être liée de nouveau avec un nouveau code.', yes: 'Délier', no: 'Garder' },
  unlinked: '«\u00a0{name}\u00a0» est délié.',
  error: {
    INVALID_CODE: 'Le code compte 8\u00a0lettres, par exemple BCDF-GHJK.',
    CODE_EXPIRED: 'Ce code a expiré ou n’existe pas. Demandez-en un nouveau dans l’appli.',
    ALREADY_USED: 'Ce code a déjà servi.',
    RATE_LIMITED: 'Trop d’essais. Patientez une minute.',
    NOT_GUILD_MEMBER: 'Choisissez un serveur où Greg et vous êtes présents.',
    generic: 'L’opération n’a pas abouti. Réessayez dans un instant.',
  },
},
```

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/devices.test.mjs`) :

```js
const D = await loadTs('../src/lib/devices.ts');
const { api } = await loadTs('../src/lib/api.ts');
const { tx } = await loadTs('../src/theme/copy.extra.ts');
const kv = () => { const m = new Map(); return { m, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }; };

test('normalizeUserCode / formatUserCode', () => {
  for (const [raw, code] of [['bcdf-ghjk', 'BCDFGHJK'], [' BCDF GHJK ', 'BCDFGHJK'], ['bcdf—ghjk', 'BCDFGHJK'],
    ['BCDF-GHJ', null], ['BCDF-GHJA', null], ['', null], [null, null], [12345678, null]]) assert.equal(D.normalizeUserCode(raw), code, String(raw));
  assert.equal(D.formatUserCode('BCDFGHJK'), 'BCDF-GHJK');
});

test('code en attente : 10 min, illisible retiré, stockage absent ou qui lève sans effet', () => {
  const s = kv(); D.savePendingCode(s, 'bcdf-ghjk', 0);
  assert.equal(D.peekPendingCode(s, 599_999), 'BCDFGHJK');
  assert.equal(D.peekPendingCode(s, 600_000), null); assert.equal(s.m.has(D.PENDING_KEY), false);
  s.setItem(D.PENDING_KEY, '{pas du json'); assert.equal(D.peekPendingCode(s, 0), null); assert.equal(s.m.size, 0);
  D.savePendingCode(s, 'nope', 0); assert.equal(s.m.size, 0);
  assert.equal(D.peekPendingCode(null, 0), null);
  const boom = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() { throw new Error('x'); } };
  assert.doesNotThrow(() => D.savePendingCode(boom, 'BCDFGHJK', 0)); assert.equal(D.peekPendingCode(boom, 0), null);
});

test('takePendingCode consomme le code (pas de seconde redirection)', () => {            // Review Focus 5
  const s = kv(); D.savePendingCode(s, 'BCDFGHJK', 0);
  assert.equal(D.takePendingCode(s, 1), 'BCDFGHJK'); assert.equal(D.peekPendingCode(s, 2), null);
});

test('pickDeviceGuild : enregistré, puis vocal, puis en lecture, puis le premier', () => {
  const g = (id, o = {}) => ({ id, name: id, icon_url: null, greg_voice: null, user_voice: null, playing: false, ...o });
  const all = [g('1'), g('2', { playing: true }), g('3', { user_voice: { id: '9', name: 'V' } })];
  assert.equal(D.pickDeviceGuild(all, '2'), '2'); assert.equal(D.pickDeviceGuild(all, '8'), '3');
  assert.equal(D.pickDeviceGuild(all.slice(0, 2), null), '2'); assert.equal(D.pickDeviceGuild([g('1')], null), '1');
  assert.equal(D.pickDeviceGuild([], '1'), null);
});

test('deviceErrorKey et textes', () => {
  for (const [code, key] of [['CODE_EXPIRED', 'devices.error.CODE_EXPIRED'], ['ALREADY_USED', 'devices.error.ALREADY_USED'],
    ['RATE_LIMITED', 'devices.error.RATE_LIMITED'], ['NOT_GUILD_MEMBER', 'devices.error.NOT_GUILD_MEMBER'],
    ['INVALID_REQUEST', 'devices.error.INVALID_CODE'], ['CSRF_FAILED', 'devices.error.generic'], [undefined, 'devices.error.generic']]) {
    assert.equal(D.deviceErrorKey({ payload: { error: code } }), key); assert.notEqual(tx(key), key);
  }
  assert.equal(D.ageMinutes(1000, 1000 * 1000 + 125_000), 2); assert.equal(D.ageMinutes(2000, 1000), 0);
  assert.equal(tx('devices.age', { n: 3 }), 'Demandé il y a 3\u00a0min');
  assert.equal(tx('devices.approved'), 'C’est fait, Sire. Retournez à votre jeu.');
});

test('api.device* : chemins, corps, session, jamais d’identité', async () => {
  for (const [fn, method, path, body] of [
    [() => api.deviceMe(), 'GET', '/api/v1/overlay/me', undefined],
    [() => api.deviceGuilds(), 'GET', '/api/v1/overlay/guilds', undefined],
    [() => api.deviceLookup('BCDFGHJK'), 'GET', '/api/v1/overlay/device/lookup', undefined],
    [() => api.deviceDecide('BCDFGHJK', 'approve', '42'), 'POST', '/api/v1/overlay/device/approve', { user_code: 'BCDFGHJK', decision: 'approve', guild_id: '42' }],
    [() => api.deviceDecide('BCDFGHJK', 'deny'), 'POST', '/api/v1/overlay/device/approve', { user_code: 'BCDFGHJK', decision: 'deny' }],
    [() => api.deviceTokens(), 'GET', '/api/v1/overlay/tokens', undefined],
    [() => api.deviceRevoke('t1'), 'POST', '/api/v1/overlay/tokens/revoke', { id: 't1' }]]) {
    const { calls } = await capture(fn);
    assert.deepEqual({ method: calls[0].method, path: calls[0].path, body: calls[0].body }, { method, path, body });
    assert.equal(calls[0].credentials, 'include'); assert.ok(!JSON.stringify(calls[0].body ?? {}).includes('user_id'));
  }
  assert.equal((await capture(() => api.deviceLookup('BCDFGHJK'))).calls[0].query, 'user_code=BCDFGHJK');
});
```
  (`capture` recopié de `tests/library-api.test.mjs` l. 10-18, en notant aussi `query: new URL(String(url)).searchParams.toString()`.)
- [ ] **Étape 2 : les voir échouer.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npm test` → `devices.test.mjs` : `Cannot find module …/src/lib/devices.ts`.
- [ ] **Étape 3 : implémenter** `devices.ts` (aucun import à l'exécution), les six méthodes (une ligne d'en-tête ajoutée au commentaire de `api.ts`), et la section `devices` telle quelle.
- [ ] **Étape 4 : les voir passer.** `[WEB]` → `npm test` : `fail 0` (dont `copy-extra.test.mjs` : typographie et casting) ; `GREG_TEST_TRANSPILE=1 npm test` : `fail 0` ; `npx tsc --noEmit` : code 0.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/web/src/lib/devices.ts services/web/src/lib/api.ts services/web/src/theme/copy.extra.ts services/web/tests/devices.test.mjs && git commit -m "feat(web): logique des appareils liés (code, code en attente, serveur par défaut) et appels /overlay"`

---

### Tâche 12 : site, page /lier, entrée « Appareils liés » et retour après connexion

**Files:**
- Create : `services/web/src/app/lier/page.tsx`
- Create : `services/web/src/components/Lier/lier.css`
- Modify : `services/web/src/app/globals.css` (ajout `@import '../components/Lier/lier.css';` après l. 13)
- Modify : `services/web/src/components/Header/AccountMenu.tsx` (état propriétaire ; bouton avant le `pop-sep` qui précède la déconnexion, l. 114-117)
- Modify : `services/web/src/hooks/usePlayer.ts` (`boot`, l. 577-588)
- Create : `services/web/tests/lier-contract.test.mjs`

**Interfaces:**
- Consumes : `api.getMe`, `api.getLoginUrl`, `api.device*`, tout `devices.ts`, `tx`, `t('auth.cta')`.
- Produces :
  - `src/app/lier/page.tsx` : `'use client'`, `export default function LierPage()`. Vues : chargement → `out` → `notAllowed` → propriétaire. Au montage, un seul `useEffect(…, [])`, dans cet ordre :
    1. `const urlCode = normalizeUserCode(new URLSearchParams(window.location.search).get('code'))`. Jamais `useSearchParams` : Next 14.2.35 a `experimental.missingSuspenseWithCSRBailout: true` par défaut (`node_modules/next/dist/server/config-shared.js`), et un `useSearchParams` hors `<Suspense>` dans une page prérendue fait échouer `next build`, donc le déploiement Railway (`RUN npm run build` du Dockerfile). Le mot `useSearchParams` n'apparaît nulle part dans la page, pas même en commentaire : le test de contrat le cherche.
    2. `api.getMe()`. Échec → vue `out` (non connecté) : bouton `<a className="btn-solid" href={api.getLoginUrl()}>` « Se connecter avec Discord » dont le clic appelle `savePendingCode(browserSession(), urlCode, Date.now())` quand `urlCode` existe ; le code en attente n'est pas touché.
    3. Succès de `getMe()` → **aussitôt**, avant tout appel à `api.deviceMe()` et donc avant la branche `is_owner` : `const pending = takePendingCode(browserSession(), Date.now())` (seul appel de la page). Le code est ainsi consommé pour tout connecté, propriétaire ou non, et même si `/overlay/me` échoue ensuite : `boot()` ne renvoie plus vers /lier.
    4. `api.deviceMe()` : échec → `<p role="alert">{tx(deviceErrorKey(e))}</p>` ; `me.is_owner !== true` (expression exacte) → `notAllowed` ; sinon vue propriétaire : champ prérempli par `urlCode ?? pending`, puis `history.replaceState(null, '', '/lier')`.

    Code complet → `deviceLookup` (nom et âge) ; jamais d'autorisation automatique. Choix du serveur parmi `deviceGuilds()` (`pickDeviceGuild(guilds, localStorage['greg.webplayer.guild_id'])`). Une seule fonction `async function decide(decision: 'approve' | 'deny')` appelle `api.deviceDecide`, appelée seulement par `onClick={() => decide('approve')}` (`.btn-solid`) et `onClick={() => decide('deny')}` (`.btn-ghost`). Liste `deviceTokens()` (nom, `lastUsed`, `expires` en `toLocaleDateString('fr-FR')`) avec « Délier », confirmé par un dialogue `.pop.plaque.confirm` `role="dialog"` (focus sur « Garder », `.btn-ghost` puis `.btn-danger`, Échap ferme), puis `deviceRevoke`. Erreurs : `<p role="alert">{tx(deviceErrorKey(e))}</p>`. Pas de `usePlayerInit`.
  - `lier.css` : `.lier` conteneur fixe défilant (`position: fixed; inset: 0; overflow-y: auto`, le `body` est en `overflow: hidden`), carte `.plaque` centrée, largeur max 520 px, marge latérale 16 px ; réutilise `.vl-kicker`, `.vl-title`, `.vl-body`, `.vl-small`, `.field`, `.btn-solid`, `.btn-ghost`, `.btn-danger` ; aucune courbe `linear(` en dur.
  - `AccountMenu` : à la première ouverture, `api.deviceMe()` ; si `is_owner === true`, un `<button type="button" className="pop-item">` « {tx('devices.menu')} » qui ferme le menu et fait `window.location.assign('/lier')`.
  - `boot()` : après `refreshMe()`, si `me` est connu et `peekPendingCode(browserSession(), Date.now())` rend un code → `window.location.replace('/lier')` puis `return`.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/lier-contract.test.mjs`) :

```js
import { read } from './_contract.mjs';
const { tx } = await loadTs('../src/theme/copy.extra.ts');
const page = read('src/app/lier/page.tsx'), menu = read('src/components/Header/AccountMenu.tsx');
const player = read('src/hooks/usePlayer.ts');

test('/lier : client, sans lecteur, jamais d’autorisation automatique', () => {
  assert.match(page, /^'use client';/);
  assert.ok(!page.includes('usePlayerInit'));
  assert.equal(page.match(/api\.deviceDecide\(/g)?.length, 1);
  assert.deepEqual(page.match(/decide\('(approve|deny)'\)/g), ["decide('approve')", "decide('deny')"]);
  for (const m of page.matchAll(/decide\('(approve|deny)'\)/g)) assert.match(page.slice(m.index - 20, m.index), /onClick=\{\(\) => $/);
  assert.match(page, /className="btn-solid"[^>]*onClick=\{\(\) => decide\('approve'\)\}/);
  assert.match(page, /className="btn-ghost"[^>]*onClick=\{\(\) => decide\('deny'\)\}/);
});

test('/lier consomme le code en attente au montage et nettoie l’URL', () => {      // Review Focus 5
  assert.match(page, /takePendingCode\(browserSession\(\), Date\.now\(\)\)/);
  assert.match(page, /history\.replaceState\(null, '', '\/lier'\)/);
  assert.match(page, /savePendingCode\(browserSession\(\)/);
});

test('/lier lit ?code= sans useSearchParams et prend le code avant la branche is_owner', () => {   // Review Focus 5
  assert.ok(!page.includes('useSearchParams'));
  assert.match(page, /new URLSearchParams\(window\.location\.search\)\.get\('code'\)/);
  assert.equal(page.match(/takePendingCode\(/g)?.length, 1);
  const me = page.indexOf('api.getMe()'), take = page.indexOf('takePendingCode(browserSession(), Date.now())');
  assert.ok(me >= 0 && me < take, 'le code se prend une fois getMe() réussi');
  assert.ok(take < page.indexOf('api.deviceMe()') && take < page.indexOf('is_owner !== true'),
    'et avant /overlay/me et la branche is_owner : pas de boucle « / » ↔ /lier pour un non-propriétaire');
});

test('/lier : dialogue de « Délier » au motif de Transport, textes présents', () => {
  assert.match(page, /role="dialog"/); assert.ok(page.indexOf('btn-ghost', page.indexOf('role="dialog"')) < page.indexOf('btn-danger', page.indexOf('role="dialog"')));
  for (const src of [page, menu]) for (const [, k] of src.matchAll(/tx\('(devices\.[\w.]+)'/g)) assert.notEqual(tx(k), k, k);
});

test('menu du compte : « Appareils liés » pour le seul propriétaire', () => {
  assert.match(menu, /api\.deviceMe\(\)/); assert.match(menu, /is_owner === true/);
  assert.match(menu, /tx\('devices\.menu'\)/); assert.match(menu, /location\.assign\('\/lier'\)/);
});

test('boot renvoie vers /lier quand un code attend', () => {
  const boot = player.slice(player.indexOf('async function boot()'), player.indexOf('export const playerActions'));
  assert.match(boot, /peekPendingCode\(browserSession\(\), Date\.now\(\)\)/);
  assert.match(boot, /location\.replace\('\/lier'\)/);
});

test('feuille de /lier importée', () => {
  assert.match(read('src/app/globals.css'), /@import '\.\.\/components\/Lier\/lier\.css';/);
});
```
- [ ] **Étape 2 : les voir échouer.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npm test` → `ENOENT … src/app/lier/page.tsx`.
- [ ] **Étape 3 : implémenter** la page, la feuille, l'import, l'entrée du menu et la redirection de `boot`.
- [ ] **Étape 4 : les voir passer, puis construire.** `[WEB]` → `fail 0` deux fois, `tsc` code 0. Puis `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npx next build` → code 0, et la liste `Route (app)` contient la ligne `○ /lier` (page statique : pas de `useSearchParams` hors `<Suspense>`). `next build` réécrit `tsconfig.json` et régénère `next-env.d.ts` : `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git status --short -- services/web/tsconfig.json services/web/next-env.d.ts` → exactement ` M services/web/tsconfig.json` (colonne d'index vide : modifié, jamais indexé ; `next-env.d.ts` est ignoré par `.gitignore`), et `git diff --cached --name-only` ne liste aucun des deux.
- [ ] **Étape 5 : vérifier dans un navigateur.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npx next dev -p 3001` en arrière-plan ; avec Playwright (MCP), ouvrir `http://localhost:3001/lier?code=bcdf-ghjk` après avoir posé `page.route('**/api/v1/**', …)` (via `browser_run_code_unsafe`) pour trois scénarios : `/users/me` 401 (bouton Discord, code gardé dans `sessionStorage['greg.lier.pending']`) ; connecté non propriétaire (`/overlay/me` `is_owner:false` → message neutre) ; propriétaire (`lookup` → nom et âge, serveurs, « Autoriser » → « C’est fait, Sire. Retournez à votre jeu. », liste et « Délier » avec dialogue). Vérifier à 375 px de large (aucun défilement horizontal), le focus doré au clavier, et qu'aucun POST ne part avant le clic. Arrêter le serveur ; `git status` ne doit lister ni `tsconfig.json` ni `next-env.d.ts` dans ce qui est ajouté.
- [ ] **Étape 6 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/web/src/app/lier/page.tsx services/web/src/components/Lier/lier.css services/web/src/app/globals.css services/web/src/components/Header/AccountMenu.tsx services/web/src/hooks/usePlayer.ts services/web/tests/lier-contract.test.mjs && git commit -m "feat(web): page /lier (autoriser, refuser, délier) et entrée Appareils liés du propriétaire"`

---

### Tâche 13 : site, `expected` sur retirer / déplacer / jouer maintenant, et `STALE`

**Files:**
- Modify : `services/web/src/lib/playerUtils.ts` (type et fonction près de `fingerprint` l. 97 ; `errorCopy` l. 302-338)
- Modify : `services/web/src/lib/api.ts` (`queueRemove`, `move`, `playAt` l. 202-217 ; type en fin de fichier)
- Modify : `services/web/src/theme/copy.extra.ts` (`error.STALE` dans la section `error` l. 180-187)
- Modify : `services/web/src/hooks/usePlayer.ts` (`sendMutation` l. 90-105, `onRefused` l. 116-128)
- Create : `services/web/tests/queue-expected.test.mjs`

**Interfaces:**
- Produces :
  - `playerUtils.QueueExpected = { url: string; added_by: string | null; ts: number | null }`
  - `playerUtils.expectedOf(t: Track | null | undefined): QueueExpected | undefined` : sans `raw` objet → `undefined` ; sinon `url = String(raw.url ?? t.url ?? '')`, `added_by = raw.added_by ?? raw.requested_by` en chaîne ou `null`, `ts` nombre fini ou `null`.
  - `errorCopy` : code `STALE` → `{ key: 'error.STALE', path: 'error.STALE.text' }` (avant le test `DECK_ERRORS`).
  - `EXTRA.error.STALE = { text: 'La file a bougé entre-temps\u00a0: rien n’a changé. Réessayez.' }`
  - `api.queueRemove(guildId, userId, index, expected?: QueueExpected)`, `api.move(guildId, userId, src, dst, expected?)`, `api.playAt(guildId, userId, index, expected?)` : `expected` dans le corps seulement s'il est défini (`type QueueExpected = import('./playerUtils').QueueExpected;` en fin de fichier, comme `SearchResult`).
  - `sendMutation` : `remove` → `expectedOf(q[i])`, `move` → `expectedOf(q[mv.src])`, `playAt` → `expectedOf(q[i])`. `onRefused` : `errorCode(e).toUpperCase() === 'STALE'` → `void refreshPlaylist({ quiet: true }).catch(() => {})`, en plus de l'annonce.

- [ ] **Étape 1 : écrire les tests qui échouent** (`tests/queue-expected.test.mjs`) :

```js
const { expectedOf, errorCopy } = await loadTs('../src/lib/playerUtils.ts');
const { api } = await loadTs('../src/lib/api.ts');
const { tx } = await loadTs('../src/theme/copy.extra.ts');
const E = { url: 'https://www.youtube.com/watch?v=aaaaaaaaaaa', added_by: '7', ts: 1700000000 };

test('expectedOf : url, added_by, ts du titre tel que le bot l’a', () => {
  assert.deepEqual(expectedOf({ key: 'k', url: 'x', title: 'T', raw: { ...E } }), E);
  assert.deepEqual(expectedOf({ key: 'k', url: 'x', title: 'T', raw: { url: null, requested_by: 7 } }), { url: 'x', added_by: '7', ts: null });
  assert.equal(expectedOf({ key: 'k', url: 'x', title: 'T' }), undefined); assert.equal(expectedOf(undefined), undefined);
});

test('api : expected envoyé seulement s’il est donné', async () => {
  for (const [fn, path, body] of [
    [() => api.queueRemove('42', '7', 2, E), '/api/v1/queue/remove', { index: 2, expected: E }],
    [() => api.move('42', '7', 3, 0, E), '/api/v1/player/move', { src: 3, dst: 0, expected: E }],
    [() => api.playAt('42', '7', 1, E), '/api/v1/playlist/play_at', { index: 1, expected: E }],
    [() => api.queueRemove('42', '7', 2), '/api/v1/queue/remove', { index: 2 }]]) {
    const { calls } = await capture(fn);
    assert.equal(calls[0].path, path); assert.deepEqual(calls[0].body, { ...body, guild_id: '42', user_id: '7' });
  }
});

test('409 STALE : « La file a bougé », texte typographié', () => {
  const e = { status: 409, payload: { ok: false, error: 'STALE', message: 'La file a bougé : réessayez.' } };
  assert.deepEqual(errorCopy(e, { action: 'move' }), { key: 'error.STALE', path: 'error.STALE.text' });
  assert.equal(tx('error.STALE.text'), 'La file a bougé entre-temps\u00a0: rien n’a changé. Réessayez.');
});

test('usePlayer : expected sur les trois mutations, relecture sur STALE', () => {
  const src = read('src/hooks/usePlayer.ts');
  assert.match(src, /api\.queueRemove\(gid, uid, i, expectedOf\(q\[i\]\)\)/);
  assert.match(src, /api\.move\(gid, uid, mv\.src, mv\.dst, expectedOf\(q\[mv\.src\]\)\)/);
  assert.match(src, /api\.playAt\(gid, uid, i, expectedOf\(q\[i\]\)\)/);
  const refused = src.slice(src.indexOf('onRefused:'), src.indexOf('\n});', src.indexOf('onRefused:')));
  assert.match(refused, /'STALE'/); assert.match(refused, /refreshPlaylist\(\{ quiet: true \}\)/);
});
```
  (`capture` comme en tâche 11 ; `read` de `_contract.mjs`.)
- [ ] **Étape 2 : les voir échouer.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npm test` → `expectedOf is not a function`.
- [ ] **Étape 3 : implémenter** `QueueExpected`, `expectedOf`, la branche `STALE` d'`errorCopy`, `error.STALE`, les paramètres d'`api` et les deux points de `usePlayer.ts`.
- [ ] **Étape 4 : les voir passer.** `[WEB]` → `fail 0` deux fois (`api.test.mjs` « api.move » reste vert : sans `expected`, corps inchangé), `tsc` code 0.
- [ ] **Étape 5 : commit.** `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git add services/web/src/lib/playerUtils.ts services/web/src/lib/api.ts services/web/src/theme/copy.extra.ts services/web/src/hooks/usePlayer.ts services/web/tests/queue-expected.test.mjs && git commit -m "feat(web): retirer, déplacer et jouer maintenant nomment leur titre ; 409 STALE relit la file"`

---

### Tâche 14 : suites complètes, relecture indépendante et PR

**Files:** aucun fichier de code ; la PR seulement.

- [ ] **Étape 1 : suites complètes.** `[API] tests` → `722 + nouveaux passed`, 0 failed ; `[BOT] tests` → `270 + nouveaux passed`, 0 failed ; `[WEB]` → `npm test` `fail 0`, `GREG_TEST_TRANSPILE=1 npm test` `fail 0`, `npx tsc --noEmit` code 0. Construction du site : `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin/services/web && npx next build` → code 0, la liste `Route (app)` contient `○ /lier` ; puis `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && git status --short -- services/web/tsconfig.json services/web/next-env.d.ts` → exactement ` M services/web/tsconfig.json` (non indexé ; `next-env.d.ts` ignoré), et `git diff --cached --name-only` ne liste aucun des deux. Ruff sur les fichiers Python créés : `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && uvx ruff check --select E4,E7,E9,F --ignore F811 services/api/api/services/overlay_tokens.py services/api/api/routes/overlay.py services/api/tests/overlay_fakes.py services/api/tests/test_overlay_tokens.py services/api/tests/test_identity.py services/api/tests/test_overlay_routes.py services/api/tests/test_overlay_socket.py services/api/tests/test_player_event_relay.py services/api/tests/test_queue_stale.py services/api/tests/test_csrf.py services/bot/tests/test_overlay_bot.py services/bot/tests/test_queue_expected.py services/bot/tests/test_queue_item_matches.py` → `All checks passed!`.
- [ ] **Étape 2 : relecture indépendante** (spec §7) par un agent qui n'a pas écrit le code, sur `git diff main...HEAD -- services packages`, avec pour grille les Global Constraints et la Review Focus. Corriger, relancer l'étape 1, committer chaque correctif avec ses chemins explicites.
- [ ] **Étape 3 : vérifier ce qui part.** `git status --short` : `services/web/tsconfig.json` reste modifié et non indexé ; aucun fichier interdit dans `git log main..HEAD --name-only`. `git log main..HEAD --format=%B | grep -iE "claude|co-authored|generated with"` ne rend rien.
- [ ] **Étape 4 : comparer les origines du site (lecture seule, avant la PR).** La garde CSRF de la tâche 1 n'admet que `WEB_ORIGINS` = `CORS_ORIGINS` ∪ `WEB_URL` du service API ; un domaine du site absent de cette liste recevrait 403 `CSRF_FAILED` sur toute action après le déploiement (le proxy Next transmet l'`Origin` du navigateur).
  - `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && railway domain list --service WEB` → tableau des domaines publics du site (constaté le 2026-11-25 : une ligne `gregleconsanguin.up.railway.app`, type `service`). Jamais `railway domain` sans sous-commande : il crée un domaine.
  - `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && railway variable list --service API --json | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const v=JSON.parse(s);for(const k of ['WEB_URL','CORS_ORIGINS'])console.log(k+' = '+(v[k]??'(absente)'))})"` → deux lignes, les seules valeurs affichées (des adresses publiques, aucun secret ; constaté le 2026-11-25 : l'origine de `WEB_URL` est `https://gregleconsanguin.up.railway.app`, `CORS_ORIGINS = (absente)`). Jamais `--kv` ni `--json` sans ce filtre : ils impriment les secrets du service.
  - Règle : pour chaque domaine `d` du service WEB, l'origine `https://d` doit égaler l'origine de `WEB_URL` ou une entrée de `CORS_ORIGINS`. Résultat → ligne « Origines du site » du corps de la PR (étape 5) et, s'il manque une origine, question (b) de l'étape 7. La session ne règle rien.
- [ ] **Étape 5 : écrire le corps de la PR.** Avec l'outil Write, dans le scratchpad de la session qui exécute ce plan (le « Scratchpad directory » de son invite système, jamais dans le dépôt) : fichier `pr-overlay-api.md`. Contenu exact ci-dessous, où `{API}`, `{BOT}` et `{WEB}` sont les décomptes lus à l'étape 1, et `{ORIGINES}` l'une des deux phrases données après le bloc :

```markdown
## Résumé

L'appli Overwolf de Paul obtient une entrée sûre dans Greg : un code d'appareil autorisé sur le site (`/lier`), un jeton porteur révocable valable pour le lecteur et le socket, les données qui lui manquaient (serveurs, `player_event`, `guild_id` des ticks) et une garde `expected` contre une file qui a bougé.

### API (`services/api`)
- Garde CSRF sur les routes de session et sur `/auth/logout` : corps JSON exigé, `Origin` ou `Referer` du site. Un formulaire envoyé depuis un autre site reçoit 403 `CSRF_FAILED` sans atteindre le bot.
- `OVERLAY_ORIGINS` stricte (`overwolf-extension://` suivi de l'UID), séparée des origines du site : l'appli passe CORS et Socket.IO, jamais la garde CSRF.
- Magasin Redis `overlay_tokens` : codes d'appareil RFC 8628 (usage unique, `slow_down`), jetons `greg_ow_…` stockés en sha256 seulement, révocation, limites de débit (par IP d'abord, puis plafond global ; compteurs toujours dotés d'une échéance).
- `/overlay/device` et `/overlay/token` n'acceptent qu'un corps JSON.
- Identité « session ou porteur » sur le lecteur, l'historique et la recherche (désormais authentifiée, `limit` borné à 10). Le chansonnier reste en session seule et refuse tout en-tête `Authorization`.
- Routes `/overlay/*` : `device`, `device/lookup`, `device/approve` (propriétaire seul), `token`, `me`, `tokens`, `tokens/revoke`, `logout`, `guilds`.
- Socket.IO : jeton dans `auth` du CONNECT, revérifié à chaque `join_guild` ; une révocation déconnecte les sockets du jeton.
- Relais de `player_event`, `guild_id` dans les ticks, `expected` transmis au bot, 409 `STALE`.

### Bot (`services/bot`)
- Action `user_guilds` en lecture seule (serveurs communs, salons vocaux, lecture en cours).
- `greg:player:event` après chaque commande réussie qui change l'état (auteur, titre lu avant le changement).
- Retirer, déplacer et jouer maintenant vérifient l'élément attendu : `STALE` sans rien changer.

### Site (`services/web`)
- Page `/lier` : saisir le code, voir l'appareil, choisir le serveur par défaut, autoriser ou refuser ; liste des appareils liés et « Délier ». Retour sur `/lier` après la connexion Discord, une seule fois.
- Entrée « Appareils liés » dans le menu du compte, pour le seul propriétaire.
- `expected` sur retirer, déplacer et jouer maintenant ; un 409 `STALE` relit la file.

## Écarts assumés par rapport à la spec
- Usage unique du code par `SET … XX GET KEEPTTL` : un code déjà servi donne 409 `ALREADY_USED`, distinct d'un code expiré.
- Serveur par défaut validé par `user_guilds` ; champ `is_owner` ajouté à `/overlay/me`.
- Redis indisponible pendant la vérification d'un jeton : 503 `STORAGE_UNAVAILABLE` (ou `connect_error` du même nom), jamais 401.
- La recherche demande une session ou un jeton ; un formulaire sur le chansonnier reçoit 403 `CSRF_FAILED` au lieu de 400.
- `expected` mal formé : 400 ; index hors bornes avec `expected` : `STALE` ; marge de `slow_down` : 1 s ; corps non JSON sur `/overlay/device` ou `/overlay/token` : 400 `INVALID_REQUEST`.

## Vérifications
- API : {API} passed, 0 failed.
- Bot : {BOT} passed, 0 failed.
- Site : `npm test` pass {WEB}, fail 0, en natif et avec `GREG_TEST_TRANSPILE=1` ; `tsc --noEmit` et `next build` sans erreur (`/lier` statique).
- Ruff sans alerte sur les fichiers Python créés. Relecture indépendante faite, correctifs inclus.

## Avant de fusionner
1. Confirmer l'UID `ahnflfbohhimdmoeoogpiohdmjdokiioleialagk` dans `overwolf://packages`.
2. Sur le seul service API de Railway : `GREG_OWNER_ID` (même valeur que BOT DISCORD) et `OVERLAY_ORIGINS=overwolf-extension://ahnflfbohhimdmoeoogpiohdmjdokiioleialagk`.
3. Origines du site : {ORIGINES}
4. Après le déploiement : se connecter sur le site, ouvrir `/lier` avec un code de l'appli, autoriser, vérifier « Appareils liés », puis délier.

La fusion déploie sur Railway : elle attend l'accord de Paul.
```

  `{ORIGINES}` vaut, selon l'étape 4 : « chaque domaine du service WEB (`<domaines>`) est couvert par `WEB_URL` du service API ; rien à ajouter. » ou « à ajouter dans `CORS_ORIGINS` du service API avant la fusion : `<origines manquantes, séparées par des virgules>` ; sans cela, toute action depuis ces domaines recevra 403 `CSRF_FAILED`. »
- [ ] **Étape 6 : pousser et ouvrir la PR.** `PR_BODY` = le « Scratchpad directory » de la session, écrit en barres obliques avant (forme `C:/Users/Paul/AppData/Local/Temp/claude/…/scratchpad` ; `gh.exe` les accepte et Git Bash ne les convertit pas), suivi de `/pr-overlay-api.md` :
  `cd /c/Users/Paul/Documents/Codage/GregLeConsanguin && PR_BODY='<Scratchpad directory, barres obliques avant>/pr-overlay-api.md' && test -s "$PR_BODY" && ! grep -qiE "claude|anthropic|co-authored|generated with|\{(API|BOT|WEB|ORIGINES)\}" "$PR_BODY" && git push origin feat/overlay-overwolf && gh pr create --base main --head feat/overlay-overwolf --title "Overlay Overwolf : liaison par code, jeton porteur et données de l'appli" --body-file "$PR_BODY"` → l'URL de la PR (`test -s` exige le fichier de l'étape 5 ; le `grep` refuse un corps qui mentionnerait une IA ou garderait un champ non rempli). Le chemin est celui du fichier écrit à l'étape 5, jamais un chemin inventé.
- [ ] **Étape 7 : demander à Paul.** Ne pas fusionner. Lui demander, en questions séparées : (a) son accord pour régler `GREG_OWNER_ID` et `OVERLAY_ORIGINS` sur le service API Railway ; (b) seulement si l'étape 4 a trouvé une origine du site absente : qu'il ajoute (ou nous autorise à ajouter) `CORS_ORIGINS=<origines manquantes>` sur le service API ; (c) son accord pour fusionner la PR. Rien n'est réglé ni fusionné sans un « oui » explicite.

---

## Auto-relecture (contre la spec)

**Couverture.**
- §3.1 identité, `flask.g`, routes lecteur / historique / recherche, chansonnier en session seule : tâche 4.
- §3.2 CSRF (formulaire tiers, JSON du site, logout) : tâche 1 ; origine de l'appli refusée par la garde : tâche 2.
- §3.3 origines : tâche 2 ; domaines publics du site comparés à `WEB_URL` avant la fusion : tâche 14, étape 4.
- §3.4 magasin et routes : tâches 3 et 5 (codes, usage unique, `slow_down`, émission atomique, propriétaire seul, révocation, `/overlay/guilds`, limites de débit).
- §3.5 socket : tâche 6.
- §3.6 `expected`, `guild_id` des ticks, activité : tâches 9, 10 et 13 ; tâches 8 et 10.
- §4.1 à §4.3 bot : tâches 7, 8, 9.
- §5 site : tâches 11, 12, 13.
- §7 vérification : chaque puce a son test ; « relecture indépendante » à l'étape 2 de la tâche 14 ; « en jeu, par Paul » relève du plan B.

**Balayage des étapes.** Chaque tâche a un test qui échoue, une commande, une implémentation désignée par signatures, une commande verte et un commit à chemins explicites. Aucun « TBD ».

**Cohérence des types.** `Identity.uid` est un `int` partout. `tid`, les ids des serveurs et le `guild_id` des ticks et de `player_event` sont des chaînes. Le `guild_id` d'un état complet reste l'entier du bot. `default_guild_id` vaut une chaîne ou `null`. Les horodatages sont en secondes entières, sauf `at_ms` et `relay_at_ms` en millisecondes. `expected` garde la même forme dans le site, l'API et le bot.

**Écarts assumés par rapport au texte de la spec** (à signaler à Paul et au plan B) :
- **Usage unique.** Il passe par `SET … "used" XX GET KEEPTTL` plutôt que par un GETDEL. Avec GETDEL, un code déjà servi ne se distingue plus d'un code expiré, et le contrat promet 409 `ALREADY_USED`.
- **Serveur par défaut.** Il est validé par `user_guilds` plutôt que par `get_state`. `get_state` accepte sans contrôle un serveur où Greg est absent.
- **Champ `is_owner`.** Il est ajouté à `/overlay/me` (ajout seul), pour que le site sache s'il montre « Appareils liés ».
- **Redis indisponible pour un jeton.** La réponse est 503 `STORAGE_UNAVAILABLE`, ou `connect_error` `"STORAGE_UNAVAILABLE"` sur le socket.
- **Recherche authentifiée.** La recherche demande maintenant une session ou un jeton. Elle était publique : `test_search.py` passe donc sur `logged_client`.
- **Formulaire du chansonnier.** Un corps de formulaire sur une mutation du chansonnier reçoit 403 `CSRF_FAILED`, et non plus 400. Une ligne de `test_library_routes.py` change en conséquence.
- **Hors bornes avec `expected`.** Un index hors bornes accompagné de `expected` donne `STALE`.
- **`expected` mal formé.** Il donne 400 `invalid expected`.
- **`device_code` absent ou inconnu.** Il donne `expired_token` (dans un corps JSON).
- **Corps non JSON sur `/overlay/device` et `/overlay/token`.** 400 `INVALID_REQUEST`, avant tout compteur : un formulaire ou un `text/plain` d'une page tierce n'entame pas les seaux.
- **Ordre des limites de démarrage.** Par IP d'abord ; seules les requêtes admises comptent dans le plafond global.
- **Routes en session seule.** Un en-tête `Authorization` y donne 401, cookie ou pas.
- **Marge de `slow_down`.** Elle est de 1 s.

**Review Focus.** Les cinq lignes ont chacune un test nommé dans la tâche qui possède le code : tâches 3, 4, 6, 7, 8, 10, 11, 12.

**Proportion.** Les étapes donnent des signatures, des valeurs et des tests, pas de corps de fonction. Sont fixés en entier : les textes du site (exigés exacts par la spec et le deck) et le corps de la PR ; et, parce que les signatures ne les déterminent pas, la règle de `slow_down`, le mécanisme d'usage unique, le compteur de débit (`MULTI` · `INCR` · `EXPIRE NX` · `EXEC`, IP avant global) et le verrou de `disconnect_token` (vidé sous le verrou, déconnexion hors du verrou).
