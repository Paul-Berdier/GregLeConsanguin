"""Rebuild the approved overlay mockups into self-contained HTML files (fonts and images inlined).

Usage, from the repository root:
    python docs/superpowers/specs/2026-11-25-overlay-overwolf-maquettes/build.py
The built files land next to this script as *.html (they are large; do not commit them).
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
WEB = HERE.parents[3] / "services/web/public"
ASSETS = {
    "F_GOT": WEB / "fonts/GrenzeGotisch-VF.woff2",
    "F_GRENZE": WEB / "fonts/Grenze-VF.woff2",
    "F_ALS4": WEB / "fonts/AlegreyaSans-Regular.woff2",
    "F_ALS5": WEB / "fonts/AlegreyaSans-Medium.woff2",
    "F_ALS7": WEB / "fonts/AlegreyaSans-Bold.woff2",
    "F_ALS8": WEB / "fonts/AlegreyaSans-ExtraBold.woff2",
    "F_ALI": WEB / "fonts/Alegreya-Italic-VF.woff2",
    "IMG_FACE": WEB / "gothique/greg-face-96.webp",
    "IMG_SEAL": WEB / "gothique/seals/king-seal-P.webp",
    "IMG_CAP": WEB / "gothique/jester-cap-256.webp",
    "IMG_FACE192": WEB / "gothique/greg-face-192.webp",
    "IMG_CROWN": WEB / "gothique/crown-badge-64.webp",
}

css = (HERE / "shared.css").read_text(encoding="utf-8")
for src in sorted(HERE.glob("*.tpl.html")):
    html = src.read_text(encoding="utf-8").replace("%%CSS%%", css)
    for key, path in ASSETS.items():
        token = f"%%{key}%%"
        if token in html:
            html = html.replace(token, base64.b64encode(path.read_bytes()).decode("ascii"))
    out = src.with_name(src.name.replace(".tpl.html", ".html"))
    out.write_text(html, encoding="utf-8", newline="\n")
    print(out.name, len(html) // 1024, "KB")
