"""Régénère les polices « Nuit gothique » (woff2) de public/fonts/.

Sources : les fichiers complets (non sous-ensemblés) du dépôt github.com/google/fonts, tous sous
SIL Open Font License 1.1 (textes dans public/licenses/). Ils sont lus dans --src ; ceux qui
manquent y sont téléchargés depuis raw.githubusercontent.com/google/fonts.

Sous-ensemble : latin, Latin-1, Œœ, ponctuation typographique et flèches (UNICODES), avec toutes
les fonctionnalités OpenType (`--layout-features='*'`) et la table `name` entière (copyright et
licence voyagent avec le fichier, comme l'exige l'OFL).

Espace fine insécable (U+202F) : le deck de textes la met avant « ; ! ? » et Intl.NumberFormat
(fr-FR) l'emploie comme séparateur de milliers. Aucune des fontes sources ne la contient, et le
navigateur irait alors chercher le glyphe dans une police système. On la fait donc pointer, dans
la cmap, vers le glyphe de l'espace insécable (U+00A0) de chaque fonte :
- sa chasse est celle de l'espace-mot, 0,145 à 0,169 em dans ces familles, soit une « fine » ;
- les variations (axe wght) suivent, puisque c'est un glyphe existant ;
- les glyphes U+2009 des sources ne conviennent pas : ils sont plus larges que l'espace-mot
  dans Grenze, Grenze Gotisch et Alegreya Sans Medium, Bold et ExtraBold.
Le caractère reste insécable : la coupure de ligne dépend du point de code, pas du glyphe.

Usage (depuis services/web) :
  python scripts/subset-fonts.py [--src DOSSIER] [--out DOSSIER]
Dépendances : fonttools, brotli (`pip install fonttools brotli`).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "public" / "fonts"
DEFAULT_SRC = Path(tempfile.gettempdir()) / "greg-web-fonts-full"
RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/"

# (chemin dans google/fonts/ofl, fichier produit)
FONTS: list[tuple[str, str]] = [
    ("grenzegotisch/GrenzeGotisch[wght].ttf", "GrenzeGotisch-VF.woff2"),
    ("grenze/Grenze[wght].ttf", "Grenze-VF.woff2"),
    ("alegreyasans/AlegreyaSans-Regular.ttf", "AlegreyaSans-Regular.woff2"),
    ("alegreyasans/AlegreyaSans-Medium.ttf", "AlegreyaSans-Medium.woff2"),
    ("alegreyasans/AlegreyaSans-Bold.ttf", "AlegreyaSans-Bold.woff2"),
    ("alegreyasans/AlegreyaSans-ExtraBold.ttf", "AlegreyaSans-ExtraBold.woff2"),
    ("alegreya/Alegreya-Italic[wght].ttf", "Alegreya-Italic-VF.woff2"),
]

UNICODES = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,"
    "U+20AC,U+2122,U+2190-2193,U+2212,U+2215,U+202F,U+00A0"
)
NBSP = 0x00A0
NNBSP = 0x202F


def source_path(src_dir: Path, gf_path: str) -> Path:
    """Fonte complète dans src_dir ; téléchargée depuis google/fonts si elle manque."""
    path = src_dir / gf_path.split("/")[-1]
    if not path.exists():
        url = RAW + urllib.parse.quote(gf_path)
        print(f"téléchargement {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "greg-web/subset-fonts"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
        src_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def map_nnbsp(font: TTFont) -> str:
    """U+202F → glyphe de U+00A0, dans chaque sous-table Unicode de la cmap."""
    glyph = font.getBestCmap().get(NBSP)
    if glyph is None:
        raise SystemExit("U+00A0 absent de la fonte source : impossible d'y adosser U+202F")
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap.setdefault(NNBSP, glyph)
    return glyph


def build(src: Path, out: Path) -> None:
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.flavor = "woff2"

    font = subset.load_font(str(src), options)
    map_nnbsp(font)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=subset.parse_unicodes(UNICODES))
    subsetter.subset(font)
    out.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(out), options)
    font.close()


def check(out: Path) -> str:
    """Vérifie le woff2 produit : U+202F présent et adossé à l'espace insécable."""
    font = TTFont(str(out))
    cmap = font.getBestCmap()
    if NNBSP not in cmap:
        raise SystemExit(f"{out.name} : U+202F absent de la cmap")
    if cmap[NNBSP] != cmap.get(NBSP):
        raise SystemExit(f"{out.name} : U+202F ne pointe pas vers le glyphe de U+00A0")
    axes = ",".join(a.axisTag for a in font["fvar"].axes) if "fvar" in font else "-"
    advance = font["hmtx"][cmap[NNBSP]][0]
    upm = font["head"].unitsPerEm
    version = font["name"].getDebugName(5)
    return (
        f"{out.name:<30} {out.stat().st_size / 1024:6.1f} Ko  cmap={len(cmap):4d}  "
        f"U+202F={advance / upm:.3f} em  axes={axes}  {version}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--src",
        type=Path,
        default=DEFAULT_SRC,
        help=f"dossier des fontes complètes (défaut : {DEFAULT_SRC})",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="dossier de sortie (défaut : public/fonts)"
    )
    args = parser.parse_args()

    for gf_path, name in FONTS:
        out = args.out / name
        build(source_path(args.src, gf_path), out)
        print(check(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
