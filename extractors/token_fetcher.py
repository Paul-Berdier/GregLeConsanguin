# extractors/token_fetcher.py
# ------------------------------------------------------------
# Récupération robuste du PO_TOKEN depuis YouTube
# - pip install playwright
# - python -m playwright install chromium
# - Headless par défaut (PLAYWRIGHT_HEADLESS=0 pour débug visuel)
# - Cookies optionnels via YTDLP_COOKIES_B64 (format Netscape, texte)
#
# Public:
#   fetch_po_token(video_id: str, timeout_ms: int = 15000) -> Optional[str]
#   -> Thread-safe: l’API Sync Playwright tourne dans un thread pour
#      éviter "Sync API inside asyncio loop".
# ------------------------------------------------------------
from __future__ import annotations

import base64
import os
import threading
from typing import Optional

_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")

def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG][po] {msg}")

def _inject_cookies_from_b64(context) -> None:
    """Injecte des cookies depuis YTDLP_COOKIES_B64 (format Netscape)."""
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
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, expiry, name, value = parts[-7:]
        domain = (domain or "").strip()
        name = (name or "").strip()
        value = (value or "").strip()
        if not domain or not name:
            continue
        host = domain[1:] if domain.startswith(".") else domain
        try:
            exp = int(expiry)
        except Exception:
            exp = -1
        cookies.append({
            "name": name,
            "value": value,
            "domain": host,
            "path": path or "/",
            "httpOnly": False,
            "secure": (str(secure).strip().lower() == "true"),
            "sameSite": "Lax",
            "expires": exp,
        })

    if cookies:
        try:
            context.add_cookies(cookies)
            _dbg(f"cookies injected: {len(cookies)}")
        except Exception as e:
            _dbg(f"cookies inject fail: {e}")

def _maybe_handle_consent(page, timeout_ms: int) -> None:
    """Essaye de fermer les bannières de consentement si présentes."""
    try:
        candidates = [
            'button:has-text("I agree")',
            'button:has-text("J\'accepte")',
            'button:has-text("J’accepte")',
            'text=I agree',
            'text=J\'accepte',
            '#introAgreeButton',
            'form[action*="consent"] button[type="submit"]',
            '[aria-label*="Agree"]',
            'button[aria-label*="J’accepte"]',
        ]
        for sel in candidates:
            loc = page.locator(sel)
            if loc.count() > 0:
                _dbg(f"consent: clicking {sel!r}")
                loc.first.click(timeout=min(timeout_ms, 1500))
                page.wait_for_timeout(400)
                break
    except Exception:
        pass

def _extract_token_js(page) -> Optional[str]:
    """Essaie plusieurs méthodes JS pour extraire PO_TOKEN côté client."""
    # 1) ytcfg API (mweb)
    js_primary = """
        (() => {
          try {
            const g = (window.ytcfg && ((window.ytcfg.data) || (window.ytcfg.get && window.ytcfg.get()))) || {};
            return (g && (g.PO_TOKEN || g['PO_TOKEN'])) || null;
          } catch(e) { return null; }
        })();
    """
    token = page.evaluate(js_primary)
    if token and isinstance(token, str) and len(token) > 10:
        return token

    # 2) yt.config_ (legacy)
    js_cfg = """
        (() => {
          try {
            if (window.yt && window.yt.config_ && window.yt.config_.PO_TOKEN)
              return window.yt.config_.PO_TOKEN;
            return null;
          } catch(e) { return null; }
        })();
    """
    token2 = page.evaluate(js_cfg)
    if token2 and isinstance(token2, str) and len(token2) > 10:
        return token2

    # 3) scan inline scripts
    js_scan = """
        (() => {
          try {
            const scripts = Array.from(document.querySelectorAll('script')).map(s => s.textContent || '');
            for (const code of scripts) {
              const m = code.match(/"PO_TOKEN"\\s*:\\s*"([^"]{20,})"/);
              if (m) return m[1];
            }
            // fallback: innerHTML (lourd mais dernier recours)
            const html = document.documentElement.innerHTML;
            const m2 = html.match(/"PO_TOKEN"\\s*:\\s*"([^"]{20,})"/);
            return m2 ? m2[1] : null;
          } catch(e) { return null; }
        })();
    """
    token3 = page.evaluate(js_scan)
    if token3 and isinstance(token3, str) and len(token3) > 10:
        return token3

    return None

def _worker_fetch(video_id: str, timeout_ms: int, out: dict) -> None:
    """Exécuté dans un thread séparé → autorise l'usage de l'API Sync Playwright."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        out["token"] = None
        out["why"] = "playwright_not_installed"
        return

    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "1").strip().lower()
    headless = headless_env not in ("0", "false", "no")

    # UA mobiles/desktop
    mobile_ua = os.getenv("YTDLP_FORCE_UA") or (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    desktop_ua = os.getenv("YTDLP_FORCE_UA_DESKTOP") or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    tries = [
        (f"https://m.youtube.com/watch?v={video_id}&app=m&persist_app=1", mobile_ua),
        (f"https://m.youtube.com/watch?v={video_id}&pbj=1",                mobile_ua),
        (f"https://www.youtube.com/watch?v={video_id}&bpctr=9999999999",   desktop_ua),
        (f"https://music.youtube.com/watch?v={video_id}",                  desktop_ua),
    ]

    try:
        with sync_playwright() as p:
            for url, ua in tries:
                _dbg(f"goto {url}")
                try:
                    browser = p.chromium.launch(headless=headless, args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ])
                    context = browser.new_context(user_agent=ua, locale="en-US")
                    _inject_cookies_from_b64(context)
                    page = context.new_page()

                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    _maybe_handle_consent(page, timeout_ms)

                    # Laisse du temps au bootstrap + petit polling
                    try:
                        page.wait_for_load_state("networkidle", timeout=timeout_ms)
                    except Exception:
                        pass
                    for _ in range(6):
                        tok = _extract_token_js(page)
                        if tok and len(tok) > 10:
                            out["token"] = tok
                            out["why"] = "ok"
                            _dbg(f"found PO_TOKEN (len={len(tok)})")
                            try: context.close()
                            except Exception: pass
                            try: browser.close()
                            except Exception: pass
                            return
                        page.wait_for_timeout(350)

                except Exception as e:
                    _dbg(f"try failed: {e}")
                finally:
                    try: context.close()
                    except Exception: pass
                    try: browser.close()
                    except Exception: pass

            out["token"] = None
            out["why"] = "not_found"
    except Exception:
        out["token"] = None
        out["why"] = "unexpected_error"

def fetch_po_token(video_id: str, timeout_ms: int = 15000) -> Optional[str]:
    """
    Ouvre différentes variantes de watch (m/www/music) et tente d’extraire PO_TOKEN.
    Retourne le token brut (sans préfixe) ou None.
    """
    _dbg(f"auto-fetch for video {video_id}")
    box = {"token": None, "why": "init"}
    t = threading.Thread(target=_worker_fetch, args=(video_id, timeout_ms, box), daemon=True)
    t.daemon = True
    t.start()
    t.join(timeout=(timeout_ms / 1000.0) + 6.0)  # petite marge
    if not box.get("token"):
        _dbg(f"auto-fetch ended: {box.get('why')}")
    return box.get("token")

# --- petit mode test CLI ---
if __name__ == "__main__":
    import sys
    vid = (sys.argv[1] if len(sys.argv) > 1 else "dQw4w9WgXcQ")
    tok = fetch_po_token(vid, timeout_ms=15000)
    print("PO_TOKEN:", ("<none>" if not tok else f"{tok[:12]}... (len={len(tok)})"))
