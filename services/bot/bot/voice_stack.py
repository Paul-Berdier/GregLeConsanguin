"""Pile vocale : discord.py et davey (chiffrement de bout en bout DAVE) doivent aller ensemble.

davey 0.2.0 (2 novembre 2026) ne pose plus les clés dans process_commit et process_welcome : seuls
prepare_transition et execute_transition le font. discord.py 2.7.1 n'appelle ni l'un ni l'autre
(Rapptz/discord.py#10548 l'ajoute). Avec davey 0.2, la session DAVE ne devient donc jamais prête : Greg envoie
l'Opus en clair dès la connexion et les clients Discord le jettent. Il a l'air de jouer (indicateur vert, ffmpeg
lit chaque titre jusqu'au bout) mais personne ne l'entend (Rapptz/discord.py#10549). Se reconnecter n'y change rien.
Dans l'autre sens, un discord.py qui pilote les transitions a besoin de davey 0.2 (0.1 n'a pas ces méthodes).

`python -m bot.voice_stack` : contrôle du build (Dockerfile). Sortie en erreur si la pile est incompatible.
"""
from __future__ import annotations

import inspect
import re
import sys
from importlib import metadata

# « 0.2.0 », « 0.2.0b1 », « 1 », « 1!0.1.0 » (époque PEP 440 : plus grande que toute version sans époque)
_RELEASE = re.compile(r"(?:(\d+)!)?(\d+)(?:\.(\d+))?")


def _minor(version: str) -> tuple[int, int] | None:
    """(majeure, mineure) d'une version, l'époque passant avant ; None si illisible."""
    m = _RELEASE.match(version)
    if not m:
        return None
    if m.group(1) and int(m.group(1)) > 0:
        return (10**9, 0)
    return int(m.group(2)), int(m.group(3) or 0)


def voice_stack_problem(davey_version: str | None, applies_transitions: bool) -> str | None:
    """Le problème de cette combinaison, en français, ou None.

    `davey_version` : None si davey n'est pas installé. `applies_transitions` : discord.py appelle-t-il
    prepare_transition (discord_applies_transitions) ? Une version illisible n'est pas signalée.
    """
    if davey_version is None:
        return "davey absent : discord.py refuse la voix (DAVE obligatoire depuis le 1er mars 2026)."
    release = _minor(davey_version)
    if release is None:
        return None
    if release >= (0, 2) and not applies_transitions:
        return (
            f"davey {davey_version} avec un discord.py qui n'applique pas les transitions DAVE : Greg jouera "
            "sans qu'on l'entende. Garder davey<0.2 (services/bot/requirements.txt)."
        )
    if release < (0, 2) and applies_transitions:
        return (
            f"davey {davey_version} avec un discord.py qui pilote les transitions DAVE : il lui faut davey>=0.2 "
            "(services/bot/requirements.txt)."
        )
    return None


def discord_applies_transitions() -> bool:
    """discord.py signale-t-il les transitions DAVE à davey (prepare_transition, exigé par davey 0.2) ?"""
    import discord.gateway

    try:
        return ".prepare_transition(" in inspect.getsource(discord.gateway)
    except (OSError, TypeError):
        return False  # source illisible : on ne peut pas l'affirmer


def voice_stack() -> tuple[str, str | None]:
    """(« discord.py X, davey Y », problème ou None)."""
    import discord

    try:
        davey_version: str | None = metadata.version("davey")
    except metadata.PackageNotFoundError:
        davey_version = None
    summary = f"discord.py {discord.__version__}, davey {davey_version or 'absent'}"
    return summary, voice_stack_problem(davey_version, discord_applies_transitions())


if __name__ == "__main__":
    _summary, _problem = voice_stack()
    print(f"Pile vocale : {_summary}")
    if _problem:
        sys.exit(f"FATAL: {_problem}")
