# tests/test_youtube_extractor.py
#
# Pytests 100% mockés (pas de réseau) pour extractors/youtube.py
# - Valide: détection URL, cookies (browser/file/base64), proxy/VPN, IPv4 forcé
# - Stream direct: headers FFmpeg, before_options, http_probe non bloquant
# - Stream PIPE: commande yt-dlp complète (cookies/proxy/ipv4/limit-rate), stdout binaire
# - Download: succès + fallback itag=18 quand format indisponible
# - Fallback client order (auto → ios → etc.)
# - Cas erreur (geo/403 simulé): stream() lève RuntimeError
import io
import os
import types
import builtins
import pytest
from yt_dlp.utils import DownloadError

# Import du module à tester
import importlib
youtube = importlib.import_module("extractors.youtube")

# ---------- Fixtures utilitaires ----------

class DummyFFmpegSource:
    def __init__(self, *args, **kwargs):
        # capture principaux paramètres pour assertions
        self.args = args
        self.kwargs = kwargs
        self._ytdlp_proc = None

    def cleanup(self): pass

class DummyDiscord:
    FFmpegPCMAudio = DummyFFmpegSource

@pytest.fixture(autouse=True)
def patch_discord(monkeypatch):
    # on remplace discord.FFmpegPCMAudio par un dummy
    monkeypatch.setattr(youtube, "discord", DummyDiscord, raising=False)

class FakeResp:
    def __init__(self, status=200, headers=None, body=b"OK"):
        self._status = status
        self.headers = headers or {}
        self._body = io.BytesIO(body)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    @property
    def status(self): return self._status
    def getcode(self): return self._status
    def read(self, n=-1): return self._body.read(n)

# ---------- Helpers yt-dlp fake ----------

class FakeYDL:
    """Contexte YoutubeDL mockable via closures."""
    last_opts = None
    def __init__(self, opts):
        FakeYDL.last_opts = opts
        self._opts = opts
        self._info = None
        # injecté par monkeypatch dans tests
        self._extract_behavior = None
        self._prepare_filename = "out.tmp"

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def set_behavior(self, fn):
        self._extract_behavior = fn

    def extract_info(self, query, download=False):
        if self._extract_behavior:
            return self._extract_behavior(query, download)
        # défaut : retour simple avec url + headers
        return {
            "title": "X",
            "url": "https://rr1---sn-foo.googlevideo.com/videoplayback?itag=18&expire=9999999999",
            "http_headers": {"User-Agent":"UA","Referer":"https://www.youtube.com/"},
        }

    def prepare_filename(self, info):
        return self._prepare_filename

@pytest.fixture(autouse=True)
def patch_ytdl(monkeypatch):
    monkeypatch.setattr(youtube, "YoutubeDL", FakeYDL)


# ---------- TESTS ----------

def test_is_valid_variants():
    assert youtube.is_valid("https://www.youtube.com/watch?v=abc")
    assert youtube.is_valid("https://youtu.be/abc")
    assert youtube.is_valid("https://www.youtube.com/shorts/xyz")
    assert not youtube.is_valid("https://example.com/")

def test_mk_opts_cookies_from_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_COOKIES_BROWSER", "firefox:Default")
    opts = youtube._mk_opts()
    assert "cookiesfrombrowser" in opts
    assert opts["extractor_args"]["youtube"]["player_client"][0] == "ios"

def test_mk_opts_cookiefile_and_b64(monkeypatch, tmp_path):
    # sans fichier → injection via b64
    cookie_text = "# Netscape\n.youtube.com\tTRUE\t/\tTRUE\t0\tCONSENT\tYES+cb\n"
    monkeypatch.setenv("YTDLP_COOKIES_B64", base64_encode(cookie_text))
    # supprime fichier si existant
    try:
        os.remove("youtube.com_cookies.txt")
    except FileNotFoundError:
        pass
    opts = youtube._mk_opts()
    # devrait créer le fichier par env
    assert "cookiefile" in opts
    assert os.path.exists(opts["cookiefile"])

def base64_encode(s: str) -> str:
    import base64
    return base64.b64encode(s.encode("utf-8")).decode("ascii")

def test_mk_opts_proxy_ipv4(monkeypatch):
    monkeypatch.setenv("YTDLP_HTTP_PROXY", "http://proxy:3128")
    monkeypatch.setenv("YTDLP_FORCE_IPV4", "1")
    # reload env into module caches if needed
    import importlib
    import extractors.youtube as yt
    importlib.reload(yt)
    opts = yt._mk_opts()
    assert opts.get("proxy") == "http://proxy:3128"
    assert opts.get("source_address") == "0.0.0.0"

def test_best_info_fallback_order(monkeypatch):
    calls = {"auto":0, "ios":0, "web":0}
    def behavior(query, download):
        # auto ne fournit pas d'URL, ios oui
        client = FakeYDL.last_opts["extractor_args"]["youtube"]["player_client"][0] if FakeYDL.last_opts["extractor_args"]["youtube"]["player_client"] else "auto"
        calls[client] = calls.get(client, 0)+1
        if client == "auto":
            return {"title":"T","entries":[{"title":"T-no-url"}]}  # pas de url
        if client == "ios":
            return {"title":"T","url":"https://googlevideo.com/videoplayback?expire=9999"}
        return {"title":"X"}  # unused
    def set_behavior(opts):
        FakeYDL._extract_behavior = behavior

    FakeYDL._extract_behavior = behavior
    info = youtube._best_info_with_fallbacks(
        "https://youtu.be/abc",
        cookies_file=None, cookies_from_browser=None, ffmpeg_path=None, ratelimit_bps=None
    )
    assert info and info.get("url")
    assert calls["auto"] >= 1 and calls["ios"] >= 1

def test_stream_builds_ffmpeg_with_headers(monkeypatch):
    # configure FakeYDL to return info with headers
    def behavior(query, download):
        return {
            "title":"Song",
            "url":"https://rr1---sn-foo.googlevideo.com/videoplayback?itag=18&expire=9999999999",
            "http_headers":{"User-Agent":"UAx","Referer":"https://www.youtube.com/"},
        }
    FakeYDL._extract_behavior = behavior

    # call stream
    import asyncio
    src, title = asyncio.get_event_loop().run_until_complete(
        youtube.stream("https://youtu.be/abc", "ffmpeg")
    )
    assert isinstance(src, DummyFFmpegSource)
    assert title == "Song"
    before = src.kwargs.get("before_options", "")
    assert "-headers" in before and "-user_agent" in before

def test_stream_http_probe_enabled(monkeypatch):
    # active le probe et monkeypatch urlopen
    def fake_build_opener(*h):
        class O:
            def open(self, req, timeout=10):
                return FakeResp(status=200, headers={"Server":"gws"})
        return O()
    monkeypatch.setenv("YTDBG_HTTP_PROBE", "1")
    # recharger module pour prendre env en compte
    import importlib
    yt = importlib.reload(youtube)
    monkeypatch.setattr(yt._ureq, "build_opener", fake_build_opener)
    def behavior(query, download):
        return {"title":"T","url":"https://rr1---sn-foo.googlevideo.com/videoplayback?expire=9999999999"}
    FakeYDL._extract_behavior = behavior
    import asyncio
    src, title = asyncio.get_event_loop().run_until_complete(
        yt.stream("https://youtu.be/abc", "ffmpeg")
    )
    assert title == "T"

def test_stream_pipe_cmd_includes_flags(monkeypatch, tmp_path):
    # cookies file
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    # stub which yt-dlp
    monkeypatch.setenv("YTDLP_FORCE_IPV4", "1")
    monkeypatch.setenv("YTDLP_HTTP_PROXY", "http://proxy:3128")
    def fake_which(cmd):
        return "/usr/bin/yt-dlp"
    monkeypatch.setattr(youtube.shutil, "which", fake_which)

    # fake Popen to capture cmd
    started = {}
    class FP:
        def __init__(self, cmd, **kw):
            started["cmd"] = cmd
            self.stdout = io.BytesIO(b"\x00"*16)
            self.stderr = io.BytesIO(b"yt-dlp: starting...\n")
        def readline(self): return b""
    monkeypatch.setattr(youtube.subprocess, "Popen", FP)

    def behavior(query, download):
        return {"title":"PIPE","url":"https://rr1---sn-foo.googlevideo.com/videoplayback?expire=9999999999"}
    FakeYDL._extract_behavior = behavior

    import asyncio
    src, title = asyncio.get_event_loop().run_until_complete(
        youtube.stream_pipe("https://youtu.be/abc", "ffmpeg", cookies_file=str(cookies), ratelimit_bps=2500000)
    )
    cmd = started["cmd"]
    assert "--force-ipv4" in cmd
    assert "--proxy" in cmd
    assert "--cookies" in cmd
    assert "-o" in cmd and "-" in cmd

def test_download_success(monkeypatch, tmp_path):
    outdir = tmp_path / "dl"
    def behavior(query, download):
        assert download is True
        return {"title":"DL", "duration": 123, "requested_downloads":[{"filepath": str(outdir/"x.mp3")}]}
    FakeYDL._extract_behavior = behavior
    p, title, dur = youtube.download(
        "https://youtu.be/abc", ffmpeg_path="ffmpeg", out_dir=str(outdir)
    )
    assert title == "DL" and dur == 123
    assert p.endswith(".mp3")

def test_download_fallback_itag18(monkeypatch, tmp_path):
    outdir = tmp_path / "dl2"
    class Err(DownloadError): pass
    calls = {"first":0, "second":0}
    def behavior_first(query, download):
        calls["first"] += 1
        raise DownloadError("Requested format is not available")
    def behavior_second(query, download):
        calls["second"] += 1
        return {"title":"DL2","duration":99,"requested_downloads":[{"filepath": str(outdir/"y.mp3")}]}
    # Première instance FakeYDL → échec, seconde → succès
    seq = [behavior_first, behavior_second]
    def selector(query, download):
        fn = seq[0]
        if fn is behavior_first:
            seq.pop(0)
            raise DownloadError("Requested format is not available")
        return behavior_second(query, download)
    FakeYDL._extract_behavior = selector

    p, title, dur = youtube.download(
        "https://youtu.be/abc", ffmpeg_path="ffmpeg", out_dir=str(outdir)
    )
    assert title == "DL2" and dur == 99
    assert p.endswith(".mp3")

def test_stream_error_when_no_url(monkeypatch):
    def behavior(query, download):
        return {"title":"T","entries":[{"title":"nope"}]}  # pas d'url dispo
    FakeYDL._extract_behavior = behavior
    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(
            youtube.stream("https://youtu.be/abc", "ffmpeg")
        )
