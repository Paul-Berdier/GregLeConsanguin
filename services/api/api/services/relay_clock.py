"""Horloge de l'API pour la synchro son/vidéo (spec §3, §5) : le site se cale sur elle.

relay_at_ms : heure murale de l'API (ms epoch) à la réception d'un état ou d'un tick du bot (Redis ou réponse RPC).
time_sync renvoie la même horloge : aucun écart d'horloge entre les conteneurs du bot et de l'API.
"""
from __future__ import annotations

import time


def now_ms() -> int:
    """Horloge murale de l'API, en millisecondes epoch."""
    return int(time.time() * 1000)


def with_relay_at(state: dict, at_ms: int) -> dict:
    """Copie de `state` avec relay_at_ms : l'état reçu n'est jamais modifié."""
    return {**state, "relay_at_ms": at_ms}
