import os, json
from typing import Dict, Optional, Any

# Poids par défaut (plus haut = plus prioritaire)
DEFAULT_WEIGHTS: Dict[str, int] = {
    "__ADMIN__": 100,
    "__MANAGE_GUILD__": 90,
    "DJ": 80,
    "VIP": 60,
    "Booster": 50,
    "__DEFAULT__": 10,
}

OWNER_WEIGHT = 10_000  # bien plus haut que n'importe quel rôle

# Fichier de config persistée (overrides)
CONFIG_PATH = os.getenv("PRIORITY_FILE", "data/priority.json")

def _to_int(v):
    try:
        return int(v)
    except Exception:
        try:
            return int(str(v).strip())
        except Exception:
            return None

def is_owner(user_id) -> bool:
    oid = _to_int(os.getenv("GREG_OWNER_ID", ""))
    return (oid is not None) and (_to_int(user_id) == oid)

# --- lecture overrides ENV (legacy) ---
def _load_custom_weights_env() -> Dict[str, int]:
    raw = os.getenv("PRIORITY_ROLE_WEIGHTS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): int(v) for k, v in data.items()}
    except Exception:
        return {}

# --- lecture/écriture overrides fichier ---
_OVERRIDES = {"weights": {}, "cap": None}

def _ensure_dir(path: str):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def _load_overrides_file():
    global _OVERRIDES
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                w = data.get("weights") or {}
                c = data.get("cap", None)
                if isinstance(w, dict):
                    _OVERRIDES["weights"] = {str(k): int(v) for k, v in w.items()}
                if c is not None:
                    try:
                        _OVERRIDES["cap"] = int(c)
                    except Exception:
                        pass
    except Exception:
        pass

def _save_overrides_file():
    try:
        _ensure_dir(CONFIG_PATH)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_OVERRIDES, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# état en mémoire
CUSTOM: Dict[str, int] = {}
PER_USER_CAP: int = int(os.getenv("QUEUE_PER_USER_CAP", "10") or 10)

# init
def _init_state():
    global CUSTOM, PER_USER_CAP
    env_w = _load_custom_weights_env()
    _load_overrides_file()
    CUSTOM = dict(env_w)
    CUSTOM.update(_OVERRIDES.get("weights", {}))
    if _OVERRIDES.get("cap") is not None:
        PER_USER_CAP = int(_OVERRIDES["cap"])

_init_state()

# === API publique (config) ===

def get_overrides():
    return {"weights": dict(_OVERRIDES.get("weights", {})), "cap": int(PER_USER_CAP)}

def list_keys():
    return ["__ADMIN__", "__MANAGE_GUILD__", "__DEFAULT__"]

def get_weights() -> Dict[str, int]:
    w = DEFAULT_WEIGHTS.copy()
    w.update(CUSTOM)
    return w

def set_role_weight(name: str, weight: int) -> Dict[str, int]:
    name = str(name).strip()
    CUSTOM[name] = int(weight)
    _OVERRIDES["weights"][name] = int(weight)
    _save_overrides_file()
    return get_weights()

def reset_role_weight(name: str) -> Dict[str, int]:
    name = str(name).strip()
    CUSTOM.pop(name, None)
    _OVERRIDES["weights"].pop(name, None)
    _save_overrides_file()
    return get_weights()

def set_key_weight(key: str, weight: int) -> Dict[str, int]:
    key = str(key).strip()
    if key not in list_keys():
        raise ValueError("Clé inconnue")
    CUSTOM[key] = int(weight)
    _OVERRIDES["weights"][key] = int(weight)
    _save_overrides_file()
    return get_weights()

def set_per_user_cap(n: int) -> int:
    global PER_USER_CAP
    PER_USER_CAP = max(0, int(n))
    _OVERRIDES["cap"] = PER_USER_CAP
    _save_overrides_file()
    return PER_USER_CAP

# === logique de poids / droits ===

def _member_roles_names(member) -> list[str]:
    try:
        return [r.name for r in (getattr(member, "roles", []) or []) if r and r.name and r.name != "@everyone"]
    except Exception:
        return []

def get_member_weight(bot, guild_id: int, user_id: int) -> int:
    if is_owner(user_id):
        return OWNER_WEIGHT

    weights = get_weights()
    guild = bot.get_guild(int(guild_id)) if bot else None
    if not guild:
        return int(weights.get("__DEFAULT__", 10))
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return int(weights.get("__DEFAULT__", 10))

    # Admin / Manage Guild
    if getattr(member.guild_permissions, "administrator", False):
        return int(weights.get("__ADMIN__", 100))
    if getattr(member.guild_permissions, "manage_guild", False) or getattr(member.guild_permissions, "manage_channels", False):
        base = int(weights.get("__MANAGE_GUILD__", 90))
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
    if is_owner(user_id):
        return True
    guild = bot.get_guild(int(guild_id)) if bot else None
    m = guild and guild.get_member(int(user_id))
    return bool(m and (m.guild_permissions.administrator or m.guild_permissions.manage_guild))

def can_user_bump_over(bot, guild_id: int, requester_id: int, owner_weight: int) -> bool:
    if is_owner(requester_id):
        return True
    req_w = get_member_weight(bot, guild_id, requester_id)
    if can_bypass_quota(bot, guild_id, requester_id):
        return True
    return req_w > int(owner_weight or 0)

# === helpers d’objets (utiles au service & API) ===

def build_user_meta(bot, guild_id: int, user_id: int) -> Dict[str, Any]:
    """
    Métadonnées légères pour la logique de file/priorité.
    """
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None

    roles = _member_roles_names(member) if member else []
    is_admin = bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))
    weight = get_member_weight(bot, guild_id, user_id)

    return {
        "user_id": str(user_id),
        "roles": roles,
        "weight": int(weight),
        "is_admin": is_admin,
        "is_owner": bool(is_owner(user_id)),
        "can_bypass": bool(is_admin or is_owner(user_id)),
    }

def build_user_out(bot, guild_id: int, user_id: int) -> Dict[str, Any]:
    """
    Construit un dict compatible avec api.schemas.user.UserOut (pour exposer à l’UI).
    """
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None

    if member:
        username = getattr(member, "name", str(user_id))
        # avatar url
        try:
            avatar = str(member.display_avatar.url) if getattr(member, "display_avatar", None) else None
        except Exception:
            avatar = None
        discriminator = getattr(member, "discriminator", None)
        roles = _member_roles_names(member)
        is_admin = bool(member.guild_permissions.administrator or member.guild_permissions.manage_guild)
    else:
        username, avatar, discriminator, roles, is_admin = str(user_id), None, None, [], False

    return {
        "id": str(user_id),
        "username": username,
        "avatar": avatar,
        "discriminator": discriminator,
        "roles": roles,
        "weight": int(get_member_weight(bot, guild_id, user_id)),
        "is_admin": bool(is_admin),
        "is_owner": bool(is_owner(user_id)),
    }

def build_track_prio(item: Dict[str, Any], user_meta: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item or {})
    out["priority"] = int(user_meta.get("weight", 0))
    out["added_by"] = user_meta.get("user_id")
    return out
