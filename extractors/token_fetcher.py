# extractors/token_fetcher.py
# ------------------------------------------------------------
# Récupération automatique du poToken depuis m.youtube.com
# - Nécessite Playwright (pip install playwright) + drivers (playwright install)
# - Utilise Chromium headless par défaut (PLAYWRIGHT_HEADLESS=0 pour debug)
# - Cookies facultatifs: via YTDLP_COOKIES_B64 (format Netscape) -> injectés
#
# Public:
#   fetch_po_token(video_id: str, timeout_ms: int = 15000) -> Optional[str]
# ------------------------------------------------------------
from __future__ import annotations

import base64
import os
from typing import Optional

def _ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except Exception:
        return None

def _inject_cookies_from_b64(context) -> None:
    """
    Si YTDLP_COOKIES_B64 (format Netscape) est présent, on tente d'en extraire
    les cookies *.youtube.com/*google.com utiles (très permissif).
    """
    b64 = os.getenv("YTDLP_COOKIES_B64")
    if not b64:
        return
    try:
        raw = base64.b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        return

    cookies = []
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        # Netscape cookie: domain \t flag \t path \t secure \t expiry \t name \t value
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, expiry, name, value = parts[-7:]
        domain = domain.strip()
        name = name.strip()
        value = value.strip()
        if not domain or not name:
            continue
        # Playwright attend un host sans le préfixe "." au besoin
        host = domain[1:] if domain.startswith(".") else domain
        cookies.append({
            "name": name,
            "value": value,
            "domain": host,
            "path": path or "/",
            "httpOnly": False,
            "secure": (secure.lower() == "true"),
            "sameSite": "Lax",
            "expires": int(expiry) if expiry.isdigit() else -1,
        })
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception:
            pass

def fetch_po_token(video_id: str, timeout_ms: int = 15000) -> Optional[str]:
    """
    Ouvre m.youtube.com/watch?v=<id> et tente d'extraire ytcfg.data.PO_TOKEN.
    Retourne le token brut (sans préfixe ios.gvs+/web.gvs+, etc.) ou None.
    """
    sync_playwright = _ensure_playwright()
    if not sync_playwright:
        return None

    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "1").lower()
    headless = (headless_env not in ("0", "false", "no"))

    url = f"https://m.youtube.com/watch?v={video_id}"

    with sync_playwright()() as p:
        browser = p.chromium.launch(headless=headless, args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ])
        context = browser.new_context(
            user_agent=os.getenv("YTDLP_FORCE_UA") or (
                "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
            locale="en-US",
        )

        # Cookies éventuellement
        _inject_cookies_from_b64(context)

        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Donne une chance au bootstrap JS de poser ytcfg
            page.wait_for_timeout(800)

            js = """
                (() => {
                  try {
                    const ytcfg = (window.ytcfg && (window.ytcfg.data || window.ytcfg.get && window.ytcfg.get())) || {};
                    return ytcfg && (ytcfg.PO_TOKEN || ytcfg['PO_TOKEN']) || null;
                  } catch(e) { return null; }
                })();
            """
            token = page.evaluate(js)
            if token and isinstance(token, str) and len(token) > 10:
                return token

            # Fallback: certaines versions stockent dans window.yt.config_ ou JSON embarqué
            js2 = """
                (() => {
                  try {
                    if (window.yt && window.yt.config_ && window.yt.config_.PO_TOKEN) return window.yt.config_.PO_TOKEN;
                    const scripts = Array.from(document.querySelectorAll('script')).map(s => s.textContent || '');
                    for (const code of scripts) {
                      const m = code.match(/"PO_TOKEN"\\s*:\\s*"([^"]{20,})"/);
                      if (m) return m[1];
                    }
                    return null;
                  } catch(e) { return null; }
                })();
            """
            token2 = page.evaluate(js2)
            if token2 and isinstance(token2, str) and len(token2) > 10:
                return token2

            return None
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
