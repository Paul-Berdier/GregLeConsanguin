# Web player « Nuit gothique » : spécification d'intégration

- Date : 2026-09-26
- Statut : proposée, en attente de validation de Paul
- Branche : `feat/web-nuit-gothique`, basée sur `fix/playlist-links-audit`, dont la PR #13 est en cours
- Direction choisie : n° 3, « Nuit gothique ». Le prototype de référence est `proto-gothique/index.html`, et son `DESIGN.md` fait foi pour les valeurs.

## 1. Décision

Paul a comparé 3 directions artistiques, issues d'une recherche en 6 volets puis de prototypes jugés et affinés. Il a retenu **Nuit gothique** :

- un lecteur sombre et contemporain, avec **un seul geste gothique** : une rosace de vitrail posée sur un portail de pierre (rendu Blender) ;
- la rosace est **vitrée aux couleurs de la miniature du morceau en cours** ;
- son anneau extérieur sert d'horloge de lecture.

Le reste de l'interface reste sobre et rapide.

**Casting, correction de Paul (qui fait foi) :** Greg n'est que le **valet du Roi**, à la façon de Jacquouille la Fripouille. **Le Roi, c'est l'utilisateur connecté.**

| Appartient au Roi | Appartient à Greg |
|---|---|
| La couronne (sur l'avatar de l'utilisateur) | Le bonnet à grelots |
| Le sceau à son initiale (sur ses propres titres) | La livrée, le jeton d'étain |
| Le mot « ordre » | Son portrait (Charles II), présenté comme celui d'un valet |

Les autres membres du serveur forment la **Cour**.

Les textes viennent du deck `copy-v2.json` (676 chaînes vérifiées). Greg vouvoie le Roi, et les faits passent avant les répliques.

## 2. Objectifs et non-objectifs

**Objectifs**

1. **Fluidité.**
   - Toutes les actions ont un retour immédiat (mise à jour optimiste), et reviennent en arrière si le serveur refuse.
   - N'animer que `transform` et `opacity`.
   - Utiliser les tokens de mouvement de `research/motion.md` : durées, courbes et ressorts `linear()`.
   - Respecter `prefers-reduced-motion`.
2. **Look et clarté.**
   - Identité Nuit gothique : tokens de couleur, 4 polices sous licence OFL, portail de pierre, rosace.
   - Hiérarchie claire et textes du deck v2.
3. **Ergonomie de la file.**
   - Glisser-déposer par la poignée ou la miniature, actions rapides (jouer maintenant, mettre en suivant, retirer).
   - Annuler depuis la notification ou avec Ctrl+Z.
   - Heure estimée de chaque titre et « fin vers 22 h 47 ».
   - « Souvent demandés ici » sous la file.

**Non-objectifs, car ils demandent un changement côté bot**

- Chercher une position en cliquant sur l'anneau : le bot n'a pas de commande `seek`, donc l'horloge est **en lecture seule**. Le survol affiche le temps.
- Annuler un « stop » ou un « jouer maintenant » en restaurant la position : il faudrait que l'API accepte une position de départ. Seul **l'annulation d'un retrait ou d'un ajout** est livrée.
- La limite de la « zone royale » pendant le glisser, qui attend un champ `is_priority` par item. Un refus du bot déclenche un retour en place, déjà géré.

## 3. Architecture front

`page.tsx`, un seul fichier de 671 lignes, est découpé en composants :

```
services/web/src/
  app/page.tsx                 assemblage des zones
  app/globals.css              tokens (couleurs, ombres, mouvement), plaques « plombées »
  components/Header/           Wordmark (SVG, sans couronne), SearchBar, GuildPicker, KingAvatar (couronne Blender)
  components/Stage/            Portal (pierre 9-slice), Rose (client + worker), Clock (anneau lecture seule),
                               NowPlaying (titre Grenze, demandeur), Transport (rondelle de verre), NightState
  components/Queue/            QueuePanel, QueueRow, DragLayer, RowActions, Suggestions (« Souvent demandés »)
  components/History/          HistoryPanel (rangs dorés, top 3)
  components/Herald/           Toasts « Le Héraut » (pile Sonner-like, annuler, fusion ×N)
  hooks/usePlayer.ts           store et actions optimistes (voir §5)
  hooks/useFlip.ts             FLIP des listes via l'API Web Animations (WAAPI), pas de bibliothèque
  lib/rose/                    rose-worker.ts (repris du prototype), palette.ts (extraction depuis la miniature), geometry.ts
  lib/motion.ts                tokens de mouvement exposés au JS (durées, courbes)
  lib/titles.ts                cleanTitle / parse (titres YouTube nettoyés, titre brut en info-bulle)
  theme/copy.ts                sous-ensemble typé de copy-v2.json, jeton {sire}
public/
  gothique/                    stone-rose-2048.webp, stone-frame-640.webp, crown-*.avif/webp, grain, seals, greg-face
  fonts/                       Grenze Gotisch, Grenze, Alegreya Sans, Alegreya Italic (woff2, sous-ensembles + U+202F)
  licenses/                    textes OFL et LICENSES.md (portraits : domaine public, rendus Blender : CC0)
```

Polices : `next/font/local`. Aucune nouvelle dépendance npm. Le mouvement passe par CSS et WAAPI, comme dans le prototype.

## 4. La scène

- **Portail et rosace.**
  - Une seule variable, R (le rayon du vitrail), pilote la mise en page : largeur de la vidéo = R / 0,52, et couronne visible de 70 % à 36 % de R selon la hauteur disponible (DESIGN §12.4).
  - Le calcul se fait dans `useStageLayout` (ResizeObserver). Le résultat est testé en test unitaire sur les 8 tailles d'écran du tableau.
- **Worker de rosace.** Il reprend `rose-worker.js` du prototype :
  - il peint sur un `OffscreenCanvas`, hors du fil principal ;
  - il renvoie une `ImageBitmap` affichée dans un canvas `bitmaprenderer` ;
  - la fenêtre du **prochain** titre est préparée pendant les temps morts.
- **Palette.** Elle est tirée de la miniature `i.ytimg.com`, qui renvoie `Access-Control-Allow-Origin: *` :
  - histogramme de teinte pondéré par la saturation ;
  - vitrail en grisaille si aucune teinte n'est exploitable ;
  - la couleur dominante alimente `--lumiere`.
- **Horloge.** 48 panneaux sur l'anneau : ceux déjà joués sont allumés, le panneau courant est le plus lumineux. Le masque est mis à jour **une fois par panneau** (environ toutes les 11 s), jamais à chaque image.
- **Nuit.** Quand rien ne joue, en chargement ou hors connexion :
  - la rosace entière apparaît au clair de lune ;
  - l'oculus au centre contient la couronne qui attend le Roi (rien en lecture), la couronne qui tourne (chargement) ou le portrait de Greg en bonnet (hors connexion).
- **YouTube.** L'image fixe (le poster) reste au-dessus du lecteur YouTube persistant jusqu'à PLAYING + 3,5 s, et pendant la pause (`tech.md` §5.3).

## 5. Fluidité et file

- **Actions optimistes** dans `usePlayer` : skip, retirer, déplacer, jouer maintenant, mettre en suivant, pause.
  - La modification est appliquée localement tout de suite, sur une copie de l'état.
  - Elle est réconciliée avec la réponse de l'API et les poussées Socket.IO.
  - En cas d'erreur, retour en arrière avec un message du Héraut.
  - Les poussées serveur reçues pendant une action en vol sont mises en mémoire tampon (lab `motion.md`).
- **Chorégraphies.** Durées et courbes proviennent de DESIGN §5 et §12.6 :
  - *Le Couronnement* au changement de titre : la miniature vole 420 ms, les légendes se croisent, la rosace se rallume à l'atterrissage, avec un mode rapide si on enchaîne les skips.
  - *Le Sceau* sur ton propre ajout : le sceau du Roi, à ton initiale, se pose sur la ligne.
  - *La Révérence* à la pause.
- **Glisser-déposer** en pointer events : seuil de 4 px, défilement automatique, Échap pour annuler, retour en ressort et petite secousse si le serveur refuse (`PRIORITY_FORBIDDEN`).
- **Clavier** : taper au clavier va dans la recherche ; `Espace`, `Maj+→` et `Maj+←`, `/`, `?`, `Ctrl+Z` ; tabindex itinérant dans les listes ; `Alt+↑↓` pour déplacer. Un interrupteur désactive les raccourcis (WCAG 2.1.4).

## 6. Étapes (un commit et un push par étape, chaque étape vérifiée)

1. **Fondations.**
   - Contenu : tokens, polices, assets dans `public/`, découpage de `page.tsx` à comportement identique, en-tête (wordmark, recherche, serveur, avatar couronné), textes v2.
2. **Scène.**
   - Contenu : portail de pierre, worker de rosace et palette, horloge en lecture seule, états de nuit, titre et transport.
3. **File.**
   - Contenu : lignes, actions rapides, glisser-déposer, actions optimistes et retour en arrière, Héraut avec annulation, heures estimées, suggestions, historique.
4. **Chorégraphies et finitions.**
   - Contenu : Couronnement, Sceau, Révérence, clavier, accessibilité, mouvement réduit, affichage en une colonne.
   - Mesure de performance avec le script `pacing.py` du lab : pas de tâche longue au-delà de 50 ms à vitesse CPU normale pendant un Couronnement.

**Vérifications de chaque étape**

- `npm test` pour les fonctions pures : palette, `cleanTitle`, calcul de mise en page, logique des actions optimistes, textes.
- `tsc --noEmit` et `next build`.
- Contrôle visuel avec captures dans le vrai navigateur, avec la fausse API de dev : 1440×900, 1280×720 et 390×844.
- Aucune erreur dans la console.

## 7. Risques

| Risque | Parade |
|---|---|
| Poids de la page (worker, pierre de 224 Ko, polices d'environ 260 Ko) | Préchargement ciblé ; pierre et rosace chargées après le premier affichage |
| Moteurs sans `OffscreenCanvas` / `bitmaprenderer` | Repli : dessin sur le fil principal pendant les temps morts, ou rosace statique |
| `corner-shape: bevel` (Chrome 139 et plus) | Repli en coins arrondis ; la mise en page n'en dépend pas |
| Textes : ton de Greg mal perçu | Les libellés restent neutres ; les répliques peuvent être coupées (« Répliques de Greg ») |

## 8. Critères d'acceptation

- Coller un lien de playlist, voir la file s'animer, glisser pour réordonner, retirer puis annuler, mettre en pause : tout se passe sans à-coup, sans erreur console, sur un vrai navigateur.
- Le Roi, c'est l'utilisateur : aucune couronne, aucun sceau royal ni aucun « Rex » attribué à Greg.
- Les tests, `tsc` et `next build` passent, et l'image Docker du web se construit.
