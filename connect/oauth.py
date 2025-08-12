# oauth.py — Blueprint OAuth Discord (identify + guilds)
# ------------------------------------------------------
# Endpoints:
#   - GET /login            → redirige vers Discord pour consentement
#   - GET /oauth/callback   → échange le code, récupère profil + guilds, stocke en session
#   - GET /logout           → efface la session puis redirige vers /
#
# Variables d'environnement requises (Railway ou .env) :
#   DISCORD_CLIENT_ID
#   DISCORD_CLIENT_SECRET
#   DISCORD_REDIRECT_URI     (ex: https://ton-app.up.railway.app/oauth/callback)
#
# La session Flask mettra à disposition dans `session["user"]` :
#   { id, username, avatar, guilds: [{id, name}] }
#
# Ton app.py doit enregistrer le blueprint :
#   from oauth import oauth_bp
#   app.register_blueprint(oauth_bp)

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import requests
from flask import Blueprint, request, redirect, session, url_for

DISCORD_API_BASE = "https://discord.com/api"
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")

oauth_bp = Blueprint("oauth", __name__)

def _avatar_url(user: dict) -> str | None:
    uid = user.get("id")
    avatar = user.get("avatar")
    if not uid or not avatar:
        return None
    fmt = "gif" if str(avatar).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{fmt}?size=128"


@oauth_bp.route("/login")
def login():
    """Démarre le flux OAuth vers Discord."""
    if not (CLIENT_ID and CLIENT_SECRET and REDIRECT_URI):
        return "OAuth non configuré côté serveur (variables manquantes).", 500

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",  # force l’écran si besoin
    }
    return redirect(f"{DISCORD_API_BASE}/oauth2/authorize?{urlencode(params)}")


@oauth_bp.route("/callback")
def callback():
    """Réception du code d'auth, échange contre access_token, puis récupération du profil."""
    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state or state != session.get("oauth_state"):
        return "Flux OAuth invalide (state/code).", 400

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # 1) Échange code → token
    tok = requests.post(f"{DISCORD_API_BASE}/oauth2/token", data=data, headers=headers, timeout=15)
    if not tok.ok:
        return f"Échec échange token: {tok.text}", 400

    token = tok.json().get("access_token")
    if not token:
        return "Pas d'access_token dans la réponse OAuth.", 400

    auth = {"Authorization": f"Bearer {token}"}

    # 2) Profil utilisateur
    me = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=auth, timeout=15)
    if not me.ok:
        return f"Échec /users/@me: {me.text}", 400
    user = me.json()

    # 3) Guilds utilisateur
    g = requests.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=auth, timeout=15)
    guilds = g.json() if g.ok else []

    # 4) Enregistre en session (utilisé par /api/me, /api/guilds)
    session["user"] = {
        "id": user.get("id"),
        "username": f'{user.get("username")}#{user.get("discriminator","0")}',
        "avatar": _avatar_url(user),
        "guilds": [
            {"id": str(x.get("id")), "name": x.get("name")}
            for x in guilds if x.get("id") and x.get("name")
        ],
    }
    # Optionnel : conserver l'access token pour des appels ultérieurs si besoin
    session["access_token"] = token

    # Retour à la page principale (ton overlay)
    return redirect(url_for("index"))


@oauth_bp.route("/logout")
def logout():
    """Supprime la session locale et renvoie à l’accueil."""
    session.clear()
    return redirect(url_for("index"))
