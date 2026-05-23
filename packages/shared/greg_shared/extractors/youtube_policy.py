from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class YouTubeStrategy:
    client: str
    use_cookies: bool
    needs_po_token: bool = False
    label: str = ""

    def display_name(self) -> str:
        if self.label:
            return self.label
        suffix = "+cookies" if self.use_cookies else "-nocookie"
        po = "+po" if self.needs_po_token else ""
        return f"{self.client}{po}{suffix}"


def _write_cookiefile_from_b64(target_path: str) -> Optional[str]:
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
        text = raw.decode("utf-8", errors="replace")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(text)
        return target_path
    except Exception:
        return None


def resolve_cookie_inputs(
    cookies_file: Optional[str],
    cookies_from_browser: Optional[str],
    *,
    default_cookie_file: str = "youtube.com_cookies.txt",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Résout proprement les cookies utilisables par yt-dlp.

    Ordre :
    1. arg cookies_file
    2. env YTDLP_COOKIES_FILE / YOUTUBE_COOKIES_PATH
    3. fichier local par défaut
    4. YTDLP_COOKIES_B64 -> écrit un Netscape cookiefile
    """
    browser_spec = (cookies_from_browser or os.getenv("YTDLP_COOKIES_BROWSER") or "").strip() or None

    if cookies_file and os.path.exists(cookies_file):
        return cookies_file, browser_spec

    env_file = (os.getenv("YTDLP_COOKIES_FILE") or os.getenv("YOUTUBE_COOKIES_PATH") or "").strip()
    if env_file and os.path.exists(env_file):
        return env_file, browser_spec

    if os.path.exists(default_cookie_file):
        return default_cookie_file, browser_spec

    written = _write_cookiefile_from_b64(default_cookie_file)
    if written and os.path.exists(written):
        return written, browser_spec

    return None, browser_spec


def has_auth_cookies(cookies_file: Optional[str], cookies_from_browser: Optional[str]) -> bool:
    cookiefile, browser = resolve_cookie_inputs(cookies_file, cookies_from_browser)
    return bool(cookiefile or browser)


def client_supports_cookies(client: str) -> bool:
    """
    yt-dlp/YouTube ne supportent pas toutes les combinaisons client+cookies
    de façon équivalente. On limite les clients auth aux clients web-like.
    """
    return client in {"mweb", "web", "web_creator", "web_safari"}


def strategy_order(cookies_file: Optional[str], cookies_from_browser: Optional[str]) -> List[YouTubeStrategy]:
    """
    Politique de fallback propre et déterministe (révision 2026).

    Hiérarchie :
    - `tv` / `tv_simply` : pas de PO token requis, pas de cookies → 1er choix.
    - `mweb` + PO token (avec/sans cookies) : voie historique, encore utile.
    - `web_safari` / `web_creator` + cookies : fallback navigateur authentifié.
    - `ios` / `android` / `web` no-cookie : dernier recours (souvent 403 en 2026).
    """
    has_auth = has_auth_cookies(cookies_file, cookies_from_browser)
    out: List[YouTubeStrategy] = []

    # 1) Voie royale 2026 — no-PO, no-cookies
    out.append(YouTubeStrategy("tv", use_cookies=False, needs_po_token=False, label="tv-nocookie"))
    out.append(YouTubeStrategy("tv_simply", use_cookies=False, needs_po_token=False, label="tv_simply-nocookie"))

    # 2) mweb + PO token
    out.append(YouTubeStrategy("mweb", use_cookies=False, needs_po_token=True, label="mweb+po-nocookie"))
    if has_auth:
        out.append(YouTubeStrategy("mweb", use_cookies=True, needs_po_token=True, label="mweb+po+cookies"))

    # 3) Web-like avec cookies
    if has_auth:
        out.append(YouTubeStrategy("web_safari", use_cookies=True, needs_po_token=False, label="web_safari+cookies"))
        out.append(YouTubeStrategy("web_creator", use_cookies=True, needs_po_token=False, label="web_creator+cookies"))
        out.append(YouTubeStrategy("web", use_cookies=True, needs_po_token=False, label="web+cookies"))

    # 4) Fallback no-cookie tardif (à éviter en 2026 sans PO)
    out.append(YouTubeStrategy("ios", use_cookies=False, needs_po_token=False, label="ios-nocookie"))
    out.append(YouTubeStrategy("android", use_cookies=False, needs_po_token=False, label="android-nocookie"))
    out.append(YouTubeStrategy("web", use_cookies=False, needs_po_token=False, label="web-nocookie"))

    # déduplication stable
    seen = set()
    deduped: List[YouTubeStrategy] = []
    for s in out:
        key = (s.client, s.use_cookies, s.needs_po_token)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    return deduped