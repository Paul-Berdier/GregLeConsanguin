"""Système de priorité — version 2.

Changements par rapport à v1 :
- is_priority_item() basé sur un seuil configurable (plus de truthy sur 10)
- Insertion en 2 zones (prio / normal) avec find_insert_position()
- can_control_playback() utilise >= au lieu de > strict
- Ses propres items sont toujours modifiables
- PermissionResult structuré pour des messages ciblés
- Validation des move() pour maintenir l'invariant de zone
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────── Config ───────────────────────────

OWNER_WEIGHT = 10_000

DEFAULT_WEIGHTS: Dict[str, int] = {
    "__OWNER__": OWNER_WEIGHT,
    "__ADMIN__": 100,
    "__MANAGE_GUILD__": 90,
    "DJ": 80,
    "VIP": 60,
    "Booster": 45,
    "__DEFAULT__": 10,
}

# Fichier d'overrides persisté
_CONFIG_PATH = os.getenv("PRIORITY_FILE", "data/priority.json")

# État mémoire
_overrides: Dict[str, Any] = {"weights": {}, "cap": None}
_initialized = False


def _ensure_init():
    global _initialized
    if _initialized:
        return
    _initialized = True
    _load_overrides()


def _get_threshold() -> int:
    """Seuil de priorité — en dessous = normal, au-dessus = prioritaire."""
    try:
        return int(os.getenv("PRIORITY_THRESHOLD", "50"))
    except (ValueError, TypeError):
        return 50


def _get_cap() -> int:
    """Quota par utilisateur."""
    _ensure_init()
    if _overrides.get("cap") is not None:
        return int(_overrides["cap"])
    try:
        return int(os.getenv("QUEUE_PER_USER_CAP", "10"))
    except (ValueError, TypeError):
        return 10


# ─────────────────────────── Persistence ───────────────────────────

def _load_overrides():
    global _overrides
    # 1) Fichier
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                w = data.get("weights")
                if isinstance(w, dict):
                    _overrides["weights"] = {str(k): int(v) for k, v in w.items()}
                c = data.get("cap")
                if c is not None:
                    _overrides["cap"] = int(c)
    except Exception:
        pass

    # 2) Env (prioritaire sur fichier)
    raw = os.getenv("PRIORITY_ROLE_WEIGHTS", "").strip()
    if raw:
        try:
            env_w = json.loads(raw)
            _overrides["weights"].update({str(k): int(v) for k, v in env_w.items()})
        except Exception:
            pass


def _save_overrides():
    try:
        d = os.path.dirname(_CONFIG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_overrides, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─────────────────────────── API de config ───────────────────────────

def get_weights() -> Dict[str, int]:
    """Retourne les poids effectifs (défauts + overrides)."""
    _ensure_init()
    w = DEFAULT_WEIGHTS.copy()
    w.update(_overrides.get("weights", {}))
    return w


def set_role_weight(name: str, weight: int) -> Dict[str, int]:
    _ensure_init()
    _overrides["weights"][str(name)] = int(weight)
    _save_overrides()
    return get_weights()


def reset_role_weight(name: str) -> Dict[str, int]:
    _ensure_init()
    _overrides["weights"].pop(str(name), None)
    _save_overrides()
    return get_weights()


def set_key_weight(key: str, weight: int) -> Dict[str, int]:
    allowed = ["__ADMIN__", "__MANAGE_GUILD__", "__DEFAULT__"]
    if key not in allowed:
        raise ValueError(f"Clé inconnue: {key}. Autorisées: {allowed}")
    return set_role_weight(key, weight)


def list_keys() -> List[str]:
    return ["__ADMIN__", "__MANAGE_GUILD__", "__DEFAULT__"]


def set_per_user_cap(n: int) -> int:
    _ensure_init()
    cap = max(0, int(n))
    _overrides["cap"] = cap
    _save_overrides()
    return cap


def get_per_user_cap() -> int:
    return _get_cap()


def get_overrides() -> Dict[str, Any]:
    _ensure_init()
    return {"weights": dict(_overrides.get("weights", {})), "cap": _get_cap()}


# ─────────────────────────── Permission Result ───────────────────────────

@dataclass
class PermissionResult:
    """Résultat d'un check de permission. `reason` permet un message Greg ciblé."""
    allowed: bool
    reason: str  # ok, own_item, admin, owner, equal_or_higher_rank, insufficient_rank, quota_exceeded, ...


# ─────────────────────────── Poids d'un membre ───────────────────────────

def is_owner(user_id) -> bool:
    oid = os.getenv("GREG_OWNER_ID", "")
    try:
        return bool(oid) and int(user_id) == int(oid)
    except (ValueError, TypeError):
        return False


def _is_admin_member(member) -> bool:
    """Vérifie si un member Discord est admin/manage_guild."""
    if not member:
        return False
    perms = getattr(member, "guild_permissions", None)
    if not perms:
        return False
    return bool(perms.administrator or perms.manage_guild)


def _best_role_weight(member, weights: Dict[str, int]) -> int:
    """Retourne le meilleur poids basé sur les rôles du membre."""
    best = 0
    for role in getattr(member, "roles", []) or []:
        if role and getattr(role, "name", "") != "@everyone":
            w = weights.get(role.name, 0)
            if w > best:
                best = w
    return best


def get_member_weight(bot, guild_id: int, user_id: int) -> int:
    """Retourne le poids effectif d'un membre (max de toutes ses sources)."""
    if is_owner(user_id):
        return OWNER_WEIGHT

    weights = get_weights()
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return weights.get("__DEFAULT__", 10)

    candidates = [weights.get("__DEFAULT__", 10)]

    perms = getattr(member, "guild_permissions", None)
    if perms:
        if perms.administrator:
            candidates.append(weights.get("__ADMIN__", 100))
        if perms.manage_guild or perms.manage_channels:
            candidates.append(weights.get("__MANAGE_GUILD__", 90))

    candidates.append(_best_role_weight(member, weights))
    return max(candidates)


def get_member_weight_and_key(bot, guild_id: int, user_id: int) -> Tuple[int, str]:
    """Retourne (poids, clé source) pour debug/UI."""
    if is_owner(user_id):
        return OWNER_WEIGHT, "__OWNER__"

    weights = get_weights()
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None
    if not member:
        return weights.get("__DEFAULT__", 10), "__DEFAULT__"

    best_w = weights.get("__DEFAULT__", 10)
    best_k = "__DEFAULT__"

    perms = getattr(member, "guild_permissions", None)
    if perms:
        if perms.administrator and weights.get("__ADMIN__", 100) > best_w:
            best_w, best_k = weights["__ADMIN__"], "__ADMIN__"
        elif (perms.manage_guild or perms.manage_channels) and weights.get("__MANAGE_GUILD__", 90) > best_w:
            best_w, best_k = weights["__MANAGE_GUILD__"], "__MANAGE_GUILD__"

    for role in getattr(member, "roles", []) or []:
        if role and role.name != "@everyone":
            w = weights.get(role.name, 0)
            if w > best_w:
                best_w, best_k = w, role.name

    return best_w, best_k


# ─────────────────────────── Droits d'action ───────────────────────────

def can_bypass_quota(bot, guild_id: int, user_id: int) -> bool:
    """Les owner et admins bypass le quota."""
    if is_owner(user_id):
        return True
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None
    return _is_admin_member(member)


def can_control_playback(bot, guild_id: int, requester_id: int, current_owner_weight: int) -> PermissionResult:
    """Peut-on skip/pause/stop le morceau en cours ?

    Règle : poids du requester >= poids du owner du morceau.
    (Même rang = OK. C'est le fix principal par rapport à v1.)
    """
    if is_owner(requester_id):
        return PermissionResult(True, "owner")

    if can_bypass_quota(bot, guild_id, requester_id):
        return PermissionResult(True, "admin")

    req_weight = get_member_weight(bot, guild_id, requester_id)
    if req_weight >= int(current_owner_weight or 0):
        return PermissionResult(True, "equal_or_higher_rank")

    return PermissionResult(False, "insufficient_rank")


def can_edit_queue_item(bot, guild_id: int, requester_id: int, item: dict) -> PermissionResult:
    """Peut-on supprimer/déplacer cet item de la queue ?

    1. C'est ton propre item → toujours OK
    2. Admin/Owner → toujours OK
    3. Ton poids >= poids de l'item → OK
    """
    item_owner = str(item.get("added_by") or "")

    # Règle 1 : propre item
    if item_owner and item_owner == str(requester_id):
        return PermissionResult(True, "own_item")

    # Règle 2 : admin/owner
    if is_owner(requester_id) or can_bypass_quota(bot, guild_id, requester_id):
        return PermissionResult(True, "admin")

    # Règle 3 : poids >= item
    req_weight = get_member_weight(bot, guild_id, requester_id)
    item_weight = int(item.get("priority") or 0)
    if req_weight >= item_weight:
        return PermissionResult(True, "equal_or_higher_rank")

    return PermissionResult(False, "insufficient_rank")


# ─────────────────────────── Gestion de la queue ───────────────────────────

def is_priority_item(item: dict) -> bool:
    """Un item est 'prioritaire' si son poids dépasse le seuil.

    Fix v2: avant, __DEFAULT__=10 était truthy donc TOUT était "prioritaire".
    Maintenant, c'est basé sur un seuil configurable (défaut 50).
    """
    return int(item.get("priority") or 0) > _get_threshold()


def priority_boundary(queue: List[dict]) -> int:
    """Index du premier item non-prioritaire (= frontière entre les 2 zones)."""
    for i, item in enumerate(queue):
        if not is_priority_item(item):
            return i
    return len(queue)


def find_insert_position(queue: List[dict], new_weight: int) -> int:
    """Trouve la position d'insertion pour un nouvel item.

    Logique simple en 2 zones :
    - Item prioritaire (poids > seuil) → fin du bloc prioritaire
    - Item normal (poids ≤ seuil) → fin de la queue (FIFO)

    La queue reste toujours triée en 2 blocs.
    """
    threshold = _get_threshold()
    if new_weight > threshold:
        # Trouver la fin de la zone prioritaire
        for i, item in enumerate(queue):
            if int(item.get("priority") or 0) <= threshold:
                return i  # Juste avant le premier item normal
        return len(queue)  # Toute la queue est prio → à la fin
    else:
        return len(queue)  # Normal → fin de queue (FIFO)


def validate_move(
    queue: List[dict], src: int, dst: int,
    requester_id: int, bot, guild_id: int
) -> PermissionResult:
    """Vérifie qu'un move ne casse pas l'invariant de zone.

    Interdit (sauf admin) :
    - Déplacer un item normal dans la zone prioritaire
    - Déplacer un item prioritaire dans la zone normale
    """
    n = len(queue)
    if not (0 <= src < n and 0 <= dst < n):
        return PermissionResult(False, "out_of_bounds")

    if src == dst:
        return PermissionResult(False, "same_position")

    if is_owner(requester_id) or can_bypass_quota(bot, guild_id, requester_id):
        return PermissionResult(True, "admin")

    src_item = queue[src]
    src_is_prio = is_priority_item(src_item)
    boundary = priority_boundary(queue)

    # Simule le move pour checker la position finale
    dst_in_prio_zone = dst < boundary if src >= boundary else dst < (boundary - 1)

    if not src_is_prio and dst_in_prio_zone:
        return PermissionResult(False, "cannot_promote_to_priority_zone")

    if src_is_prio and not dst_in_prio_zone:
        return PermissionResult(False, "cannot_demote_from_priority_zone")

    return PermissionResult(True, "ok")


def check_quota(queue: List[dict], user_id: int, bot, guild_id: int) -> PermissionResult:
    """Vérifie le quota de l'utilisateur."""
    if can_bypass_quota(bot, guild_id, user_id):
        return PermissionResult(True, "bypass")

    cap = _get_cap()
    count = sum(1 for item in queue if str(item.get("added_by")) == str(user_id))
    if count >= cap:
        return PermissionResult(False, f"quota_exceeded:{count}/{cap}")

    return PermissionResult(True, "ok")


# ─────────────────────────── Helpers UI ───────────────────────────

def build_user_info(bot, guild_id: int, user_id: int) -> Dict[str, Any]:
    """Construit un dict user pour l'UI/API."""
    guild = bot.get_guild(int(guild_id)) if bot else None
    member = guild.get_member(int(user_id)) if guild else None

    w, k = get_member_weight_and_key(bot, guild_id, user_id)

    if member:
        username = getattr(member, "name", str(user_id))
        display_name = getattr(member, "display_name", username) or username
        try:
            av = getattr(member, "display_avatar", None) or getattr(member, "avatar", None)
            avatar_url = str(av.url) if av else ""
        except Exception:
            avatar_url = ""
        roles = [r.name for r in (member.roles or []) if r.name != "@everyone"]
    else:
        username = str(user_id)
        display_name = str(user_id)
        avatar_url = ""
        roles = []

    return {
        "id": str(user_id),
        "username": username,
        "display_name": display_name,
        "avatar_url": avatar_url,
        "roles": roles,
        "weight": w,
        "weight_key": k,
        "is_admin": _is_admin_member(member) if member else False,
        "is_owner": is_owner(user_id),
    }
