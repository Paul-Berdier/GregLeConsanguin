# Licences des ressources du lecteur web

Ce fichier ne couvre que les fichiers livrés dans `services/web/public/`. Il reprend les sections utiles du registre de licences de la direction « Nuit gothique ». Tout est dans le domaine public, sous CC0 1.0, généré par nous, ou sous SIL Open Font License 1.1 pour les polices.

## Images (`public/gothique/`)

| Fichier | Rôle | Source | Licence |
|---|---|---|---|
| `stone-rose-2048.webp` | Remplages de pierre de la rosace, ouvertures transparentes, posés sur le verre peint par le code | Œuvre originale : carte de hauteur calculée (numpy, scipy, Pillow) depuis la géométrie du vitrail, relief rendu dans Blender 5.1 Cycles. Aucune texture ni HDRI téléchargé | CC0 1.0 |
| `stone-frame-640.webp` | Piédroits de pierre autour de la vidéo (`border-image` en 9 tranches) | Même chaîne que la rosace | CC0 1.0 |
| `crown-320.webp` | Couronne du Roi dans l'oculus quand rien ne joue | Réduction d'un rendu Blender de la couronne (modèle, matériaux et éclairage procéduraux) | CC0 1.0 |
| `crown-turn-128.avif`, `crown-still-128.avif` | Couronne qui tourne (chargement), couronne immobile (mouvement réduit) | Dérivés des 24 images d'une rotation Blender de la même couronne | CC0 1.0 |
| `crown-badge-64.webp`, `crown-badge-128.webp` | Couronne posée en haut à droite de l'avatar de l'utilisateur (le Roi) | Rendu Blender : la même couronne, polie, réduite à un cercle d'or ouvert à fleurs de lys, perles et pierres | CC0 1.0 |
| `seals/king-seal-{A..Z}.webp`, `seals/king-seal-fleur.webp` | Sceau de cire du Roi, à l'initiale de l'utilisateur, sur ses propres titres ; fleur de lys si l'initiale n'est pas une lettre A–Z | Rendu Blender d'une matrice de sceau faite par nous : couronne, légende « + SIGILLVM . DOMINI . REGIS . » et initiale en creux. Lettres dessinées avec la police Alegreya (SIL OFL 1.1) ; une image faite avec une police OFL n'est pas soumise à l'OFL | CC0 1.0 |
| `grain-256.webp` | Grain posé sur la couronne et le portrait | Généré par nous (filtres SVG `feTurbulence` rendus dans Chrome) | Aucun droit tiers |
| `greg-face-96.webp`, `greg-face-192.webp` | Portrait de Greg, le valet du Roi : médaillon de l'en-tête (96), oculus de la rosace (192) | Recadrage et réductions de Juan Carreño de Miranda, *Charles II d'Espagne*, v. 1685, Kunsthistorisches Museum, Vienne · [Commons](https://commons.wikimedia.org/wiki/File:Juan_de_Miranda_Carreno_002.jpg) | Domaine public (PD-Art ; reproduction fidèle d'une œuvre 2D, directive UE 2019/790 art. 14) |
| `minstrels-manesse-line.webp` | Ménestrels au trait, en filigrane au pied de la file | Dérivé mécanique (contours d'encre extraits) du Codex Manesse, f. 399r (Frauenlob et ses ménestrels), Zurich, v. 1305-1340, Bibliothèque universitaire de Heidelberg, Cod. Pal. germ. 848 · [Commons](https://commons.wikimedia.org/wiki/File:Codex_Manesse_Heinrich_von_Mei%C3%9Fen_(Frauenlob).jpg) · [numérisation](http://digi.ub.uni-heidelberg.de/diglit/cpg848/0793) | Domaine public (PD-Art ; directive UE 2019/790 art. 14). Le dérivé mécanique n'ajoute aucun droit |

Les transformations faites par nous (recadrages, réductions, extraction du trait) sont versées en CC0 1.0 : https://creativecommons.org/publicdomain/zero/1.0/

## Polices (`public/fonts/`), SIL Open Font License 1.1

Sous-ensembles des fichiers complets du dépôt [google/fonts](https://github.com/google/fonts), régénérés par `services/web/scripts/subset-fonts.py` :
- latin, Latin-1, Œœ, ponctuation typographique et flèches ;
- toutes les fonctionnalités OpenType conservées, table `name` complète ;
- espace fine insécable U+202F ajoutée à la cmap, sur le glyphe de l'espace insécable.

Aucune de ces familles n'a de nom de fonte réservé : les versions modifiées gardent leur nom d'origine. Le texte de la licence accompagne chaque famille dans ce dossier.

| Fichier | Rôle | Famille, copyright | Source | Texte de la licence |
|---|---|---|---|---|
| `GrenzeGotisch-VF.woff2` | Titres d'apparat (`--f-display`) | Grenze Gotisch, Copyright 2020 The Grenze Gotisch Project Authors | [ofl/grenzegotisch](https://github.com/google/fonts/tree/main/ofl/grenzegotisch) | `grenzegotisch-OFL.txt` |
| `Grenze-VF.woff2` | Titre du morceau en lecture (`--f-title`) | Grenze, Copyright 2019, The Grenze Project Authors | [ofl/grenze](https://github.com/google/fonts/tree/main/ofl/grenze) | `grenze-OFL.txt` |
| `AlegreyaSans-Regular.woff2`, `AlegreyaSans-Medium.woff2`, `AlegreyaSans-Bold.woff2`, `AlegreyaSans-ExtraBold.woff2` | Interface (`--f-ui`) | Alegreya Sans, Copyright 2013 The Alegreya Sans Project Authors | [ofl/alegreyasans](https://github.com/google/fonts/tree/main/ofl/alegreyasans) | `alegreyasans-OFL.txt` |
| `Alegreya-Italic-VF.woff2` | Répliques de Greg (`--f-voice`) | Alegreya, Copyright 2011 The Alegreya Project Authors | [ofl/alegreya](https://github.com/google/fonts/tree/main/ofl/alegreya) | `alegreya-OFL.txt` |

## Déjà présent

| Fichier | Source | Licence |
|---|---|---|
| `public/images/icon.png` | Logo actuel, d'après un portrait anonyme de Charles II âgé en perruque (début du XVIIIe s.) · [Commons](https://commons.wikimedia.org/wiki/File:Carlosiielltimomonarcadq.jpg) | Domaine public (PD-Art) |
