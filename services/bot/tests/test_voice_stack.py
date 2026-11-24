"""Pile vocale : discord.py et davey (chiffrement DAVE) doivent aller ensemble (bot/voice_stack.py).

Incident du 24 novembre 2026 : l'image reconstruite a tiré davey 0.2.0, que discord.py 2.7.1 ne sait pas piloter.
Greg rejoignait le salon, l'indicateur vert s'allumait, ffmpeg lisait chaque titre jusqu'au bout, et personne
n'entendait rien (Rapptz/discord.py#10549).
"""
from __future__ import annotations

import inspect
import os
import re
import runpy
import warnings
from importlib import metadata

import pytest
from packaging.requirements import Requirement

from bot.voice_stack import (
    discord_applies_transitions,
    voice_stack,
    voice_stack_problem,
)

_BOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _requirements() -> dict[str, Requirement]:
    reqs: dict[str, Requirement] = {}
    with open(os.path.join(_BOT, "requirements.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                req = Requirement(line)
                reqs[req.name.lower()] = req
    return reqs


def test_requirements_keep_davey_below_0_2_while_discord_py_2_7_1_is_allowed():
    reqs = _requirements()
    assert "voice" in reqs["discord.py"].extras, "discord.py[voice] : PyNaCl et davey"
    if not reqs["discord.py"].specifier.contains("2.7.1"):
        return  # discord.py relevé (celui qui gère davey 0.2) : son extra [voice] borne davey lui-même
    # discord.py 2.7.1 n'appelle ni prepare_transition ni execute_transition : avec davey 0.2, Greg est muet
    assert "davey" in reqs, "davey pincé à part : discord.py[voice] 2.7.1 le tire sans borne haute (davey>=0.1.0)"
    davey_spec = reqs["davey"].specifier
    assert not davey_spec.contains("0.2.0", prereleases=True)
    assert not davey_spec.contains("0.2.0b1", prereleases=True)
    # mais une version qui chiffre : 0.1.7, la dernière 0.1
    assert davey_spec.contains("0.1.7")


@pytest.mark.parametrize("davey", ["0.2.0", "0.2.0b1", "0.2.0.post1", "0.10.0", "1", "1.0.0", "1!0.1.0"])
def test_davey_0_2_or_later_without_transitions_is_a_problem(davey):
    problem = voice_stack_problem(davey, applies_transitions=False)
    assert problem is not None
    assert f"davey {davey}" in problem and "davey<0.2" in problem


@pytest.mark.parametrize("davey", ["0.1.0", "0.1.7", "0.1.7.post1", "0.1"])
def test_davey_0_1_is_fine_with_discord_py_2_7_1(davey):
    assert voice_stack_problem(davey, applies_transitions=False) is None


@pytest.mark.parametrize("davey", ["0.1.7", "0.1"])
def test_davey_0_1_is_a_problem_once_discord_py_applies_transitions(davey):
    # Rapptz/discord.py#10548 appelle prepare_transition, execute_transition et can_encrypt : absents de davey 0.1
    problem = voice_stack_problem(davey, applies_transitions=True)
    assert problem is not None
    assert f"davey {davey}" in problem and "davey>=0.2" in problem


def test_davey_0_2_is_fine_once_discord_py_applies_transitions():
    assert voice_stack_problem("0.2.0", applies_transitions=True) is None


def test_missing_davey_is_a_problem():
    # discord.py le dit aussi (« voice will NOT be supported ») : la connexion vocale échoue
    problem = voice_stack_problem(None, applies_transitions=False)
    assert problem is not None and "davey" in problem


@pytest.mark.parametrize("davey", ["", "inconnue", "x.y"])
def test_unreadable_davey_version_is_not_reported(davey):
    # une version illisible n'arrête pas le build pour rien
    assert voice_stack_problem(davey, applies_transitions=False) is None
    assert voice_stack_problem(davey, applies_transitions=True) is None


def test_discord_py_2_7_1_does_not_apply_transitions():
    import discord

    if discord.__version__ != "2.7.1":
        pytest.skip(f"discord.py {discord.__version__} installé")
    assert discord_applies_transitions() is False


def test_voice_stack_summary_names_both_versions():
    import discord

    summary, problem = voice_stack()
    assert summary.startswith(f"discord.py {discord.__version__}, davey ")
    assert problem is None or "davey" in problem


def _run_build_check(monkeypatch, davey: str, gateway_source: str = "") -> None:
    """`python -m bot.voice_stack` avec ce davey-là et ce gateway.py de discord.py."""
    real_version = metadata.version
    monkeypatch.setattr(metadata, "version", lambda name: davey if name == "davey" else real_version(name))
    monkeypatch.setattr(inspect, "getsource", lambda _obj: gateway_source)
    with warnings.catch_warnings():
        # bot.voice_stack déjà importé par ce fichier : runpy le signale, sans effet ici
        warnings.filterwarnings("ignore", "'bot.voice_stack' found in sys.modules", RuntimeWarning)
        runpy.run_module("bot.voice_stack", run_name="__main__")


def test_build_check_fails_with_davey_0_2_and_discord_py_2_7_1(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run_build_check(monkeypatch, "0.2.0")
    assert str(exc.value.code).startswith("FATAL: davey 0.2.0 ")
    assert "Pile vocale : discord.py " in capsys.readouterr().out


def test_build_check_passes_with_davey_0_1_7(monkeypatch, capsys):
    _run_build_check(monkeypatch, "0.1.7")  # pas de SystemExit
    assert capsys.readouterr().out.strip().endswith(", davey 0.1.7")


def test_build_check_passes_with_davey_0_2_once_discord_py_applies_transitions(monkeypatch):
    _run_build_check(monkeypatch, "0.2.0", "state.dave_session.prepare_transition(transition_id, version)")


def test_bot_logs_its_voice_stack_at_startup():
    with open(os.path.join(_BOT, "bot", "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"summary, problem = voice_stack\(\)", src)
    assert 'logger.info("Pile vocale : %s", summary)' in src
    assert 'logger.error("Pile vocale : %s", problem)' in src


def test_image_build_fails_on_an_incompatible_voice_stack():
    # Railway garde le déploiement précédent si le build échoue : mieux qu'un Greg muet
    with open(os.path.join(_BOT, "Dockerfile"), encoding="utf-8") as f:
        src = f.read()
    code = src.index("COPY services/bot/ .")
    check = re.search(r"^RUN python -m bot\.voice_stack$", src, re.MULTILINE)
    assert check, "le contrôle seul sur sa ligne : ni « || true » ni suite qui avalerait son échec"
    assert check.start() > code, "le contrôle lit le code du bot : après sa copie"
