"""Configuration pytest commune aux tests du bot (services/bot/tests/**).

- Met `greg_shared` (packages/shared) et `bot` (services/bot) sur le sys.path,
  pour importer le code source directement (pas besoin d'installer les paquets).
- Aucun accès réseau : les fonctions d'extraction (yt-dlp, recherche, stream)
  sont remplacées dans chaque test (voir core_fakes.py).
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_REPO = os.path.abspath(os.path.join(_BOT_ROOT, "..", ".."))
_SHARED = os.path.join(_REPO, "packages", "shared")

for _p in (_HERE, _BOT_ROOT, _SHARED):
    if _p not in sys.path:
        sys.path.insert(0, _p)
