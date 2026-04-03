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
    """
    Injecte des cookies depuis YTDLP_COOKIES_B64 (format Netscape).
    Utile si le provider Playwright a besoin d'un contexte déjà authentifié.
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
    """
    Ferme les bannières de consentement si présentes.
    """
    try:
        candidates = [
            'button:has-text("I agree")',
            'button:has-text("Accept all")',
            'button:has-text("J\'accepte")',
            'button:has-text("J’accepte")',
            "#introAgreeButton",
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
    """
    Plusieurs méthodes JS pour extraire un PO token.
    """
    js_candidates = [
        """
        (() => {
          try {
            const g = (window.ytcfg && ((window.ytcfg.data_) || (window.ytcfg.data) || (window.ytcfg.get && window.ytcfg.get()))) || {};
            return (g && (g.PO_TOKEN || g['PO_TOKEN'])) || null;
          } catch(e) { return null; }
        })();
        """,
        """
        (() => {
          try {
            if (window.yt && window.yt.config_ && window.yt.config_.PO_TOKEN) {
              return window.yt.config_.PO_TOKEN;
            }
            return null;
          } catch(e) { return null; }
        })();
        """,
        """
        (() => {
          try {
            const html = document.documentElement.outerHTML || '';
            const m = html.match(/"PO_TOKEN"\\s*:\\s*"([^"]{20,})"/);
            return m ? m[1] : null;
          } catch(e) { return null; }
        })();
        """,
    ]

    for js in js_candidates:
        try:
            token = page.evaluate(js)
            if token and isinstance(token, str) and len(token) > 10:
                return token
        except Exception:
            pass

    return None


def _worker_fetch(video_id: str, timeout_ms: int, out: dict) -> None:
    """
    Thread worker pour éviter l'usage sync Playwright dans la loop asyncio.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        out["token"] = None
        out["why"] = "playwright_not_installed"
        return

    # Fast-fail: vérifie si les binaires Playwright sont installés
    # avant de tenter 3 lancements qui échouent tous
    try:
        import subprocess
        result = subprocess.run(
            ["playwright", "install", "--dry-run"],
            capture_output=True, timeout=3,
        )
        # Si la commande n'existe pas ou échoue, on vérifie autrement
    except Exception:
        pass

    # Vérification directe du binaire chromium
    _chromium_paths = [
        os.path.expanduser("~/.cache/ms-playwright"),
        "/root/.cache/ms-playwright",
    ]
    _has_browser = False
    for base in _chromium_paths:
        if os.path.isdir(base):
            # Cherche n'importe quel chrome/chromium exécutable
            for root, dirs, files in os.walk(base):
                for f in files:
                    if "chrome" in f.lower() and os.access(os.path.join(root, f), os.X_OK):
                        _has_browser = True
                        break
                if _has_browser:
                    break
        if _has_browser:
            break

    if not _has_browser:
        _dbg("Playwright browsers not installed — skipping PO token fetch")
        out["token"] = None
        out["why"] = "playwright_browsers_missing"
        return

    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "1").strip().lower()
    headless = headless_env not in ("0", "false", "no")

    mobile_ua = os.getenv("YTDLP_FORCE_UA") or (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )

    # On se concentre sur les surfaces les plus utiles pour mweb / youtube music
    tries = [
        (f"https://m.youtube.com/watch?v={video_id}&app=m&persist_app=1", mobile_ua),
        (f"https://music.youtube.com/watch?v={video_id}", mobile_ua),
        (f"https://www.youtube.com/watch?v={video_id}&bpctr=9999999999", mobile_ua),
    ]

    with sync_playwright() as p:
        for url, ua in tries:
            browser = None
            context = None
            try:
                _dbg(f"goto {url}")

                browser = p.chromium.launch(
                    headless=headless,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(user_agent=ua, locale="en-US")
                _inject_cookies_from_b64(context)
                page = context.new_page()

                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                _maybe_handle_consent(page, timeout_ms)

                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
                except Exception:
                    pass

                for _ in range(10):
                    tok = _extract_token_js(page)
                    if tok and len(tok) > 10:
                        out["token"] = tok
                        out["why"] = "ok"
                        _dbg(f"found PO token (len={len(tok)})")
                        return
                    page.wait_for_timeout(300)

            except Exception as e:
                _dbg(f"try failed: {e}")
            finally:
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    if browser:
                        browser.close()
                except Exception:
                    pass

        out["token"] = None
        out["why"] = "not_found"


def fetch_po_token(video_id: str, timeout_ms: int = 15000) -> Optional[str]:
    """
    Retourne un token brut (sans préfixe client.gvs+).
    """
    _dbg(f"auto-fetch for video {video_id}")
    box = {"token": None, "why": "init"}

    t = threading.Thread(target=_worker_fetch, args=(video_id, timeout_ms, box), daemon=True)
    t.start()
    t.join(timeout=(timeout_ms / 1000.0) + 8.0)

    token = box.get("token")
    why = box.get("why")
    if token and isinstance(token, str) and len(token) > 10:
        return token

    _dbg(f"auto-fetch ended: {why}")
    return None