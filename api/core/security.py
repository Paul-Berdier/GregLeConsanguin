# api/core/security.py

from __future__ import annotations

import hmac
import os
from hashlib import sha256
from time import time


def hmac_sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), sha256).hexdigest()


def make_state(secret: str, subject: str, ttl_seconds: int = 600) -> str:
    exp = int(time()) + ttl_seconds
    raw = f"{subject}:{exp}"
    sig = hmac_sign(secret, raw)
    return f"{raw}:{sig}"


def verify_state(secret: str, state: str) -> bool:
    try:
        subject, exp_str, sig = state.split(":", 2)
        raw = f"{subject}:{exp_str}"
        expected = hmac_sign(secret, raw)
        if not hmac.compare_digest(expected, sig):
            return False
        return int(exp_str) >= int(time())
    except Exception:
        return False
