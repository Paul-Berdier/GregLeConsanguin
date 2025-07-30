from flask import Blueprint, redirect, request, session, url_for
import os
import requests

oauth_bp = Blueprint('oauth', __name__)

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET ")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI") or "http://localhost:3000/callback"
DISCORD_API_BASE_URL = "https://discord.com/api"

@oauth_bp.route("/login")
def login():
    scope = "identify guilds"
    discord_auth_url = (
        f"{DISCORD_API_BASE_URL}/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope.replace(' ', '%20')}"
    )
    return redirect(discord_auth_url)

@oauth_bp.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Missing code", 400

    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "scope": "identify guilds"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    r = requests.post(f"{DISCORD_API_BASE_URL}/oauth2/token", data=data, headers=headers)
    r.raise_for_status()
    token_data = r.json()
    access_token = token_data["access_token"]

    # Récupère infos utilisateur
    user_res = requests.get(
        f"{DISCORD_API_BASE_URL}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    user_res.raise_for_status()
    user = user_res.json()

    # Récupère serveurs
    guilds_res = requests.get(
        f"{DISCORD_API_BASE_URL}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    guilds_res.raise_for_status()
    guilds = guilds_res.json()

    user["guilds"] = [
        {"id": g["id"], "name": g["name"], "icon": g["icon"]}
        for g in guilds
    ]

    session["user"] = user
    return redirect("/panel")
