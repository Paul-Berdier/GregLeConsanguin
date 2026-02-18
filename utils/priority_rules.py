import os, json
from typing import Dict, Optional, Any, List, Tuple

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


def _member_roles_names(member) -> List[str]:
    try:
        return [r.name for r in (getattr(member, "roles", []) or []) if r and r.name and r.name != "@everyone"]
    except Exception:
        return []


def _best_weight_and_key_for_member(member, weights: Dict[str, int]) -> Tuple[int, str]:
    """
    Retourne (best_weight, best_key) pour debug/UI.
    best_key = "__ADMIN__" / "__MANAGE_GUILD__" / nom de rôle / "__DEFAULT__"
    """
    if not member:
        return int(weights.get("__DEFAULT__", 10)), "__DEFAULT__"

    # Admin
    if getattr(member.guild_permissions, "administrator", False):
        return int(weights.get("__ADMIN__", 100)), "__ADMIN__"

    # Manage guild/channels
    if getattr(member.guild_permissions, "manage_guild", False) or getattr(member.guild_permissions, "manage_channels", False):
        base = int(weights.get("__MANAGE_GUILD__", 90))
        best_w, best_k = base, "__MANAGE_GUILD__"
        for r in getattr(member, "roles", []) or []:
            if r and r.name in weights:
                w = int(weights[r.name])
                if w > best_w:
                    best_w, best_k = w, r.name
        return best_w, best_k

    # Default + rôles nommés
    best_w, best_k = int(weights.get("__DEFAULT__", 10)), "__DEFAULT__"
    for r in getattr(member, "roles", []) or []:
        if r and r.name in weights:
            w = int(weights[r.name])
            if w > best_w:
                best_w, best_k = w, r.name
    return best_w, best_k


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

    best_w, _ = _best_weight_and_key_for_member(member, weights)
    return int(best_w)


def get_member_weight_key(bot, guild_id: int, user_id: int) -> Tuple[int, str]:
    """
    Version enrichie: renvoie (poids, clé) où clé = __ADMIN__/__MANAGE_GUILD__/DJ/VIP/.../__DEFAULT__/__OWNER__
    """
    if is_owner(user_id):
        return OWNER_WEIGHT, "__OWNER__"

    weights = get_weights()
    guild = bot.get_guild(int(guild_id)) if bot else None
    if not guild:
        return int(weights.get("__DEFAULT__", 10)), "__DEFAULT__"
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return int(weights.get("__DEFAULT__", 10)), "__DEFAULT__"

    w, k = _best_weight_and_key_for_member(member, weights)
    return int(w), str(k)


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


def is_priority_item(item: dict) -> bool:
    return bool(item and (item.get("priority") or item.get("pin") or item.get("pinned")))


def first_non_priority_index(queue: List[dict]) -> int:
    for i, it in enumerate(queue or []):
        if not is_priority_item(it):
            return i
    return len(queue or [])


def can_user_edit_item(bot, guild_id: int, requester_id: int, item: dict) -> bool:
    # owner OK, admin OK, poids >= owner_weight OK
    if not item:
        return False
    owner_id = str(item.get("added_by") or item.get("owner_id") or "")
    if owner_id and str(owner_id) == str(requester_id):
        return True
    if can_bypass_quota(bot, guild_id, requester_id):
        return True

    owner_w = int(item.get("priority") or 0)
    if owner_w <= 0:
        # fallback si l'item n'expose pas la priorité
        try:
            owner_id_int = int(owner_id)
            owner_w = get_member_weight(bot, guild_id, owner_id_int)
        except Exception:
            owner_w = 0
    return can_user_bump_over(bot, guild_id, requester_id, owner_w)


def build_user_meta(bot, guild_id: int, user_id: int) -> Dict[str, Any]:
    """
    Métadonnées légères pour la logique de file/priorité.
    """
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None

    roles = _member_roles_names(member) if member else []
    is_admin = bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))

    weight, weight_key = get_member_weight_key(bot, guild_id, user_id)

    # username + display (utile pour logs)
    if member:
        username = getattr(member, "name", str(user_id))
        display = getattr(member, "display_name", username) or username
        discriminator = getattr(member, "discriminator", None)
        try:
            avatar = str(member.display_avatar.url) if getattr(member, "display_avatar", None) else None
        except Exception:
            avatar = None
    else:
        username, display, discriminator, avatar = str(user_id), str(user_id), None, None

    return {
        "user_id": str(user_id),
        "roles": roles,
        "weight": int(weight),
        "weight_key": str(weight_key),
        "is_admin": is_admin,
        "is_owner": bool(is_owner(user_id)),
        "can_bypass": bool(is_admin or is_owner(user_id)),
        "username": username,
        "display_name": display,
        "discriminator": discriminator,
        "avatar": avatar,
    }


def build_user_out(bot, guild_id: int, user_id: int) -> Dict[str, Any]:
    """
    Construit un dict compatible avec api.schemas.user.UserOut (pour exposer à l’UI).
    """
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None

    if member:
        username = getattr(member, "name", str(user_id))
        display_name = getattr(member, "display_name", username) or username
        # avatar url
        try:
            avatar = str(member.display_avatar.url) if getattr(member, "display_avatar", None) else None
        except Exception:
            avatar = None
        discriminator = getattr(member, "discriminator", None)
        roles = _member_roles_names(member)
        is_admin = bool(member.guild_permissions.administrator or member.guild_permissions.manage_guild)
    else:
        username, display_name, avatar, discriminator, roles, is_admin = str(user_id), str(user_id), None, None, [], False

    w, k = get_member_weight_key(bot, guild_id, user_id)

    return {
        "id": str(user_id),
        "username": username,
        "display_name": display_name,
        "avatar": avatar,
        "discriminator": discriminator,
        "roles": roles,
        "weight": int(w),
        "weight_key": str(k),
        "is_admin": bool(is_admin),
        "is_owner": bool(is_owner(user_id)),
    }


def format_user_display(user_out: Dict[str, Any]) -> str:
    """
    Retourne un display 'propre' à afficher.
    Ex: 'Paul' ou 'Paul#1234' si discriminant dispo.
    """
    if not user_out:
        return "Unknown"
    name = (user_out.get("display_name") or user_out.get("username") or user_out.get("id") or "Unknown")
    disc = user_out.get("discriminator")
    # Discord moderne: discriminator parfois None / "0"
    if disc and str(disc) not in ("0", "None"):
        return f"{name}#{disc}"
    return str(name)


def build_track_prio(item: Dict[str, Any], user_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrichit un item de queue avec identité + priorité.
    """
    out = dict(item or {})
    weight = int(user_meta.get("weight", 0) or 0)

    out["priority"] = weight
    out["priority_key"] = str(user_meta.get("weight_key") or "")

    out["added_by"] = str(user_meta.get("user_id") or "")
    out["added_by_name"] = str(user_meta.get("display_name") or user_meta.get("username") or out["added_by"])
    out["added_by_avatar"] = user_meta.get("avatar")
    out["added_by_roles"] = list(user_meta.get("roles") or [])

    # Format affichage
    user_out_like = {
        "display_name": user_meta.get("display_name"),
        "username": user_meta.get("username"),
        "id": user_meta.get("user_id"),
        "discriminator": user_meta.get("discriminator"),
    }
    out["added_by_display"] = format_user_display(user_out_like)

    return out
