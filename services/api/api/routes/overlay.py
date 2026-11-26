"""Overlay routes — liaison de l'appli Overwolf par code d'appareil (RFC 8628) et gestion de ses jetons
(spec 2026-11-25 §3.4 ; stockage : api.services.overlay_tokens).

Tout compte connecté au site lie l'appli à SON PROPRE compte : aucun contrôle de propriétaire. L'uid et le portrait
viennent de la session (autoriser) ou de l'enregistrement du jeton, jamais du corps. Chacun ne liste et ne révoque
que ses jetons ; un porteur ne révoque que lui-même.

- Démarrer et récupérer le jeton : sans authentification, corps JSON exigé avant tout accès à Redis (un formulaire
  ou un text/plain d'une page tierce n'entame aucun compteur).
- Consulter et autoriser un code : session seule (`require_session_user`, CSRF compris pour autoriser).
- Le reste : session ou jeton (`require_identity`) ; la déconnexion de l'appli : jeton seul (`require_bearer`).
- Erreurs : {ok: false, error} (OverlayError, rendue par le gestionnaire du blueprint), 429 RATE_LIMITED, et 503
  STORAGE_UNAVAILABLE (avec message) quand Redis est injoignable, jamais 401 : l'appli effacerait son jeton.
"""
from __future__ import annotations

import re
from typing import Any

from flask import Blueprint, jsonify, request, session

from api import web_url
from api.routes.player import error_status
from api.services import overlay_tokens as ot
from api.services.authz import (
    current_identity,
    current_user_id,
    not_authenticated,
    require_bearer,
    require_identity,
    require_session_user,
)
from api.services.bot_bridge import send_command

bp = Blueprint("overlay", __name__)

DEFAULT_CLIENT_NAME = "Appli Overwolf"
# (seau, plafond, fenêtre en secondes) de ot.hit_rate_limit.
RATE_START_GLOBAL = ("device_start", 30, 3600)
RATE_START_IP = ("device_start_ip", 5, 60)
RATE_APPROVE = ("approve", 5, 60)
# user_guilds se lit dans le cache du bot (spec §4.1) : réponse rapide attendue.
USER_GUILDS_TIMEOUT = 5
_DECISIONS = ("approve", "deny")
# fullmatch : « $ » de re.match accepterait un « \n » final
_GUILD_ID_RE = re.compile(r"[0-9]{1,20}")


@bp.errorhandler(ot.OverlayError)
def _overlay_error(e: ot.OverlayError):
    return jsonify(e.body()), e.status


def _invalid() -> ot.OverlayError:
    return ot.OverlayError("INVALID_REQUEST", 400)


def _check_rate(rule: tuple[str, int, int], subject: str) -> None:
    """Compte la requête dans le seau de `rule` ; 429 RATE_LIMITED au-delà du plafond."""
    bucket, limit, window_s = rule
    if ot.hit_rate_limit(bucket, subject, limit, window_s):
        raise ot.OverlayError("RATE_LIMITED", 429)


def _json_object() -> dict[str, Any] | None:
    """Corps JSON objet, sinon None (JSON illisible ou autre chose qu'un objet)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _user_snapshot(discord_user: dict) -> dict:
    """Portrait Discord gardé avec le jeton : {id (texte), username, global_name, avatar}, valeurs absentes → None."""
    uid = discord_user.get("id")
    return {
        "id": None if uid is None else str(uid),
        "username": discord_user.get("username"),
        "global_name": discord_user.get("global_name"),
        "avatar": discord_user.get("avatar"),
    }


def _client_name(body: dict[str, Any] | None) -> str:
    """`client_name` facultatif : texte d'au plus 40 caractères une fois rogné ; absent ou vide → nom par défaut."""
    if body is None:
        raise _invalid()
    raw = body.get("client_name")
    if raw is None:
        return DEFAULT_CLIENT_NAME
    if not isinstance(raw, str) or len(raw.strip()) > ot.CLIENT_NAME_MAX:
        raise _invalid()
    return raw.strip() or DEFAULT_CLIENT_NAME


def _valid_guild_id(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and _GUILD_ID_RE.fullmatch(raw) is not None)


def _lists_guild(guilds: Any, guild_id: str) -> bool:
    """Vrai si la réponse de user_guilds (serveurs communs à Greg et à l'utilisateur) contient `guild_id`."""
    return isinstance(guilds, list) and any(isinstance(g, dict) and str(g.get("id")) == guild_id for g in guilds)


# ── Parcours de l'appareil ──

@bp.post("/overlay/device")
def device_start():
    """Démarrer une liaison (sans authentification).

    Limite par IP d'abord : une requête qu'elle refuse ne compte jamais dans le plafond global, donc une IP seule ne
    bloque pas la liaison des autres comptes. remote_addr est déjà tiré de X-Forwarded-For (ProxyFix).
    """
    if not request.is_json:
        raise _invalid()
    _check_rate(RATE_START_IP, request.remote_addr or "unknown")
    _check_rate(RATE_START_GLOBAL, "all")
    d = ot.start_device(_client_name(_json_object()))
    web = web_url().rstrip("/")
    return jsonify({
        "ok": True,
        "device_code": d.device_code,
        "user_code": d.user_code,
        "verification_uri": f"{web}/lier",
        "verification_uri_complete": f"{web}/lier?code={d.user_code}",
        "expires_in": d.expires_in,
        "interval": d.interval,
    }), 200


@bp.get("/overlay/device/lookup")
@require_session_user
def device_lookup():
    """Ce que /lier montre avant d'autoriser (nom et âge de l'appareil), pour tout compte connecté."""
    code = ot.normalize_user_code(request.args.get("user_code"))
    if code is None:
        raise _invalid()
    info = ot.lookup_user_code(code)
    if info is None:
        raise ot.OverlayError("CODE_EXPIRED", 404)
    return jsonify({"ok": True, **info}), 200


@bp.post("/overlay/device/approve")
@require_session_user
def device_approve():
    """Autoriser ou refuser un code pour son propre compte.

    L'uid et le portrait sont ceux de la session : les clés `uid`, `user_id` et `user` du corps ne sont jamais lues,
    et le jeton émis appartient toujours à celui qui a cliqué. Le serveur par défaut est vérifié par le bot
    (user_guilds, qui contrôle l'appartenance) avant de consommer le code : un refus le laisse utilisable.
    """
    uid = current_user_id()  # celui de la session : require_session_user refuse tout jeton porteur
    _check_rate(RATE_APPROVE, str(uid))
    body = _json_object()
    if body is None:
        raise _invalid()
    code = ot.normalize_user_code(body.get("user_code"))
    decision = body.get("decision")
    guild_id = body.get("guild_id")
    if code is None or decision not in _DECISIONS or not _valid_guild_id(guild_id):
        raise _invalid()
    approve = decision == "approve"
    if approve and guild_id is not None:
        res = send_command("user_guilds", 0, uid, timeout=USER_GUILDS_TIMEOUT)
        if not res.get("ok"):
            return jsonify(res), error_status(res, 503)
        if not _lists_guild(res.get("guilds"), guild_id):
            raise ot.OverlayError("NOT_GUILD_MEMBER", 403)
    ot.decide(code, approve=approve, uid=uid, user=_user_snapshot(session["discord_user"]),
              guild_id=guild_id if approve else None)
    return jsonify({"ok": True}), 200


@bp.post("/overlay/token")
def token():
    """Sondage de l'appli : le jeton une fois autorisé, sinon une erreur RFC 8628 en 400 (un `device_code` absent,
    non textuel ou inconnu donne expired_token)."""
    if not request.is_json:
        raise _invalid()
    body = _json_object()
    out = ot.poll(body.get("device_code") if body is not None else None)
    if isinstance(out, str):
        return jsonify({"ok": False, "error": out}), 400
    return jsonify({
        "ok": True,
        "access_token": out.access_token,
        "token_type": "Bearer",
        "expires_in": out.expires_in,
        "user": out.record.user,
        "default_guild_id": out.record.default_guild_id,
    }), 200


# ── Jetons ──

@bp.get("/overlay/me")
@require_identity
def me():
    """Le compte de l'appelant : portrait de la session, ou celui enregistré avec le jeton et son serveur par défaut."""
    ident = current_identity()  # posée par require_identity
    if ident.via == "session":
        return jsonify({"ok": True, "via": "session", "user": _user_snapshot(session["discord_user"]),
                        "default_guild_id": None}), 200
    rec = next((r for r in ot.list_tokens(ident.uid) if r.tid == ident.tid), None)
    if rec is None:  # révoqué depuis la vérification du jeton
        return not_authenticated()
    return jsonify({"ok": True, "via": "overlay", "user": rec.user, "default_guild_id": rec.default_guild_id}), 200


@bp.get("/overlay/tokens")
@require_identity
def tokens():
    """Les jetons de l'appelant seulement, jamais d'empreinte ; `current` marque celui de la requête."""
    ident = current_identity()
    rows = [r.public() | {"current": r.tid == ident.tid} for r in ot.list_tokens(ident.uid)]
    return jsonify({"ok": True, "tokens": rows}), 200


@bp.post("/overlay/tokens/revoke")
@require_identity
def tokens_revoke():
    """Session (CSRF par require_identity) : ses propres jetons, car ot.revoke ne cherche que dans le HASH de
    l'appelant ; porteur : lui-même seulement. Tout autre `id` → 404 NOT_FOUND, sans rien supprimer."""
    ident = current_identity()
    body = _json_object()
    tid = body.get("id") if body is not None else None
    if not isinstance(tid, str) or (ident.via == "overlay" and tid != ident.tid) or not ot.revoke(ident.uid, tid):
        raise ot.OverlayError("NOT_FOUND", 404)
    return jsonify({"ok": True}), 200


@bp.post("/overlay/logout")
@require_bearer
def logout():
    """L'appli se délie : révoque le jeton de la requête."""
    ident = current_identity()
    ot.revoke(ident.uid, ident.tid)
    return jsonify({"ok": True}), 200


# ── Serveurs ──

@bp.get("/overlay/guilds")
@require_identity
def guilds():
    """Serveurs communs à Greg et à l'appelant, lus dans le cache du bot (action user_guilds, spec §4.1)."""
    res = send_command("user_guilds", 0, current_user_id(), timeout=USER_GUILDS_TIMEOUT)
    if not res.get("ok"):
        return jsonify(res), error_status(res, 503)
    return jsonify({"ok": True, "guilds": res.get("guilds", [])}), 200
