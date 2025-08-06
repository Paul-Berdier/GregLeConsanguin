# web/oauth.py

from flask import Blueprint, redirect, request, session, url_for
import os
import requests
import sys

oauth_bp = Blueprint('oauth', __name__)

DISCORD_API_BASE_URL = "https://discord.com/api"

def get_discord_client_id():
    return os.environ.get("DISCORD_CLIENT_ID")

def get_discord_client_secret():
    # ⚠️ PAS D’ESPACE !
    return os.environ.get("DISCORD_CLIENT_SECRET")

def get_discord_redirect_uri():
    return os.environ.get("DISCORD_REDIRECT_URI") or "http://localhost:3000/callback"

@oauth_bp.route("/login")
def login():
    scope = "identify guilds"
    client_id = get_discord_client_id()
    redirect_uri = get_discord_redirect_uri()

    discord_auth_url = (
        f"{DISCORD_API_BASE_URL}/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope.replace(' ', '%20')}"
    )
    print(f"[DEBUG][OAUTH] Redirection vers : {discord_auth_url}", file=sys.stderr)
    return redirect(discord_auth_url)

@oauth_bp.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Missing code", 400

    client_id = get_discord_client_id()
    client_secret = get_discord_client_secret()
    redirect_uri = get_discord_redirect_uri()


    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "scope": "identify guilds"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    print("DEBUG: token payload:", data, file=sys.stderr)
    print("DEBUG: headers:", headers, file=sys.stderr)
    print("DEBUG: URL:", f"{DISCORD_API_BASE_URL}/oauth2/token", file=sys.stderr)

    # Échange le code contre un access_token
    r = requests.post(f"{DISCORD_API_BASE_URL}/oauth2/token", data=data, headers=headers)
    print("DEBUG: status_code:", r.status_code, file=sys.stderr)
    print("DEBUG: response text:", r.text, file=sys.stderr)
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

    # Récupère serveurs (guilds)
    guilds_res = requests.get(
        f"{DISCORD_API_BASE_URL}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    print("DEBUG: guilds payload:", guilds_res, file=sys.stderr)
    guilds_res.raise_for_status()
    guilds = guilds_res.json()

    user["guilds"] = [
        {"id": g["id"], "name": g["name"], "icon": g["icon"]}
        for g in guilds
    ]

    # DEBUG print list
    print("[DEBUG] Guilds côté utilisateur (user['guilds']):", file=sys.stderr)
    for g in user["guilds"]:
        print(f" - {g['id']} : {g['name']}", file=sys.stderr)
    print("DEBUG: user payload:", user, file=sys.stderr)

    session["user"] = user

    # Redirige vers la sélection serveur/salon
    return redirect("/select")
