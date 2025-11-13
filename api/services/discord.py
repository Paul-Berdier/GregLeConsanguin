# api/services/discord.py
from __future__ import annotations
import time
import requests

DISCORD_API = "https://discord.com/api/v10"
_GUILDS_CACHE = {}  # token -> (ts, data)

class RateLimited(Exception):
    def __init__(self, retry_after: float | None = None, message: str = "rate_limited"):
        super().__init__(message)
        self.retry_after = retry_after

def get_user_guilds(token: str, ttl: int = 60):
    """
    Récupère les guilds de l'utilisateur avec petit cache mémoire et gestion 429.
    """
    now = time.time()
    ts_data = _GUILDS_CACHE.get(token)
    if ts_data and (now - ts_data[0] < ttl):
        return ts_data[1]

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{DISCORD_API}/users/@me/guilds"
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.status_code == 429:
        retry_after = None
        try:
            j = resp.json()
            retry_after = float(j.get("retry_after", 1))
        except Exception:
            pass
        # Si on a un cache ancien, on le renvoie; sinon on remonte une 429 "contrôlée"
        if ts_data:
            return ts_data[1]
        raise RateLimited(retry_after=retry_after)

    resp.raise_for_status()
    data = resp.json()
    _GUILDS_CACHE[token] = (now, data)
    return data

def get_guilds(token: str, ttl: int = 60):
    """
    Wrapper existant dans ton code : renvoie juste la liste JSON.
    """
    return get_user_guilds(token, ttl=ttl)
