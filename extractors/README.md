# YouTube — ce qu’il faut savoir (PO_TOKEN, cookies, clients, erreurs courantes)

Cette section explique comment **Greg le Consanguin** lit YouTube de façon robuste, pourquoi ça casse parfois, et quoi faire quand ça casse.

## Vue d’ensemble

* **Deux chemins de lecture**

  * **Direct** (préféré) : on récupère une URL audio “signée” via `yt-dlp` et on la passe **directement** à FFmpeg. Ultra-léger, très peu de latence.
  * **Pipe** (secours) : `yt-dlp` télécharge le flux et l’envoie **en pipe** à FFmpeg. Plus stable quand YouTube refuse l’accès au direct (403/410/429), mais un peu plus lourd.
* **PO_TOKEN** : certains “clients” YouTube (iOS/Android/web) exigent un **Proof-Of-Origin token** pour générer les URLs directes.

  * On tente d’abord un **fetch automatique** (Playwright) → `extractors/token_fetcher.py`.
  * Sinon, on utilise un **token en .env** (`YT_PO_TOKEN`/`YTDLP_PO_TOKEN`) si vous en fournissez un.
  * S’il n’y a **aucun** token valide, beaucoup de vidéos continueront à marcher (surtout via `web_mobile`), mais **pas toutes**.
* **Cookies** : pour lever les restrictions (âge, région, quota), vous pouvez fournir des **cookies** de votre propre session YouTube.

  * Le module supporte **cookies depuis le navigateur**, **fichier cookies**, ou **base64 en .env**.

## Variables d’environnement utiles

* **PO token**

  * `YT_PO_TOKEN` ou `YTDLP_PO_TOKEN` : token brut (sans préfixe). Le code ajoute tout seul `ios.gvs+`, `android.gvs+`, `web.gvs+`.
  * Optionnel : `YT_PO_TOKEN_PREFIXED` si vous voulez donner un token déjà préfixé (ex: `ios.gvs+…`).
* **Cookies**

  * `YTDLP_COOKIES_BROWSER` : ex. `chrome:Default` (Windows) ou `chrome:Profile 1`.
  * `YOUTUBE_COOKIES_PATH` : chemin vers un fichier cookies (format Netscape).
  * `YTDLP_COOKIES_B64` : contenu **base64** de votre fichier cookies (pratique sur Railway).
* **Clients / formats / réseau**

  * `YTDLP_CLIENTS` : ordre d’essai des clients, ex. `ios,android,web_creator,web,web_mobile`.
  * `YTDLP_FORMAT` : chaîne de formats, ex. `bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/251/140/18/best[protocol^=m3u8]/best`.
  * `YTDLP_FORCE_IPV4=1` : force IPv4 (utile sur host avec IPv6 capricieux).
  * `YTDLP_HTTP_PROXY` (ou `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`) : proxy unique propagé à `yt-dlp` et FFmpeg.
  * `YTDLP_FORCE_UA` : User-Agent forcé si besoin (rare).

## Comment fournir des cookies

### Option A — depuis le navigateur (le plus simple en local)

```bash
# Exemple : utiliser le profil "Default" de Chrome
set YTDLP_COOKIES_BROWSER=chrome:Default
python -m extractors.youtube --test direct --url "https://www.youtube.com/watch?v=..."
```

### Option B — via un fichier cookies (Netscape)

1. Exportez vos cookies `youtube.com` (extension navigateur type “Get cookies.txt”).
2. Déposez le fichier à la racine (ex. `youtube.com_cookies.txt`) ou donnez un chemin via :

   * `YOUTUBE_COOKIES_PATH=/app/youtube.com_cookies.txt`

### Option C — via **base64** (idéal sur Railway)

* **Linux/macOS** :

  ```bash
  base64 -w0 youtube.com_cookies.txt
  ```
* **Windows (PowerShell)** :

  ```powershell
  [Convert]::ToBase64String([IO.File]::ReadAllBytes("youtube.com_cookies.txt"))
  ```
* Collez la chaîne en `.env` :

  ```
  YTDLP_COOKIES_B64="...votre_base64..."
  ```

> ⚠️ Vos cookies sont **vos** identifiants de session. Protégez-les, ne les commitez jamais.

## Playwright (PO_TOKEN auto)

* Installation côté dev (Windows) :

  ```powershell
  python -m pip install playwright
  python -m playwright install chromium
  ```
* Débogage visuel :

  ```
  PLAYWRIGHT_HEADLESS=0
  ```
* Le fetch automatique est **thread-safe** (pas d’API sync dans un event-loop asyncio).
  Le code essaie plusieurs URLs : `m.youtube.com`, `www.youtube.com`, `music.youtube.com`, et clique les consentements si besoin.

## Erreurs courantes & correctifs

| Message / Symptôme                                 | Cause probable                                                 | Correctifs recommandés                                                                                                                                  |
| -------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Requested format is not available`                | Le format choisi n’existe pas pour cette vidéo / ce client     | L’extracteur retente déjà **plusieurs clients** et finit par **itag=18** en pipe. Vous pouvez aussi ajuster `YTDLP_FORMAT`.                             |
| `403 Forbidden` en direct                          | URL signée qui requiert PO_TOKEN/cookies, ou hotlinking bloqué | L’extracteur bascule **auto en PIPE**. Ajoutez **cookies** et/ou **PO_TOKEN**, ou changez l’ordre des **clients** (`web_mobile` est souvent permissif). |
| `410 Gone`                                         | URLs expirées / client non autorisé                            | Même solution que 403.                                                                                                                                  |
| `429 Too Many Requests`                            | Rate-limit YouTube                                             | Cookies de votre compte, **limiter le débit** (`--limit-rate` déjà supporté), proxy IP, attendre.                                                       |
| “Veuillez vous connecter pour confirmer votre âge” | Gated 18+                                                      | Fournir des **cookies** valides de votre compte (A).                                                                                                    |
| “La vidéo n’est pas dispo dans votre pays”         | Geo-block                                                      | Cookies + Proxy (**responsablement**), ou vidéo alternative.                                                                                            |
| “Le direct marche chez moi mais pas sur Railway”   | FS éphémère / pas de profilm navigateur                        | Utilisez **`YTDLP_COOKIES_B64`** pour embarquer les cookies.                                                                                            |
| “Playwright… inside asyncio loop”                  | API sync utilisée dans un event-loop                           | Notre fetcher tourne en **thread** pour l’éviter (OK). Assurez-vous d’avoir bien remplacé les fichiers.                                                 |

## Conseils de prod

* **Ordre des clients** : par défaut `ios,android,web_creator,web,web_mobile`.

  * `web_mobile` est souvent celui qui **passe** quand les autres échouent (moins strict), mais qualité un peu inférieure.
  * `ios`/`android` peuvent exiger un **PO_TOKEN** plus souvent.
* **PIPE vs Direct** : le **Direct** est top quand il marche. En cas de doute (**403/410/429**), laissez l’auto-fallback en **PIPE**.
* **Latence** : le direct est le plus bas. Le preflight FFmpeg (2s) est seulement un **test rapide**, pas la lecture finale.
* **Proxy & IPv4** : si votre host aime l’IPv6 mais pas YouTube, forcez `YTDLP_FORCE_IPV4=1`.
* **Secrets** : **ne committez jamais** vos tokens/cookies. Utilisez les variables d’env du provider (Railway).

## Tests rapides

* **Direct**

  ```bash
  python -m extractors.youtube --test direct --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ```
* **Pipe**

  ```bash
  python -m extractors.youtube --test pipe --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ```

Vous verrez dans les logs :

* le client sélectionné (`client=ios → no direct url`, puis fallback),
* si un **PO_TOKEN** a été trouvé/utilisé,
* si on a basculé en **PIPE**,
* et les en-têtes **FFmpeg** utilisés (Referer/Origin/UA).

## Limites & conformité

* YouTube **change régulièrement** ses règles (clients, formats, headers, tokens). Le module est pensé pour **dégrader proprement** (fallbacks) et vous donner des **leviers** (tokens, cookies, clients).
* Utilisez cette intégration **dans le respect** des **Conditions d’utilisation** de YouTube et des droits d’auteur. Ne contournez pas de DRM/paywalls.
  Les cookies/PO_TOKEN ne servent qu’à **accéder à vos propres droits d’accès** (comme dans votre navigateur).