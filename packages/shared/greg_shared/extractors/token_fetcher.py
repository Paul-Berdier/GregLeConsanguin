"""PO Token auto-fetcher (Greg le Consanguin).

Récupère un PO token YouTube via Playwright/Chromium, à utiliser avec
`--extractor-args "youtube:po_token=client.gvs+TOKEN"` côté yt-dlp.

Évolutions vs ancienne version :
- Détection robuste du binaire Chromium (multi-chemin + var d'env Playwright).
- Cache négatif TTL : si Playwright est manquant, on arrête de retenter
  (évite des dizaines d'appels à chaque lecture).
- Aucun appel `subprocess` inutile.
- Logging clair indiquant la raison de l'échec.
- Auto-install optionnelle (`PLAYWRIGHT_AUTOINSTALL=1`) en dev/local.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
import time
from typing import Optional

_YTDBG = os.getenv("YTDBG", "1").lower() not in ("0", "false", "")

# ─── Cache négatif : on ne retente pas un fetch impossible toutes les 5s. ───
_NEG_TTL = float(os.getenv("PO_NEG_TTL_SEC", "600"))   # 10 minutes par défaut
_neg_until: float = 0.0
_neg_reason: str = ""
_neg_lock = threading.Lock()


def _dbg(msg: str) -> None:
    if _YTDBG:
        print(f"[YTDBG][po] {msg}", flush=True)


def _set_negative_cache(reason: str) -> None:
    global _neg_until, _neg_reason
    with _neg_lock:
        _neg_until = time.monotonic() + _NEG_TTL
        _neg_reason = reason


def _check_negative_cache() -> Optional[str]:
    with _neg_lock:
        if time.monotonic() < _neg_until:
            return _neg_reason
    return None


# ─── Détection Chromium ───
def _candidate_browser_paths() -> list[str]:
    paths = []
    env = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        paths.append(env)
    paths.extend([
        "/ms-playwright",
        os.path.expanduser("~/.cache/ms-playwright"),
        "/root/.cache/ms-playwright",
        "/home/claude/.cache/ms-playwright",
    ])
    # Déduplication en gardant l'ordre
    seen = set()
    return [p for p in paths if p and not (p in seen or seen.add(p))]


def _find_chromium_executable() -> Optional[str]:
    """Cherche un binaire Chromium installé par Playwright."""
    for base in _candidate_browser_paths():
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.lower() in ("chrome", "chromium", "headless_shell"):
                    full = os.path.join(root, f)
                    if os.access(full, os.X_OK):
                        return full
    return None


def _try_autoinstall() -> bool:
    """Tente `playwright install chromium` si PLAYWRIGHT_AUTOINSTALL=1."""
    if os.getenv("PLAYWRIGHT_AUTOINSTALL", "0").lower() not in ("1", "true", "yes"):
        return False
    try:
        _dbg("auto-installing chromium (PLAYWRIGHT_AUTOINSTALL=1)…")
        cp = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, timeout=180,
        )
        ok = cp.returncode == 0
        _dbg(f"auto-install {'OK' if ok else 'FAILED'} rc={cp.returncode}")
        return ok
    except Exception as e:
        _dbg(f"auto-install exception: {e}")
        return False


# ─── Cookies (injection Netscape → Playwright context) ───
def _inject_cookies_from_b64(context) -> None:
    """Injecte les cookies depuis YTDLP_COOKIES_B64 (format Netscape)."""
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
        if not domain or not name:
            continue
        host = domain[1:] if domain.startswith(".") else domain
        try:
            exp = int(expiry)
        except Exception:
            exp = -1
        cookies.append({
            "name": name,
            "value": (value or "").strip(),
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
    """Ferme la bannière de consentement Google si présente."""
    candidates = [
        'button:has-text("I agree")',
        'button:has-text("Accept all")',
        'button:has-text("J\'accepte")',
        'button:has-text("J\u2019accepte")',
        "#introAgreeButton",
        'form[action*="consent"] button[type="submit"]',
        '[aria-label*="Agree"]',
        'button[aria-label*="J\u2019accepte"]',
    ]
    try:
        for sel in candidates:
            loc = page.locator(sel)
            if loc.count() > 0:
                _dbg(f"consent: clicking {sel!r}")
                loc.first.click(timeout=min(timeout_ms, 1500))
                page.wait_for_timeout(400)
                break
    except Exception:
        pass


# ─── Extraction JS du PO token ───
_JS_CANDIDATES = [
    # 1) ytcfg.data_ / ytcfg.data / ytcfg.get()
    """
    (() => {
      try {
        const g = (window.ytcfg && ((window.ytcfg.data_) || (window.ytcfg.data)
                  || (window.ytcfg.get && window.ytcfg.get()))) || {};
        return (g && (g.PO_TOKEN || g['PO_TOKEN'])) || null;
      } catch(e) { return null; }
    })();
    """,
    # 2) window.yt.config_
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
    # 3) Regex sur le HTML brut
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


def _extract_token_js(page) -> Optional[str]:
    for js in _JS_CANDIDATES:
        try:
            token = page.evaluate(js)
            if token and isinstance(token, str) and len(token) > 10:
                return token
        except Exception:
            pass
    return None


# ─── Worker thread (Playwright sync API) ───
def _worker_fetch(video_id: str, timeout_ms: int, out: dict) -> None:
    # 1) Vérifie le cache négatif
    neg = _check_negative_cache()
    if neg:
        out["token"] = None
        out["why"] = f"negative_cache:{neg}"
        return

    # 2) Module Playwright présent ?
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        _dbg(f"playwright module missing: {e}")
        _set_negative_cache("playwright_not_installed")
        out["token"] = None
        out["why"] = "playwright_not_installed"
        return

    # 3) Binaire Chromium présent ? (sinon tentative d'auto-install)
    if not _find_chromium_executable():
        if _try_autoinstall() and _find_chromium_executable():
            _dbg("chromium installed on demand")
        else:
            _dbg("Playwright browsers not installed — skipping PO token fetch")
            _set_negative_cache("playwright_browsers_missing")
            out["token"] = None
            out["why"] = "playwright_browsers_missing"
            return

    headless = os.getenv("PLAYWRIGHT_HEADLESS", "1").strip().lower() not in ("0", "false", "no")
    mobile_ua = os.getenv("YTDLP_FORCE_UA") or (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )

    # Surfaces les plus susceptibles d'exposer un PO token :
    # mweb (m.youtube.com) > music.youtube.com > www avec bpctr (bypass age-gate)
    tries = [
        (f"https://m.youtube.com/watch?v={video_id}&app=m&persist_app=1", mobile_ua),
        (f"https://music.youtube.com/watch?v={video_id}", mobile_ua),
        (f"https://www.youtube.com/watch?v={video_id}&bpctr=9999999999", mobile_ua),
    ]

    try:
        with sync_playwright() as p:
            for url, ua in tries:
                browser = context = None
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
                        page.wait_for_load_state("networkidle",
                                                 timeout=min(timeout_ms, 5000))
                    except Exception:
                        pass

                    for _ in range(10):
                        tok = _extract_token_js(page)
                        if tok:
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

    except Exception as e:
        _dbg(f"sync_playwright crashed: {e}")
        # Si Playwright lui-même crashe (ex: lib manquante), on bloque les retries.
        _set_negative_cache(f"playwright_crash:{type(e).__name__}")
        out["token"] = None
        out["why"] = f"playwright_crash:{type(e).__name__}"
        return

    out["token"] = None
    out["why"] = "not_found"


def fetch_po_token(video_id: str, timeout_ms: int = 15000) -> Optional[str]:
    """Récupère un PO token brut (sans préfixe `client.gvs+`).

    Retourne None si Playwright/Chromium n'est pas dispo, ou si le token
    n'a pas pu être extrait. Met en cache négatif les erreurs structurelles
    pour éviter les retries en rafale.
    """
    neg = _check_negative_cache()
    if neg:
        _dbg(f"auto-fetch skipped (negative cache: {neg})")
        return None

    _dbg(f"auto-fetch for video {video_id}")
    box: dict = {"token": None, "why": "init"}
    t = threading.Thread(target=_worker_fetch,
                         args=(video_id, timeout_ms, box),
                         daemon=True)
    t.start()
    t.join(timeout=(timeout_ms / 1000.0) + 10.0)
    if t.is_alive():
        _dbg("worker timed out")
        return None

    token = box.get("token")
    why = box.get("why")
    if token and isinstance(token, str) and len(token) > 10:
        return token
    _dbg(f"auto-fetch ended: {why}")
    return None


def invalidate_negative_cache() -> None:
    """À appeler quand l'environnement change (ex: après /yt_cookies_update)."""
    global _neg_until, _neg_reason
    with _neg_lock:
        _neg_until = 0.0
        _neg_reason = ""
