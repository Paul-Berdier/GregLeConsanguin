# api/auth/discord_oauth.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from flask import current_app

DISCORD_BASE = "https://discord.com/api/v10"


def build_authorize_url(state: str) -> str:
    cfg = current_app.config
    params = {
        "client_id": cfg["DISCORD_CLIENT_ID"],
        "response_type": "code",
        "scope": cfg["DISCORD_OAUTH_SCOPES"],
        "redirect_uri": cfg["DISCORD_REDIRECT_URI"],
        "prompt": "consent",
        "state": state,
    }
    return f"{DISCORD_BASE}/oauth2/authorize?{urlencode(params)}"


def exchange_code_for_token(code: str) -> Dict[str, Any]:
    cfg = current_app.config
    data = {
        "client_id": cfg["DISCORD_CLIENT_ID"],
        "client_secret": cfg["DISCORD_CLIENT_SECRET"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["DISCORD_REDIRECT_URI"],
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(f"{DISCORD_BASE}/oauth2/token", data=data, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_user_info(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"{DISCORD_BASE}/users/@me", headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_user_guilds(access_token: str) -> list[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"{DISCORD_BASE}/users/@me/guilds", headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()
