# api/auth/discord_oauth.py
from __future__ import annotations

import os
import time
import math
import random
import requests
from typing import Any, Dict, List, Optional, Tuple

DISCORD_BASE = "https://discord.com/api/v10"

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://127.0.0.1:3000/auth/callback")

# Garde IDENTIFY + GUILDS (lecture des serveurs), ajoute offline_access pour refresh
SCOPES = os.getenv("DISCORD_OAUTH_SCOPES", "identify guilds").split()

TIMEOUT = 10


def _request(method: str, url: str, **kw) -> requests.Response:
    """Requête HTTP avec gestion simple du 429 (Discord rate limit)."""
    session: requests.Session = kw.pop("_session", None) or requests.Session()
    for attempt in range(5):
        resp = session.request(method, url, timeout=TIMEOUT, **kw)
        if resp.status_code != 429:
            return resp
        # Backoff
        retry_after = 0.0
        try:
            j = resp.json()
            retry_after = float(j.get("retry_after", 0))
        except Exception:
            pass
        retry_after = max(retry_after, 0.5) + random.random() * 0.35
        time.sleep(retry_after)
    return resp


def make_authorize_url(state: str, extra_params: Optional[Dict[str, str]] = None) -> str:
    from urllib.parse import urlencode
    q = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "prompt": "consent",
        "state": state,
    }
    if extra_params:
        q.update(extra_params)
    return f"{DISCORD_BASE.replace('/api/v10','')}/oauth2/authorize?{urlencode(q)}"


def exchange_code_for_token(code: str) -> Dict[str, Any]:
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = _request("POST", f"{DISCORD_BASE}/oauth2/token", data=data, headers=headers)
    r.raise_for_status()
    tok = r.json()  # {access_token, token_type, expires_in, scope, refresh_token}
    # Ajoute expires_at en epoch pour auto-refresh
    tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600)) - 30
    return tok


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = _request("POST", f"{DISCORD_BASE}/oauth2/token", data=data, headers=headers)
    r.raise_for_status()
    tok = r.json()
    tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600)) - 30
    return tok


def fetch_user_me(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = _request("GET", f"{DISCORD_BASE}/users/@me", headers=headers)
    r.raise_for_status()
    return r.json()


def fetch_user_guilds(access_token: str) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = _request("GET", f"{DISCORD_BASE}/users/@me/guilds", headers=headers)
    r.raise_for_status()
    return r.json()
