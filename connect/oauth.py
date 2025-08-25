# connect/oauth.py
from __future__ import annotations
import os, secrets, string, requests
from typing import Tuple, Dict, Any, Optional

DISCORD_BASE = "https://discord.com/api"
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:3000/auth/callback")
SCOPES = os.getenv("DISCORD_OAUTH_SCOPES", "identify guilds").split()

TIMEOUT = 8

def _rand_state(n: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

def make_authorize_url(state: str) -> str:
    from urllib.parse import urlencode
    q = urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "prompt": "consent",
        "state": state,
    })
    return f"{DISCORD_BASE}/oauth2/authorize?{q}"

def exchange_code_for_token(code: str) -> Dict[str, Any]:
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(f"{DISCORD_BASE}/oauth2/token", data=data, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()  # {access_token, token_type, expires_in, scope, refresh_token}

def fetch_user_me(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"{DISCORD_BASE}/users/@me", headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def fetch_user_guilds(access_token: str) -> list[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"{DISCORD_BASE}/users/@me/guilds", headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def start_oauth_flow() -> Tuple[str, str]:
    """Retourne (state, authorize_url)."""
    st = _rand_state()
    return st, make_authorize_url(st)
