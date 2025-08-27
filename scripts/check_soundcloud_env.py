#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Self-test SoundCloud env:
- ffmpeg availability + protocols (https, hls)
- network reachability to soundcloud.com
- get client_ids from env + scraping
- v2 resolve + pick progressive/hls + signed URL
- probe playback with ffmpeg (with proper headers)
- yt-dlp fallback extraction + probe

Exit codes:
 0 = OK (at least one playback path succeeded)
 1 = FAIL
"""

import os, sys, platform, json, time, subprocess, shlex
from pathlib import Path

# ---------- Config ----------
TEST_URL = os.getenv("SC_TEST_URL", "https://soundcloud.com/damsoofficial/pa-pa-paw")
FFMPEG_CANDIDATES = [
    "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "ffmpeg",
    r"D:\Paul Berdier\ffmpeg\bin\ffmpeg.exe"
]
REQUEST_TIMEOUT = float(os.getenv("SC_SELFTEST_TIMEOUT", "8.0"))
VERBOSE = os.getenv("SC_SELFTEST_VERBOSE", "1") == "1"

# ---------- Helpers ----------
def log(*a):
    print(*a, flush=True)

def detect_ffmpeg():
    for p in FFMPEG_CANDIDATES:
        try:
            if p == "ffmpeg":
                # will rely on PATH; still test -version
                out = subprocess.run([p, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
                if out.returncode == 0:
                    return p
                continue
            if os.path.exists(p) and os.access(p, os.X_OK):
                out = subprocess.run([p, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
                if out.returncode == 0:
                    return p
        except Exception:
            pass
    return "ffmpeg"  # last hope (PATH)

def ffmpeg_has_protocol(ffmpeg_path, proto):
    try:
        out = subprocess.run([ffmpeg_path, "-protocols"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8, text=True)
        return proto in (out.stdout or "")
    except Exception:
        return False

def ffmpeg_version_str(ffmpeg_path):
    try:
        out = subprocess.run([ffmpeg_path, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8, text=True)
        return (out.stdout or "").splitlines()[0]
    except Exception as e:
        return f"ffmpeg -version failed: {e}"

def run_ffmpeg_probe(ffmpeg_path, url, headers: dict | None, hls_whitelist=True, seconds=2):
    """
    Try to actually open/parse a few seconds with ffmpeg.
    Returns (ok_bool, returncode, combined_output_tail)
    """
    # Build -headers value (must end with CRLF; multiple lines CRLF-separated)
    def headers_str(h):
        h = {str(k).lower(): str(v) for k,v in (h or {}).items()}
        ua = h.get("user-agent") or "Mozilla/5.0"
        ref = h.get("referer") or "https://soundcloud.com"
        org = h.get("origin") or "https://soundcloud.com"
        lines = [f"User-Agent: {ua}", f"Referer: {ref}", f"Origin: {org}"]
        if h.get("authorization"):
            lines.append(f"Authorization: {h['authorization']}")
        return ("\r\n".join(lines) + "\r\n")

    before = []
    if headers:
        before += ["-headers", headers_str(headers)]
    # robust reconnect & allow HLS crypto
    before += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
    if hls_whitelist:
        before += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-allowed_extensions", "ALL"]

    cmd = [ffmpeg_path, *sum([["-hide_banner", "-loglevel", "error"], before], []),
           "-t", str(seconds), "-i", url, "-f", "null", "-"]
    if VERBOSE:
        log("[FFMPEG] probe:", " ".join(shlex.quote(x) for x in cmd))
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, text=True)
        ok = (out.returncode == 0)
        tail = "\n".join((out.stdout or "").splitlines()[-10:])
        return ok, out.returncode, tail
    except subprocess.TimeoutExpired:
        return False, 124, "ffmpeg probe: TIMEOUT"
    except Exception as e:
        return False, 1, f"ffmpeg probe exception: {e}"

def import_project():
    """Ensure project modules are importable (when run from /app)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # /app
    from yt_dlp import YoutubeDL  # noqa
    import requests                # noqa
    try:
        from extractors import soundcloud as sc  # noqa
    except Exception as e:
        log("ERROR: can't import extractors.soundcloud:", e)
        raise
    return sc

def try_requests_head(url, timeout):
    import requests
    try:
        r = requests.get(url, timeout=timeout)
        return True, r.status_code
    except Exception as e:
        return False, str(e)

# ---------- Main ----------
def main():
    log("== SC SELFTEST ==")
    log("Python:", sys.version.split()[0], "| Platform:", platform.platform())
    # ffmpeg
    ff = detect_ffmpeg()
    log("ffmpeg:", ffmpeg_version_str(ff))
    has_https = ffmpeg_has_protocol(ff, "https")
    has_hls   = ffmpeg_has_protocol(ff, "hls")
    log("ffmpeg protocols → https:", has_https, "hls:", has_hls)

    # network
    ok_net, net_info = try_requests_head("https://soundcloud.com/", REQUEST_TIMEOUT)
    log("Network to soundcloud.com:", "OK" if ok_net else "FAIL", net_info)

    # import project + deps
    try:
        sc = import_project()
        from yt_dlp import YoutubeDL
        import requests
        log("yt-dlp version:", YoutubeDL().params.get("compat_opts", "unknown") or "ok")
    except Exception as e:
        log("IMPORT FAIL:", e)
        return 1

    # collect client_ids: env + scraper
    env_raw = (os.getenv("SOUNDCLOUD_CLIENT_ID", "") or "").strip()
    env_ids = [x.strip() for x in env_raw.replace(";", ",").replace(" ", ",").split(",") if x.strip()]
    scraped_ids = []
    try:
        scraped_ids = sc._sc_scrape_client_ids()
    except Exception as e:
        log("[SC] scraping exception:", e)

    uniq_ids = []
    for cid in env_ids + scraped_ids:
        if cid and cid not in uniq_ids:
            uniq_ids.append(cid)
    log(f"client_ids: env={len(env_ids)} scraped={len(scraped_ids)} unique={len(uniq_ids)}")

    # Try resolve+progressive
    resolved_ok = False
    progressive_ok = False
    progressive_url = None
    progressive_headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://soundcloud.com", "Origin": "https://soundcloud.com"}
    chosen_title = None

    for cid in uniq_ids or [None]:
        if not cid:
            break
        try:
            tr = sc._sc_resolve_track(TEST_URL, cid, timeout=REQUEST_TIMEOUT)
            if not tr:
                log(f"[SC] resolve(cid=****{cid[-4:]}) → no track")
                continue
            resolved_ok = True
            media = (tr.get("media") or {})
            trans = media.get("transcodings") or []
            protos = [(t.get("format") or {}).get("protocol") for t in trans]
            log(f"[SC] resolve → transcodings: {protos}")

            signed_url, title, duration, proto = sc._sc_pick_progressive_stream(tr, cid, timeout=REQUEST_TIMEOUT)
            if signed_url:
                log(f"[SC] chosen: protocol={proto}, host={Path(signed_url).anchor or ''}")
                chosen_title = title
                if proto == "progressive" and ".mp3" in signed_url.split("?")[0].lower():
                    ok, rc, tail = run_ffmpeg_probe(ff, signed_url, progressive_headers, hls_whitelist=False)
                    log(f"[SC] probe progressive → {'OK' if ok else 'FAIL'} (rc={rc})")
                    if not ok and VERBOSE:
                        log(tail)
                    progressive_ok = ok
                    progressive_url = signed_url
                    break
                else:
                    # try HLS with headers
                    ok, rc, tail = run_ffmpeg_probe(ff, signed_url, progressive_headers, hls_whitelist=True)
                    log(f"[SC] probe HLS(resolve) → {'OK' if ok else 'FAIL'} (rc={rc})")
                    if not ok and VERBOSE:
                        log(tail)
                    if ok:
                        progressive_ok = True
                        progressive_url = signed_url
                        break
        except Exception as e:
            log(f"[SC] resolve attempt failed (cid=****{cid[-4:]}) →", e)

    # If progressive/HLS via resolve failed, try yt-dlp fallback
    ytdlp_ok = False
    if not progressive_ok:
        log("[SC] fallback: yt_dlp download=False")
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True, 'default_search': 'scsearch3', 'nocheckcertificate': True}
        def extract():
            with YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(TEST_URL, download=False)
        try:
            data = extract()
            info = data['entries'][0] if 'entries' in data else data
            stream_url = info['url']
            chosen_title = chosen_title or info.get('title', 'Son inconnu')
            http_headers = info.get('http_headers') or data.get('http_headers') or {}
            log("[SC] yt_dlp → stream host:", (stream_url.split('/')[2] if '://' in stream_url else 'unknown'),
                "headers:", bool(http_headers))
            ok, rc, tail = run_ffmpeg_probe(ff, stream_url, http_headers, hls_whitelist=True)
            log(f"[SC] probe HLS(yt_dlp) → {'OK' if ok else 'FAIL'} (rc={rc})")
            if not ok and VERBOSE:
                log(tail)
            ytdlp_ok = ok
        except Exception as e:
            log("[SC] yt_dlp fallback failed:", e)

    # Summary
    log("\n=== SUMMARY ===")
    log("ffmpeg https/hls:", has_https, has_hls)
    log("network:", ok_net)
    log("resolve_ok:", resolved_ok, "progressive_or_hls_ok:", progressive_ok)
    log("yt_dlp_ok:", ytdlp_ok)
    any_ok = progressive_ok or ytdlp_ok

    if any_ok:
        log(f"✅ SUCCESS — can stream: {chosen_title or '(unknown title)'}")
        return 0
    else:
        log("❌ FAIL — no streaming path worked. Likely causes:")
        if not has_https or not has_hls:
            log("  - ffmpeg build missing https/hls support")
        if not ok_net:
            log("  - network egress blocked to soundcloud.com")
        if not uniq_ids:
            log("  - no SoundCloud client_id from env nor scraping")
        log("  - SC HLS signed URLs rejected by ffmpeg (headers/protocol_whitelist issue)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
