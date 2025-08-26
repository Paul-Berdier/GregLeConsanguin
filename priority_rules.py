# priority_rules.py
import os, json
from typing import Dict, Tuple, Optional

# Poids par défaut (plus haut = plus prioritaire)
DEFAULT_WEIGHTS: Dict[str, int] = {
    "__ADMIN__": 100,
    "__MANAGE_GUILD__": 90,
    "DJ": 80,
    "VIP": 60,
    "Booster": 50,     # rôle optionnel
    "__DEFAULT__": 10, # tout le monde
}

# Quota de pistes en file par utilisateur (peut être contourné par admin)
PER_USER_CAP = int(os.getenv("QUEUE_PER_USER_CAP", "3"))

def _load_custom_weights() -> Dict[str, int]:
    """
    Permet de surcharger via env : PRIORITY_ROLE_WEIGHTS='{"DJ":85,"VIP":65}'
    Les clés spéciales: __ADMIN__, __MANAGE_GUILD__, __DEFAULT__
    """
    raw = os.getenv("PRIORITY_ROLE_WEIGHTS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): int(v) for k, v in data.items()}
    except Exception:
        return {}

CUSTOM = _load_custom_weights()

def get_weights() -> Dict[str, int]:
    w = DEFAULT_WEIGHTS.copy()
    w.update(CUSTOM)
    return w

def get_member_weight(bot, guild_id: int, user_id: int) -> int:
    """
    Calcule le poids d'un membre en se basant sur les rôles du serveur + flags admin.
    """
    weights = get_weights()
    guild = bot.get_guild(int(guild_id)) if bot else None
    if not guild:
        return int(weights.get("__DEFAULT__", 10))
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return int(weights.get("__DEFAULT__", 10))

    # Admin ou Manage Guild → très haut
    if getattr(member.guild_permissions, "administrator", False):
        return int(weights.get("__ADMIN__", 100))
    if getattr(member.guild_permissions, "manage_guild", False) or getattr(member.guild_permissions, "manage_channels", False):
        base = int(weights.get("__MANAGE_GUILD__", 90))
        # Si la personne a aussi un rôle nommé DJ/VIP etc., on prend le max
        best_named = base
        for r in getattr(member, "roles", []) or []:
            if r and r.name in weights:
                best_named = max(best_named, int(weights[r.name]))
        return best_named

    best = int(weights.get("__DEFAULT__", 10))
    for r in getattr(member, "roles", []) or []:
        if r and r.name in weights:
            best = max(best, int(weights[r.name]))
    return best

def can_bypass_quota(bot, guild_id: int, user_id: int) -> bool:
    # Admins peuvent dépasser le quota
    guild = bot.get_guild(int(guild_id)) if bot else None
    m = guild and guild.get_member(int(user_id))
    return bool(m and (m.guild_permissions.administrator or m.guild_permissions.manage_guild))

def can_user_bump_over(bot, guild_id: int, requester_id: int, owner_weight: int) -> bool:
    """
    Autorise un bump si le poids du demandeur est STRICTEMENT supérieur au poids de l'auteur de la piste.
    (ou s'il est admin)
    """
    req_w = get_member_weight(bot, guild_id, requester_id)
    if can_bypass_quota(bot, guild_id, requester_id):
        return True
    return req_w > int(owner_weight or 0)
